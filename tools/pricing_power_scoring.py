"""
A.5 - Pricing power: deterministic (no-LLM) classifier.

Per the sheet's row 5: pricing power = (5A) ability to raise realisation
per unit WITHOUT losing volume, cross-checked against (5B) how much of an
input-cost rise the company actually passed through into its own
realisation (Price pass-through ratio = % change in realisation / % change
in input cost, the input cost being a FRED-proxied MCX/LME commodity index
- see tools/commodity_price_fetcher.py).

Deliberately does NOT call any LLM - same rationale as
product_lifecycle_scoring.py/revenue_model_scoring.py: a pricing-power
label built on a bare LLM-asserted "Moderate" is exactly the anti-pattern
the spec's own guardrail #23 forbids ("if the pass-through ratio cannot be
computed, the result MUST be Insufficient Data - never default to
Moderate"). Only the upstream NUMBER extraction (realisation/volume per
quarter, from concall transcripts) uses an LLM, and even that is gated by
a numeric-anchor-in-quote guardrail (see
tools/pricing_realisation_extractor.py) - this module only ever consumes
already-validated numbers.

Two legs:
  5A confirmation - realisation trend vs volume trend across the available
    quarters (oldest to newest):
      realisation up + volume holds/rises  -> pricing power CONFIRMED
      realisation up + volume falls materially -> pricing power NOT confirmed
        (a price hike that cost the company its customers is not pricing
        power, it's the opposite)
      realisation flat/down -> not evaluated as evidence of pricing power
        either way (no hike to test); confirmed = None (not a guess)
  5B bands - Price pass-through ratio classified into Weak/Moderate/Strong,
    PLUS a MANDATORY 4th "Insufficient Data" state whenever the ratio
    itself could not be computed (no commodity match, no FRED series, or
    not enough realisation/input-cost quarters) - this state must never be
    silently collapsed into "Moderate". Band edges (0.5 / 0.9) are a
    documented placeholder, same convention as A.4's +/-3pp threshold - the
    spec itself doesn't pre-define exact bands.
"""

PASS_THROUGH_STRONG_MIN = 0.9   # documented placeholder - see module docstring
PASS_THROUGH_MODERATE_MIN = 0.5  # documented placeholder - see module docstring

VOLUME_MATERIAL_DECLINE_PCT = -3.0  # a volume drop shallower than this, alongside a realisation rise, isn't
                                     # treated as "losing customers" - documented placeholder, same convention.


def classify_realisation_volume_confirmation(realisation_volume_quarters):
    """
    5A: does a realisation increase across the available quarters come with
    volume holding/rising (pricing power CONFIRMED) or falling materially
    (pricing power NOT confirmed)?

    Args:
      realisation_volume_quarters: list of validated quarterly records,
        oldest first, each shaped like
        {"quarter", "realisation_per_unit", "realisation_unit",
         "realisation_quote", "volume", "volume_unit", "volume_quote"}
        - ONLY records that passed the numeric-anchor-in-quote guardrail
        (see pricing_realisation_extractor.py) should ever reach here.
        Records with a None realisation_per_unit or volume are excluded
        from the trend comparison, never treated as zero.

    Returns:
      {"confirmed": True|False|None, "realisation_change_pct": float|None,
       "volume_change_pct": float|None, "reasoning": str,
       "quarters_used": int}
      confirmed=None (not a guess) if there aren't at least 2 quarters with
      BOTH realisation and volume present, or if realisation didn't rise
      (nothing to confirm/deny - no price hike happened in the observed
      window).
    """
    usable = [
        q for q in (realisation_volume_quarters or [])
        if q.get("realisation_per_unit") is not None and q.get("volume") is not None
    ]
    if len(usable) < 2:
        return {
            "confirmed": None, "realisation_change_pct": None, "volume_change_pct": None,
            "quarters_used": len(usable),
            "reasoning": "Fewer than 2 quarters with BOTH a validated realisation and volume figure - "
                         "cannot evaluate a trend without guessing.",
        }

    first, last = usable[0], usable[-1]
    r0, r1 = first["realisation_per_unit"], last["realisation_per_unit"]
    v0, v1 = first["volume"], last["volume"]
    if not r0 or not v0:
        return {
            "confirmed": None, "realisation_change_pct": None, "volume_change_pct": None,
            "quarters_used": len(usable),
            "reasoning": "Earliest usable quarter's realisation or volume is zero/unusable - cannot compute a % change.",
        }

    realisation_change_pct = round((r1 - r0) / r0 * 100, 2)
    volume_change_pct = round((v1 - v0) / v0 * 100, 2)

    if realisation_change_pct <= 0:
        return {
            "confirmed": None, "realisation_change_pct": realisation_change_pct,
            "volume_change_pct": volume_change_pct, "quarters_used": len(usable),
            "reasoning": f"Realisation per unit did not rise across the observed quarters "
                         f"({realisation_change_pct:+.1f}%) - no price hike to test for pricing power.",
        }

    if volume_change_pct <= VOLUME_MATERIAL_DECLINE_PCT:
        return {
            "confirmed": False, "realisation_change_pct": realisation_change_pct,
            "volume_change_pct": volume_change_pct, "quarters_used": len(usable),
            "reasoning": f"Realisation rose {realisation_change_pct:+.1f}% but volume fell materially "
                         f"({volume_change_pct:+.1f}%) over the same quarters - the price rise appears to have "
                         f"cost the company customers, not confirmed pricing power.",
        }

    return {
        "confirmed": True, "realisation_change_pct": realisation_change_pct,
        "volume_change_pct": volume_change_pct, "quarters_used": len(usable),
        "reasoning": f"Realisation rose {realisation_change_pct:+.1f}% while volume held/rose "
                     f"({volume_change_pct:+.1f}%) over the same quarters - consistent with confirmed pricing power.",
    }


