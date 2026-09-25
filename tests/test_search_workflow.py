from __future__ import annotations

import copy
import unittest

from hermes_research_report.errors import ContractError
from hermes_research_report.search_workflow import (
    assess_screening_stop,
    assess_search_stop,
    assess_search_strategy,
    compile_query_ast,
    record_search_environment,
)


def node(
    node_id: str,
    node_type: str,
    *,
    value: str | None = None,
    field: str | None = None,
    operator: str | None = None,
    children: list[str] | None = None,
    distance: int | None = None,
    ordered: bool | None = None,
    lower: str | None = None,
    upper: str | None = None,
) -> dict:
    return {
        "node_id": node_id,
        "type": node_type,
        "value": value,
        "field": field,
        "operator": operator,
        "children": children or [],
        "distance": distance,
        "ordered": ordered,
        "lower": lower,
        "upper": upper,
    }


def query_request(profile: str) -> dict:
    return {
        "schema_version": 1,
        "query_ast": {
            "ast_id": "AST-1",
            "version": 1,
            "root_id": "BOOL-1",
            "nodes": [
                node("HEADING-1", "heading", value="Diabetes Mellitus"),
                node("PHRASE-1", "phrase", value="blood pressure"),
                node("TERM-1", "term", value="outcomes"),
                node(
                    "PROX-1",
                    "proximity",
                    children=["PHRASE-1", "TERM-1"],
                    distance=3,
                    ordered=False,
                ),
                node(
                    "BOOL-1",
                    "boolean",
                    operator="OR",
                    children=["HEADING-1", "PROX-1"],
                ),
            ],
        },
        "compiler": {
            "compiler_id": f"compiler-{profile}",
            "compiler_version": "1.0.0",
            "database": "MEDLINE",
            "platform": "PubMed" if profile == "pubmed" else "Ovid",
            "syntax_profile": profile,
            "field_map": [
                {
                    "canonical": "title_abstract",
                    "native": "Title/Abstract" if profile == "pubmed" else "ti,ab",
                }
            ],
            "heading_mode": "native",
            "supports_proximity": profile == "ovid",
            "supports_range": True,
            "semantic_extensions": [],
        },
    }


def strategy_request(*, review: bool = True) -> dict:
    strategy_hash = "a" * 64
    return {
        "schema_version": 1,
        "strategy_id": "STRATEGY-1",
        "strategy_version": 1,
        "strategy_hash": strategy_hash,
        "material": True,
        "review": (
            {
                "review_id": "REVIEW-1",
                "reviewer_id": "REVIEWER-2",
                "independent": True,
                "reviewed_strategy_hash": strategy_hash,
                "status": "pass",
                "reviewed_at": "2026-09-15T00:00:00Z",
                "valid_until": "2026-10-15T00:00:00Z",
                "dimensions": ["concepts", "syntax", "sources", "limits"],
                "findings": [],
            }
            if review
            else None
        ),
        "repeat_requests": [],
    }


def environment_request(*, stable: bool = True) -> dict:
    compiled = compile_query_ast(query_request("pubmed"))["compiled_query"]
    return {
        "schema_version": 1,
        "search_id": "SEARCH-1",
        "executable_query": compiled,
        "provider_receipt_ref": "provider/SEARCH-1",
        "environment": {
            "database": "MEDLINE",
            "platform": "PubMed",
            "coverage_start": "1946-01-01",
            "coverage_end": "2026-09-15",
            "executed_at": "2026-09-15T00:00:00Z",
            "locale": "en-US",
            "index_version": "2026-09-15",
            "ranking_version": "best-match-2026-09",
            "filters": {"language": ["en"]},
            "personalization": "disabled",
            "paid_insertions": "none_observed",
            "mode": "live",
            "stable_snapshot": stable,
            "snapshot_id": "SNAPSHOT-1" if stable else None,
            "cursor_id": "CURSOR-ROOT" if stable else None,
        },
        "pages": [
            {
                "page_number": 1,
                "item_ids": ["A", "B"],
                "set_version": "SET-1",
                "watermark": "2026-09-15T00:00:00Z",
                "request_cursor": None,
                "continuation_cursor": "CURSOR-2",
                "raw_receipt_ref": "raw/page-1",
                "observed_at": "2026-09-15T00:00:01Z",
            },
            {
                "page_number": 2,
                "item_ids": ["B", "C"],
                "set_version": "SET-1",
                "watermark": "2026-09-15T00:00:00Z",
                "request_cursor": "CURSOR-2",
                "continuation_cursor": None,
                "raw_receipt_ref": "raw/page-2",
                "observed_at": "2026-09-15T00:00:02Z",
            },
        ],
        "qualification_evidence": [
            {
                "mode": "frozen",
                "status": "pass",
                "receipt_ref": "qualification/frozen",
                "environment_hash": "b" * 64,
            }
        ],
        "requested_qualification_mode": "frozen",
    }


