"""Remove a company's records (by internal symbol) from the canonical store and every
derived layer, safely.

    # plan only - touches nothing
    venv/Scripts/python.exe tools/remove_company_records.py SYM1 SYM2
    # do it
    venv/Scripts/python.exe tools/remove_company_records.py SYM1 SYM2 --apply \
        --backup-dir ../_removed_records/<name> [--extra-file cache/x/y.json ...]

What it does (in order), and why it is safe:
  1. Counts every database row keyed on the symbols, and every file whose NAME carries
     the symbol as an exact token (not a substring - a different company whose symbol
     merely contains the text is never matched).
  2. Writes a full JSON snapshot of all database rows and moves (never deletes) the
     files into the backup dir, preserving their relative paths - fully restorable.
  3. Verifies the snapshot row counts equal the live counts BEFORE deleting anything.
  4. Deletes child rows explicitly, then the `companies` row, then re-counts: every
     table must read zero or the run reports failure.

Only symbols named on the command line are ever touched.
"""
import argparse
import datetime
import json
import os
import re
import shutil
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)
from tools.supabase_client import get_client  # noqa: E402

# children first, `companies` last. All keyed on a `symbol` column.
SYMBOL_TABLES = [
    "extracted_values", "uploaded_documents", "fundamental_analysis_results",
    "qualitative_values", "qualitative_research_jobs", "ratio_values", "refresh_jobs",
    "price_eod", "price_intraday", "chat_messages", "companies",
]
FILE_ROOTS = ["cache", "uploads"]
PAGE = 1000


def fetch_all(sb, table, symbols):
    rows, start = [], 0
    while True:
        chunk = (sb.table(table).select("*").in_("symbol", symbols).range(start, start + PAGE - 1).execute().data or [])
        rows.extend(chunk)
        if len(chunk) < PAGE:
            return rows
        start += PAGE


def count_rows(sb, table, symbols):
    return sb.table(table).select("symbol", count="exact").in_("symbol", symbols).limit(1).execute().count


def token_regex(symbols):
    alt = "|".join(re.escape(s) for s in symbols)
    return re.compile(rf"(^|[_.\-]|\s)(?:{alt})([_.\-]|\s|$)", re.IGNORECASE)


def find_files(symbols, extra):
    rx = token_regex(symbols)
    hits, substring_only = [], []
    for base in FILE_ROOTS:
        for dirpath, dirnames, filenames in os.walk(os.path.join(ROOT, base)):
            rel_dir = os.path.relpath(dirpath, ROOT)
            # a directory named for the symbol (uploads/<SYMBOL>/) is taken whole
            if rx.search(os.path.basename(dirpath)):
                hits.append(("dir", rel_dir))
                dirnames[:] = []
                continue
            for fn in filenames:
                p = os.path.join(rel_dir, fn)
                if rx.search(fn):
                    hits.append(("file", p))
                elif any(s.lower() in fn.lower() for s in symbols):
                    substring_only.append(p)  # similar string, NOT this company - reported, never touched
    for e in extra:
        if os.path.exists(os.path.join(ROOT, e)):
            hits.append(("file", e))
    return hits, substring_only


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("symbols", nargs="+")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--backup-dir")
    ap.add_argument("--extra-file", action="append", default=[], help="project-relative file to move too")
    a = ap.parse_args()
    symbols = [s.upper() for s in a.symbols]
    sb = get_client()

    live = {t: count_rows(sb, t, symbols) for t in SYMBOL_TABLES}
    print("== database rows keyed on", symbols, "==")
    for t, n in live.items():
        print(f"  {t:32} {n}")
    hits, substring_only = find_files(symbols, a.extra_file)
    n_files = sum(1 for k, _ in hits if k == "file")
    print(f"== files: {n_files} files + {sum(1 for k, _ in hits if k == 'dir')} dirs by exact symbol token ==")
    print(f"== similar-name files NOT matched (left alone): {len(substring_only)} ==")
    for p in substring_only[:10]:
        print("   ", p)
    if not a.apply:
        print("\nDRY RUN - nothing changed. Re-run with --apply --backup-dir <dir>.")
        return 0
    if not a.backup_dir:
        print("--backup-dir is required with --apply")
        return 2

    backup = os.path.abspath(a.backup_dir)
    os.makedirs(backup, exist_ok=True)

    # 2a. full row snapshot
    snapshot = {t: fetch_all(sb, t, symbols) for t in SYMBOL_TABLES if live[t]}
    with open(os.path.join(backup, "db_snapshot.json"), "w", encoding="utf-8") as fh:
        json.dump({"symbols": symbols, "taken_at": datetime.datetime.now().isoformat(), "rows": snapshot}, fh, default=str, indent=1)
    # 3. snapshot must equal live before any delete
    for t, rows in snapshot.items():
        if len(rows) != live[t]:
            print(f"ABORT: snapshot of {t} has {len(rows)} rows but live count is {live[t]}")
            return 1
    print(f"snapshot saved ({sum(len(r) for r in snapshot.values())} rows) -> {backup}")

    # 4. delete rows: children first, companies last
    for t in SYMBOL_TABLES:
        if live[t]:
            sb.table(t).delete().in_("symbol", symbols).execute()
            print(f"  deleted {live[t]:>5} from {t}")

    # 2b. move files into the backup (restorable), preserving relative paths
    moved = 0
    for kind, rel in hits:
        src = os.path.join(ROOT, rel)
        if not os.path.exists(src):
            continue
        dst = os.path.join(backup, "files", rel)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.move(src, dst)
        moved += 1
    print(f"  moved {moved} file/dir entries -> {os.path.join(backup, 'files')}")

    # verify zero
    after = {t: count_rows(sb, t, symbols) for t in SYMBOL_TABLES}
    bad = {t: n for t, n in after.items() if n}
    print("== after: ", "all tables ZERO" if not bad else f"NON-ZERO: {bad}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
