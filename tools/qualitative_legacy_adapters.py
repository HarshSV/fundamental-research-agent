"""
Generic CASE-A legacy-scorer migration adapter (spec: "Migration Decision
Tree - CASE A: exact universal equivalence").

130 of `qualitative_engine.py`'s compute_* functions follow ONE identical
template (mechanically confirmed by parsing the module's own source via
`tools/extract_legacy_adapter_mapping.py`, not assumed or hand-surveyed):

    evidence = _fetch_ar_evidence_excerpts(sym, name, <ANCHORS>, <cache_prefix>, ...)
    text = " ".join(excerpt texts)
    result = <scoring_module>.<scorefn>(text)

`LEGACY_AR_TEXT_SCORER_ADAPTERS` below is GENERATED (paste-reviewed output
of that script) mapping each such task_id to the exact
(module, function, anchor-list, cache-prefix) the legacy compute_fn
already calls. `evaluate_via_legacy_scorer` calls those EXACT SAME
functions - not a reimplementation, not a re-derived approximation - so
behavioural equivalence is guaranteed BY CONSTRUCTION, satisfying the
decision tree's "only after equivalence is demonstrated, migrate"
requirement for every task in this table without hand-authoring 130
individual primitives (which would itself be a source of transcription
error the direct-call approach avoids entirely).

The anchor lists themselves are NOT copied - they are imported live from
`tools.qualitative_engine`'s own module-level constants (e.g.
`_T_1_1_ANCHORS`), so there is exactly one copy of each anchor list in the
codebase and a future edit to it is automatically picked up here too.

Result-shape normalization (`_normalize_scorer_result`) is the one generic
piece of new logic in this file - the 60+ distinct scoring functions
return a handful of common shapes (`(specific_bool_or_label, score)` tuples
from the shared `qualitative_evidence_scoring.score_evidence_tier`
convention, bare category-label strings from `classify_status`-based
functions, bare numeric scores, or a details dict with a `*_score`/`score`
key) - normalized generically by shape, never by guessing an individual
function's specific business meaning.
"""

from typing import Any, Optional, Tuple

from tools.qualitative_evidence import (
    Confidence, ConfidenceTier, EvidenceBundle, EvidenceStatus, QualitativeEvidence,
)
from tools.qualitative_source_router import resolve_availability

