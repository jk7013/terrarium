"""Capture and compare deterministic Terrarium retrieval baselines."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DEFAULT_QUERY_FILE = Path("benchmarks/retrieval/queries.json")
DEFAULT_BASELINE_FILE = Path("benchmarks/retrieval/baseline.json")
DEFAULT_PROFILES = ("fast", "default", "quality")
FAILURE_STATUSES = {
    "empty",
    "error",
    "http_error",
    "invalid_response",
    "timeout",
}


class QuerySpecError(ValueError):
    """Raised when the query specification cannot produce a safe baseline."""


@dataclass(frozen=True)
class Comparison:
    failures: list[dict[str, Any]]
    warnings: list[dict[str, Any]]

    @property
    def passed(self) -> bool:
        return not self.failures


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def read_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise QuerySpecError(f"{path} must contain one JSON object")
    return data


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def validate_query_spec(spec: dict[str, Any]) -> None:
    if spec.get("schema_version") != 1:
        raise QuerySpecError("query schema_version must be 1")

    profiles = spec.get("profiles", list(DEFAULT_PROFILES))
    if not isinstance(profiles, list) or not profiles:
        raise QuerySpecError("profiles must be a non-empty list")
    if any(profile not in DEFAULT_PROFILES for profile in profiles):
        raise QuerySpecError("profiles may only contain fast, default, and quality")
    if len(set(profiles)) != len(profiles):
        raise QuerySpecError("profiles must not contain duplicates")

    cases = spec.get("cases")
    if not isinstance(cases, list) or not cases:
        raise QuerySpecError("cases must be a non-empty list")

    case_ids: set[str] = set()
    for index, case in enumerate(cases):
        if not isinstance(case, dict):
            raise QuerySpecError(f"case #{index + 1} must be an object")
        case_id = str(case.get("case_id", "")).strip()
        query = str(case.get("query", "")).strip()
        source = str(case.get("source", "")).strip()
        if not case_id or not query or not source:
            raise QuerySpecError(
                f"case #{index + 1} needs non-empty case_id, query, and source"
            )
        if case_id in case_ids:
            raise QuerySpecError(f"duplicate case_id: {case_id}")
        case_ids.add(case_id)


def query_spec_sha256(spec: dict[str, Any]) -> str:
    encoded = json.dumps(
        spec,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def percentile(values: list[int], ratio: float) -> int | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, math.ceil(len(ordered) * ratio) - 1)
    return ordered[index]


def summarize_runs(runs: list[dict[str, Any]]) -> dict[str, Any]:
    statuses: dict[str, int] = {}
    mixed_source_runs = 0
    latency_by_profile: dict[str, list[int]] = {}

    for run in runs:
        status = str(run.get("status", "error"))
        statuses[status] = statuses.get(status, 0) + 1
        if run.get("source_mixing"):
            mixed_source_runs += 1
        if status == "success":
            profile = str(run["profile"])
            latency_by_profile.setdefault(profile, []).append(
                int(run["client_latency_ms"])
            )

    profile_summary: dict[str, dict[str, int | None]] = {}
    for profile, values in sorted(latency_by_profile.items()):
        profile_summary[profile] = {
            "count": len(values),
            "min": min(values),
            "median": percentile(values, 0.5),
            "p95": percentile(values, 0.95),
            "max": max(values),
        }

    return {
        "total_runs": len(runs),
        "statuses": statuses,
        "failed_runs": sum(
            count for status, count in statuses.items() if status in FAILURE_STATUSES
        ),
        "mixed_source_runs": mixed_source_runs,
        "latency_ms_by_profile": profile_summary,
    }


def _error_run(
    *,
    case: dict[str, Any],
    profile: str,
    status: str,
    elapsed_ms: int,
    error: str,
) -> dict[str, Any]:
    return {
        "case_id": case["case_id"],
        "group": case.get("group", ""),
        "query": case["query"],
        "source": case["source"],
        "profile": profile,
        "status": status,
        "client_latency_ms": elapsed_ms,
        "server_latency_ms": None,
        "results": [],
        "source_mixing": [],
        "error": error,
    }


def execute_run(
    *,
    base_url: str,
    case: dict[str, Any],
    profile: str,
    top_k: int,
    final_contexts: int,
    timeout_seconds: float,
    opener: Callable[..., Any] = urllib.request.urlopen,
    clock: Callable[[], float] = time.perf_counter,
) -> dict[str, Any]:
    payload = {
        "query": case["query"],
        "source": case["source"],
        "profile": profile,
        "options": {
            "top_k": top_k,
            "final_contexts": final_contexts,
        },
    }
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}/api/retrieve",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    started = clock()
    try:
        with opener(request, timeout=timeout_seconds) as response:
            body = response.read()
        elapsed_ms = round((clock() - started) * 1000)
        data = json.loads(body)
    except TimeoutError as exc:
        elapsed_ms = round((clock() - started) * 1000)
        return _error_run(
            case=case,
            profile=profile,
            status="timeout",
            elapsed_ms=elapsed_ms,
            error=str(exc) or f"request exceeded {timeout_seconds:g}s",
        )
    except urllib.error.HTTPError as exc:
        elapsed_ms = round((clock() - started) * 1000)
        return _error_run(
            case=case,
            profile=profile,
            status="http_error",
            elapsed_ms=elapsed_ms,
            error=f"HTTP {exc.code}: {exc.reason}",
        )
    except (OSError, urllib.error.URLError) as exc:
        elapsed_ms = round((clock() - started) * 1000)
        return _error_run(
            case=case,
            profile=profile,
            status="error",
            elapsed_ms=elapsed_ms,
            error=str(exc),
        )
    except (json.JSONDecodeError, UnicodeDecodeError, TypeError) as exc:
        elapsed_ms = round((clock() - started) * 1000)
        return _error_run(
            case=case,
            profile=profile,
            status="invalid_response",
            elapsed_ms=elapsed_ms,
            error=str(exc),
        )

    contexts = data.get("contexts")
    if not isinstance(contexts, list):
        return _error_run(
            case=case,
            profile=profile,
            status="invalid_response",
            elapsed_ms=elapsed_ms,
            error="response contexts is not a list",
        )

    expected_source = case["source"]
    results: list[dict[str, Any]] = []
    source_mixing: list[dict[str, Any]] = []
    for rank, context in enumerate(contexts[:top_k], start=1):
        meta = context.get("meta") if isinstance(context.get("meta"), dict) else {}
        tags = meta.get("tags") if isinstance(meta.get("tags"), list) else []
        item = {
            "rank": rank,
            "chunk_id": str(context.get("chunk_id", "")),
            "score": round(float(context.get("score", 0.0)), 12),
            "tags": [str(tag) for tag in tags],
        }
        results.append(item)
        if expected_source not in item["tags"]:
            source_mixing.append(
                {
                    "rank": rank,
                    "chunk_id": item["chunk_id"],
                    "tags": item["tags"],
                }
            )

    retrieval_meta = data.get("meta", {}).get("retrieval", {})
    status = "success" if results else "empty"
    return {
        "case_id": case["case_id"],
        "group": case.get("group", ""),
        "query": case["query"],
        "source": expected_source,
        "profile": profile,
        "status": status,
        "client_latency_ms": elapsed_ms,
        "server_latency_ms": retrieval_meta.get("latency_ms"),
        "results": results,
        "source_mixing": source_mixing,
        "error": None if results else "search returned no contexts",
    }


def capture(
    spec: dict[str, Any],
    *,
    base_url: str,
    timeout_seconds: float,
    opener: Callable[..., Any] = urllib.request.urlopen,
    progress: Callable[[str], None] | None = None,
    existing_snapshot: dict[str, Any] | None = None,
    checkpoint: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    validate_query_spec(spec)
    profiles = spec.get("profiles", list(DEFAULT_PROFILES))
    request_options = spec.get("request", {})
    top_k = int(request_options.get("top_k", 5))
    final_contexts = int(request_options.get("final_contexts", top_k))
    spec_hash = query_spec_sha256(spec)
    created_at = utc_now()
    saved_runs: dict[tuple[str, str], dict[str, Any]] = {}
    if existing_snapshot:
        existing_query_set = existing_snapshot.get("query_set_id")
        if existing_query_set != spec.get("query_set_id", ""):
            raise QuerySpecError(
                "resume snapshot query_set_id does not match the query specification"
            )
        existing_hash = existing_snapshot.get("query_spec_sha256")
        if existing_hash and existing_hash != spec_hash:
            raise QuerySpecError(
                "resume snapshot was created from a different query specification"
            )
        created_at = str(existing_snapshot.get("created_at") or created_at)
        saved_runs = {
            _run_key(run): run
            for run in existing_snapshot.get("runs", [])
            if isinstance(run, dict) and run.get("case_id") and run.get("profile")
        }

    runs: list[dict[str, Any]] = []
    total = len(spec["cases"]) * len(profiles)

    def build_snapshot() -> dict[str, Any]:
        return {
            "schema_version": 1,
            "query_set_id": spec.get("query_set_id", ""),
            "query_spec_sha256": spec_hash,
            "created_at": created_at,
            "updated_at": utc_now(),
            "base_url": base_url.rstrip("/"),
            "request": {
                "endpoint": "/api/retrieve",
                "top_k": top_k,
                "final_contexts": final_contexts,
                "timeout_seconds": timeout_seconds,
            },
            "profiles": profiles,
            "query_count": len(spec["cases"]),
            "summary": summarize_runs(runs),
            "runs": runs,
        }

    for case in spec["cases"]:
        for profile in profiles:
            key = str(case["case_id"]), str(profile)
            saved_run = saved_runs.get(key)
            if progress:
                progress(
                    f"[{len(runs) + 1}/{total}] "
                    f"{case['case_id']} ({case['source']}, {profile})"
                    f"{' [saved]' if saved_run else ''}"
                )
            run = saved_run or execute_run(
                base_url=base_url,
                case=case,
                profile=profile,
                top_k=top_k,
                final_contexts=final_contexts,
                timeout_seconds=timeout_seconds,
                opener=opener,
            )
            runs.append(run)
            if progress and run["status"] != "success":
                progress(f"  -> {run['status']}: {run['error']}")
            if checkpoint:
                checkpoint(build_snapshot())

    return build_snapshot()


def _run_key(run: dict[str, Any]) -> tuple[str, str]:
    return str(run["case_id"]), str(run["profile"])


def compare_snapshots(
    baseline: dict[str, Any],
    candidate: dict[str, Any],
    *,
    score_tolerance: float,
    latency_ratio: float,
    latency_slack_ms: int,
) -> Comparison:
    failures: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    baseline_runs = {_run_key(run): run for run in baseline.get("runs", [])}
    candidate_runs = {_run_key(run): run for run in candidate.get("runs", [])}

    for key in sorted(baseline_runs.keys() - candidate_runs.keys()):
        failures.append({"type": "missing_run", "case_id": key[0], "profile": key[1]})
    for key in sorted(candidate_runs.keys() - baseline_runs.keys()):
        failures.append({"type": "unexpected_run", "case_id": key[0], "profile": key[1]})

    for key in sorted(baseline_runs.keys() & candidate_runs.keys()):
        before = baseline_runs[key]
        after = candidate_runs[key]
        common = {"case_id": key[0], "profile": key[1]}

        if after.get("status") != "success":
            failures.append(
                {
                    "type": "search_failure",
                    **common,
                    "status": after.get("status"),
                    "error": after.get("error"),
                }
            )
            continue
        if after.get("source_mixing"):
            failures.append(
                {
                    "type": "source_mixing",
                    **common,
                    "results": after["source_mixing"],
                }
            )

        before_ids = [item["chunk_id"] for item in before.get("results", [])]
        after_ids = [item["chunk_id"] for item in after.get("results", [])]
        if before_ids != after_ids:
            failures.append(
                {
                    "type": "result_ids_changed",
                    **common,
                    "before": before_ids,
                    "after": after_ids,
                }
            )

        before_scores = [float(item["score"]) for item in before.get("results", [])]
        after_scores = [float(item["score"]) for item in after.get("results", [])]
        score_changes = [
            {
                "rank": rank,
                "before": old,
                "after": new,
                "difference": round(new - old, 12),
            }
            for rank, (old, new) in enumerate(
                zip(before_scores, after_scores, strict=False), start=1
            )
            if abs(new - old) > score_tolerance
        ]
        if score_changes:
            failures.append({"type": "scores_changed", **common, "changes": score_changes})

    baseline_latency = summarize_runs(list(baseline_runs.values()))[
        "latency_ms_by_profile"
    ]
    candidate_latency = summarize_runs(list(candidate_runs.values()))[
        "latency_ms_by_profile"
    ]
    for profile in sorted(set(baseline_latency) & set(candidate_latency)):
        for metric in ("median", "p95"):
            before_latency = int(baseline_latency[profile][metric])
            after_latency = int(candidate_latency[profile][metric])
            allowed_latency = round(before_latency * latency_ratio + latency_slack_ms)
            issue = {
                "profile": profile,
                "metric": metric,
                "before_ms": before_latency,
                "after_ms": after_latency,
                "allowed_ms": allowed_latency,
            }
            if after_latency > allowed_latency:
                failures.append({"type": "latency_regression", **issue})
            elif after_latency > before_latency:
                warnings.append(
                    {"type": "latency_increase_within_limit", **issue}
                )

    return Comparison(failures=failures, warnings=warnings)


def print_capture_summary(snapshot: dict[str, Any]) -> None:
    summary = snapshot["summary"]
    print(
        "runs={total_runs} failed={failed_runs} mixed_source={mixed_source_runs}".format(
            **summary
        )
    )
    for profile, latency in summary["latency_ms_by_profile"].items():
        print(
            f"{profile}: median={latency['median']}ms "
            f"p95={latency['p95']}ms max={latency['max']}ms"
        )


def print_comparison(comparison: Comparison) -> None:
    print(
        f"comparison={'PASS' if comparison.passed else 'FAIL'} "
        f"failures={len(comparison.failures)} warnings={len(comparison.warnings)}"
    )
    for issue in comparison.failures:
        location = (
            f"{issue.get('case_id')} / {issue.get('profile')}"
            if issue.get("case_id")
            else f"{issue.get('profile', '-')} / {issue.get('metric', '-')}"
        )
        print(
            f"FAIL {issue['type']}: {location}"
        )
    for issue in comparison.warnings:
        location = (
            f"{issue.get('case_id')} / {issue.get('profile')}"
            if issue.get("case_id")
            else f"{issue.get('profile', '-')} / {issue.get('metric', '-')}"
        )
        print(
            f"WARN {issue['type']}: {location}"
        )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Capture or compare Terrarium retrieval baselines."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    capture_parser = subparsers.add_parser("capture", help="write a baseline snapshot")
    capture_parser.add_argument("--queries", type=Path, default=DEFAULT_QUERY_FILE)
    capture_parser.add_argument("--output", type=Path, default=DEFAULT_BASELINE_FILE)
    capture_parser.add_argument("--base-url", default="http://127.0.0.1:9000")
    capture_parser.add_argument("--timeout", type=float, default=120.0)
    capture_parser.add_argument(
        "--resume",
        action="store_true",
        help="continue from an existing output file",
    )

    check_parser = subparsers.add_parser(
        "check", help="capture current results and compare them with a baseline"
    )
    check_parser.add_argument("--queries", type=Path, default=DEFAULT_QUERY_FILE)
    check_parser.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE_FILE)
    check_parser.add_argument("--candidate-output", type=Path)
    check_parser.add_argument("--base-url", default="http://127.0.0.1:9000")
    check_parser.add_argument("--timeout", type=float, default=120.0)
    check_parser.add_argument("--score-tolerance", type=float, default=0.000001)
    check_parser.add_argument("--latency-ratio", type=float, default=1.5)
    check_parser.add_argument("--latency-slack-ms", type=int, default=500)
    check_parser.add_argument(
        "--resume",
        action="store_true",
        help="continue from an existing candidate output file",
    )

    compare_parser = subparsers.add_parser(
        "compare", help="compare two existing snapshot files"
    )
    compare_parser.add_argument("--baseline", type=Path, required=True)
    compare_parser.add_argument("--candidate", type=Path, required=True)
    compare_parser.add_argument("--score-tolerance", type=float, default=0.000001)
    compare_parser.add_argument("--latency-ratio", type=float, default=1.5)
    compare_parser.add_argument("--latency-slack-ms", type=int, default=500)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "capture":
            spec = read_json(args.queries)
            existing = (
                read_json(args.output)
                if args.resume and args.output.exists()
                else None
            )
            snapshot = capture(
                spec,
                base_url=args.base_url,
                timeout_seconds=args.timeout,
                progress=lambda message: print(message, flush=True),
                existing_snapshot=existing,
                checkpoint=lambda current: write_json(args.output, current),
            )
            write_json(args.output, snapshot)
            print(f"wrote {args.output}")
            print_capture_summary(snapshot)
            summary = snapshot["summary"]
            return int(
                summary["failed_runs"] > 0 or summary["mixed_source_runs"] > 0
            )

        if args.command == "check":
            spec = read_json(args.queries)
            baseline = read_json(args.baseline)
            existing = (
                read_json(args.candidate_output)
                if args.resume
                and args.candidate_output
                and args.candidate_output.exists()
                else None
            )
            candidate = capture(
                spec,
                base_url=args.base_url,
                timeout_seconds=args.timeout,
                progress=lambda message: print(message, flush=True),
                existing_snapshot=existing,
                checkpoint=(
                    (lambda current: write_json(args.candidate_output, current))
                    if args.candidate_output
                    else None
                ),
            )
            if args.candidate_output:
                write_json(args.candidate_output, candidate)
                print(f"wrote {args.candidate_output}")
            print_capture_summary(candidate)
            comparison = compare_snapshots(
                baseline,
                candidate,
                score_tolerance=args.score_tolerance,
                latency_ratio=args.latency_ratio,
                latency_slack_ms=args.latency_slack_ms,
            )
            print_comparison(comparison)
            return 0 if comparison.passed else 1

        baseline = read_json(args.baseline)
        candidate = read_json(args.candidate)
        comparison = compare_snapshots(
            baseline,
            candidate,
            score_tolerance=args.score_tolerance,
            latency_ratio=args.latency_ratio,
            latency_slack_ms=args.latency_slack_ms,
        )
        print_comparison(comparison)
        return 0 if comparison.passed else 1
    except (OSError, QuerySpecError, json.JSONDecodeError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
