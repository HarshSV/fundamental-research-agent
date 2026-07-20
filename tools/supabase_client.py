"""
Shared Supabase client for the fundamentals/price database.

Always uses the service_role key (full read/write, bypasses Row Level
Security) — this module must NEVER be imported by anything that ships to
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
    """Lazily-created, process-wide Supabase client (service_role key)."""
    global _client
    if _client is None:
        from supabase import create_client
        url = os.environ["SUPABASE_URL"]
        key = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
        _client = create_client(url, key)
    return _client