LEGACY_AR_TEXT_SCORER_ADAPTERS = {
    'A.5.A': {"module": 'business_model_gap_scoring', "scorefn": 'score_pricing_power_ability', "anchors_var": '_A5_A_ANCHORS', "cache_prefix": 'ar_a5_a_v1'},
    'A.5.B': {"module": 'business_model_gap_scoring', "scorefn": 'score_cost_passthrough', "anchors_var": '_A5_B_ANCHORS', "cache_prefix": 'ar_a5_b_v1'},
    'A.6.B': {"module": 'business_model_gap_scoring', "scorefn": 'score_exceptional_items', "anchors_var": '_A6_B_ANCHORS', "cache_prefix": 'ar_a6_b_v1'},
    'E.4.2': {"module": 'receivables_risk_scoring', "scorefn": 'score_receivables_ageing', "anchors_var": '_RECEIVABLES_AGEING_ANCHORS', "cache_prefix": 'ar_recvageing_text_v1'},
    'E.4.3': {"module": 'receivables_risk_scoring', "scorefn": 'score_revenue_recognition_risk', "anchors_var": '_REVENUE_RECOGNITION_ANCHORS', "cache_prefix": 'ar_revrec_text_v1'},
    'E.5.3': {"module": 'inventory_risk_scoring', "scorefn": 'score_inventory_obsolescence', "anchors_var": '_INVENTORY_OBSOLESCENCE_ANCHORS', "cache_prefix": 'ar_invobs_text_v1'},
    'E.7.1': {"module": 'accounting_policy_scoring', "scorefn": 'score_policy_changes', "anchors_var": '_ACCOUNTING_POLICY_ANCHORS', "cache_prefix": 'ar_policychg_text_v4'},
    'E.7.2': {"module": 'accounting_policy_scoring', "scorefn": 'score_estimate_changes', "anchors_var": '_ACCOUNTING_POLICY_ANCHORS', "cache_prefix": 'ar_policychg_text_v4'},
    'F.2.1': {"module": 'entry_barrier_scoring', "scorefn": 'score_entry_barriers', "anchors_var": '_ENTRY_BARRIER_ANCHORS', "cache_prefix": 'ar_entrybarrier_text_v1'},
    'G.1.1': {"module": 'channel_distribution_scoring', "scorefn": 'score_channel_mix', "anchors_var": '_CHANNEL_MIX_ANCHORS', "cache_prefix": 'ar_channelmix_text_v1'},
    'G.1.2': {"module": 'channel_distribution_scoring', "scorefn": 'score_channel_control', "anchors_var": '_CHANNEL_CONTROL_ANCHORS', "cache_prefix": 'ar_channelcontrol_text_v1'},
    'G.2.1': {"module": 'channel_distribution_scoring', "scorefn": 'score_channel_conflict', "anchors_var": '_CHANNEL_CONFLICT_ANCHORS', "cache_prefix": 'ar_channelconflict_text_v2'},
    'G.3.1': {"module": 'channel_distribution_scoring', "scorefn": 'score_contract_quality', "anchors_var": '_CONTRACT_QUALITY_ANCHORS', "cache_prefix": 'ar_contractquality_text_v1'},
    'G.3.2': {"module": 'channel_distribution_scoring', "scorefn": 'score_customer_retention', "anchors_var": '_CUSTOMER_RETENTION_ANCHORS', "cache_prefix": 'ar_custretention_text_v1'},
    'G.4.1': {"module": 'channel_distribution_scoring', "scorefn": 'score_distribution_reach', "anchors_var": '_DISTRIBUTION_REACH_ANCHORS', "cache_prefix": 'ar_distreach_text_v1'},
    'G.4.2': {"module": 'channel_distribution_scoring', "scorefn": 'score_peer_distribution_advantage', "anchors_var": '_PEER_DISTRIBUTION_ANCHORS', "cache_prefix": 'ar_peerdist_text_v1'},
    'H.1.2': {"module": 'product_tech_scoring', "scorefn": 'score_ip_expiry', "anchors_var": '_IP_EXPIRY_ANCHORS', "cache_prefix": 'ar_ipexpiry_text_v1'},
    'H.2.1': {"module": 'product_tech_scoring', "scorefn": 'score_rd_pipeline', "anchors_var": '_RD_PIPELINE_ANCHORS', "cache_prefix": 'ar_rdpipeline_text_v1'},
    'H.3.1': {"module": 'product_tech_scoring', "scorefn": 'score_legacy_dependence', "anchors_var": '_LEGACY_TECH_ANCHORS', "cache_prefix": 'ar_legacytech_text_v1'},
    'H.3.2': {"module": 'product_tech_scoring', "scorefn": 'score_cybersecurity_posture', "anchors_var": '_CYBERSECURITY_ANCHORS', "cache_prefix": 'ar_cybersec_text_v1'},
    'H.4.1': {"module": 'product_tech_scoring', "scorefn": 'score_thirdparty_tech_dependence', "anchors_var": '_THIRDPARTY_TECH_ANCHORS', "cache_prefix": 'ar_thirdpartytech_text_v1'},
    'H.4.2': {"module": 'product_tech_scoring', "scorefn": 'score_license_continuity_risk', "anchors_var": '_LICENSE_CONTINUITY_ANCHORS', "cache_prefix": 'ar_licensecontinuity_text_v1'},
    'I.1.1': {"module": 'supply_chain_scoring', "scorefn": 'score_single_source_risk', "anchors_var": '_SINGLE_SOURCE_ANCHORS', "cache_prefix": 'ar_singlesource_text_v1'},
    'I.1.2': {"module": 'supply_chain_scoring', "scorefn": 'score_geographic_concentration', "anchors_var": '_GEO_CONCENTRATION_ANCHORS', "cache_prefix": 'ar_geoconcentration_text_v1'},
    'I.1.3': {"module": 'supply_chain_scoring', "scorefn": 'score_inventory_buffers', "anchors_var": '_INVENTORY_BUFFER_ANCHORS', "cache_prefix": 'ar_invbuffer_text_v1'},
    'I.2.2': {"module": 'supply_chain_scoring', "scorefn": 'score_capacity_demand_balance', "anchors_var": '_CAPACITY_DEMAND_ANCHORS', "cache_prefix": 'ar_capacitydemand_text_v1'},
    'I.2.3': {"module": 'supply_chain_scoring', "scorefn": 'score_scale_constraints', "anchors_var": '_SCALE_CONSTRAINT_ANCHORS', "cache_prefix": 'ar_scaleconstraint_text_v1'},
    'I.3.1': {"module": 'supply_chain_scoring', "scorefn": 'score_price_protection', "anchors_var": '_PRICE_PROTECTION_ANCHORS', "cache_prefix": 'ar_priceprotection_text_v1'},
    'I.3.2': {"module": 'supply_chain_scoring', "scorefn": 'score_currency_protection', "anchors_var": '_CURRENCY_CLAUSE_ANCHORS', "cache_prefix": 'ar_currencyclause_text_v1'},
    'I.4.1': {"module": 'supply_chain_scoring', "scorefn": 'score_operational_efficiency', "anchors_var": '_LEADTIME_THROUGHPUT_ANCHORS', "cache_prefix": 'ar_leadtime_text_v1'},
    'I.4.2': {"module": 'supply_chain_scoring', "scorefn": 'score_quality_risk', "anchors_var": '_QUALITY_WARRANTY_ANCHORS', "cache_prefix": 'ar_qualitywarranty_text_v1'},
    'J.1.2': {"module": 'regulatory_legal_scoring', "scorefn": 'score_renewal_burden', "anchors_var": '_RENEWAL_BURDEN_ANCHORS', "cache_prefix": 'ar_renewalburden_text_v1'},
    'J.2.1': {"module": 'regulatory_legal_scoring', "scorefn": 'score_litigation_materiality', "anchors_var": '_LITIGATION_ANCHORS', "cache_prefix": 'ar_litigation_text_v1'},
    'J.2.2': {"module": 'regulatory_legal_scoring', "scorefn": 'score_outcome_assessment', "anchors_var": '_OUTCOME_ASSESSMENT_ANCHORS', "cache_prefix": 'ar_outcomeassess_text_v1'},
    'J.3.2': {"module": 'regulatory_legal_scoring', "scorefn": 'score_competition_impact', "anchors_var": '_COMPETITION_IMPACT_ANCHORS', "cache_prefix": 'ar_competitionimpact_text_v1'},
    'J.4.1': {"module": 'regulatory_legal_scoring', "scorefn": 'score_tax_dispute_exposure', "anchors_var": '_TAX_DISPUTE_ANCHORS', "cache_prefix": 'ar_taxdispute_text_v1'},
    'J.4.2': {"module": 'regulatory_legal_scoring', "scorefn": 'score_historic_tax_risk', "anchors_var": '_TAX_DISPUTE_ANCHORS', "cache_prefix": 'ar_historictax_text_v1'},
    'J.4.3': {"module": 'regulatory_legal_scoring', "scorefn": 'classify_tax_audit_status', "anchors_var": '_TAX_AUDIT_ANCHORS', "cache_prefix": 'ar_taxaudit_text_v1'},
    'J.5.1': {"module": 'regulatory_legal_scoring', "scorefn": 'score_subsidy_dependence', "anchors_var": '_SUBSIDY_ANCHORS', "cache_prefix": 'ar_subsidydep_text_v1'},
    'J.5.2': {"module": 'regulatory_legal_scoring', "scorefn": 'score_environmental_regulation_exposure', "anchors_var": '_ENV_REGULATION_ANCHORS', "cache_prefix": 'ar_envregexposure_text_v1'},
    'K.1.1': {"module": 'macro_exposure_scoring', "scorefn": 'score_commodity_input_dependence', "anchors_var": '_K_1_1_ANCHORS', "cache_prefix": 'ar_k_1_1_v1'},
    'K.2.1': {"module": 'macro_exposure_scoring', "scorefn": 'score_export_import_dependence', "anchors_var": '_K_2_1_ANCHORS', "cache_prefix": 'ar_k_2_1_v1'},
    'K.2.2': {"module": 'macro_exposure_scoring', "scorefn": 'score_geopolitical_trade_risk', "anchors_var": '_K_2_2_ANCHORS', "cache_prefix": 'ar_k_2_2_v1'},
    'K.3.1': {"module": 'macro_exposure_scoring', "scorefn": 'score_interest_rate_sensitivity', "anchors_var": '_K_3_1_ANCHORS', "cache_prefix": 'ar_k_3_1_v1'},
    'K.3.2': {"module": 'macro_exposure_scoring', "scorefn": 'score_economic_cyclicality', "anchors_var": '_K_3_2_ANCHORS', "cache_prefix": 'ar_k_3_2_v1'},
    'K.4.2': {"module": 'macro_exposure_scoring', "scorefn": 'score_hedging_protection', "anchors_var": '_K_4_2_ANCHORS', "cache_prefix": 'ar_k_4_2_v1'},
    'L.1.1': {"module": 'financial_policy_scoring', "scorefn": 'score_leverage_policy', "anchors_var": '_L_1_1_ANCHORS', "cache_prefix": 'ar_l_1_1_v1'},
    'L.1.2': {"module": 'financial_policy_scoring', "scorefn": 'score_covenant_management', "anchors_var": '_L_1_2_ANCHORS', "cache_prefix": 'ar_l_1_2_v1'},
    'L.2.1': {"module": 'financial_policy_scoring', "scorefn": 'score_refinancing_history', "anchors_var": '_L_2_1_ANCHORS', "cache_prefix": 'ar_l_2_1_v1'},
    'L.2.2': {"module": 'financial_policy_scoring', "scorefn": 'classify_covenant_breach_status', "anchors_var": '_L_2_2_ANCHORS', "cache_prefix": 'ar_l_2_2_v1'},
    'L.3.1': {"module": 'financial_policy_scoring', "scorefn": 'score_dividend_consistency', "anchors_var": '_L_3_1_ANCHORS', "cache_prefix": 'ar_l_3_1_v1'},
    'L.3.2': {"module": 'financial_policy_scoring', "scorefn": 'score_dividend_rationale', "anchors_var": '_L_3_2_ANCHORS', "cache_prefix": 'ar_l_3_2_v1'},
    'L.4.1': {"module": 'financial_policy_scoring', "scorefn": 'score_lease_commitments', "anchors_var": '_L_4_1_ANCHORS', "cache_prefix": 'ar_l_4_1_v1'},
    'L.4.2': {"module": 'financial_policy_scoring', "scorefn": 'score_structured_arrangements', "anchors_var": '_L_4_2_ANCHORS', "cache_prefix": 'ar_l_4_2_v1'},
    'M.1.1': {"module": 'ma_scoring', "scorefn": 'score_ma_frequency', "anchors_var": '_M_1_1_ANCHORS', "cache_prefix": 'ar_m_1_1_v1'},
    'M.1.3': {"module": 'ma_scoring', "scorefn": 'score_ma_discipline', "anchors_var": '_M_1_3_ANCHORS', "cache_prefix": 'ar_m_1_3_v1'},
    'M.2.1': {"module": 'ma_scoring', "scorefn": 'score_related_party_acquisitions', "anchors_var": '_M_2_1_ANCHORS', "cache_prefix": 'ar_m_2_1_v1'},
    'M.2.2': {"module": 'ma_scoring', "scorefn": 'score_affiliate_disposals', "anchors_var": '_M_2_2_ANCHORS', "cache_prefix": 'ar_m_2_2_v1'},
    'M.3.1': {"module": 'ma_scoring', "scorefn": 'score_ma_pipeline', "anchors_var": '_M_3_1_ANCHORS', "cache_prefix": 'ar_m_3_1_v1'},
    'M.3.2': {"module": 'ma_scoring', "scorefn": 'score_value_creation_rationale', "anchors_var": '_M_3_2_ANCHORS', "cache_prefix": 'ar_m_3_2_v1'},
    'N.1.1': {"module": 'esg_scoring', "scorefn": 'score_esg_targets', "anchors_var": '_N_1_1_ANCHORS', "cache_prefix": 'ar_n_1_1_v1'},
    'N.2.1': {"module": 'esg_scoring', "scorefn": 'score_community_impact', "anchors_var": '_N_2_1_ANCHORS', "cache_prefix": 'ar_n_2_1_v1'},
    'N.2.2': {"module": 'esg_scoring', "scorefn": 'classify_displacement_risk', "anchors_var": '_N_2_2_ANCHORS', "cache_prefix": 'ar_n_2_2_v1'},
    'N.3.1': {"module": 'esg_scoring', "scorefn": 'score_environmental_incidents', "anchors_var": '_N_3_1_ANCHORS', "cache_prefix": 'ar_n_3_1_v1'},
    'N.3.2': {"module": 'esg_scoring', "scorefn": 'score_hazardous_waste', "anchors_var": '_N_3_2_ANCHORS', "cache_prefix": 'ar_n_3_2_v1'},
    'N.3.3': {"module": 'esg_scoring', "scorefn": 'classify_clearance_status', "anchors_var": '_N_3_3_ANCHORS', "cache_prefix": 'ar_n_3_3_v1'},
    'N.4.1': {"module": 'esg_scoring', "scorefn": 'score_union_exposure', "anchors_var": '_N_4_1_ANCHORS', "cache_prefix": 'ar_n_4_1_v1'},
    'N.4.2': {"module": 'esg_scoring', "scorefn": 'score_strikes_disputes', "anchors_var": '_N_4_2_ANCHORS', "cache_prefix": 'ar_n_4_2_v1'},
    'N.4.3': {"module": 'esg_scoring', "scorefn": 'score_employee_grievances', "anchors_var": '_N_4_3_ANCHORS', "cache_prefix": 'ar_n_4_3_v1'},
    'N.5.1': {"module": 'esg_scoring', "scorefn": 'score_human_rights_policy', "anchors_var": '_N_5_1_ANCHORS', "cache_prefix": 'ar_n_5_1_v1'},
    'N.5.2': {"module": 'esg_scoring', "scorefn": 'classify_forced_labour_status', "anchors_var": '_N_5_2_ANCHORS', "cache_prefix": 'ar_n_5_2_v1'},
    'O.1.1': {"module": 'reputation_scoring', "scorefn": 'score_material_controversies', "anchors_var": '_O_1_1_ANCHORS', "cache_prefix": 'ar_o_1_1_v1'},
    'O.1.2': {"module": 'reputation_scoring', "scorefn": 'score_stakeholder_complaints', "anchors_var": '_O_1_2_ANCHORS', "cache_prefix": 'ar_o_1_2_v1'},
    'O.2.2': {"module": 'reputation_scoring', "scorefn": 'score_safety_incidents', "anchors_var": '_O_2_2_ANCHORS', "cache_prefix": 'ar_o_2_2_v1'},
    'O.2.3': {"module": 'reputation_scoring', "scorefn": 'score_reputation_response', "anchors_var": '_O_2_3_ANCHORS', "cache_prefix": 'ar_o_2_3_v1'},
    'O.3.1': {"module": 'reputation_scoring', "scorefn": 'score_regulatory_fines', "anchors_var": '_O_3_1_ANCHORS', "cache_prefix": 'ar_o_3_1_v1'},
    'O.3.2': {"module": 'reputation_scoring', "scorefn": 'classify_public_investigation_status', "anchors_var": '_O_3_2_ANCHORS', "cache_prefix": 'ar_o_3_2_v1'},
    'P.1.1': {"module": 'disclosure_audit_scoring', "scorefn": 'score_disclosure_detail', "anchors_var": '_P_1_1_ANCHORS', "cache_prefix": 'ar_p_1_1_v1'},
    'P.2.1': {"module": 'disclosure_audit_scoring', "scorefn": 'score_rpt_completeness', "anchors_var": '_P_2_1_ANCHORS', "cache_prefix": 'ar_p_2_1_v1'},
    'P.2.2': {"module": 'disclosure_audit_scoring', "scorefn": 'score_rpt_explanation_quality', "anchors_var": '_P_2_2_ANCHORS', "cache_prefix": 'ar_p_2_2_v1'},
    'P.3.1': {"module": 'disclosure_audit_scoring', "scorefn": 'classify_audit_opinion', "anchors_var": '_P_3_1_ANCHORS', "cache_prefix": 'ar_p_3_1_v1'},
    'P.3.2': {"module": 'disclosure_audit_scoring', "scorefn": 'score_emphasis_of_matter', "anchors_var": '_P_3_2_ANCHORS', "cache_prefix": 'ar_p_3_2_v1'},
    'P.3.3': {"module": 'disclosure_audit_scoring', "scorefn": 'score_restatements', "anchors_var": '_P_3_3_ANCHORS', "cache_prefix": 'ar_p_3_3_v1'},
    'P.4.2': {"module": 'disclosure_audit_scoring', "scorefn": 'score_multiple_currencies', "anchors_var": '_P_4_2_ANCHORS', "cache_prefix": 'ar_p_4_2_v1'},
    'P.4.3': {"module": 'disclosure_audit_scoring', "scorefn": 'score_subsidiary_complexity', "anchors_var": '_P_4_3_ANCHORS', "cache_prefix": 'ar_p_4_3_v1'},
    'Q.1.2': {"module": 'structural_redflag_scoring', "scorefn": 'score_cfo_churn', "anchors_var": '_Q_1_2_ANCHORS', "cache_prefix": 'ar_q_1_2_v1'},
    'Q.3.1': {"module": 'structural_redflag_scoring', "scorefn": 'score_group_structure_opacity', "anchors_var": '_Q_3_1_ANCHORS', "cache_prefix": 'ar_q_3_1_v1'},
    'Q.3.2': {"module": 'structural_redflag_scoring', "scorefn": 'score_dormant_entities', "anchors_var": '_Q_3_2_ANCHORS', "cache_prefix": 'ar_q_3_2_v1'},
    'Q.4.1': {"module": 'structural_redflag_scoring', "scorefn": 'score_year_end_concentration', "anchors_var": '_Q_4_1_ANCHORS', "cache_prefix": 'ar_q_4_1_v1'},
    'Q.4.2': {"module": 'structural_redflag_scoring', "scorefn": 'score_explanation_quality', "anchors_var": '_Q_4_2_ANCHORS', "cache_prefix": 'ar_q_4_2_v1'},
    'R.1.1': {"module": 'earlywarning_scoring', "scorefn": 'score_sudden_departures', "anchors_var": '_R_1_1_ANCHORS', "cache_prefix": 'ar_r_1_1_v1'},
    'R.1.2': {"module": 'earlywarning_scoring', "scorefn": 'score_succession_response', "anchors_var": '_R_1_2_ANCHORS', "cache_prefix": 'ar_r_1_2_v1'},
    'R.3.1': {"module": 'earlywarning_scoring', "scorefn": 'score_capital_raise_frequency', "anchors_var": '_R_3_1_ANCHORS', "cache_prefix": 'ar_r_3_1_v1'},
    'R.3.2': {"module": 'earlywarning_scoring', "scorefn": 'score_discount_pricing', "anchors_var": '_R_3_2_ANCHORS', "cache_prefix": 'ar_r_3_2_v1'},
    'R.4.1': {"module": 'earlywarning_scoring', "scorefn": 'score_oneoff_transaction_frequency', "anchors_var": '_R_4_1_ANCHORS', "cache_prefix": 'ar_r_4_1_v1'},
    'R.4.2': {"module": 'earlywarning_scoring', "scorefn": 'score_transfer_pricing_rationale', "anchors_var": '_R_4_2_ANCHORS', "cache_prefix": 'ar_r_4_2_v1'},
    'R.5.1': {"module": 'earlywarning_scoring', "scorefn": 'score_auditor_resignation', "anchors_var": '_R_5_1_ANCHORS', "cache_prefix": 'ar_r_5_1_v1'},
    'R.5.2': {"module": 'earlywarning_scoring', "scorefn": 'score_internal_control_issues', "anchors_var": '_R_5_2_ANCHORS', "cache_prefix": 'ar_r_5_2_v1'},
    'R.6.1': {"module": 'earlywarning_scoring', "scorefn": 'score_response_cadence', "anchors_var": '_R_6_1_ANCHORS', "cache_prefix": 'ar_r_6_1_v1'},
    'R.6.2': {"module": 'earlywarning_scoring', "scorefn": 'score_response_substance', "anchors_var": '_R_6_2_ANCHORS', "cache_prefix": 'ar_r_6_2_v1'},
    'S.1.1': {"module": 'sector_specific_scoring', "scorefn": 'score_asset_quality', "anchors_var": '_S_1_1_ANCHORS', "cache_prefix": 'ar_s_1_1_v1'},
    'S.1.2': {"module": 'sector_specific_scoring', "scorefn": 'score_rpt_exposure_bank', "anchors_var": '_S_1_2_ANCHORS', "cache_prefix": 'ar_s_1_2_v1'},
    'S.1.3': {"module": 'sector_specific_scoring', "scorefn": 'score_regulatory_capital', "anchors_var": '_S_1_3_ANCHORS', "cache_prefix": 'ar_s_1_3_v1'},
    'S.1.4': {"module": 'sector_specific_scoring', "scorefn": 'score_underwriting_quality', "anchors_var": '_S_1_4_ANCHORS', "cache_prefix": 'ar_s_1_4_v1'},
    'S.2.2': {"module": 'sector_specific_scoring', "scorefn": 'score_patent_cliffs', "anchors_var": '_S_2_2_ANCHORS', "cache_prefix": 'ar_s_2_2_v1'},
    'S.2.3': {"module": 'sector_specific_scoring', "scorefn": 'score_regulatory_inspections', "anchors_var": '_S_2_3_ANCHORS', "cache_prefix": 'ar_s_2_3_v1'},
    'S.2.4': {"module": 'sector_specific_scoring', "scorefn": 'score_price_controls', "anchors_var": '_S_2_4_ANCHORS', "cache_prefix": 'ar_s_2_4_v1'},
    'S.3.1': {"module": 'sector_specific_scoring', "scorefn": 'score_model_refresh_cycle', "anchors_var": '_S_3_1_ANCHORS', "cache_prefix": 'ar_s_3_1_v1'},
    'S.3.2': {"module": 'sector_specific_scoring', "scorefn": 'score_channel_inventory', "anchors_var": '_S_3_2_ANCHORS', "cache_prefix": 'ar_s_3_2_v1'},
    'S.3.3': {"module": 'sector_specific_scoring', "scorefn": 'score_export_dependency_s3', "anchors_var": '_S_3_3_ANCHORS', "cache_prefix": 'ar_s_3_3_v1'},
    'S.4.1': {"module": 'sector_specific_scoring', "scorefn": 'score_client_concentration', "anchors_var": '_S_4_1_ANCHORS', "cache_prefix": 'ar_s_4_1_v1'},
    'S.4.2': {"module": 'sector_specific_scoring', "scorefn": 'score_contract_renewal_risk', "anchors_var": '_S_4_2_ANCHORS', "cache_prefix": 'ar_s_4_2_v1'},
    'S.4.3': {"module": 'sector_specific_scoring', "scorefn": 'score_visa_dependence', "anchors_var": '_S_4_3_ANCHORS', "cache_prefix": 'ar_s_4_3_v1'},
    'S.5.1': {"module": 'sector_specific_scoring', "scorefn": 'score_brand_strength_s5', "anchors_var": '_S_5_1_ANCHORS', "cache_prefix": 'ar_s_5_1_v1'},
    'S.5.2': {"module": 'sector_specific_scoring', "scorefn": 'score_distribution_depth_s5', "anchors_var": '_S_5_2_ANCHORS', "cache_prefix": 'ar_s_5_2_v1'},
    'S.5.3': {"module": 'sector_specific_scoring', "scorefn": 'score_commodity_volatility_s5', "anchors_var": '_S_5_3_ANCHORS', "cache_prefix": 'ar_s_5_3_v1'},
    'T.1.1': {"module": 'geopolitical_scoring', "scorefn": 'score_sanctions_exposure', "anchors_var": '_T_1_1_ANCHORS', "cache_prefix": 'ar_t_1_1_v1'},
    'T.1.2': {"module": 'geopolitical_scoring', "scorefn": 'score_tariff_exposure', "anchors_var": '_T_1_2_ANCHORS', "cache_prefix": 'ar_t_1_2_v1'},
    'T.2.1': {"module": 'geopolitical_scoring', "scorefn": 'score_gst_sensitivity', "anchors_var": '_T_2_1_ANCHORS', "cache_prefix": 'ar_t_2_1_v1'},
    'T.2.2': {"module": 'geopolitical_scoring', "scorefn": 'score_import_duty_sensitivity', "anchors_var": '_T_2_2_ANCHORS', "cache_prefix": 'ar_t_2_2_v1'},
    'T.3.1': {"module": 'geopolitical_scoring', "scorefn": 'score_convertibility_risk', "anchors_var": '_T_3_1_ANCHORS', "cache_prefix": 'ar_t_3_1_v1'},
    'T.3.2': {"module": 'geopolitical_scoring', "scorefn": 'score_repatriation_risk', "anchors_var": '_T_3_2_ANCHORS', "cache_prefix": 'ar_t_3_2_v1'},
    'U.1.1': {"module": 'management_qa_scoring', "scorefn": 'score_top_risk', "anchors_var": '_U_1_1_ANCHORS', "cache_prefix": 'ar_u_1_1_v1'},
    'U.2.1': {"module": 'management_qa_scoring', "scorefn": 'score_capital_allocation_framework', "anchors_var": '_U_2_1_ANCHORS', "cache_prefix": 'ar_u_2_1_v1'},
    'U.3.1': {"module": 'management_qa_scoring', "scorefn": 'score_named_competitors', "anchors_var": '_U_3_1_ANCHORS', "cache_prefix": 'ar_u_3_1_v1'},
    'U.4.1': {"module": 'management_qa_scoring', "scorefn": 'score_revenue_sensitivity', "anchors_var": '_U_4_1_ANCHORS', "cache_prefix": 'ar_u_4_1_v1'},
    'U.4.2': {"module": 'management_qa_scoring', "scorefn": 'score_margin_sensitivity', "anchors_var": '_U_4_2_ANCHORS', "cache_prefix": 'ar_u_4_2_v1'},
    'U.5.1': {"module": 'management_qa_scoring', "scorefn": 'score_rpt_management_explanation', "anchors_var": '_U_5_1_ANCHORS', "cache_prefix": 'ar_u_5_1_v1'},
    'U.6.1': {"module": 'management_qa_scoring', "scorefn": 'score_ceo_succession', "anchors_var": '_U_6_1_ANCHORS', "cache_prefix": 'ar_u_6_1_v1'},
    'U.6.2': {"module": 'management_qa_scoring', "scorefn": 'score_cfo_succession', "anchors_var": '_U_6_2_ANCHORS', "cache_prefix": 'ar_u_6_2_v1'},
}


