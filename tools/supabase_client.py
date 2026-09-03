"""
Shared Supabase client for the fundamentals/price database.

Always uses the service_role key (full read/write, bypasses Row Level
Security) - this module must NEVER be imported by anything that ships to
the browser; it is backend-only (app.py / precompute worker / scripts).

Schema lives in db/001_schema.sql (run once via Supabase's SQL Editor).
"""

import os

try:
    from tools import ssl_bootstrap  # noqa: F401 - fixes SSL cert verification on this machine
except Exception:
    pass

from dotenv import load_dotenv
load_dotenv()

_client = None


def get_client():
    """Lazily-created, process-wide Supabase client (service_role key).

    Forces HTTP/1.1 for every Supabase REST call instead of postgrest-py's
    own hardcoded `http2=True` (venv/Lib/site-packages/postgrest/_sync/
    client.py) - confirmed real root cause of the intermittent
    "[WinError 10035] A non-blocking socket operation could not be
    completed immediately" failures seen throughout this app (document
    upload, fundamental-ratio writes, qualitative-value writes), on a
    single, non-concurrent request, not just under thread load. This is
    a known httpx/httpcore HTTP/2 read-loop issue on Windows (h2's
    non-blocking socket read occasionally races WSAEWOULDBLOCK), not
    something a request-level retry can fully paper over since it can
    recur on the retry too. HTTP/1.1 doesn't use that read path at all,
    so this is a genuine root-cause fix rather than another retry-wrapper
    bolted onto yet another call site - every existing per-call-site
    retry (write_qualitative, the fundamental bulk upsert) stays in place
    as defense-in-depth, but this should make them rarely if ever fire."""
    global _client
    if _client is None:
        from supabase import create_client
        from supabase.lib.client_options import SyncClientOptions
        import httpx
        url = os.environ["SUPABASE_URL"]
        key = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
        http_client = httpx.Client(http2=False, follow_redirects=True, timeout=120)
        _client = create_client(url, key, options=SyncClientOptions(httpx_client=http_client))
    return _client
