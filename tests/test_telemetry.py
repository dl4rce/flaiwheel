"""Tests for persistent telemetry storage and impact metrics."""

import json

from flaiwheel import telemetry as telemetry_module
from flaiwheel.telemetry import MIRROR_DIRNAME, MIRROR_FILENAME, TelemetryStore


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


# ── Cold-start mirror persistence ─────────────────────


def _fake_monotonic_factory(monkeypatch):
    """Return a clock function whose return value lives in a closure."""
    clock = {"now": 1000.0}

    def fake_monotonic() -> float:
        return clock["now"]

    monkeypatch.setattr(telemetry_module, "_monotonic", fake_monotonic)
    return clock


def test_save_summary_mirrors_to_project_docs(tmp_path, monkeypatch):
    """Hot-tier save also writes per-project mirror file."""
    _fake_monotonic_factory(monkeypatch)
    vectorstore = tmp_path / "data"
    docs = tmp_path / "docs" / "demo"
    docs.mkdir(parents=True)

    store = TelemetryStore(str(vectorstore))
    store.set_project_mirror("demo", docs)
    store.save_summary({"demo": {"total_calls": 7, "searches": 3, "last_tool": "search_docs"}})

    mirror = docs / MIRROR_DIRNAME / MIRROR_FILENAME
    assert mirror.exists(), "Mirror file should be written"
    payload = json.loads(mirror.read_text())
    assert payload["project"] == "demo"
    assert payload["total_calls"] == 7
    assert payload["searches"] == 3
    assert "updated_at" in payload


def test_unregistered_project_is_not_mirrored(tmp_path, monkeypatch):
    """Projects with no mirror registration are never mirrored."""
    _fake_monotonic_factory(monkeypatch)
    vectorstore = tmp_path / "data"
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir()

    store = TelemetryStore(str(vectorstore))
    # Note: no set_project_mirror call.
    store.save_summary({"unknown": {"total_calls": 1}})

    # The fake docs tree must remain empty.
    assert list(docs_dir.rglob(MIRROR_FILENAME)) == []


def test_mirror_writes_are_rate_limited(tmp_path, monkeypatch):
    """Rapid saves don't produce a mirror write per call."""
    clock = _fake_monotonic_factory(monkeypatch)
    vectorstore = tmp_path / "data"
    docs = tmp_path / "docs" / "demo"
    docs.mkdir(parents=True)
    mirror = docs / MIRROR_DIRNAME / MIRROR_FILENAME

    store = TelemetryStore(str(vectorstore))
    store.set_project_mirror("demo", docs)

    # First save establishes the mirror.
    store.save_summary({"demo": {"total_calls": 1}})
    first_mtime_ns = mirror.stat().st_mtime_ns

    # Second save within the rate-limit window is dropped (same mtime).
    clock["now"] += 1.0  # 1s later, well under MIRROR_MIN_INTERVAL_SECONDS.
    store.save_summary({"demo": {"total_calls": 2}})
    assert mirror.stat().st_mtime_ns == first_mtime_ns, (
        "Mirror file should NOT be rewritten inside the rate-limit window"
    )

    # Advance past the window; next save updates the mirror.
    clock["now"] += telemetry_module.MIRROR_MIN_INTERVAL_SECONDS + 1.0
    store.save_summary({"demo": {"total_calls": 3}})
    payload = json.loads(mirror.read_text())
    assert payload["total_calls"] == 3, "Mirror must reflect the latest data after the window"


def test_hydrate_from_mirrors_recovers_after_cold_start(tmp_path, monkeypatch):
    """When the hot tier is wiped, the mirror file rebuilds the summary."""
    _fake_monotonic_factory(monkeypatch)
    vectorstore = tmp_path / "data"
    docs = tmp_path / "docs" / "demo"
    docs.mkdir(parents=True)

    # Simulate a previous lifetime: write the mirror file directly.
    mirror_dir = docs / MIRROR_DIRNAME
    mirror_dir.mkdir()
    (mirror_dir / MIRROR_FILENAME).write_text(json.dumps({
        "project": "demo",
        "total_calls": 42,
        "searches": 30,
        "writes": 5,
        "last_tool": "search_docs",
    }))

    # Fresh store with empty hot tier (vectorstore_path doesn't pre-exist).
    store = TelemetryStore(str(vectorstore))
    store.set_project_mirror("demo", docs)
    hydrated = store.hydrate_from_mirrors()

    assert "demo" in hydrated
    assert hydrated["demo"]["total_calls"] == 42
    assert hydrated["demo"]["searches"] == 30
    assert hydrated["demo"]["writes"] == 5

    # Side effect: the hot tier is now populated too, so the *next*
    # restart doesn't need to read the mirror.
    reloaded = store.load_summary()
    assert reloaded["demo"]["total_calls"] == 42


def test_hot_tier_wins_over_mirror(tmp_path, monkeypatch):
    """A populated hot tier is authoritative; mirrors only fill gaps."""
    _fake_monotonic_factory(monkeypatch)
    vectorstore = tmp_path / "data"
    docs = tmp_path / "docs" / "demo"
    docs.mkdir(parents=True)

    # Pre-existing hot-tier data.
    store = TelemetryStore(str(vectorstore))
    store.set_project_mirror("demo", docs)
    store.save_summary({"demo": {"total_calls": 100}})

    # A stale mirror with a different value should NOT overwrite it.
    (docs / MIRROR_DIRNAME / MIRROR_FILENAME).write_text(json.dumps({
        "project": "demo",
        "total_calls": 999,
    }))

    hydrated = store.hydrate_from_mirrors()
    assert hydrated["demo"]["total_calls"] == 100


def test_reset_project_zeroes_counters_and_mirror(tmp_path, monkeypatch):
    """reset_project clears hot tier + mirror but preserves events."""
    _fake_monotonic_factory(monkeypatch)
    vectorstore = tmp_path / "data"
    docs = tmp_path / "docs" / "demo"
    docs.mkdir(parents=True)
    mirror = docs / MIRROR_DIRNAME / MIRROR_FILENAME

    store = TelemetryStore(str(vectorstore))
    store.set_project_mirror("demo", docs)
    store.save_summary({"demo": {"total_calls": 17, "searches": 9}})
    store.append_event("search_result", "demo", {"tool_name": "search_docs", "hit": True})

    fresh = store.reset_project("demo")
    assert fresh["total_calls"] == 0
    assert fresh["searches"] == 0

    # Hot tier reflects the reset.
    reloaded = store.load_summary()
    assert reloaded["demo"]["total_calls"] == 0

    # Mirror reflects the reset (force-write bypasses rate limit).
    payload = json.loads(mirror.read_text())
    assert payload["total_calls"] == 0
    assert payload["searches"] == 0

    # Events history is preserved so impact metrics stay reproducible.
    metrics = store.compute_impact_metrics(project="demo", days=30)
    assert metrics["search_hits"] == 1


def test_reset_project_with_unknown_project_is_safe(tmp_path):
    """Reset on a project we've never seen returns a zero slice."""
    store = TelemetryStore(str(tmp_path))
    result = store.reset_project("never-existed")
    assert result["total_calls"] == 0
    # Should not raise even though no mirror was registered.
    assert "searches" in result


def test_reset_project_with_empty_name_is_noop(tmp_path):
    """Empty project names are rejected silently with a default slice."""
    store = TelemetryStore(str(tmp_path))
    result = store.reset_project("")
    assert result["total_calls"] == 0
