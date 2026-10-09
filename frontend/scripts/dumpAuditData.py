"""Dump real candles for the pattern audit (run from the repo root):
    venv/Scripts/python.exe frontend/scripts/dumpAuditData.py TCS 2026-10-01
Writes frontend/.audit-data/<SYMBOL>/{intraday,daily,weekly,day}.json (gitignored).
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from tools.live_chart_yf import get_candles, get_session_with_warmup  # noqa: E402

symbol = sys.argv[1] if len(sys.argv) > 1 else "TCS"
date = sys.argv[2] if len(sys.argv) > 2 else None
out = os.path.join(os.path.dirname(__file__), "..", ".audit-data", symbol)
os.makedirs(out, exist_ok=True)
json.dump(get_candles(symbol, "5m"), open(os.path.join(out, "intraday.json"), "w"))
json.dump(get_candles(symbol, "1d", "5y"), open(os.path.join(out, "daily.json"), "w"))
json.dump(get_candles(symbol, "1wk", "5y"), open(os.path.join(out, "weekly.json"), "w"))
if date:
    s, w = get_session_with_warmup(symbol, date)
    json.dump({"candles": s, "warmup": w}, open(os.path.join(out, "day.json"), "w"))
print("wrote", out)