# Second CASE-A template: `tools.ar_table_extractor.extract_text_near_anchors`
# (single anchor key) + a scoring-module function - mechanically confirmed
# by direct read of each listed compute_fn's body (fewer of these follow
# the exact template than the `_fetch_ar_evidence_excerpts` one, so this
# table is hand-verified per entry rather than regex-generated, but each
# entry's (anchor_key, anchors, scorefn) is copied verbatim from the
# legacy function it replaces - not re-derived).
LEGACY_TABLE_TEXT_ADAPTERS = {
    "B.3.1": {"module": "management_bench_scoring", "scorefn": "score_leadership_depth_from_text",
              "anchor_key": "smp",
              "anchors": ["senior management personnel", "executive leadership team", "senior management team"],
              "max_pages_per_key": 4},
    "C.3.4": {"module": "rpt_disclosure_scoring", "scorefn": "score_disclosure_quality",
              "anchor_key": "governance",
              "anchors": ["audit committee", "related party transactions policy", "omnibus approval"],
              "max_pages_per_key": 6},
    "C.4.1": {"module": "group_structure_scoring", "scorefn": "score_offbalance_sheet_risk",
              "anchor_key": "contingent",
              "anchors": ["contingent liabilities and commitments", "corporate guarantee", "capital commitments"],
              "max_pages_per_key": 6},
    "C.7.1": {"module": "capital_allocation_scoring", "scorefn": "score_capex_type",
              "anchor_key": "capex",
              "anchors": ["capital expenditure", "expansion", "greenfield", "de-bottlenecking", "new factory"],
              "max_pages_per_key": 6},
    "C.8.1": {"module": "minority_treatment_scoring", "scorefn": "score_disclosure_quality",
              "anchor_key": "disclosures",
              "anchors": ["related party transactions", "contingent liabilities", "commitments",
                          "corporate governance report"],
              "max_pages_per_key": 8},
}


