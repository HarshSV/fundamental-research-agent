"""Assemble the full daily-phase report (all numbers computed from the stored data and the OOS files - none typed in)."""
import json
import os

import numpy as np
import pandas as pd

from .. import config, evaluate, store
from . import dataset, gate, long_horizon, quality, report, universe
from .features import WARMUP_BARS
from .labels import LONG_H, SHORT_H


def coverage_section(con, cfg):
    rows = []
    for s in cfg["indices"] + cfg["symbols"]:
        r = con.execute("SELECT count(*), min(date), max(date) FROM daily_candles WHERE symbol=?", (s,)).fetchone()
        q = con.execute("SELECT count(*), sum(verified) FROM daily_session_quality WHERE symbol=?", (s,)).fetchone()
        fl = dict(con.execute("SELECT flag, count(*) FROM daily_quality_flags WHERE symbol=? GROUP BY flag", (s,)).fetchall())
        rows.append({"symbol": s, "kind": "index" if s in cfg["indices"] else "equity", "bars": r[0], "first": r[1], "last": r[2], "sessions": q[0],
                     "verified": q[1], "verified_pct": round(100 * (q[1] or 0) / max(q[0], 1), 2), "missing_sessions": fl.get("missing_session", 0),
                     "zero_volume": fl.get("zero_volume", 0), "flat_bars": fl.get("flat_bar", 0), "ohlc_invalid": fl.get("ohlc_invalid", 0),
                     "extreme_moves": fl.get("extreme_move", 0), "unadjusted_suspect": fl.get("possible_unadjusted_corporate_action", 0)})
    df = pd.DataFrame(rows)
    eq = df[df["kind"] == "equity"]
    flags = con.execute("SELECT flag, severity, count(*) FROM daily_quality_flags GROUP BY flag, severity ORDER BY 3 DESC").fetchall()
    fetch = con.execute("SELECT status, count(*) FROM daily_fetch_log GROUP BY status").fetchall()
    total_bars = int(eq["bars"].sum())
    out = ["## 1. Daily data coverage\n",
           f"Equities: {len(eq)} | indices: {int((df['kind'] == 'index').sum())} | equity bars stored: {total_bars:,} | "
           f"history {eq['first'].min()} .. {eq['last'].max()} | median bars/equity: {int(eq['bars'].median()):,} | "
           f"equities with >=15y: {int((eq['bars'] >= 3750).sum())} | >=20y: {int((eq['bars'] >= 5000).sum())}",
           f"Provider fetch log (chunks): {dict(fetch)}",
           "```\n" + df.to_string(index=False) + "\n```",
           "## 2. Missing / gap statistics and data-quality problems\n",
           f"Flags (flag, severity, count): {flags}",
           f"Equities: verified-session share min/median = {eq['verified_pct'].min()}% / {eq['verified_pct'].median()}%; total missing sessions = {int(eq['missing_sessions'].sum())}; "
           f"flat bars = {int(eq['flat_bars'].sum())}; zero-volume = {int(eq['zero_volume'].sum())}; invalid OHLC = {int(eq['ohlc_invalid'].sum())}; "
           f"real extreme moves kept = {int(eq['extreme_moves'].sum())}; suspected unadjusted corporate actions = {int(eq['unadjusted_suspect'].sum())}",
           "Worst symbols by missing sessions: " + ", ".join(f"{r.symbol}={r.missing_sessions}" for r in eq.sort_values("missing_sessions", ascending=False).head(6).itertuples()),
           "Worst by flat bars: " + ", ".join(f"{r.symbol}={r.flat_bars}" for r in eq.sort_values("flat_bars", ascending=False).head(6).itertuples()),
           "Suspected unadjusted corporate actions (fatal, excluded): " + str(con.execute("SELECT symbol,date,detail FROM daily_quality_flags WHERE flag='possible_unadjusted_corporate_action'").fetchall()),
           "Invalid OHLC bars (excluded): " + str(con.execute("SELECT symbol,date FROM daily_quality_flags WHERE flag='ohlc_invalid' ORDER BY symbol,date").fetchall()),
           "Special-session days (bars on a consensus non-trading day, excluded): " + str(con.execute("SELECT date,count(*) FROM daily_quality_flags WHERE flag='bars_on_closed_session' GROUP BY date").fetchall()),
           ]
    return "\n".join(out)


def features_section(fcols):
    return "## 3. Daily feature list\n\n" + f"{len(fcols)} features (warm-up {WARMUP_BARS} bars per contiguous segment):\n\n" + ", ".join(fcols) + "\n"


def main():
    con = store.connect()
    cfg = universe.load()
    parts = [f"# Navrist daily forecasting - phase report\n", coverage_section(con, cfg)]
    sh = pd.read_parquet(os.path.join(config.DATA_DIR, "daily_oos_short.parquet"))
    M, fcols, skipped = dataset.load_pooled(con, cfg["symbols"][:3], SHORT_H, lambda *_: None)
    parts.append(features_section(fcols))
    text, bt = report.build(sh, "short")
    parts.append("## 4-9. Short-horizon walk-forward (baselines, models, +1/+3/+5/+10/+20, calibration, per-symbol, per-regime)\n")
    parts.append(text)
    g = gate.daily_gate(sh, "ens", SHORT_H)
    parts.append("## Promotion-gate evaluation (ensemble), pre-registered criteria\n```\n" + json.dumps({h: {k: (v if not isinstance(v, tuple) else list(v)) for k, v in d.items()} for h, d in g["horizons"].items()}, indent=1, default=float) + "\n```")
    lp = os.path.join(config.DATA_DIR, "daily_oos_long.parquet")
    if os.path.exists(lp):
        lg = pd.read_parquet(lp)
        ML, _, _ = dataset.load_pooled(con, cfg["symbols"], LONG_H, lambda *_: None)
        parts.append("## 10. Long-horizon investigation\n### Independent evidence\n```\n" + long_horizon.independence_report(ML, LONG_H).to_string(index=False) + "\n```")
        mods = [m for m in ("gbm", "har", "ens") if f"{m}_ret_{LONG_H[0]}" in lg]
        parts.append("### Pre-registered validation of each long horizon\n```\n" + long_horizon.assess(lg, mods + ["hist_vol"], LONG_H).to_string(index=False) + "\n```")
        parts.append("### Long-horizon walk-forward metrics\n```\n" + evaluate.report(lg, mods + report.BASELINES, LONG_H, "rv20").to_string(index=False, float_format=lambda x: f"{x:.4f}") + "\n```")
    out = os.path.join(config.ROOT, "docs", "daily_validation_2026-10.md")
    open(out, "w", encoding="utf-8").write("\n\n".join(parts))
    print("[final report]", out)


if __name__ == "__main__":
    main()
