# Flaiwheel – Self-improving knowledge base for AI coding agents
# Copyright (c) 2026 4rce.com Digital Technologies GmbH.
# Use of this software is governed by the Business Source License 1.1. See LICENSE.

"""
Persistent telemetry storage and impact metrics.

Telemetry is written to the vectorstore volume so it survives restarts and updates:
  <vectorstore_path>/telemetry/summary.json
  <vectorstore_path>/telemetry/events.jsonl
"""

import json
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


def _project_defaults() -> dict[str, int | str]:
    return {
        "searches": 0,
        "search_misses": 0,
        "bugfix_searches": 0,
        "writes": 0,
        "bugfix_writes": 0,
        "session_saves": 0,
        "total_calls": 0,
        "last_tool": "",
        "nudges_sent": 0,
        "ci_reports": 0,
        "guardrail_violations_found": 0,
        "guardrail_violations_blocking": 0,
        "guardrail_violations_fixed": 0,
    }


class TelemetryStore:
    LOOKUP_MINUTES_PER_HIT = 2.5
    PREMERGE_FIX_MINUTES = 15.0

    def __init__(self, vectorstore_path: str):
        root = Path(vectorstore_path) / "telemetry"
        root.mkdir(parents=True, exist_ok=True)
        self._summary_path = root / "summary.json"
        self._events_path = root / "events.jsonl"
        self._lock = threading.Lock()

    def load_summary(self) -> dict[str, dict]:
        with self._lock:
            if not self._summary_path.exists():
                return {}
            try:
                raw = json.loads(self._summary_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                return {}
            if not isinstance(raw, dict):
                return {}
            normalized: dict[str, dict] = {}
            for project, values in raw.items():
                normalized[project] = self._normalize_project(values)
            return normalized

    def save_summary(self, summary: dict[str, dict]) -> None:
        with self._lock:
            normalized = {
                project: self._normalize_project(values)
                for project, values in summary.items()
            }
            tmp = self._summary_path.with_suffix(".tmp")
            tmp.write_text(
                json.dumps(normalized, indent=2, sort_keys=True),
                encoding="utf-8",
            )
            tmp.replace(self._summary_path)

    def append_event(self, event_type: str, project: str, payload: dict[str, Any]) -> None:
        event = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event_type": event_type,
            "project": project or "_default",
            **payload,
        }
        with self._lock:
            with self._events_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(event, sort_keys=True) + "\n")

    def compute_impact_metrics(self, project: str | None, days: int = 30) -> dict[str, Any]:
        window_days = max(1, min(int(days), 365))
        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(days=window_days)

        search_events = 0
        search_hits = 0

        ci_reports = 0
        violations_found = 0
        violations_blocking = 0
        violations_fixed = 0
        observed_cycle_saved_minutes = 0.0

        for event in self._iter_events(project):
            ts = self._parse_ts(event.get("timestamp"))
            if ts is None or ts < cutoff:
                continue

            event_type = event.get("event_type", "")
            if event_type == "search_result":
                search_events += 1
                if bool(event.get("hit")):
                    search_hits += 1
            elif event_type == "ci_guardrail_report":
                ci_reports += 1
                found = self._int(event.get("violations_found", 0))
                blocking = self._int(event.get("violations_blocking", 0))
                fixed = self._int(event.get("violations_fixed_before_merge", 0))
                violations_found += found
                violations_blocking += blocking
                violations_fixed += fixed

                baseline = self._float_or_none(event.get("cycle_time_baseline_minutes"))
                actual = self._float_or_none(event.get("cycle_time_actual_minutes"))
                if baseline is not None and actual is not None and baseline > actual:
                    observed_cycle_saved_minutes += (baseline - actual)

        lookup_saved = search_hits * self.LOOKUP_MINUTES_PER_HIT
        premerge_saved = violations_fixed * self.PREMERGE_FIX_MINUTES
        estimated_total = observed_cycle_saved_minutes + lookup_saved + premerge_saved

        return {
            "project": project or "all",
            "window_days": window_days,
            "search_events": search_events,
            "search_hits": search_hits,
            "ci_reports": ci_reports,
            "guardrail_violations_found": violations_found,
            "guardrail_violations_blocking": violations_blocking,
            "regressions_avoided": violations_fixed,
            "cycle_time_minutes_saved_observed": round(observed_cycle_saved_minutes, 2),
            "estimated_time_saved_minutes": round(estimated_total, 2),
            "estimated_time_saved_hours": round(estimated_total / 60.0, 2),
            "assumptions": {
                "lookup_minutes_per_search_hit": self.LOOKUP_MINUTES_PER_HIT,
                "minutes_saved_per_premerge_guardrail_fix": self.PREMERGE_FIX_MINUTES,
            },
        }

    def _iter_events(self, project: str | None):
        with self._lock:
            if not self._events_path.exists():
                return []
            lines = self._events_path.read_text(encoding="utf-8").splitlines()

        parsed: list[dict[str, Any]] = []
        for line in lines:
            if not line.strip():
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(event, dict):
                continue
            if project and event.get("project") != project:
                continue
            parsed.append(event)
        return parsed

    @staticmethod
    def _parse_ts(value: Any) -> datetime | None:
        if not isinstance(value, str) or not value:
            return None
        text = value.strip()
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(text)
        except ValueError:
            return None
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt

    @staticmethod
    def _int(value: Any) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def _float_or_none(value: Any) -> float | None:
        try:
            if value is None:
                return None
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _normalize_project(values: Any) -> dict:
        normalized = _project_defaults()
        if not isinstance(values, dict):
            return normalized

        for key, default in normalized.items():
            if key not in values:
                continue
            if isinstance(default, int):
                try:
                    normalized[key] = int(values[key])
                except (TypeError, ValueError):
                    normalized[key] = default
            else:
                normalized[key] = str(values[key] or "")
        return normalized
