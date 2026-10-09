"""Run the real search/resolver against the real company universe (NSE names cache +
the Supabase `companies` master) - an integration probe, not a unit test.

    venv/Scripts/python.exe tests/company_search_probe.py "prime fresh" TCS ...
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import types  # noqa: E402

# Optional: when a native dependency of the research-agent graph can't load on this machine
# (e.g. an OS Application Control policy blocking langchain's uuid_utils DLL), stub ONLY that
# import - the search/resolver/universe code under test is the real app.py either way.
if os.environ.get("PROBE_STUB_AGENT") == "1":
    _stub = types.ModuleType("agent.stock_agent")
    _stub.app = object()
    sys.modules["agent.stock_agent"] = _stub

import app  # noqa: E402

names = json.load(open(os.path.join(app._BASE_DIR, "cache", "nse_company_names.json"), encoding="utf-8"))
app._NSE_LISTED.update(names.keys())
curated = {i["symbol"].upper() for i in app.STOCK_REGISTRY}
app.STOCK_REGISTRY = list(app.STOCK_REGISTRY) + [
    {"symbol": s, "name": n} for s, n in sorted(names.items()) if s not in curated
]
app._rebuild_company_universe()
app._REGISTRY_READY.set()
print("NSE registry:", len(app.STOCK_REGISTRY), "| company universe:", len(app._COMPANY_UNIVERSE))

queries = sys.argv[1:] or [
    "Prime Fresh", "prime fresh", "PRIME FRESH", "PrimeFresh", "PRIMEFRESH", "Prime Fresh Ltd",
    "TCS", "Tata Consultancy Services", "HINDUNILVR", "Hindustan Unilever", "Reliance", "Reliance Industries",
    "540404", "500696", "INE442V01012", "zzzzqqq", "primefresh limited",
]
for q in queries:
    res = app._company_index().search(q, limit=4)
    top = [f"{r['symbol']}[{'/'.join(r['exchanges']) or '-'}|{r['match']}]" for r in res]
    print(f"{q!r:32} -> resolve={app.resolve_symbol_from_registry(q)!r:18} search={top}")
