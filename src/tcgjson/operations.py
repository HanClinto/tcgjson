"""Evaluate operational constraints for scheduled catalog update jobs."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


DEFAULT_CONSTRAINTS_PATH = Path("operations-constraints.json")
BYTES_PER_MEGABYTE = 1024 * 1024


def load_constraints(path: Path = DEFAULT_CONSTRAINTS_PATH) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def evaluate_operations(
    *,
    constraints_path: Path = DEFAULT_CONSTRAINTS_PATH,
    metrics_path: Path | None = None,
    data_cache_dir: Path = Path("data-cache"),
) -> dict[str, Any]:
    constraints = load_constraints(constraints_path)
    checks = []
    metrics = _load_optional_json(metrics_path)

    if metrics is not None:
        max_runtime_seconds = int(constraints["githubActions"]["jobTimeoutMinutes"]) * 60
        duration_seconds = float(metrics.get("durationSeconds") or 0)
        checks.append(
            _check(
                "build.durationSeconds",
                duration_seconds <= max_runtime_seconds,
                observed=round(duration_seconds, 3),
                limit=max_runtime_seconds,
                unit="seconds",
            )
        )

    if data_cache_dir.exists():
        cache_bytes = _directory_size(data_cache_dir)
        max_cache_bytes = int(constraints["dataCache"]["maxTrackedCacheMegabytes"]) * BYTES_PER_MEGABYTE
        max_files_per_dir = int(constraints["dataCache"]["maxFilesPerDirectory"])
        warn_files_per_dir = int(constraints["dataCache"]["warnFilesPerDirectory"])
        busiest = _busiest_directory(data_cache_dir)
        checks.extend(
            [
                _check(
                    "dataCache.sizeMegabytes",
                    cache_bytes <= max_cache_bytes,
                    observed=round(cache_bytes / BYTES_PER_MEGABYTE, 3),
                    limit=constraints["dataCache"]["maxTrackedCacheMegabytes"],
                    unit="MiB",
                ),
                _check(
                    "dataCache.maxFilesPerDirectory",
                    busiest[1] <= max_files_per_dir,
                    observed=busiest[1],
                    limit=max_files_per_dir,
                    unit="files",
                    path=busiest[0],
                    warning=busiest[1] > warn_files_per_dir,
                ),
            ]
        )

    return {
        "object": "tcgjson_operations_evaluation",
        "version": 1,
        "constraintsPath": str(constraints_path),
        "metricsPath": str(metrics_path) if metrics_path is not None else "",
        "dataCacheDir": str(data_cache_dir),
        "passed": all(check["passed"] for check in checks),
        "checks": checks,
    }


def evaluation_text(evaluation: dict[str, Any]) -> str:
    lines = ["Operations constraints evaluation"]
    for check in evaluation["checks"]:
        marker = "PASS" if check["passed"] else "FAIL"
        if check.get("warning") and check["passed"]:
            marker = "WARN"
        line = f"{marker} {check['name']}: observed {check['observed']} {check['unit']} <= {check['limit']}"
        if check.get("path"):
            line += f" ({check['path']})"
        lines.append(line)
    lines.append(f"Overall: {'PASS' if evaluation['passed'] else 'FAIL'}")
    return "\n".join(lines)


def _load_optional_json(path: Path | None) -> dict[str, Any] | None:
    if path is None or not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _directory_size(path: Path) -> int:
    return sum(child.stat().st_size for child in path.rglob("*") if child.is_file())


def _busiest_directory(path: Path) -> tuple[str, int]:
    busiest_path = path
    busiest_count = 0
    for directory in [path, *[child for child in path.rglob("*") if child.is_dir()]]:
        file_count = sum(1 for child in directory.iterdir() if child.is_file())
        if file_count > busiest_count:
            busiest_path = directory
            busiest_count = file_count
    return str(busiest_path), busiest_count


def _check(
    name: str,
    passed: bool,
    *,
    observed: int | float,
    limit: int | float,
    unit: str,
    path: str = "",
    warning: bool = False,
) -> dict[str, Any]:
    return {
        "name": name,
        "passed": passed,
        "warning": warning,
        "observed": observed,
        "limit": limit,
        "unit": unit,
        "path": path,
    }