def evaluate_via_legacy_table_scorer(symbol: str, name: Optional[str], fiscal_year: Optional[int],
                                      task_key: str, subtask_key: str) -> EvidenceBundle:
    """Second CASE-A adapter - calls the EXACT `extract_text_near_anchors` +
    `<module>.<scorefn>` pair the legacy compute_fn already calls for tasks
    in `LEGACY_TABLE_TEXT_ADAPTERS`. Same equivalence-by-construction
    guarantee as `evaluate_via_legacy_scorer`, for the (structurally
    different, single-anchor-key) second template."""
    sym = (symbol or "").strip().upper().replace(".NS", "")
    bundle = EvidenceBundle(company_identity=sym, fiscal_year=fiscal_year,
                             task_key=task_key, subtask_key=subtask_key)
    spec = LEGACY_TABLE_TEXT_ADAPTERS.get(subtask_key)
    if spec is None:
        return bundle

    try:
        import importlib
        from tools.ar_table_extractor import extract_text_near_anchors
        scoring_module = importlib.import_module(f"tools.{spec['module']}")
        score_fn = getattr(scoring_module, spec["scorefn"])
    except Exception:
        bundle.source_availability["annual_report"] = resolve_availability(
            available=True, searched=True, search_failed=True)
        return bundle

    try:
        texts = extract_text_near_anchors(
            sym, name, {spec["anchor_key"]: spec["anchors"]}, max_pages_per_key=spec["max_pages_per_key"],
        )
        text = (texts or {}).get(spec["anchor_key"], "")
    except Exception:
        bundle.source_availability["annual_report"] = resolve_availability(
            available=True, searched=True, search_failed=True)
        return bundle

    bundle.source_availability["annual_report"] = resolve_availability(
        available=True, searched=True, found=bool(text))
    if not text:
        return bundle

    try:
        result = score_fn(text)
    except Exception:
        return bundle

    normalized_value, score = _normalize_scorer_result(result)
    if normalized_value is None:
        return bundle

    ev = QualitativeEvidence.build(
        company_identity=sym, fiscal_year=fiscal_year, task_key=task_key, subtask_key=subtask_key,
        evidence_type=subtask_key, source_document=None, source_document_type="annual_report",
        extracted_text=text[:600], normalized_value=normalized_value,
        status=EvidenceStatus.PARTIALLY_VERIFIED,
        confidence=Confidence(ConfidenceTier.MEDIUM, None,
                               f"legacy scorer tools.{spec['module']}.{spec['scorefn']} (single AR pass)"),
        source_priority=10, extraction_method="legacy_scorer_adapter",
    )
    bundle.add(ev)
    bundle.legacy_score = score
    return bundle


