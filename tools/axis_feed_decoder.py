"""
Decoder for Axis Direct RAPID API's binary WebSocket/UDP feed frames.
Used only by tools/axis_feed_ws.py for the live-charts feature - no other
part of the app touches this wire format.

All multi-byte fields are little-endian, per the RAPID docs. Frame layouts
below are struct-format strings mirroring the documented byte offsets/sizes
exactly (uint8=B, uint32=I, float32=f), and are untested against a live
feed since Axis has not yet provisioned credentials - re-verify field
order against a captured frame once a real connection is available.
"""

import struct

FEED_LITE = 61
FEED_LTP = 62
FEED_MARKET_DEPTH = 63
FEED_MARKET_DEPTH_TBTN = 64
FEED_CAS = 66

EXCHANGE_CODES = {
    51: "nse",
    52: "bse",
    53: "mcx",
    54: "cdx",
    55: "nsefao",
    56: "bsefao",
    60: "unknown",
}

_LITE_FMT = "<BBBIfff"          # feedType, exchangeCode, version, t, p, f, g
_LITE_SIZE = struct.calcsize(_LITE_FMT)  # 19 bytes

_LTP_SIZE = 83

_MD_HEADER_FMT = "<BBBI"   # feedType, exchangeCode, version, token
_MD_HEADER_SIZE = struct.calcsize(_MD_HEADER_FMT)  # 7 bytes
_MD_ITEM_FMT = "<IfI"      # quantity, price, order
_MD_ITEM_SIZE = struct.calcsize(_MD_ITEM_FMT)  # 12 bytes

_TBTN_FMT = "<BBBIIII"   # feedType, exchangeCode, version, token, tb, ts, c
_TBTN_SIZE = struct.calcsize(_TBTN_FMT)  # 19 bytes

_CAS_FMT = "<BBBIIIfff"  # feedType, exchangeCode, version, token, c, r, rp, ic, iq
_CAS_SIZE = struct.calcsize(_CAS_FMT)  # 27 bytes


def decode_lite(buf: bytes) -> dict:
    feed_type, exch, version, token, p, f, g = struct.unpack(_LITE_FMT, buf[:_LITE_SIZE])
    return {
        "feed_type": feed_type,
        "exchange": EXCHANGE_CODES.get(exch, "unknown"),
        "version": version,
        "token": token,
        "ltp": p,
        "pct_change": f,
        "price_diff": g,
    }


def decode_ltp(buf: bytes) -> dict:
    """Full LTP snapshot (feedType=62, 83 bytes). Field order per docs:
    feedType, exchangeCode, version, token, r, p, a, o, h, l, e, f, g,
    w, b, s, ah, al, u, i, j, k, op.
    """
    (feed_type, exch, version, token, r,
     p, a, o, h, l, e, f, g,
     w, b, s,
     ah, al, u, i,
     j, k, op) = struct.unpack("<BBBIIffffffffIIIffffIff", buf[:_LTP_SIZE])
    return {
        "feed_type": feed_type,
        "exchange": EXCHANGE_CODES.get(exch, "unknown"),
        "version": version,
        "token": token,
        "timestamp": r,
        "ltp": p,
        "avg_price": a,
        "open": o,
        "high": h,
        "low": l,
        "close": e,
        "pct_change": f,
        "price_diff": g,
        "volume": w,
        "total_buy": b,
        "total_sell": s,
        "day_high": ah,
        "day_low": al,
        "upper_circuit": u,
        "lower_circuit": i,
        "oi": j,
        "oi_diff": k,
        "oi_diff_pct": op,
    }


def decode_market_depth(buf: bytes) -> dict:
    feed_type, exch, version, token = struct.unpack(_MD_HEADER_FMT, buf[:_MD_HEADER_SIZE])
    items = []
    offset = _MD_HEADER_SIZE
    while offset + _MD_ITEM_SIZE <= len(buf):
        qty, price, order = struct.unpack(_MD_ITEM_FMT, buf[offset:offset + _MD_ITEM_SIZE])
        items.append({"quantity": qty, "price": price, "order": order})
        offset += _MD_ITEM_SIZE
    return {
        "feed_type": feed_type,
        "exchange": EXCHANGE_CODES.get(exch, "unknown"),
        "version": version,
        "token": token,
        "items": items,
    }


def decode_market_depth_tbtn(buf: bytes) -> dict:
    feed_type, exch, version, token, tb, ts, c = struct.unpack(_TBTN_FMT, buf[:_TBTN_SIZE])
    return {
        "feed_type": feed_type,
        "exchange": EXCHANGE_CODES.get(exch, "unknown"),
        "version": version,
        "token": token,
        "total_buy_qty": tb,
        "total_sell_qty": ts,
        "cocode": c,
    }


def decode_cas(buf: bytes) -> dict:
    feed_type, exch, version, token, c, r, rp, ic, iq = struct.unpack(_CAS_FMT, buf[:_CAS_SIZE])
    return {
        "feed_type": feed_type,
        "exchange": EXCHANGE_CODES.get(exch, "unknown"),
        "version": version,
        "token": token,
        "cocode": c,
        "timestamp": r,
        "reference_price": rp,
        "indicative_close": ic,
        "indicative_imbalance_qty": iq,
    }


_DECODERS = {
    FEED_LITE: decode_lite,
    FEED_LTP: decode_ltp,
    FEED_MARKET_DEPTH: decode_market_depth,
    FEED_MARKET_DEPTH_TBTN: decode_market_depth_tbtn,
    FEED_CAS: decode_cas,
}


def decode_frame(buf: bytes):
    """Dispatches a raw binary frame to the right decoder based on its
    first byte (feedType). Returns None for an unrecognized/short frame
    rather than raising - a malformed tick should never crash the feed
    consumer.
    """
    if not buf:
        return None
    feed_type = buf[0]
    decoder = _DECODERS.get(feed_type)
    if decoder is None:
        return None
    try:
        return decoder(buf)
    except struct.error:
        return None
