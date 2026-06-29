import json

from tcgjson.cli import main
from tcgjson.operations import evaluate_operations, evaluation_text


def test_evaluate_operations_checks_metrics_and_data_cache(tmp_path) -> None:
    constraints = {
        "githubActions": {"jobTimeoutMinutes": 1},
        "dataCache": {"maxTrackedCacheMegabytes": 1, "maxFilesPerDirectory": 2, "warnFilesPerDirectory": 1},
    }
    constraints_path = tmp_path / "constraints.json"
    metrics_path = tmp_path / "metrics.json"
    data_cache_dir = tmp_path / "data-cache"
    bucket = data_cache_dir / "product-details" / "540" / "213"
    bucket.mkdir(parents=True)
    (bucket / "540213.json").write_text("{}", encoding="utf-8")
    (bucket / "540214.json").write_text("{}", encoding="utf-8")
    constraints_path.write_text(json.dumps(constraints), encoding="utf-8")
    metrics_path.write_text(json.dumps({"durationSeconds": 30}), encoding="utf-8")

    evaluation = evaluate_operations(
        constraints_path=constraints_path,
        metrics_path=metrics_path,
        data_cache_dir=data_cache_dir,
    )

    assert evaluation["passed"] is True
    assert {check["name"] for check in evaluation["checks"]} == {
        "build.durationSeconds",
        "dataCache.sizeMegabytes",
        "dataCache.maxFilesPerDirectory",
    }
    assert "WARN dataCache.maxFilesPerDirectory" in evaluation_text(evaluation)


def test_evaluate_operations_fails_when_metrics_exceed_runtime(tmp_path) -> None:
    constraints_path = tmp_path / "constraints.json"
    metrics_path = tmp_path / "metrics.json"
    constraints_path.write_text(
        json.dumps(
            {
                "githubActions": {"jobTimeoutMinutes": 1},
                "dataCache": {"maxTrackedCacheMegabytes": 1, "maxFilesPerDirectory": 1, "warnFilesPerDirectory": 1},
            }
        ),
        encoding="utf-8",
    )
    metrics_path.write_text(json.dumps({"durationSeconds": 61}), encoding="utf-8")

    evaluation = evaluate_operations(constraints_path=constraints_path, metrics_path=metrics_path)

    assert evaluation["passed"] is False
    assert evaluation["checks"][0]["name"] == "build.durationSeconds"


def test_ops_evaluate_is_soft_by_default_and_strict_when_requested(tmp_path, capsys) -> None:
    constraints_path = tmp_path / "constraints.json"
    metrics_path = tmp_path / "metrics.json"
    constraints_path.write_text(
        json.dumps(
            {
                "githubActions": {"jobTimeoutMinutes": 1},
                "dataCache": {"maxTrackedCacheMegabytes": 1, "maxFilesPerDirectory": 1, "warnFilesPerDirectory": 1},
            }
        ),
        encoding="utf-8",
    )
    metrics_path.write_text(json.dumps({"durationSeconds": 61}), encoding="utf-8")

    assert main(["ops", "evaluate", "--constraints", str(constraints_path), "--metrics", str(metrics_path)]) == 0
    assert "Overall: FAIL" in capsys.readouterr().out

    assert (
        main(
            [
                "ops",
                "evaluate",
                "--constraints",
                str(constraints_path),
                "--metrics",
                str(metrics_path),
                "--strict",
            ]
        )
        == 1
    )
