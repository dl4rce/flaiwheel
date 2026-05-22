# Flaiwheel – Self-improving knowledge base for AI coding agents
# Copyright (c) 2026 4rce.com Digital Technologies GmbH.
# Use of this software is governed by the Business Source License 1.1. See LICENSE.

"""
Persistent telemetry storage and impact metrics.

Telemetry has two storage tiers:

1. **Hot tier (Docker volume)** — written on every tool call:
     <vectorstore_path>/telemetry/summary.json
     <vectorstore_path>/telemetry/events.jsonl
   Survives container restarts and image updates, but is lost when the
   ``flaiwheel-data`` volume is removed.

2. **Cold-start tier (knowledge repo)** — a *summary* slice is mirrored
   periodically into each project's knowledge repo at
     <project_docs_path>/.flaiwheel/telemetry.json
   This file lives next to the docs and is excluded from indexing
   (see ``indexer._iter_docs`` and ``quality._check_*``).  When the
   Docker volume is wiped, ``hydrate_from_mirrors()`` reconstructs the
   in-memory summary from the per-project mirror files on the next
   start so dashboards do not reset to zero.

Events (``events.jsonl``) are intentionally *not* mirrored — they would
make commit history noisy and they are only used for the rolling
``impact-metrics`` window, which gracefully degrades to zero when missing.
"""

import json
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


def _monotonic() -> float:
    """Wrap ``time.monotonic`` so tests can patch it deterministically."""
    return time.monotonic()

# Per-project summary mirror file (relative to each project's docs_path).
# Kept under ``.flaiwheel/`` so the indexer / quality checker skip it.
MIRROR_DIRNAME = ".flaiwheel"
MIRROR_FILENAME = "telemetry.json"

# Minimum interval between two mirror writes for the *same* project.
# Hot-tier writes still happen on every call; only the knowledge-repo
# mirror is rate-limited so we don't generate one Git commit per tool call.
MIRROR_MIN_INTERVAL_SECONDS = 60.0


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

        # Per-project mirror configuration: name -> docs_path
        # Populated by ``set_project_mirror`` once projects are loaded.
        self._mirror_roots: dict[str, Path] = {}
        # Last successful mirror write per project (monotonic seconds).
        self._mirror_last_write: dict[str, float] = {}

    # ── Cold-start mirror configuration ──────────────

    def set_project_mirror(self, project: str, docs_path: Path | str) -> None:
        """Register the knowledge-repo docs path for a project.

        After this call, ``save_summary`` will (rate-limited) mirror the
        project's slice into ``<docs_path>/.flaiwheel/telemetry.json`` so
        the data survives ``docker volume rm`` of ``flaiwheel-data``.
        """
        if not project:
            return
        with self._lock:
            self._mirror_roots[project] = Path(docs_path)

    def hydrate_from_mirrors(self) -> dict[str, dict]:
        """Reconstruct the in-memory summary from per-project mirror files.

        Called once on startup *after* ``set_project_mirror`` has been
        invoked for every known project. Only fills slices that are
        missing from ``summary.json`` (the Docker-volume file wins when
        both exist) so a corrupted mirror cannot overwrite live data.

        Returns the merged summary so the caller can rebind its
        in-memory cache atomically.
        """
        with self._lock:
            current = self._load_summary_locked()
            mirror_roots = dict(self._mirror_roots)

        recovered = 0
        for project, docs_path in mirror_roots.items():
            if project in current:
                continue
            mirror_path = Path(docs_path) / MIRROR_DIRNAME / MIRROR_FILENAME
            if not mirror_path.exists():
                continue
            try:
                raw = json.loads(mirror_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
            if not isinstance(raw, dict):
                continue
            # Mirror files store the project's *slice* directly.
            current[project] = self._normalize_project(raw)
            recovered += 1

        if recovered > 0:
            # Persist the hydrated state to the hot tier so subsequent
            # restarts (with the volume intact) don't re-read mirrors.
            self.save_summary(current)
        return current

    def load_summary(self) -> dict[str, dict]:
        with self._lock:
            return self._load_summary_locked()

    def _load_summary_locked(self) -> dict[str, dict]:
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

            # Mirror each project's slice into its knowledge repo
            # (rate-limited; ignores projects without a registered mirror).
            now = _monotonic()
            for project, slice_data in normalized.items():
                root = self._mirror_roots.get(project)
                if root is None:
                    continue
                last = self._mirror_last_write.get(project, 0.0)
                if (now - last) < MIRROR_MIN_INTERVAL_SECONDS:
                    continue
                if self._write_mirror_locked(project, root, slice_data):
                    self._mirror_last_write[project] = now

    def reset_project(self, project: str) -> dict:
        """Zero a single project's summary counters.

        Clears the in-memory slice (via the next ``save_summary`` call),
        the Docker-volume copy, and the knowledge-repo mirror. Returns
        the freshly zeroed slice. Events (``events.jsonl``) are kept
        intact so historical impact metrics remain reproducible.
        """
        if not project:
            return _project_defaults()

        fresh = _project_defaults()
        with self._lock:
            summary = self._load_summary_locked()
            summary[project] = dict(fresh)
            tmp = self._summary_path.with_suffix(".tmp")
            tmp.write_text(
                json.dumps(summary, indent=2, sort_keys=True),
                encoding="utf-8",
            )
            tmp.replace(self._summary_path)

            root = self._mirror_roots.get(project)
            if root is not None:
                # Force-write (bypass rate limit) so a remote viewer sees
                # the reset immediately.
                self._write_mirror_locked(project, root, fresh)
                self._mirror_last_write[project] = _monotonic()
        return dict(fresh)

    def _write_mirror_locked(
        self, project: str, root: Path, slice_data: dict
    ) -> bool:
        """Write a single project's mirror file. Lock must be held."""
        try:
            target_dir = root / MIRROR_DIRNAME
            target_dir.mkdir(parents=True, exist_ok=True)
            target = target_dir / MIRROR_FILENAME
            tmp = target.with_suffix(".tmp")
            payload = {
                "project": project,
                "updated_at": datetime.now(timezone.utc).isoformat(),
                **slice_data,
            }
            tmp.write_text(
                json.dumps(payload, indent=2, sort_keys=True),
                encoding="utf-8",
            )
            tmp.replace(target)
            return True
        except OSError:
            # Mirror write failures are non-fatal — hot tier already has
            # the data. Try again on the next save.
            return False

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
