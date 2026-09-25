"""Bound material checks; content hashes never imply source truth or acceptance."""

import hashlib
import json

from .canonical import sha256_json


def primary_evidence_valid(value):
    if not isinstance(value, dict):
        return False
    text, quote = value.get("source_text"), value.get("quote")
    start, end = value.get("char_start"), value.get("char_end")
    return (
        isinstance(text, str)
        and isinstance(quote, str)
        and bool(quote)
        and type(start) is int
        and type(end) is int
        and 0 <= start < end <= len(text)
        and text[start:end] == quote
        and value.get("source_sha256") == hashlib.sha256(text.encode()).hexdigest()
        and isinstance(value.get("source_ref"), str)
        and bool(value["source_ref"])
    )


def extraction_binding_issues(field, accepted_value, schema, codebook):
    binding = field.get("primary_verification")
    if not isinstance(binding, dict):
        return ["extraction_primary_verification_missing"]
    issues = []
    target = {
        "schema": schema,
        "codebook": codebook,
        "field": {k: v for k, v in field.items() if k != "primary_verification"},
    }
    if binding.get("target_sha256") != sha256_json(target):
        issues.append("extraction_review_target_changed")
    if not primary_evidence_valid(binding.get("evidence")):
        issues.append("extraction_primary_evidence_invalid")
    reviewer = binding.get("reviewer_id")
    if not reviewer or reviewer in {x.get("extractor_id") for x in field["values"]}:
        issues.append("extraction_verifier_not_independent")
    protocol = binding.get("protocol_json")
    if not isinstance(protocol, str):
        protocol = ""
    try:
        expected = json.loads(protocol)
    except (ValueError, TypeError):
        expected = None
    if (
        not isinstance(expected, dict)
        or set(expected) != {"study_id", "outcome_id", "window"}
        or any(not isinstance(v, str) or not v for v in expected.values())
    ):
        issues.append("extraction_protocol_invalid")
    elif (
        binding.get("protocol_sha256") != hashlib.sha256(protocol.encode()).hexdigest()
    ):
        issues.append("extraction_protocol_hash_mismatch")
    observed = binding.get("observed_tuple")
    if not isinstance(observed, dict) or set(observed) != {
        "study_id",
        "outcome_id",
        "window",
        "value_json",
        "uncertainty_json",
    }:
        issues.append("extraction_observed_tuple_invalid")
    else:
        if not expected or any(
            observed[k] != expected[k] for k in ("study_id", "outcome_id", "window")
        ):
            issues.append("protocol_outcome_mismatch")
        if observed["value_json"] != accepted_value:
            issues.append("extraction_verified_value_mismatch")
        try:
            value = json.loads(observed["uncertainty_json"])
            json.dumps(value, allow_nan=False)
        except (ValueError, TypeError):
            issues.append("extraction_uncertainty_invalid")
    return issues


ROB_DOMAINS = {
    "randomized_trial": (
        "randomization",
        "deviations",
        "missing_data",
        "measurement",
        "selective_reporting",
    ),
    "nonrandomized": (
        "confounding",
        "selection",
        "classification",
        "deviations",
        "missing_data",
        "measurement",
        "selective_reporting",
    ),
}
ROB_LEVELS = {
    "randomized_trial": ("low", "some_concerns", "high"),
    "nonrandomized": ("low", "moderate", "serious", "critical", "no_information"),
}


