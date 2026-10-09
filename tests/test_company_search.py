"""
Company search / resolution (tools/company_search.py).

Synthetic registry only - the same shapes the real universe has (an NSE+BSE
company, a BSE-only company stored under a legacy symbol with a placeholder
duplicate row, similarly named companies for ranking) but never a real
company. Real-universe checks live in tests/company_search_probe.py.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from tools.company_search import CompanyIndex, normalize, strip_legal  # noqa: E402

REGISTRY = [
    # NSE + BSE company
    {"symbol": "NORTHCS", "name": "Northwind Consultancy Services Limited", "bse_code": "500111", "exchanges": ["NSE", "BSE"]},
    {"symbol": "NORTHPWR", "name": "Northwind Power Limited", "bse_code": "500112", "exchanges": ["NSE", "BSE"]},
    {"symbol": "NORTHWIND", "name": "Northwind Industries Limited", "exchanges": ["NSE"]},
    {"symbol": "NORTH", "name": "North Star Holdings Limited", "exchanges": ["NSE"]},
    # BSE-only company stored under a legacy symbol, with its real data (ISIN, scrip code) ...
    {"symbol": "OLDNAMEFOODS", "name": "Acme Fresh Foods Limited", "isin": "INE000A01012", "bse_code": "540999", "exchanges": ["BSE"]},
    # ... plus the placeholder row minted from the bare slug of the same company
    {"symbol": "ACMEFRESHFOODS", "name": "ACMEFRESHFOODS", "exchanges": []},
    # unrelated
    {"symbol": "ZENITH", "name": "Zenith Agro Products Limited", "exchanges": ["NSE"]},
    {"symbol": "AB&CO", "name": "A & B Company Limited", "exchanges": ["NSE"]},
    {"symbol": "TATAXYZ", "name": "Tata Xyz Limited", "exchanges": ["NSE"]},
]
IDX = CompanyIndex(REGISTRY)


def top(q):
    r = IDX.search(q, limit=5)
    return r[0]["symbol"] if r else None


# -- Prime-Fresh-shaped lookups: every spelling reaches the SAME company ------------------
def test_all_spellings_resolve_to_one_company():
    for q in ["Acme Fresh Foods", "acme fresh foods", "ACME FRESH FOODS", "AcmeFreshFoods", "ACMEFRESHFOODS",
              "Acme Fresh Foods Ltd", "acme fresh foods limited", "  acme   fresh  foods  "]:
        assert top(q) == "OLDNAMEFOODS", q


def test_placeholder_row_is_folded_not_a_second_company():
    hits = IDX.search("acme fresh", limit=10)
    assert [h["symbol"] for h in hits] == ["OLDNAMEFOODS"]
    assert "ACMEFRESHFOODS" in hits[0]["alias_symbols"]


def test_bse_scrip_code_and_isin_resolve():
    assert top("540999") == "OLDNAMEFOODS"
    assert top("INE000A01012") == "OLDNAMEFOODS"
    assert top("ine000a01012") == "OLDNAMEFOODS"


def test_exchanges_are_reported_per_company():
    by = {h["symbol"]: h for h in IDX.search("northwind", limit=10)}
    assert by["NORTHCS"]["exchanges"] == ["NSE", "BSE"]
    assert by["NORTHCS"]["primary_exchange"] == "NSE"
    assert by["NORTHWIND"]["exchanges"] == ["NSE"]
    acme = IDX.search("acme fresh")[0]
    assert acme["exchanges"] == ["BSE"] and acme["primary_exchange"] == "BSE"
    assert acme["bse_code"] == "540999" and acme["isin"] == "INE000A01012"


# -- ranking ------------------------------------------------------------------------------
def test_ranking_exact_symbol_then_exact_name_then_prefix_then_contains():
    hits = IDX.search("north")
    assert hits[0]["symbol"] == "NORTH" and hits[0]["match"] == "symbol"          # exact symbol first
    assert {h["match"] for h in hits[1:]} == {"prefix"}                            # then starts-with names
    assert IDX.search("northwind industries")[0]["match"] == "name"                # exact name
    assert IDX.search("northwind industries")[0]["symbol"] == "NORTHWIND"
    contains = IDX.search("consultancy services")
    assert contains and contains[0]["symbol"] == "NORTHCS" and contains[0]["match"] == "contains"


def test_partial_and_full_names():
    assert top("Northwind Consultancy") == "NORTHCS"
    assert top("northwind consultancy services") == "NORTHCS"
    assert top("Northwind Consultancy Services Limited") == "NORTHCS"
    assert top("Zenith Agro") == "ZENITH"


def test_case_and_symbol_variants():
    assert top("northcs") == "NORTHCS" and top("NorthCS") == "NORTHCS"
    assert top("zenith") == "ZENITH"


def test_ampersand_and_punctuation_variants():
    assert top("A & B Company") == "AB&CO"
    assert top("a and b company") == "AB&CO"
    assert top("A&B Co") == "AB&CO"
    assert top("ab&co") == "AB&CO"
    assert normalize("A & B Co.") == "a and b co"


def test_legal_suffix_normalisation():
    assert strip_legal(normalize("Zenith Agro Products Ltd.")) == "zenith agro products"
    assert strip_legal(normalize("The Tata Xyz Pvt Ltd")) == "tata xyz"
    assert top("Zenith Agro Products Ltd") == "ZENITH"


# -- fuzzy must stay conservative -------------------------------------------------------------
def test_fuzzy_catches_a_typo_only_as_last_resort():
    hits = IDX.search("zenth agro products")
    assert hits and hits[0]["symbol"] == "ZENITH" and hits[0]["match"] == "fuzzy"


def test_fuzzy_never_returns_unrelated_companies():
    for q in ["qqqzzzxx", "xylophone", "zzzzqqq", "qz", "q"]:
        assert IDX.search(q) == [], q


def test_fuzzy_does_not_fire_when_a_real_match_exists():
    assert all(h["match"] != "fuzzy" for h in IDX.search("northwind"))


def test_short_queries_do_not_substring_match_everything():
    assert IDX.search("u") == []                       # not a prefix of any symbol/name here
    assert all(h["match"] in ("symbol", "prefix") for h in IDX.search("no"))


# -- strict resolver (API plumbing) ---------------------------------------------------------------
def test_resolve_returns_company_item_and_never_fuzzy():
    assert IDX.resolve("acme fresh foods")["symbol"] == "OLDNAMEFOODS"
    assert IDX.resolve("Tata Xyz")["symbol"] == "TATAXYZ"
    assert IDX.resolve("zenth agro products") is None          # typo-only is not strong enough to resolve
    assert IDX.resolve("totally unknown co") is None


def test_synthetic_upload_slug_is_never_resolved_to_a_company():
    # A slug like ACMEFRESHFOODSLIM (symbol + legal tail) must not be auto-attached to any
    # company by the strict resolver, and the search box may only offer it as a typo-tier
    # suggestion the user still has to pick.
    assert IDX.resolve("ACMEFRESHFOODSLIM") is None
    assert all(h["match"] == "fuzzy" for h in IDX.search("ACMEFRESHFOODSLIM"))


def test_every_hit_carries_company_identity_fields():
    for h in IDX.search("northwind"):
        assert set(["symbol", "name", "isin", "bse_code", "exchanges", "primary_exchange", "match"]) <= set(h)


def test_empty_and_whitespace_queries():
    assert IDX.search("") == [] and IDX.search("   ") == [] and IDX.search("!!!") == []


if __name__ == "__main__":  # no pytest in the project venv: run every test_* directly
    failed = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"PASS {name}")
            except AssertionError as e:
                failed += 1
                print(f"FAIL {name}: {e}")
    sys.exit(1 if failed else 0)