# Third CASE-A template: a PRIVATE helper function already defined in
# `tools.qualitative_engine` itself (e.g. `_fetch_group_entities`,
# `_fetch_latest_audit_opinion_text`, `_fetch_competitive_landscape_text`) -
# fetches either bare data/text, or a (text, pdf_url) tuple - followed by
# one scoring-module function call on that result. Hand-verified per entry
# (each `helper`/`module`/`scorefn`/`returns_tuple` copied verbatim from the
# legacy compute_fn it replaces) since these helpers aren't module-level
# constants greppable the way the first template's anchors are.
LEGACY_PRIVATE_HELPER_ADAPTERS = {
    "C.4.2": {"helper": "_fetch_group_entities", "module": "group_structure_scoring",
              "scorefn": "score_spv_complexity", "returns_tuple": False},
    "C.6.3": {"helper": "_fetch_latest_audit_opinion_text", "module": "auditor_scoring",
              "scorefn": "score_audit_opinion", "returns_tuple": False},
    "C.6.4": {"helper": "_fetch_latest_audit_opinion_text", "module": "auditor_scoring",
              "scorefn": "score_audit_observations", "returns_tuple": False},
    "D.5.1": {"helper": "_fetch_rpt_text_for_loans", "module": "promoter_loan_scoring",
              "scorefn": "score_loan_direction", "returns_tuple": True},
    "D.5.2": {"helper": "_fetch_rpt_text_for_loans", "module": "promoter_loan_scoring",
              "scorefn": "score_loan_terms", "returns_tuple": True},
    "E.2.1": {"helper": "_fetch_customer_concentration_text", "module": "customer_concentration_scoring",
              "scorefn": "score_customer_concentration", "returns_tuple": True},
    "E.3.1": {"helper": "_fetch_supplier_concentration_text", "module": "supplier_concentration_scoring",
              "scorefn": "score_supplier_concentration", "returns_tuple": True},
    "F.1.1": {"helper": "_fetch_competitive_landscape_text", "module": "competitive_landscape_scoring",
              "scorefn": "score_competitor_count", "returns_tuple": True},
    "F.1.2": {"helper": "_fetch_competitive_landscape_text", "module": "competitive_landscape_scoring",
              "scorefn": "score_market_position", "returns_tuple": True},
    "F.1.3": {"helper": "_fetch_competitive_landscape_text", "module": "competitive_landscape_scoring",
              "scorefn": "score_competitor_strength", "returns_tuple": True},
    "F.5.1": {"helper": "_fetch_foreign_competition_text", "module": "foreign_competition_scoring",
              "scorefn": "score_foreign_competitor_presence", "returns_tuple": True},
}


