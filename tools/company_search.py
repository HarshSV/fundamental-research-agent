"""Company search + resolution over the application's EXISTING company master
(app.py's STOCK_REGISTRY, which is the NSE universe merged with the Supabase
`companies` table). This module owns no data of its own - it only ranks and
resolves entries of that registry, so there is one company universe and one
matching implementation.

Identity is company-first, not symbol-first: an entry carries
    symbol        the application's key (what research / documents are stored under)
    name          company name
    isin, bse_code
    exchanges     ['NSE', 'BSE'] where it trades (NSE/BSE availability, not a guess)
    alias_symbols other symbols that mean the same company (e.g. a BSE trading
                  symbol stored as a placeholder row next to the real one)

Ranking (strongest first):
    1 symbol   exact symbol / alias / BSE scrip code / ISIN
    2 name     exact company name (normalised)
    3 prefix   symbol or name starts with the query
    4 contains substring of symbol/name, or every query word is in the name
    5 fuzzy    small typo tolerance only (never for short queries)
"""

import re
from difflib import SequenceMatcher

# Trailing legal-form words that people omit when typing a name.
_LEGAL_SUFFIXES = {
    "limited", "ltd", "pvt", "private", "public", "inc", "corp", "corporation",
    "co", "company", "plc", "llp", "the",
}

MATCH_SYMBOL, MATCH_NAME, MATCH_PREFIX, MATCH_CONTAINS, MATCH_FUZZY = (
    "symbol", "name", "prefix", "contains", "fuzzy",
)
_TIER = {MATCH_SYMBOL: 1, MATCH_NAME: 2, MATCH_PREFIX: 3, MATCH_CONTAINS: 4, MATCH_FUZZY: 5}


def normalize(text):
    """lower-case, '&' -> 'and', punctuation -> space, whitespace collapsed."""
    s = str(text or "").lower().replace("&", " and ")
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def strip_legal(norm_text):
    toks = norm_text.split()
    while toks and toks[-1] in _LEGAL_SUFFIXES:
        toks.pop()
    while toks and toks[0] == "the":
        toks.pop(0)
    return " ".join(toks)


def compact(norm_text):
    return norm_text.replace(" ", "")


def _is_placeholder(item):
    """A row minted from a bare slug: name is just the symbol, no identifiers."""
    return (
        normalize(item.get("name")) == normalize(item.get("symbol"))
        and not item.get("isin")
        and not item.get("bse_code")
    )


