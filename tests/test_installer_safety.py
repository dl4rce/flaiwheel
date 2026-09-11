"""Regression tests for the installer's shared-deployment safety.

These assert on ``scripts/install.sh`` as text rather than executing it,
because every defect they guard against is STRUCTURAL — a check in the wrong
branch, a missing volume, an ungated destructive command — and each one caused
a real outage or a silent data-loss risk.

Background (2026-09-11, CT122):
  * The port-conflict precheck lived in the ``else`` arm of the exact-container
    -name test, so it never ran for the normal ``flaiwheel-<project>`` name.
    Even when it ran it grepped ``docker ps`` only, making it blind to host
    nginx holding the port. The container was destroyed and then failed to
    start — a full outage instead of a rollback.
  * ``/docs`` was never mounted although the image declares it, so a "successful"
    start ran against an empty knowledge directory with no error.
  * ``docker image prune -af`` / ``docker container prune -f`` / ``systemctl
    stop docker`` ran host-wide on a shared box.
"""

from __future__ import annotations

import pathlib
import subprocess

import pytest

INSTALLER = pathlib.Path(__file__).resolve().parents[1] / "scripts" / "install.sh"


@pytest.fixture(scope="module")
def src() -> str:
    return INSTALLER.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def build_image_body(src: str) -> str:
    body = src[src.index("build_image() {") :]
    body = body[: body.index("\n    }\n")]
    # Drop comment lines: the explanatory comments name the very commands under
    # test, and a naive substring search would match prose instead of code.
    return "\n".join(
        line for line in body.splitlines() if not line.strip().startswith("#")
    )


class TestInstallerParses:
    def test_bash_syntax_is_valid(self):
        result = subprocess.run(
            ["bash", "-n", str(INSTALLER)], capture_output=True, text=True
        )
        assert result.returncode == 0, result.stderr


class TestPortConflictDetection:
    def test_probes_real_socket_not_just_containers(self, src: str):
        """The old check grepped `docker ps` and could not see host processes."""
        assert "_port_in_use() {" in src
        assert "socket" in src and "SO_REUSEADDR" in src

    def test_reports_the_holder_of_a_foreign_port(self, src: str):
        assert "_port_owner() {" in src

    def test_check_runs_on_every_path_including_exact_name_match(self, src: str):
        """Regression: the check used to be skipped for the normal container name."""
        block = src.split('if [ "$FAST_PATH" = false ]; then', 1)[1]
        name_match = block.index('EXISTING_CONTAINER="$CONTAINER_NAME"')
        call = block.index('_check_ports_free "$EXISTING_CONTAINER"')
        assert call > name_match, "port check must run after name detection"

        call_line = next(
            line
            for line in block.splitlines()
            if '_check_ports_free "$EXISTING_CONTAINER"' in line
        )
        # Must sit at if-block level (4 spaces), NOT inside the `else` arm (8).
        assert not call_line.startswith("        "), (
            "port check must not be nested inside the else-branch; "
            "that is exactly the bug that took CT122 down"
        )

    def test_refuses_to_continue_on_conflict(self, src: str):
        body = src[src.index("_check_ports_free() {") :]
        body = body[: body.index("\n}\n")]
        assert "fail " in body
        assert "FLAIWHEEL_WEB_PORT" in body and "FLAIWHEEL_SSE_PORT" in body


class TestConfigurablePorts:
    def test_ports_and_binds_are_overridable(self, src: str):
        assert 'WEB_PORT="${FLAIWHEEL_WEB_PORT:-8080}"' in src
        assert 'SSE_PORT="${FLAIWHEEL_SSE_PORT:-8081}"' in src
        assert 'WEB_BIND="${FLAIWHEEL_WEB_BIND:-0.0.0.0}"' in src
        assert 'SSE_BIND="${FLAIWHEEL_SSE_BIND:-0.0.0.0}"' in src

    def test_no_hardcoded_port_publish_remains(self, src: str):
        assert "-p 8080:8080" not in src
        assert "-p 8081:8081" not in src
        assert '-p "${WEB_BIND}:${WEB_PORT}:8080"' in src
        assert '-p "${SSE_BIND}:${SSE_PORT}:8081"' in src

    def test_update_mode_inherits_existing_binding(self, src: str):
        assert "_old_binding() {" in src
        assert '"8080/tcp"' in src and '"8081/tcp"' in src


class TestVolumeMounts:
    def test_docs_volume_is_declared_and_mounted(self, src: str):
        assert 'DOCS_VOLUME_NAME="flaiwheel-${PROJECT}-docs"' in src
        assert '-v "${VOLUME_NAME}:/data"' in src
        assert '-v "${DOCS_VOLUME_NAME}:/docs"' in src

    def test_update_mode_preserves_the_docs_volume_name(self, src: str):
        assert 'OLD_DOCS_VOLUME=' in src
        assert 'if [ -n "$OLD_DOCS_VOLUME" ]; then' in src

    def test_post_start_verifies_both_mounts(self, src: str):
        assert "_MOUNTS=" in src
        assert "for _dest in /data /docs" in src
        # a missing mount must be fatal, not a warning
        block = src[src.index("for _dest in /data /docs") :]
        block = block[: block.index("done") + 4]
        assert "fail " in block


class TestDestructiveCleanupGating:
    def test_prunes_live_only_inside_the_aggressive_block(
        self, build_image_body: str
    ):
        body = build_image_body
        start = body.index('if [ "${AGGRESSIVE_CLEANUP}" = "1" ]; then')
        end = body.index("elif", start)
        guarded = body[start:end]
        for cmd in (
            "docker builder prune -af",
            "docker image prune -af",
            "docker container prune -f",
        ):
            assert cmd in guarded, f"{cmd} should be inside the aggressive-cleanup block"
            assert body.count(cmd) == 1, f"{cmd} is also executed outside the guard"

    def test_non_aggressive_path_does_not_delete_images(self, build_image_body: str):
        # The safe path may free build cache, but must never delete images.
        start = build_image_body.index('if [ "${AGGRESSIVE_CLEANUP}" = "1" ]; then')
        end = build_image_body.index("elif", start)
        outside = build_image_body[:start] + build_image_body[end:]
        assert "docker image prune" not in outside
        assert "docker builder prune -f" in outside

    def test_systemctl_stop_docker_is_gated(self, build_image_body: str):
        idx = build_image_body.index("systemctl stop docker")
        preceding = build_image_body[max(0, idx - 400) : idx]
        assert "AGGRESSIVE_CLEANUP" in preceding, (
            "`systemctl stop docker` stops every container on the host and must "
            "never run unconditionally"
        )

    def test_aggressive_cleanup_defaults_to_off(self, src: str):
        assert 'AGGRESSIVE_CLEANUP="${FLAIWHEEL_AGGRESSIVE_CLEANUP:-0}"' in src


class TestUpgradeIsNotAnOutage:
    def test_image_is_built_before_the_old_container_is_removed(self, src: str):
        """If the build happens after `docker rm`, a build failure = outage."""
        build = src.index('if [ "$_SKIP_BUILD" = false ]; then\n            build_image')
        remove = src.index('docker rm "$OLD_CONTAINER_NAME"')
        assert build < remove

    def test_all_mcp_env_is_carried_over_on_update(self, src: str):
        # Dropping all but three variables silently changes behaviour.
        assert "OLD_MCP_ENV=" in src
        assert "carried_env" in src
        assert "^MCP_(GIT_REPO_URL|GIT_AUTO_PUSH|WEBHOOK_SECRET|GIT_TOKEN)=" in src
