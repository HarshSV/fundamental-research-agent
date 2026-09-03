"""
Cross-platform TLS trust bootstrap.

On Windows, many corporate / ISP / antivirus setups run a TLS-inspecting proxy
that re-signs HTTPS with a private root CA. That root lives in the Windows
certificate store but NOT in certifi's bundle, so Python `requests` AND the
`curl_cffi` transport used by yfinance fail with "unable to get local issuer
certificate" - leaving the app with no market data.

This module exports the machine's ROOT + CA stores (which include that private
root) into a single PEM and points every HTTP layer at it via the standard
environment variables. Verification stays ON and correct - this is not an
insecure bypass; it simply trusts the certificates the machine already trusts.

On Linux / macOS (i.e. the production cloud box) this is a no-op and the normal
system / certifi trust store is used.

Import this module as early as possible, before any HTTPS call is made.
"""

import os
import ssl
import sys
import tempfile

_DONE = False


def ensure_trust():
    global _DONE
    if _DONE:
        return
    _DONE = True

    # Only needed on Windows; elsewhere the system store already works.
    if not sys.platform.startswith("win"):
        return

    # 1) Python `ssl` layer (requests / urllib -> Angel SmartAPI, Groq, scrip
    #    master). truststore verifies via the Windows API, which is lenient about
    #    quirks like "Basic Constraints not marked critical" that make OpenSSL
    #    reject a raw PEM bundle. This is the correct, secure path.
    try:
        import truststore
        truststore.inject_into_ssl()
    except Exception as e:
        print(f"[ssl_bootstrap] truststore unavailable: {e}")

    # 2) curl_cffi layer (yfinance, NSE scraper). curl_cffi does NOT use Python's
    #    ssl module, so truststore can't help it. Point it at a PEM exported from
    #    the Windows ROOT+CA stores via CURL_CA_BUNDLE (libcurl is tolerant of the
    #    above quirk). Only set this var; leave SSL_CERT_FILE alone so the strict
    #    OpenSSL path keeps using truststore.
    try:
        import certifi
        pems = [certifi.contents()]
        for store in ("ROOT", "CA"):
            try:
                for cert, enc, _trust in ssl.enum_certificates(store):
                    if enc == "x509_asn":
                        pems.append(ssl.DER_cert_to_PEM_cert(cert))
            except Exception:
                continue

        bundle = os.path.join(tempfile.gettempdir(), "navrist_ca_bundle.pem")
        with open(bundle, "w", encoding="utf-8") as fh:
            fh.write("\n".join(pems))

        os.environ.setdefault("CURL_CA_BUNDLE", bundle)
        print(f"[ssl_bootstrap] curl CA bundle ready ({len(pems)} certs) -> {bundle}")
    except Exception as e:
        print(f"[ssl_bootstrap] could not build curl CA bundle: {e}")


# Run on import.
ensure_trust()