def rob_binding_issues(assessment):
    design = assessment["design"]
    domains = assessment.get("domains")
    levels = ROB_LEVELS.get(design)
    if levels is None:
        return ["rob_design_scheme_not_supported"]
    issues = []
    schemes = {
        "randomized_trial": {("RoB2-like", "1.0"), ("RoB2", "2019"), ("RoB 2", "2019")},
        "nonrandomized": {("ROBINS-I", "2016"), ("ROBINS-I-like", "1.0")},
    }
    if (assessment["scheme"], assessment["scheme_version"]) not in schemes[design]:
        issues.append("rob_design_scheme_mismatch")

    if (
        assessment["algorithmic_judgement"] not in levels
        or assessment["final_judgement"] not in levels
    ):
        issues.append("compensatory_quality_score")
    if (
        not isinstance(domains, list)
        or any(
            not isinstance(x, dict) or not isinstance(x.get("domain"), str)
            for x in domains
        )
        or {x["domain"] for x in domains} != set(ROB_DOMAINS[design])
        or len(domains) != len(ROB_DOMAINS[design])
    ):
        return issues + ["rob_required_domains_missing"]
    valid = []
    for row in domains:
        if row.get("judgement") not in levels or not primary_evidence_valid(
            row.get("evidence")
        ):
            issues.append("rob_domain_evidence_invalid")
        else:
            valid.append(levels.index(row["judgement"]))
    if len(valid) == len(domains):
        # A reassuring domain cannot offset a material concern elsewhere.
        worst = max(valid)
        for key in ("algorithmic_judgement", "final_judgement"):
            if assessment[key] in levels and levels.index(assessment[key]) < worst:
                issues.append("compensatory_quality_score")
        if worst > 0 and assessment.get("consequence_for_synthesis") not in {
            "sensitivity_only",
            "exclude_primary_pool",
            "include_with_explicit_limitations",
        }:
            issues.append("rob_synthesis_consequence_missing")
    if assessment.get("consequence_for_synthesis") not in {
        "include",
        "sensitivity_only",
        "exclude_primary_pool",
        "include_with_explicit_limitations",
    }:
        issues.append("rob_synthesis_consequence_missing")
    return sorted(set(issues))


def sensitivity_binding_issues(model, results):
    required = model.get("required_sensitivity")
    records = model.get("sensitivity_results")
    if (
        not isinstance(required, list)
        or not required
        or any(not isinstance(x, str) or not x for x in required)
        or len(set(required)) != len(required)
    ):
        return ["sensitivity_required_inventory_missing"]
    if not isinstance(records, list):
        return ["sensitivity_results_missing"]
    issues = []
    seen = set()
    protocol_text = model.get("sensitivity_protocol_json")
    try:
        protocol = json.loads(protocol_text)
    except (ValueError, TypeError):
        protocol = None
    if not isinstance(protocol, dict) or set(protocol) != {
        "protocol_id",
        "revision",
        "required_sensitivity",
    }:
        issues.append("sensitivity_protocol_missing")
    elif (
        not isinstance(protocol["protocol_id"], str)
        or not protocol["protocol_id"]
        or type(protocol["revision"]) is not int
        or protocol["revision"] < 1
        or protocol["required_sensitivity"] != required
        or model.get("sensitivity_protocol_sha256")
        != hashlib.sha256(protocol_text.encode()).hexdigest()
    ):
        issues.append("sensitivity_protocol_inventory_changed")

    for row in records:
        if not isinstance(row, dict):
            issues.append("sensitivity_result_invalid")
            continue
        ident = row.get("check_id")
        if not isinstance(ident, str) or ident in seen:
            issues.append("sensitivity_result_duplicate_or_invalid")
            continue
        seen.add(ident)
        if row.get("input_sha256") != sha256_json(results):
            issues.append("sensitivity_input_changed")
        if (
            row.get("status") not in {"completed", "not_computable"}
            or not isinstance(row.get("reason"), str)
            or not row["reason"].strip()
        ):
            issues.append("sensitivity_result_invalid")
        if row.get("status") == "not_computable":
            if row.get("effect_on_conclusion") != "no_pool":
                issues.append("sensitivity_uncomputable_not_disclosed")
            issues.append("sensitivity_no_pool")
        elif row.get("effect_on_conclusion") not in {
            "unchanged",
            "limited",
            "direction_changed",
        }:
            issues.append("sensitivity_conclusion_effect_missing")
        if row.get("effect_on_conclusion") in {"limited", "direction_changed"} and (
            not isinstance(model.get("conclusion_limitations"), list)
            or not model["conclusion_limitations"]
            or any(
                not isinstance(x, str) or not x.strip()
                for x in model["conclusion_limitations"]
            )
        ):
            issues.append("sensitivity_conclusion_limitations_missing")
        if not primary_evidence_valid(row.get("evidence")):
            issues.append("sensitivity_evidence_invalid")
    if set(required) - seen:
        issues.append("selective_sensitivity_reporting")
    if set(required) != set(model["sensitivity_receipts"]):
        issues.append("sensitivity_receipt_inventory_mismatch")
    return sorted(set(issues))
