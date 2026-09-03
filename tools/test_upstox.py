"""
Standalone test for the Upstox integration. Run directly:

    python tools/test_upstox.py

Fetches a live quote and 1 year of daily historical OHLC for RELIANCE to
confirm auth + API access work.
"""
import datetime
from upstox_client import get_authenticated_client, BASE_URL

INSTRUMENT_KEY = "NSE_EQ|INE002A01018"  # Reliance Industries


def test_quote(session):
    resp = session.get(
        f"{BASE_URL}/market-quote/quotes",
        params={"instrument_key": INSTRUMENT_KEY},
    )
    resp.raise_for_status()
    print("=== Live quote ===")
    print(resp.json())


def test_historical_ohlc(session):
    to_date = datetime.date.today().isoformat()
    from_date = (datetime.date.today() - datetime.timedelta(days=365)).isoformat()
    resp = session.get(
        f"{BASE_URL}/historical-candle/{INSTRUMENT_KEY}/day/{to_date}/{from_date}"
    )
    resp.raise_for_status()
    data = resp.json()
    candles = data.get("data", {}).get("candles", [])
    print(f"\n=== Historical OHLC (day) - {len(candles)} candles ===")
    print("First 3:", candles[:3])
    print("Last 3:", candles[-3:])


def main():
    session = get_authenticated_client()
    test_quote(session)
    test_historical_ohlc(session)


if __name__ == "__main__":
    main()