def evaluate_via_private_helper_scorer(symbol: str, name: Optional[str], fiscal_year: Optional[int],
                                        task_key: str, subtask_key: str) -> EvidenceBundle:
    """Third CASE-A adapter - calls the EXACT private fetch helper (already
    defined in `tools.qualitative_engine`, imported live rather than
    duplicated) + `<module>.<scorefn>` pair the legacy compute_fn already
    calls, for tasks in `LEGACY_PRIVATE_HELPER_ADAPTERS`."""
    sym = (symbol or "").strip().upper().replace(".NS", "")
    bundle = EvidenceBundle(company_identity=sym, fiscal_year=fiscal_year,
                             task_key=task_key, subtask_key=subtask_key)
    spec = LEGACY_PRIVATE_HELPER_ADAPTERS.get(subtask_key)
    if spec is None:
        return bundle

    try:
        import importlib
        import tools.qualitative_engine as qe
        helper = getattr(qe, spec["helper"])
        scoring_module = importlib.import_module(f"tools.{spec['module']}")
        score_fn = getattr(scoring_module, spec["scorefn"])
    except Exception:
        bundle.source_availability["annual_report"] = resolve_availability(
            available=True, searched=True, search_failed=True)
        return bundle

    try:
        fetched = helper(sym, name)
        text_or_data = fetched[0] if spec["returns_tuple"] else fetched
        source_doc = fetched[1] if spec["returns_tuple"] and len(fetched) > 1 else None
    except Exception:
        bundle.source_availability["annual_report"] = resolve_availability(
            available=True, searched=True, search_failed=True)
        return bundle

    bundle.source_availability["annual_report"] = resolve_availability(
        available=True, searched=True, found=bool(text_or_data))
    if not text_or_data:
        return bundle

    try:
        result = score_fn(text_or_data)
    except Exception:
        return bundle

    normalized_value, score = _normalize_scorer_result(result)
    if normalized_value is None:
        return bundle

    excerpt = text_or_data if isinstance(text_or_data, str) else None
    ev = QualitativeEvidence.build(
        company_identity=sym, fiscal_year=fiscal_year, task_key=task_key, subtask_key=subtask_key,
        evidence_type=subtask_key, source_document=source_doc, source_document_type="annual_report",
        extracted_text=(excerpt[:600] if excerpt else None), normalized_value=normalized_value,
        status=EvidenceStatus.PARTIALLY_VERIFIED,
        confidence=Confidence(ConfidenceTier.MEDIUM, None,
                               f"legacy scorer tools.{spec['module']}.{spec['scorefn']} (single AR pass)"),
        source_priority=10, extraction_method="legacy_scorer_adapter",
    )
    bundle.add(ev)
    bundle.legacy_score = score
    return bundle