def search_stop_request() -> dict:
    return {
        "schema_version": 1,
        "coverage_cells": [
            {
                "cell_id": "CELL-WEB",
                "family": "web",
                "channel": "general-search",
                "status": "covered",
                "receipt_refs": ["search/web"],
            },
            {
                "cell_id": "CELL-CITATION",
                "family": "academic",
                "channel": "citation-chasing",
                "status": "covered",
                "receipt_refs": ["search/citation"],
            },
        ],
        "yield_iterations": [
            {
                "iteration": 1,
                "new_origins": 3,
                "new_families": 1,
                "new_material_claims": 1,
            },
            {
                "iteration": 2,
                "new_origins": 0,
                "new_families": 0,
                "new_material_claims": 0,
            },
            {
                "iteration": 3,
                "new_origins": 0,
                "new_families": 0,
                "new_material_claims": 0,
            },
        ],
        "residual_estimate": {
            "estimated_mass": 0.02,
            "missing_probability": 0.03,
            "uncertainty": 0.04,
            "model_ref": "capture-recapture",
            "model_version": "1.0",
            "calibrated": True,
        },
        "policy": {
            "max_residual_mass": 0.05,
            "max_missing_probability": 0.05,
            "max_uncertainty": 0.1,
            "max_recent_material_gain": 0,
            "minimum_independent_seeds": 3,
        },
        "url_novelty_zero": True,
        "budget_exhausted": False,
        "citation_seeds": [
            {
                "seed_id": f"SEED-{index}",
                "origin_cluster": f"ORIGIN-{index}",
                "selection_method": "independent_stratified",
                "unique_result_ids": [f"RESULT-{index}"],
                "claim_ids": [f"CLAIM-{index}"],
            }
            for index in range(1, 4)
        ],
        "leave_one_seed_results": [
            {
                "removed_seed_id": f"SEED-{index}",
                "lost_result_ids": [f"RESULT-{index}"],
                "changed_claim_ids": [f"CLAIM-{index}"] if index == 3 else [],
            }
            for index in range(1, 4)
        ],
    }


def screening_request() -> dict:
    decisions = [
        {
            "record_id": f"R-{index}",
            "rank": index,
            "probability": max(0, 1 - index / 10),
            "model_decision": "include" if index <= 2 else "exclude",
            "human_override": "include" if index == 3 else None,
            "final_decision": "include" if index <= 3 else "exclude",
            "reason": "fixture decision",
        }
        for index in range(1, 11)
    ]
    return {
        "schema_version": 1,
        "model": {
            "model_id": "SCREEN-1",
            "model_version": "1.0",
            "model_hash": "1" * 64,
            "instruction_hash": "2" * 64,
            "feature_schema_hash": "3" * 64,
            "seed_examples_hash": "4" * 64,
        },
        "stopping_rule": {
            "rule_id": "RULE-1",
            "rule_version": "1.0",
            "rule_hash": "5" * 64,
            "frozen_before_screening": True,
        },
        "decisions": decisions,
        "proposal": {
            "tail_record_ids": [f"R-{index}" for index in range(3, 11)],
            "exclusion_fraction": 0.8,
            "probability_threshold": 0.8,
        },
        "calibration": {
            "sample_size": 100,
            "recall": 0.99,
            "false_negative_rate": 0.01,
            "receipt_ref": "calibration/1",
        },
        "tail_sample": {
            "method": "random",
            "sampled_record_ids": ["R-4", "R-6"],
            "relevant_record_ids": [],
            "estimated_false_negative_rate": 0.01,
            "uncertainty": 0.02,
            "receipt_ref": "tail-sample/1",
        },
        "policy": {
            "minimum_calibration_size": 50,
            "minimum_tail_sample_size": 2,
            "maximum_false_negative_rate": 0.05,
            "allowed_sampling_methods": ["random", "stratified"],
        },
    }