class CompanyIndex:
    """Precomputed normalised forms of a registry. Rebuild when the registry changes."""

    def __init__(self, registry):
        rows = []
        for i, item in enumerate(registry):
            sym = str(item.get("symbol") or "").strip()
            if not sym:
                continue
            name_n = strip_legal(normalize(item.get("name") or sym))
            rows.append({
                "item": item, "order": i,
                "sym_c": compact(normalize(sym)),
                "name_n": name_n, "name_c": compact(name_n),
                "tokens": set(name_n.split()),
                "aliases_c": set(),
                "alias_syms": [],
                "placeholder": _is_placeholder(item),
                "bse_code": str(item.get("bse_code") or "").strip(),
                "isin": str(item.get("isin") or "").strip().upper(),
            })
        # Fold placeholder rows into the real company they duplicate: a
        # placeholder whose symbol equals another row's compact company name
        # (e.g. symbol PRIMEFRESH vs "Prime Fresh Limited") is just that
        # company's trading symbol / slug, not a second company.
        by_name = {}
        for r in rows:
            if not r["placeholder"] and r["name_c"]:
                by_name.setdefault(r["name_c"], r)
        self.rows = []
        for r in rows:
            target = by_name.get(r["sym_c"]) if r["placeholder"] else None
            if target is not None and target is not r:
                target["aliases_c"].add(r["sym_c"])
                target["alias_syms"].append(r["item"]["symbol"])
            else:
                self.rows.append(r)
        self.by_symbol = {}
        for r in self.rows:
            self.by_symbol[r["item"]["symbol"].upper()] = r
            for a in r["alias_syms"]:
                self.by_symbol.setdefault(a.upper(), r)

    # -- scoring -----------------------------------------------------------------
    def _match(self, r, q_raw, q_n, q_c, q_tokens, allow_fuzzy):
        if not q_c:
            return None
        if (q_c == r["sym_c"] or q_c in r["aliases_c"]
                or (q_raw.isdigit() and r["bse_code"] == q_raw)
                or (r["isin"] and q_raw.upper() == r["isin"])):
            return MATCH_SYMBOL
        q_name_c = compact(strip_legal(q_n))
        if q_name_c and q_name_c == r["name_c"]:
            return MATCH_NAME
        if r["sym_c"].startswith(q_c) or r["name_c"].startswith(q_c) or any(a.startswith(q_c) for a in r["aliases_c"]):
            return MATCH_PREFIX
        if len(q_c) >= 3:
            # a symbol is an arbitrary token, so substring-in-symbol needs a longer query
            if q_c in r["name_c"] or (len(q_c) >= 5 and q_c in r["sym_c"]):
                return MATCH_CONTAINS
            if len(q_tokens) >= 2 and q_tokens <= r["tokens"]:
                return MATCH_CONTAINS
        if allow_fuzzy and len(q_c) >= 5:
            # typo tolerance against the company name (whole, and same-length prefix)
            cands = [r["name_c"], r["name_c"][: len(q_c) + 1]]
            if any(c and c[0] == q_c[0] and SequenceMatcher(None, q_c, c).ratio() >= 0.88 for c in cands):
                return MATCH_FUZZY
        return None

    def search(self, query, limit=10):
        q_raw = str(query or "").strip()
        q_n = normalize(q_raw)
        q_c = compact(q_n)
        if not q_c:
            return []
        q_tokens = set(strip_legal(q_n).split()) or set(q_n.split())
        scored = []
        for r in self.rows:
            m = self._match(r, q_raw, q_n, q_c, q_tokens, allow_fuzzy=False)
            if m:
                scored.append((_TIER[m], r["order"], m, r))
        if not scored:  # fuzzy only as a last resort, so it can never outrank a real match
            for r in self.rows:
                m = self._match(r, q_raw, q_n, q_c, q_tokens, allow_fuzzy=True)
                if m == MATCH_FUZZY:
                    scored.append((_TIER[m], r["order"], m, r))
        # tier, then shorter (more specific) names first, then registry order
        scored.sort(key=lambda t: (t[0], len(t[3]["name_c"]), t[1]))
        out, seen = [], set()
        for _, _, m, r in scored:
            sym = r["item"]["symbol"]
            if sym in seen:
                continue
            seen.add(sym)
            out.append(describe(r["item"], m, r["alias_syms"]))
            if len(out) >= limit:
                break
        return out

    def resolve(self, query):
        """Strict resolution for API plumbing: a symbol/name/prefix/all-words match, never fuzzy.
        Returns the registry item or None."""
        for hit in self.search(query, limit=5):
            if hit["match"] in (MATCH_SYMBOL, MATCH_NAME, MATCH_PREFIX, MATCH_CONTAINS):
                r = self.by_symbol.get(hit["symbol"].upper())
                return r["item"] if r else None
            break
        return None


def describe(item, match=None, alias_symbols=None):
    exchanges = list(item.get("exchanges") or [])
    out = {
        "symbol": item["symbol"],
        "name": item.get("name") or item["symbol"],
        "isin": item.get("isin") or None,
        "bse_code": item.get("bse_code") or None,
        "exchanges": exchanges,
        "primary_exchange": exchanges[0] if exchanges else None,
    }
    if alias_symbols:
        out["alias_symbols"] = list(alias_symbols)
    if match:
        out["match"] = match
    return out