# Fourth CASE-A template: `annual_report_financials.fetch_rpt_evidence_from_annual_report`
# (a public function that itself wraps `_fetch_ar_evidence_excerpts` with
# Ind AS 24 anchors, returning the SAME excerpts/pdf_url shape) + one
# scoring-module function over the joined excerpt text - the Related-Party-
# Transaction family of tasks.
LEGACY_RPT_EVIDENCE_ADAPTERS = {
    "C.3.1": {"module": "rpt_disclosure_scoring", "scorefn": "score_rpt_frequency"},
    "E.1.1": {"module": "rpt_leakage_scoring", "scorefn": "score_payment_frequency"},
    "E.1.3": {"module": "rpt_leakage_scoring", "scorefn": "score_payment_rationale"},
    "E.6.2": {"module": "rpt_leakage_scoring", "scorefn": "score_payment_rationale"},
}


def evaluate_via_rpt_evidence_scorer(symbol: str, name: Optional[str], fiscal_year: Optional[int],
                                      task_key: str, subtask_key: str) -> EvidenceBundle:
    """Fourth CASE-A adapter - calls the EXACT
    `annual_report_financials.fetch_rpt_evidence_from_annual_report` +
    `<module>.<scorefn>` pair the legacy compute_fn already calls, for
    tasks in `LEGACY_RPT_EVIDENCE_ADAPTERS`."""
    sym = (symbol or "").strip().upper().replace(".NS", "")
    bundle = EvidenceBundle(company_identity=sym, fiscal_year=fiscal_year,
                             task_key=task_key, subtask_key=subtask_key)
    spec = LEGACY_RPT_EVIDENCE_ADAPTERS.get(subtask_key)
    if spec is None:
        return bundle

    try:
        import importlib
        from tools.annual_report_financials import fetch_rpt_evidence_from_annual_report
        scoring_module = importlib.import_module(f"tools.{spec['module']}")
        score_fn = getattr(scoring_module, spec["scorefn"])
    except Exception:
        bundle.source_availability["annual_report"] = resolve_availability(
            available=True, searched=True, search_failed=True)
        return bundle

    try:
        evidence = fetch_rpt_evidence_from_annual_report(sym, name, fiscal_year=fiscal_year)
    except Exception:
        bundle.source_availability["annual_report"] = resolve_availability(
            available=True, searched=True, search_failed=True)
        return bundle

    if not isinstance(evidence, dict) or "error" in evidence:
        bundle.source_availability["annual_report"] = resolve_availability(
            available=True, searched=True, found=False)
        return bundle

    excerpts = evidence.get("excerpts") or []
    text = " ".join((ex.get("text") or "") for ex in excerpts)
    bundle.source_availability["annual_report"] = resolve_availability(
        available=True, searched=True, found=bool(text))
    if not text:
        return bundle

    try:
        result = score_fn(text)
    except Exception:
        return bundle

    normalized_value, score = _normalize_scorer_result(result)
    if normalized_value is None:
        return bundle

    ev = QualitativeEvidence.build(
        company_identity=sym, fiscal_year=fiscal_year, task_key=task_key, subtask_key=subtask_key,
        evidence_type=subtask_key, source_document=evidence.get("pdf_url"), source_document_type="annual_report",
        extracted_text=text[:600], normalized_value=normalized_value,
        status=EvidenceStatus.PARTIALLY_VERIFIED,
        confidence=Confidence(ConfidenceTier.MEDIUM, None,
                               f"legacy scorer tools.{spec['module']}.{spec['scorefn']} (single AR pass)"),
        source_priority=10, extraction_method="legacy_scorer_adapter",
    )
    bundle.add(ev)
    bundle.legacy_score = score
    return bundle


# Fifth CASE-A template: `tools.governance_scraper.fetch_latest_governance_filing`
# (the SAME structured source `tools.qualitative_evidence_extraction.
# extract_board_composition` already uses) + `board_governance_scoring`'s
# committee/director-quality scorers - hand-verified per entry against
# `qualitative_engine.py`'s `_compute_committee_subpoint`/
# `compute_c5_1_independent_director_quality`.
LEGACY_GOVERNANCE_FILING_ADAPTERS = {
    "C.5.1": {"kind": "director_quality"},
    "C.5.2": {"kind": "committee", "committee_name": "Audit Committee"},
    "C.5.3": {"kind": "committee", "committee_name": "Nomination and Remuneration Committee"},
}