class SearchWorkflowTests(unittest.TestCase):
    def test_tc_150_mesh_proximity_compiles_to_pubmed_and_ovid(self) -> None:
        pubmed = compile_query_ast(query_request("pubmed"))
        ovid = compile_query_ast(query_request("ovid"))
        self.assertEqual(
            pubmed["compiled_query"]["executable_query"],
            '("Diabetes Mellitus"[MeSH Terms] OR ("blood pressure" AND outcomes))',
        )
        self.assertEqual(
            ovid["compiled_query"]["executable_query"],
            '(exp Diabetes Mellitus/ OR ("blood pressure" adj3 outcomes))',
        )
        self.assertEqual(pubmed["status"], "compiled_with_changes")
        self.assertEqual(
            pubmed["translation_losses"][0]["reason"],
            "proximity_degraded_to_conjunction",
        )
        self.assertEqual(ovid["status"], "compiled_exact")

    def test_tc_151_material_search_requires_current_independent_review(self) -> None:
        blocked = assess_search_strategy(strategy_request(review=False))
        self.assertEqual(blocked["status"], "blocked")
        self.assertFalse(blocked["main_search_allowed"])
        self.assertEqual(blocked["issues"], ["search_strategy_review_required"])
        ready = assess_search_strategy(strategy_request())
        self.assertEqual(ready["status"], "strategy_ready")
        self.assertTrue(ready["main_search_allowed"])

    def test_tc_152_environment_receipt_preserves_all_execution_fields(self) -> None:
        result = record_search_environment(environment_request())
        self.assertEqual(result["status"], "recorded")
        self.assertEqual(result["environment"]["database"], "MEDLINE")
        self.assertEqual(result["environment"]["platform"], "PubMed")
        self.assertEqual(result["environment"]["coverage_start"], "1946-01-01")
        self.assertEqual(result["environment"]["index_version"], "2026-09-15")
        self.assertIn("Diabetes Mellitus", result["exact_executable_query"])
        self.assertEqual(result["raw_result_count"], 4)
        self.assertEqual(result["deduplicated_result_count"], 3)

    def test_tc_153_dynamic_pages_expose_result_set_drift_and_gap_risk(self) -> None:
        request = environment_request(stable=False)
        request["pages"][1]["set_version"] = "SET-2"
        request["pages"][1]["item_ids"] = ["C", "D"]
        result = record_search_environment(request)
        self.assertEqual(result["status"], "result_set_drift")
        self.assertTrue(result["result_set_drift"])
        self.assertTrue(result["potential_omission"])
        self.assertFalse(result["deduplication_hides_omission"])

    def test_tc_154_frozen_pass_does_not_qualify_live(self) -> None:
        request = environment_request()
        request["requested_qualification_mode"] = "live"
        result = record_search_environment(request)
        self.assertEqual(result["qualified_modes"], ["frozen"])
        self.assertEqual(result["qualification_claim_status"], "rejected")
        self.assertFalse(result["mode_qualification_transfer"])

    def test_tc_155_zero_new_urls_cannot_hide_open_channel(self) -> None:
        request = search_stop_request()
        request["coverage_cells"][1]["status"] = "uncovered"
        result = assess_search_stop(request)
        self.assertEqual(result["status"], "continue")
        self.assertFalse(result["stop_approved"])
        self.assertIn("CELL-CITATION", result["uncovered_cell_ids"])
        self.assertIn("coverage_open", result["blockers"])
        self.assertFalse(result["repeated_url_is_sufficient"])
        self.assertEqual(result["residual_estimate"]["estimated_mass"], 0.02)

    def test_tc_156_three_independent_seeds_preserve_leave_one_deltas(self) -> None:
        result = assess_search_stop(search_stop_request())
        self.assertEqual(result["status"], "stop_approved")
        self.assertEqual(result["citation_seed_count"], 3)
        self.assertEqual(result["independent_seed_origin_count"], 3)
        self.assertEqual(len(result["seed_sensitivity"]), 3)
        self.assertEqual(
            result["seed_sensitivity"][2]["changed_claim_ids"], ["CLAIM-3"]
        )

    def test_tc_157_screening_versions_ranks_decisions_and_override_are_reproducible(
        self,
    ) -> None:
        result = assess_screening_stop(screening_request())
        self.assertEqual(result["status"], "stop_approved")
        self.assertEqual(result["model"]["model_version"], "1.0")
        self.assertEqual(result["human_override_count"], 1)
        overridden = next(
            item for item in result["decisions"] if item["record_id"] == "R-3"
        )
        self.assertEqual(overridden["model_decision"], "exclude")
        self.assertEqual(overridden["human_override"], "include")
        self.assertEqual(overridden["final_decision"], "include")

    def test_tc_158_tail_exclusion_requires_calibration_and_random_sample(self) -> None:
        request = screening_request()
        request["calibration"] = None
        request["tail_sample"] = None
        result = assess_screening_stop(request)
        self.assertEqual(result["status"], "stop_rejected")
        self.assertEqual(
            set(result["blockers"]), {"calibration_missing", "tail_sample_missing"}
        )
        self.assertFalse(result["automatic_tail_exclusion_allowed"])

    def test_tc_159_relevant_sample_record_reopens_screening(self) -> None:
        request = screening_request()
        request["tail_sample"]["relevant_record_ids"] = ["R-6"]
        request["tail_sample"]["estimated_false_negative_rate"] = 0.2
        result = assess_screening_stop(request)
        self.assertEqual(result["status"], "stop_rejected")
        self.assertTrue(result["screening_must_resume"])
        self.assertIn("screening_false_negative_observed", result["blockers"])
        self.assertIn("tail_false_negative_rate_exceeded", result["blockers"])

    def test_repeat_tool_requires_new_dimension_and_expected_gain(self) -> None:
        request = strategy_request()
        request["repeat_requests"] = [
            {
                "repeat_id": "REPEAT-1",
                "tool_ref": "search-provider",
                "new_purpose": False,
                "new_scope": False,
                "new_method": False,
                "expected_gain": 0,
            }
        ]
        result = assess_search_strategy(request)
        self.assertEqual(result["status"], "blocked")
        self.assertFalse(result["repeat_decisions"][0]["allowed"])

    def test_query_cycles_and_page_cursor_gaps_are_detected(self) -> None:
        request = query_request("pubmed")
        request["query_ast"]["nodes"][0]["children"] = ["BOOL-1"]
        request["query_ast"]["nodes"][0]["type"] = "field"
        request["query_ast"]["nodes"][0]["field"] = "title_abstract"
        with self.assertRaisesRegex(ContractError, "цикл"):
            compile_query_ast(request)
        request = environment_request(stable=False)
        request["pages"][1]["request_cursor"] = "WRONG"
        result = record_search_environment(request)
        self.assertTrue(result["result_set_drift"])
        self.assertEqual(result["continuation_gap_pages"], [2])

    def test_functions_do_not_mutate_requests(self) -> None:
        requests_and_functions = [
            (query_request("pubmed"), compile_query_ast),
            (strategy_request(), assess_search_strategy),
            (environment_request(), record_search_environment),
            (search_stop_request(), assess_search_stop),
            (screening_request(), assess_screening_stop),
        ]
        for request, function in requests_and_functions:
            original = copy.deepcopy(request)
            function(request)
            self.assertEqual(request, original)


if __name__ == "__main__":
    unittest.main()
