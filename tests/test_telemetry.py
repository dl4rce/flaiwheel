"""Tests for persistent telemetry storage and impact metrics."""

from flaiwheel.telemetry import TelemetryStore


def test_summary_roundtrip_with_normalization(tmp_path):
    store = TelemetryStore(str(tmp_path))
    store.save_summary({
        "demo": {
            "total_calls": 2,
            "searches": 1,
            "search_misses": 1,
            "last_tool": "search_docs",
        }
    })

    loaded = store.load_summary()
    assert "demo" in loaded
    assert loaded["demo"]["total_calls"] == 2
    assert loaded["demo"]["searches"] == 1
    assert loaded["demo"]["search_misses"] == 1
    assert loaded["demo"]["writes"] == 0


def test_compute_impact_metrics_from_events(tmp_path):
    store = TelemetryStore(str(tmp_path))
    store.append_event("search_result", "demo", {
        "tool_name": "search_docs",
        "hit": True,
        "result_count": 3,
    })
    store.append_event("ci_guardrail_report", "demo", {
        "violations_found": 4,
        "violations_blocking": 2,
        "violations_fixed_before_merge": 1,
        "cycle_time_baseline_minutes": 30.0,
        "cycle_time_actual_minutes": 20.0,
    })

    metrics = store.compute_impact_metrics(project="demo", days=30)
    assert metrics["search_hits"] >= 1
    assert metrics["guardrail_violations_found"] >= 4
    assert metrics["regressions_avoided"] >= 1
    assert metrics["estimated_time_saved_minutes"] > 0