def evaluate_via_governance_filing_scorer(symbol: str, name: Optional[str], fiscal_year: Optional[int],
                                           task_key: str, subtask_key: str) -> EvidenceBundle:
    """Fifth CASE-A adapter - calls the EXACT `governance_scraper.
    fetch_latest_governance_filing` + `board_governance_scoring` function
    pair the legacy compute_fn already calls, for tasks in
    `LEGACY_GOVERNANCE_FILING_ADAPTERS`."""
    sym = (symbol or "").strip().upper().replace(".NS", "")
    bundle = EvidenceBundle(company_identity=sym, fiscal_year=fiscal_year,
                             task_key=task_key, subtask_key=subtask_key)
    spec = LEGACY_GOVERNANCE_FILING_ADAPTERS.get(subtask_key)
    if spec is None:
        return bundle

    try:
        from tools.governance_scraper import fetch_latest_governance_filing
        from tools.board_governance_scoring import score_independent_director_quality, score_committee_effectiveness
        filing = fetch_latest_governance_filing(sym) or {}
    except Exception:
        bundle.source_availability["quarterly_corporate_governance_filing"] = resolve_availability(
            available=True, searched=True, search_failed=True)
        return bundle

    bundle.source_availability["quarterly_corporate_governance_filing"] = resolve_availability(
        available=True, searched=True, found=bool(filing))
    if not filing:
        return bundle

    try:
        if spec["kind"] == "director_quality":
            result = score_independent_director_quality(filing.get("cobod"))
        else:
            committee_name = spec["committee_name"]
            composition = (filing.get("coc") or {}).get(committee_name) or []
            meetings = [m for m in (filing.get("meetingcomm") or []) if m.get("commName") == committee_name]
            result = score_committee_effectiveness(composition, meetings)
    except Exception:
        return bundle

    normalized_value, score = _normalize_scorer_result(result)
    if normalized_value is None:
        return bundle

    ev = QualitativeEvidence.build(
        company_identity=sym, fiscal_year=fiscal_year, task_key=task_key, subtask_key=subtask_key,
        evidence_type=subtask_key, source_document=None,
        source_document_type="quarterly_corporate_governance_filing",
        extracted_text=None, normalized_value=normalized_value,
        status=EvidenceStatus.PARTIALLY_VERIFIED,
        confidence=Confidence(ConfidenceTier.HIGH, None, "structured regulatory filing"),
        source_priority=1, extraction_method="legacy_scorer_adapter", evidence_date=filing.get("as_of_quarter"),
    )
    bundle.add(ev)
    bundle.legacy_score = score
    return bundle


def _normalize_scorer_result(result: Any) -> Tuple[Any, Optional[float]]:
    """Generic, shape-based normalization (never per-function business
    logic) of the 60+ distinct scoring functions' return values into
    (normalized_value, numeric_score_or_None):
      - None                          -> (None, None)               nothing matched
      - int/float                     -> (value, value)              bare numeric score
      - (label_or_bool, score) tuple  -> (label_or_bool, score)       score_evidence_tier convention
      - str                           -> (str, None)                 classify_status category label
      - dict with a *_score/score key -> (dict, that field's value)   details dict
      - dict without one              -> (dict, None)
      - dict/tuple whose fields are ALL None -> (None, None)          scorer found nothing conclusive
    """
    if result is None:
        return None, None
    if isinstance(result, bool):
        return result, None
    if isinstance(result, (int, float)):
        return result, result
    if isinstance(result, tuple) and len(result) == 2:
        label, score = result
        if label is None and score is None:
            return None, None  # e.g. (None, None) - scorer's own "nothing matched" convention
        return label, (score if isinstance(score, (int, float)) else None)
    if isinstance(result, str):
        return result, None
    if isinstance(result, dict):
        if result and all(v is None for v in result.values()):
            return None, None  # every field None - the scorer found nothing, not a real (empty) finding
        for key in result:
            if key == "score" or key.endswith("_score"):
                v = result[key]
                if isinstance(v, (int, float)):
                    return result, v
        return result, None
    return result, None


def evaluate_via_legacy_scorer(symbol: str, name: Optional[str], fiscal_year: Optional[int],
                                task_key: str, subtask_key: str) -> EvidenceBundle:
    """The generic CASE-A adapter. `subtask_key` must be a key in
    `LEGACY_AR_TEXT_SCORER_ADAPTERS`. Calls the EXACT `_fetch_ar_evidence_excerpts`
    + `<module>.<scorefn>` pair the legacy compute_fn for this task already
    calls - see module docstring."""
    sym = (symbol or "").strip().upper().replace(".NS", "")
    bundle = EvidenceBundle(company_identity=sym, fiscal_year=fiscal_year,
                             task_key=task_key, subtask_key=subtask_key)
    spec = LEGACY_AR_TEXT_SCORER_ADAPTERS.get(subtask_key)
    if spec is None:
        return bundle

    try:
        import importlib
        import tools.qualitative_engine as qe
        anchors = getattr(qe, spec["anchors_var"])
        scoring_module = importlib.import_module(f"tools.{spec['module']}")
        score_fn = getattr(scoring_module, spec["scorefn"])
        from tools.annual_report_financials import _fetch_ar_evidence_excerpts
    except Exception:
        bundle.source_availability["annual_report"] = resolve_availability(
            available=True, searched=True, search_failed=True)
        return bundle

    try:
        evidence = _fetch_ar_evidence_excerpts(
            sym, name, anchors, spec["cache_prefix"], fiscal_year=fiscal_year,
            max_per_page=4, max_excerpts=20, fetch_label=spec["cache_prefix"],
        )
    except Exception:
        bundle.source_availability["annual_report"] = resolve_availability(
            available=True, searched=True, search_failed=True)
        return bundle

    if not isinstance(evidence, dict) or "error" in evidence:
        bundle.source_availability["annual_report"] = resolve_availability(
            available=True, searched=True, found=False)
        return bundle

    excerpts = evidence.get("excerpts") or []
    text = " ".join((ex.get("text") or "") for ex in excerpts)
    bundle.source_availability["annual_report"] = resolve_availability(
        available=True, searched=True, found=bool(text))
    if not text:
        return bundle

    try:
        result = score_fn(text)
    except Exception:
        return bundle

    normalized_value, score = _normalize_scorer_result(result)
    if normalized_value is None:
        return bundle  # scorer found nothing conclusive - NOT_DISCLOSED at bundle level, never fabricated

    excerpt_preview = text[:600]
    ev = QualitativeEvidence.build(
        company_identity=sym, fiscal_year=fiscal_year, task_key=task_key, subtask_key=subtask_key,
        evidence_type=subtask_key, source_document=evidence.get("pdf_url"), source_document_type="annual_report",
        extracted_text=excerpt_preview, normalized_value=normalized_value,
        status=EvidenceStatus.PARTIALLY_VERIFIED,
        confidence=Confidence(ConfidenceTier.MEDIUM, None,
                               f"legacy scorer tools.{spec['module']}.{spec['scorefn']} (single AR pass)"),
        source_priority=10, extraction_method="legacy_scorer_adapter",
    )
    bundle.add(ev)
    bundle.legacy_score = score  # stashed for the engine's _score_for to read - see qualitative_task_engine.py
    return bundle