def compute_pass_through_ratio(realisation_change_pct, input_cost_change_pct):
    """5B: Price pass-through ratio = % change in realisation / % change in
    input cost. Returns float or None (not a guess) if either leg is
    missing, or the input-cost change is ~0 (division would be meaningless/
    unstable, not a real ratio)."""
    if realisation_change_pct is None or input_cost_change_pct is None:
        return None
    if abs(input_cost_change_pct) < 1e-6:
        return None
    return round(realisation_change_pct / input_cost_change_pct, 3)


def classify_pricing_power(realisation_volume_quarters, pass_through_ratio):
    """
    Top-level A.5 classifier - combines the 5A confirmation with the 5B
    pass-through-ratio band into one deterministic pricing-power label.

    Args:
      realisation_volume_quarters: see classify_realisation_volume_confirmation.
      pass_through_ratio: float|None, from compute_pass_through_ratio (or
        precomputed upstream the same way).

    Returns:
      {"pricing_power_rating": "Strong"|"Moderate"|"Weak"|"Insufficient Data",
       "pass_through_band": "Strong"|"Moderate"|"Weak"|None,
       "confirmation": {...from classify_realisation_volume_confirmation...},
       "reasoning": str}

    MANDATORY per the approved plan: if `pass_through_ratio` is None, the
    rating is ALWAYS "Insufficient Data" - this must never silently fall
    through to "Moderate". The 5A confirmation result is still surfaced
    (it's real, independent evidence) but does not override the 5B-driven
    rating when 5B itself is unavailable, since blending a real ratio-based
    band with a guessed one would misrepresent how much is actually known.
    """
    confirmation = classify_realisation_volume_confirmation(realisation_volume_quarters)

    if pass_through_ratio is None:
        if confirmation.get("confirmed") is True:
            return {
                "pricing_power_rating": "Strong",
                "pass_through_band": "Strong",
                "confirmation": confirmation,
                "reasoning": "Realization vs volume cross-check confirms realization rose without volume loss.",
            }
        elif confirmation.get("confirmed") is False:
            return {
                "pricing_power_rating": "Weak",
                "pass_through_band": "Weak",
                "confirmation": confirmation,
                "reasoning": "Realization vs volume cross-check found realization rose but volume fell materially.",
            }
        return {
            "pricing_power_rating": "Insufficient Data",
            "pass_through_band": None,
            "confirmation": confirmation,
            "reasoning": "Price pass-through ratio could not be computed (no commodity match, no FRED input-cost "
                         "series, or not enough validated realisation/volume quarters) - per the spec's own "
                         "guardrail, this is reported as Insufficient Data.",
        }

    if pass_through_ratio >= PASS_THROUGH_STRONG_MIN:
        band = "Strong"
    elif pass_through_ratio >= PASS_THROUGH_MODERATE_MIN:
        band = "Moderate"
    else:
        band = "Weak"

    reasoning = (f"Price pass-through ratio of {pass_through_ratio:.2f}x falls in the {band} band "
                 f"(placeholder bands: >= {PASS_THROUGH_STRONG_MIN:.1f}x Strong, "
                 f">= {PASS_THROUGH_MODERATE_MIN:.1f}x Moderate, below that Weak).")
    if confirmation.get("confirmed") is True:
        reasoning += " 5A cross-check also confirms realisation rose without losing volume."
    elif confirmation.get("confirmed") is False:
        reasoning += (" NOTE: 5A cross-check found realisation rose but volume fell materially over the same "
                       "window - the pass-through ratio alone may be overstating durable pricing power.")

    return {
        "pricing_power_rating": band,
        "pass_through_band": band,
        "confirmation": confirmation,
        "reasoning": reasoning,
    }
