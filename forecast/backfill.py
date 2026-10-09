"""CLI: python -m forecast.backfill --symbols RELIANCE TCS --years 3
Resumable: re-running only fetches chunks that are missing/open/errored."""
import argparse
import json

from . import collector, config, store

DEFAULT_PILOT = ["NIFTY 50", "RELIANCE", "TCS", "HDFCBANK", "INFY", "ICICIBANK", "SBIN", "ITC", "LT"]


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", nargs="+", default=DEFAULT_PILOT)
    ap.add_argument("--years", type=float, default=3.0)
    ap.add_argument("--interval", default=config.INTERVAL)
    ap.add_argument("--min-delay", type=float, default=2.0)
    ap.add_argument("--cooldown", type=float, default=20.0)
    ap.add_argument("--max-delay", type=float, default=12.0)
    a = ap.parse_args(argv)
    con = store.connect()
    client = collector.AngelHistory(min_delay=a.min_delay, max_delay=a.max_delay, cooldown=a.cooldown)
    client.login()
    for sym in a.symbols:
        res = collector.backfill_symbol(client, con, sym, a.interval, a.years)
        print(json.dumps(res, default=str), flush=True)
    print(f"[done] requests={client.requests} rate_limit_hits={client.rate_limit_hits} final_delay={client.delay:.1f}s", flush=True)


if __name__ == "__main__":
    main()
