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

    def test_bindings_are_learned_BEFORE_the_port_check(self, src: str):
        """v3.14.1 shipped the inheritance AFTER the check.

        On a proxy-fronted host (MCP on 127.0.0.1:18081, nginx on :8081) the
        check therefore validated the DEFAULTS, saw nginx on 8081 and refused to
        upgrade a perfectly healthy deployment. Preserving the shape must happen
        first, or the "safe" check becomes a stuck installer.
        """
        block = src.split('if [ "$FAST_PATH" = false ]; then', 1)[1]
        inherit = block.index('_old_binding "$EXISTING_CONTAINER" "8081/tcp"')
        check = block.index('_check_ports_free "$EXISTING_CONTAINER"')
        assert inherit < check, (
            "existing host bindings must be inherited before the port check, "
            "otherwise the check judges the defaults instead of the real shape"
        )

    def test_empty_host_ip_is_normalized(self, src: str):
        """Docker reports an unpinned bind as HostIp "", which would produce an
        invalid `-p :8080:8080`."""
        assert 'or "0.0.0.0"' in src
        assert 'get("HostIp") or "0.0.0.0"' in src


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


class TestSummaryBoxAlignment:
    """The closing login box must line up for ANY address or password.

    It previously used hardcoded padding, which was 2 characters short of its
    own border and only looked correct for a 127.0.0.1:8080 URL. The warning
    line was also written separately, so it missed the dynamic padding entirely
    and overflowed by one character.
    """

    @staticmethod
    def _run_box(src: str, web_url: str, password: str) -> list[str]:
        fn_start = src.index("    _box_line() {")
        fn_end = src.index("\n    }\n", fn_start) + len("\n    }\n")
        fn = src[fn_start:fn_end]

        box_start = src.index('echo -e "  ${BOLD}╔')
        tail = src[box_start:]
        box_end = tail.index("\n", tail.index("╚")) + 1
        box = tail[:box_end]

        script = (
            "BOLD=''; GREEN=''; NC=''; YELLOW=''\n"
            f"WEB_URL={web_url!r}\n"
            f"_DISPLAY_PASS={password!r}\n"
            f"{fn}\n{box}"
        )
        out = subprocess.run(
            ["bash", "-c", script], capture_output=True, text=True, check=True
        ).stdout
        ansi = __import__("re").compile(r"\x1b\[[0-9;]*m")
        return [ansi.sub("", ln) for ln in out.splitlines() if ln.strip()]

    def test_all_lines_have_equal_width(self, src: str):
        lines = self._run_box(src, "http://192.168.178.230:8080", "s3cr3t-p@ss-w0rd")
        assert len(lines) >= 8
        widths = {len(ln) for ln in lines}
        assert len(widths) == 1, f"ragged box, widths={sorted(widths)}\n" + "\n".join(
            f"{len(ln):>3} {ln}" for ln in lines
        )

    @pytest.mark.parametrize(
        "url",
        [
            "http://127.0.0.1:8080",
            "http://192.168.178.230:8080",
            "http://10.0.0.9:18080",
        ],
    )
    def test_stays_aligned_for_varying_url_lengths(self, src: str, url: str):
        lines = self._run_box(src, url, "pw")
        assert len({len(ln) for ln in lines}) == 1, f"ragged for {url}"

    def test_warning_line_uses_the_padding_helper(self, src: str):
        """Regression: the 'Save this' line was hardcoded and overflowed."""
        assert '_box_line "Save this' in src
        assert "it won't be shown again!${NC}${BOLD}" not in src


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
