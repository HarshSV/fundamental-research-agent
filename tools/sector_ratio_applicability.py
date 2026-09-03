"""
Sector applicability for the 8 bank/NBFC-specific ratios (Sr 58-65: NIM,
CASA, Gross NPA, Net NPA, PCR, CRAR, Credit-to-Deposit, Cost-to-Income),
transcribed from "Ratio_Sheet_V8_patched 2.xls", sheet "Sector
Applicability Matrix". Every one of these 8 rows is Core ('C') only for
Banks and NBFC and Not Applicable ('N') for all other 24 sectors in the
26-sector taxonomy (including Insurance, which uses its own separate
Solvency/Combined/Claims Ratio set, not this bank block) - a uniform rule
across all 8, so this is a single applicable-sector set rather than a
per-ratio table.

Sector labels match tools/nse_sector_map.py:get_nse_sector()'s verbatim
NSE sector strings (same 26-sector taxonomy as frontend/src/lib/
sectorMatrix.js).
"""

BANK_RATIO_KEYS = {
    "net_interest_margin", "casa_ratio", "gross_npa_pct", "net_npa_pct",
    "provision_coverage_ratio", "capital_adequacy_ratio",
    "credit_to_deposit_ratio", "cost_to_income_ratio",
}

_APPLICABLE_SECTORS = {"Banks", "NBFC"}


def is_bank_ratio_applicable(sector):
    """True if `sector` (an nse_sector_map.get_nse_sector() value) is a
    sector where the bank/NBFC ratio block (Sr 58-65) is Core. Unknown/
    unresolved sector is treated as NOT applicable (never guess a company
    is a bank without a real sector match)."""
    return sector in _APPLICABLE_SECTORS
