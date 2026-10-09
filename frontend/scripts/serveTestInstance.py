"""Throwaway local instance of the backend for browser testing - NOT for deploy.

Runs app.py on 127.0.0.1:8010 with a fixed TEST login password and TEST JWT
secret, so UI tests never need the real SITE_PASSWORD. python-dotenv does not
override variables that are already set, so these win over .env.

    venv/Scripts/python.exe frontend/scripts/serveTestInstance.py
    login password: navrist-local-test
"""
import os
import runpy
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
os.chdir(ROOT)
sys.path.insert(0, ROOT)
os.environ.update(
    SITE_PASSWORD="navrist-local-test",
    JWT_SECRET_KEY="local-test-secret-not-for-production-0123456789",
    HOST="127.0.0.1",
    PORT="8010",
    RELOAD="0",
)
if os.environ.get("TEST_STUB_AGENT") == "1":
    # Only when a native dependency of the research-agent graph cannot load on this machine
    # (e.g. an OS Application Control policy blocking langchain's uuid_utils DLL): stub that one
    # import so search / live chart / quotes can still be exercised. Research endpoints won't work.
    import types
    _stub = types.ModuleType("agent.stock_agent")
    _stub.app = object()
    sys.modules["agent.stock_agent"] = _stub
runpy.run_path(os.path.join(ROOT, "app.py"), run_name="__main__")
