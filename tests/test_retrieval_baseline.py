import json
from pathlib import Path
from typing import Self

import pytest

from scripts import retrieval_baseline


class FakeResponse:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self.payload).encode()


def minimal_spec() -> dict:
    return {
        "schema_version": 1,
        "query_set_id": "test",
        "profiles": ["fast"],
        "request": {"top_k": 2, "final_contexts": 2},
        "cases": [
            {
                "case_id": "mdn-1",
                "group": "mdn_http",
                "source": "mdn_http",
                "query": "What is HTTP?",
            }
        ],
    }


def test_validate_query_spec_rejects_duplicate_case_ids() -> None:
    spec = minimal_spec()
    spec["cases"].append(dict(spec["cases"][0]))

    with pytest.raises(retrieval_baseline.QuerySpecError, match="duplicate case_id"):
        retrieval_baseline.validate_query_spec(spec)


def test_repository_query_set_contains_approved_mdn_and_fixed_law_cases() -> None:
    spec = retrieval_baseline.read_json(
        Path("benchmarks/retrieval/queries.json")
    )
    retrieval_baseline.validate_query_spec(spec)

    groups = [case["group"] for case in spec["cases"]]
    assert groups.count("mdn_http") == 25
    assert groups.count("law") == 3
    assert spec["profiles"] == ["fast", "default", "quality"]


def test_capture_records_ids_scores_latency_and_source_mixing() -> None:
    payload = {
        "contexts": [
            {
                "chunk_id": "mdn:1",
                "score": 0.12345678901234,
                "meta": {"tags": ["mdn_http"]},
            },
            {
                "chunk_id": "law:1",
                "score": 0.1,
                "meta": {"tags": ["law"]},
            },
        ],
        "meta": {"retrieval": {"latency_ms": 17}},
    }

    snapshot = retrieval_baseline.capture(
        minimal_spec(),
        base_url="http://terrarium.test",
        timeout_seconds=1,
        opener=lambda request, timeout: FakeResponse(payload),
    )

    run = snapshot["runs"][0]
    assert run["status"] == "success"
    assert run["results"] == [
        {
            "rank": 1,
            "chunk_id": "mdn:1",
            "score": 0.123456789012,
            "tags": ["mdn_http"],
        },
        {
            "rank": 2,
            "chunk_id": "law:1",
            "score": 0.1,
            "tags": ["law"],
        },
    ]
    assert run["server_latency_ms"] == 17
    assert run["source_mixing"] == [
        {"rank": 2, "chunk_id": "law:1", "tags": ["law"]}
    ]
    assert snapshot["summary"]["mixed_source_runs"] == 1


def test_timeout_is_preserved_as_a_result() -> None:
    def timeout_opener(request: object, timeout: float) -> None:
        raise TimeoutError("too slow")

    snapshot = retrieval_baseline.capture(
        minimal_spec(),
        base_url="http://terrarium.test",
        timeout_seconds=1,
        opener=timeout_opener,
    )

    run = snapshot["runs"][0]
    assert run["status"] == "timeout"
    assert run["results"] == []
    assert run["error"] == "too slow"
    assert snapshot["summary"]["failed_runs"] == 1


def test_capture_resumes_saved_runs_without_calling_api_again() -> None:
    saved = {
        "query_set_id": "test",
        "runs": [
            {
                "case_id": "mdn-1",
                "group": "mdn_http",
                "query": "What is HTTP?",
                "source": "mdn_http",
                "profile": "fast",
                "status": "success",
                "client_latency_ms": 10,
                "server_latency_ms": 8,
                "results": [
                    {
                        "rank": 1,
                        "chunk_id": "saved",
                        "score": 0.5,
                        "tags": ["mdn_http"],
                    }
                ],
                "source_mixing": [],
                "error": None,
            }
        ],
    }

    def unexpected_opener(request: object, timeout: float) -> None:
        raise AssertionError("saved run should not call the API")

    snapshot = retrieval_baseline.capture(
        minimal_spec(),
        base_url="http://terrarium.test",
        timeout_seconds=1,
        opener=unexpected_opener,
        existing_snapshot=saved,
    )

    assert snapshot["runs"][0]["results"][0]["chunk_id"] == "saved"
    assert snapshot["query_spec_sha256"] == retrieval_baseline.query_spec_sha256(
        minimal_spec()
    )


def test_compare_detects_result_score_source_and_latency_regressions() -> None:
    base_run = {
        "case_id": "mdn-1",
        "profile": "fast",
        "status": "success",
        "client_latency_ms": 100,
        "results": [{"chunk_id": "old", "score": 0.5}],
        "source_mixing": [],
    }
    candidate_run = {
        "case_id": "mdn-1",
        "profile": "fast",
        "status": "success",
        "client_latency_ms": 1000,
        "results": [{"chunk_id": "new", "score": 0.4}],
        "source_mixing": [{"chunk_id": "new", "tags": ["law"]}],
    }

    comparison = retrieval_baseline.compare_snapshots(
        {"runs": [base_run]},
        {"runs": [candidate_run]},
        score_tolerance=0.000001,
        latency_ratio=1.5,
        latency_slack_ms=100,
    )

    assert not comparison.passed
    assert {failure["type"] for failure in comparison.failures} == {
        "source_mixing",
        "result_ids_changed",
        "scores_changed",
        "latency_regression",
    }


def test_compare_accepts_identical_results_with_small_timing_noise() -> None:
    baseline = {
        "runs": [
            {
                "case_id": "mdn-1",
                "profile": "fast",
                "status": "success",
                "client_latency_ms": 100,
                "results": [{"chunk_id": "same", "score": 0.5}],
                "source_mixing": [],
            }
        ]
    }
    candidate = json.loads(json.dumps(baseline))
    candidate["runs"][0]["client_latency_ms"] = 120

    comparison = retrieval_baseline.compare_snapshots(
        baseline,
        candidate,
        score_tolerance=0.000001,
        latency_ratio=1.5,
        latency_slack_ms=100,
    )

    assert comparison.passed
    assert comparison.warnings[0]["type"] == "latency_increase_within_limit"
