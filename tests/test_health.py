"""Tests for the HealthTracker."""
import threading


class TestRecordSearch:
    def test_hit_increments(self, health):
        health.record_search("search_docs", True)
        s = health.status
        assert s["searches_total"] == 1
        assert s["searches_hits"] == 1
        assert s["searches_misses"] == 0
        assert s["searches_by_tool"]["search_docs"] == 1

    def test_miss_increments(self, health):
        health.record_search("search_docs", False)
        s = health.status
        assert s["searches_total"] == 1
        assert s["searches_hits"] == 0
        assert s["searches_misses"] == 1

    def test_multiple_tools(self, health):
        health.record_search("search_docs", True)
        health.record_search("search_bugfixes", False)
        health.record_search("search_by_type", True)
        s = health.status
        assert s["searches_total"] == 3
        assert s["searches_hits"] == 2
        assert s["searches_misses"] == 1
        assert s["searches_by_tool"]["search_docs"] == 1
        assert s["searches_by_tool"]["search_bugfixes"] == 1
        assert s["searches_by_tool"]["search_by_type"] == 1

    def test_unknown_tool_not_tracked_per_tool(self, health):
        health.record_search("search_tests", True)
        s = health.status
        assert s["searches_total"] == 1
        assert "search_tests" not in s["searches_by_tool"]

    def test_last_search_at_set(self, health):
        assert health.status["last_search_at"] is None
        health.record_search("search_docs", True)
        assert health.status["last_search_at"] is not None


class TestRecordQuality:
    def test_stores_values(self, health):
        health.record_quality(score=85, critical=1, warnings=2, info=3)
        s = health.status
        assert s["quality_score"] == 85
        assert s["quality_issues_critical"] == 1
        assert s["quality_issues_warnings"] == 2
        assert s["quality_issues_info"] == 3

    def test_defaults_to_zero(self, health):
        health.record_quality(score=100)
        s = health.status
        assert s["quality_issues_critical"] == 0
        assert s["quality_issues_warnings"] == 0
        assert s["quality_issues_info"] == 0


class TestRecordIndex:
    def test_success(self, health):
        health.record_index(ok=True, chunks=42, files=5)
        s = health.status
        assert s["last_index_ok"] is True
        assert s["last_index_chunks"] == 42
        assert s["last_index_files"] == 5
        assert s["last_index_at"] is not None

    def test_failure(self, health):
        health.record_index(ok=False, error="disk full")
        s = health.status
        assert s["last_index_ok"] is False
        assert s["last_index_error"] == "disk full"


class TestRecordSkippedFiles:
    def test_stores_list(self, health):
        skipped = [{"file": "bad.md", "reason": "critical issue"}]
        health.record_skipped_files(skipped)
        assert health.status["skipped_files"] == skipped

    def test_replaces_previous(self, health):
        health.record_skipped_files([{"file": "a.md", "reason": "x"}])
        health.record_skipped_files([{"file": "b.md", "reason": "y"}])
        assert len(health.status["skipped_files"]) == 1
        assert health.status["skipped_files"][0]["file"] == "b.md"


class TestIsHealthy:
    def test_initially_unhealthy(self, health):
        assert health.is_healthy is False

    def test_healthy_after_good_index(self, health):
        health.record_index(ok=True, chunks=10)
        assert health.is_healthy is True

    def test_unhealthy_after_bad_index(self, health):
        health.record_index(ok=True, chunks=10)
        health.record_index(ok=False, error="fail")
        assert health.is_healthy is False


class TestThreadSafety:
    def test_concurrent_search_recording(self, health):
        """Verify no data corruption under concurrent writes."""
        def record_many():
            for _ in range(100):
                health.record_search("search_docs", True)

        threads = [threading.Thread(target=record_many) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert health.status["searches_total"] == 1000
        assert health.status["searches_hits"] == 1000
