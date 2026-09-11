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

import json
import os
import pathlib
import re
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

    def test_owner_detection_reads_port_bindings_not_docker_ps_text(self, src: str):
        """Regression: parsing `docker ps` text missed coalesced port ranges.

        Docker renders two adjacent published ports as ONE token:
            0.0.0.0:8080-8081->8080-8081/tcp
        so grepping for ":8081->" finds nothing and the checker fails to
        recognise its own container, refusing to upgrade a healthy deployment.
        """
        body = src[src.index("_port_container() {") :]
        body = body[: body.index("\n}\n")]
        assert "PortBindings" in body
        assert 'grep -E ":${port}->"' not in body


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
    def _run_box(src: str, web_url: str, password: str, locale: str = "") -> list[str]:
        fn_start = src.index("    _box_line() {")
        fn_end = src.index("\n    }\n", fn_start) + len("\n    }\n")
        fn = src[fn_start:fn_end]

        box_start = src.index('echo -e "  ${BOLD}╔')
        tail = src[box_start:]
        box_end = tail.index("\n", tail.index("╚")) + 1
        box = tail[:box_end]

        # Real escape sequences, not empty strings. Blanking the colours makes
        # the padding maths identical while hiding the case that matters: the
        # helper once used printf, whose %s arguments do NOT interpret \033, so
        # the box printed "\033[1m║  Web UI Login" to the terminal.
        script = (
            "BOLD='\\033[1m'; GREEN='\\033[0;32m'; NC='\\033[0m'; YELLOW='\\033[1;33m'\n"
            f"WEB_URL={web_url!r}\n"
            f"_DISPLAY_PASS={password!r}\n"
            f"{fn}\n{box}"
        )
        env = dict(os.environ)
        if locale:
            env["LC_ALL"] = locale
        out = subprocess.run(
            ["bash", "-c", script], capture_output=True, text=True, check=True, env=env
        )
        ansi = re.compile(r"\x1b\[[0-9;]*m")
        return [ansi.sub("", ln) for ln in out.stdout.splitlines() if ln.strip()]

    @staticmethod
    def _run_box_raw(src: str, web_url: str, password: str) -> list[str]:
        """Like _run_box but keeps the escape sequences, for literal-escape checks."""
        fn_start = src.index("    _box_line() {")
        fn_end = src.index("\n    }\n", fn_start) + len("\n    }\n")
        fn = src[fn_start:fn_end]
        box_start = src.index('echo -e "  ${BOLD}╔')
        tail = src[box_start:]
        box = tail[: tail.index("\n", tail.index("╚")) + 1]
        script = (
            "BOLD='\\033[1m'; GREEN='\\033[0;32m'; NC='\\033[0m'; YELLOW='\\033[1;33m'\n"
            f"WEB_URL={web_url!r}\n"
            f"_DISPLAY_PASS={password!r}\n"
            f"{fn}\n{box}"
        )
        return [
            ln
            for ln in subprocess.run(
                ["bash", "-c", script], capture_output=True, text=True, check=True
            ).stdout.splitlines()
            if ln.strip()
        ]

    def test_no_literal_escape_sequences_in_output(self, src: str):
        """Regression: printf printed the colour codes verbatim.

        The previous assertions all passed with BOLD='' and GREEN='', which made
        the emitted padding identical while hiding that the box rendered as
        "\\033[1m║  Web UI Login" instead of a coloured box.
        """
        for line in self._run_box_raw(src, "http://192.168.178.230:8080", "pw"):
            assert "\\033" not in line, f"literal escape sequence in output: {line!r}"

    def test_uses_echo_not_printf_for_coloured_lines(self, src: str):
        helper = src[src.index("    _box_line() {") :]
        helper = helper[: helper.index("\n    }\n")]
        # printf is still fine for padding; what must not happen is passing the
        # colour variables to it, since %s does not expand \033.
        assert 'printf \'  %s║' not in helper
        assert 'echo -e "  ${BOLD}║' in helper

    def test_all_lines_have_equal_width(self, src: str):
        lines = self._run_box(src, "http://192.168.178.230:8080", "s3cr3t-p@ss-w0rd")
        assert len(lines) >= 8
        widths = {len(ln) for ln in lines}
        assert len(widths) == 1, f"ragged box, widths={sorted(widths)}\n" + "\n".join(
            f"{len(ln):>3} {ln}" for ln in lines
        )

    @pytest.mark.parametrize("locale", ["C", "en_US.UTF-8", "C.UTF-8"])
    def test_alignment_holds_in_any_locale(self, src: str, locale: str):
        """Regression: under LC_ALL=C the em-dash line was two columns short.

        ``${#plain}`` counts BYTES when the locale is not UTF-8, so
        "Save this — it won't be shown again!" measured 38 instead of 36 and the
        padding came out wrong. Alignment must not depend on the caller's locale.
        """
        lines = self._run_box(
            src, "http://192.168.178.230:8080", "2MElHssYTlvnJAE1", locale=locale
        )
        widths = {len(ln) for ln in lines}
        assert len(widths) == 1, (
            f"ragged box under LC_ALL={locale}, widths={sorted(widths)}\n"
            + "\n".join(f"{len(ln):>3} {ln}" for ln in lines)
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


class TestSequentialStepNumbering:
    """Conditional items are omitted, so hardcoded numbers skipped values.

    A run without Claude Desktop and without VS Code printed "1. ... 3. ... 5."
    because the numbers were literals in the script rather than a counter.
    """

    def test_no_hardcoded_step_numbers_in_summaries(self, src: str):
        hard = re.findall(r'echo -e "    [0-9]+\.', src)
        assert not hard, f"hardcoded step numbers remain: {hard}"

    def test_counter_helper_exists(self, src: str):
        assert re.search(r"^_STEP=0$", src, re.M)
        assert re.search(r"^_step\(\) \{ _STEP=\$\(\(_STEP \+ 1\)\); \}$", src, re.M)

    def test_counter_is_reset_at_each_summary_block(self, src: str):
        blocks = src.count("What to do next:")
        resets = src.count("_STEP=0")
        # One declaration plus one reset per block.
        assert resets >= blocks, f"{blocks} blocks but only {resets} resets"

    def test_helper_is_not_called_in_a_subshell(self, src: str):
        """$( _step ) increments in a subshell and the new value is lost."""
        code = "\n".join(
            ln for ln in src.splitlines() if not ln.strip().startswith("#")
        )
        assert "$(_step)" not in code
        assert "$( _step" not in code

    @staticmethod
    def _render(src: str, **flags: bool) -> list[str]:
        """Render one 'What to do next' list with the given client flags."""
        block = src[src.index('    _STEP=0\n    echo -e "  ${BOLD}What to do next:') :]
        block = block[: block.index("\n    echo \"\"")]
        setup = "\n".join(
            f"{name}={'true' if value else 'false'}"
            for name, value in flags.items()
        )
        # The counter helper is declared near the colour variables, far from the
        # summary blocks, so the harness has to supply it. Without it every
        # ${_STEP} expands to 0 and the numbering assertions are vacuous.
        harness = (
            "BOLD=''; GREEN=''; NC=''; YELLOW=''\n"
            "_STEP=0\n"
            "_step() { _STEP=$((_STEP + 1)); }\n"
            "PROJECT='demo'\n"
            "HOST_WEB_URL='http://127.0.0.1:8080'\n"
            f"{setup}\n"
            f"{block}\n"
        )
        out = subprocess.run(
            ["bash", "-c", harness], capture_output=True, text=True, check=True
        ).stdout
        return [ln.strip() for ln in out.splitlines() if ln.strip() and "next:" not in ln]

    def test_numbers_are_contiguous_with_no_gaps(self, src: str):
        lines = self._render(src, CLAUDE_DESKTOP_REGISTERED=False,
                             CLAUDE_MCP_REGISTERED=True, VSCODE_REGISTERED=False)
        numbers = [
            int(m.group(1))
            for ln in lines
            if (m := re.match(r"^(\d+)\.", ln))
        ]
        assert numbers == list(range(1, len(numbers) + 1)), (
            f"step numbers are not contiguous: {numbers}"
        )

    def test_no_duplicate_numbers(self, src: str):
        lines = self._render(src, CLAUDE_DESKTOP_REGISTERED=True,
                             CLAUDE_MCP_REGISTERED=False, VSCODE_REGISTERED=True)
        numbers = [
            int(m.group(1)) for ln in lines if (m := re.match(r"^(\d+)\.", ln))
        ]
        assert len(numbers) == len(set(numbers)), f"duplicate numbers: {numbers}"


class TestTlsStatusIsReported:
    """Auto-TLS is opt-in, so the summary must state the status either way.

    Silence about TLS is what makes an operator wonder whether it was enabled,
    which is exactly what prompted this.
    """

    def test_status_line_always_printed(self, src: str):
        idx = src.index('echo -e "    MCP (SSE):')
        tail = src[idx : idx + 1800]
        assert 'echo -e "    TLS:' in tail
        # The three branches plus the else default.
        assert tail.count('echo -e "    TLS:') >= 3

    def test_states_that_tls_is_off_rather_than_saying_nothing(self, src: str):
        idx = src.index("elif [ -n \"${MCP_SSE_TLS_CERTFILE:-}\" ]")
        tail = src[idx : idx + 900]
        assert "off" in tail
        assert "not encrypted" in tail or "unencrypted" in tail

    def test_off_state_names_the_opt_in_flag(self, src: str):
        idx = src.index("elif [ -n \"${MCP_SSE_TLS_CERTFILE:-}\" ]")
        tail = src[idx : idx + 900]
        assert "FLAIWHEEL_TLS_AUTO=1" in tail

    def test_spacing_matches_python_len_for_multibyte(self, src: str):
        """The pad must be computed in characters, not bytes."""
        helper = src[src.index("    _box_line() {") :]
        helper = helper[: helper.index("\n    }\n")]
        assert "python3" in helper, (
            "${#plain} counts bytes outside a UTF-8 locale, so the em-dash line "
            "came out short under LC_ALL=C"
        )

    def test_auto_state_reports_a_host_readable_ca_and_the_anchor(self, src: str):
        # Anchor on the summary's own branch, not the container-setup one.
        idx = src.index('echo -e "    TLS:')
        tail = src[idx : idx + 1800]
        # The in-volume path (/data/tls/ca.pem) is not readable by a client
        # process, so the summary must quote the exported host path instead.
        assert "CLIENT_CA_PATH" in tail
        assert "SSE_CA_PATH" not in tail
        assert "NODE_EXTRA_CA_CERTS" in tail
        # And it must distinguish this host from other machines.
        assert "another machine" in tail.lower() or "other machine" in tail.lower()


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


class TestGeneratedClientConfigsMatchTls:
    """Client configs must describe the endpoint that is actually served.

    Every generated config previously hardcoded ``http://localhost:8081/sse``
    with no trust anchor. Enabling TLS therefore produced configs that could not
    connect — an http:// URL against an https listener, and an untrusted
    self-signed certificate — while the installer still reported success. The
    summary advertised ``https://`` and the clients were told ``http://``.
    """

    @staticmethod
    def _entry(src: str, scheme: str, tls_auto: str) -> dict:
        """Build the client entry the way the installer does, and parse it."""
        def fn(name: str) -> str:
            start = src.index(f"{name}() {{")
            end = src.index("\n}\n", start) + len("\n}\n")
            return src[start:end]

        script = (
            "GREEN=''; NC=''\n"
            f"_SSE_SCHEME={scheme!r}\n"
            f"TLS_AUTO={tls_auto!r}\n"
            "CLIENT_CA_PATH='/home/u/.flaiwheel/ca.pem'\n"
            'CLIENT_SSE_URL="${_SSE_SCHEME}://localhost:8081/sse"\n'
            f"{fn('_client_entry_json')}\n"
            "_client_entry_json\n"
        )
        out = subprocess.run(
            ["bash", "-c", script], capture_output=True, text=True, check=True
        ).stdout.strip()
        return json.loads(out)

    @staticmethod
    def _entry_file(src: str, scheme: str, tls_auto: str) -> dict:
        """Assemble a full config file via the heredoc path, then parse it."""
        start = src.index("_client_entry_body() {")
        end = src.index("\n}\n", start) + len("\n}\n")
        body = src[start:end]
        script = (
            "GREEN=''; NC=''\n"
            f"_SSE_SCHEME={scheme!r}\n"
            f"TLS_AUTO={tls_auto!r}\n"
            "CLIENT_CA_PATH='/home/u/.flaiwheel/ca.pem'\n"
            'CLIENT_SSE_URL="${_SSE_SCHEME}://localhost:8081/sse"\n'
            f"{body}\n"
            'cat << EOF\n'
            '{\n  "mcpServers": {\n    "flaiwheel": {\n'
            '$(_client_entry_body "      ")\n'
            '    }\n  }\n}\nEOF\n'
        )
        out = subprocess.run(
            ["bash", "-c", script], capture_output=True, text=True, check=True
        ).stdout
        return json.loads(out)

    @pytest.mark.parametrize("tls_auto", ["0", "1"])
    def test_single_line_entry_is_valid_json(self, src: str, tls_auto: str):
        entry = self._entry(src, "https", tls_auto)
        assert entry["type"] == "sse"

    @pytest.mark.parametrize("tls_auto", ["0", "1"])
    def test_heredoc_entry_is_valid_json(self, src: str, tls_auto: str):
        cfg = self._entry_file(src, "https", tls_auto)
        assert cfg["mcpServers"]["flaiwheel"]["type"] == "sse"

    def test_tls_on_uses_https_and_sets_the_trust_anchor(self, src: str):
        entry = self._entry(src, "https", "1")
        assert entry["url"].startswith("https://")
        assert entry["env"]["NODE_EXTRA_CA_CERTS"].endswith("ca.pem")

    def test_heredoc_entry_also_carries_the_anchor_when_tls_on(self, src: str):
        cfg = self._entry_file(src, "https", "1")
        entry = cfg["mcpServers"]["flaiwheel"]
        assert entry["url"].startswith("https://")
        assert "NODE_EXTRA_CA_CERTS" in entry["env"]

    def test_tls_off_is_unchanged_and_needs_no_anchor(self, src: str):
        entry = self._entry(src, "http", "0")
        assert entry["url"] == "http://localhost:8081/sse"
        assert "env" not in entry

    def test_no_config_writer_hardcodes_the_url(self, src: str):
        """Only the CLIENT_SSE_URL definition (and its comment) may contain it."""
        offenders = [
            (i + 1, ln.strip())
            for i, ln in enumerate(src.splitlines())
            if "http://localhost:8081/sse" in ln
            and not ln.strip().startswith("#")
            and "CLIENT_SSE_URL=" not in ln
        ]
        assert not offenders, f"hardcoded endpoint remains: {offenders}"

    def test_ca_is_exported_before_client_configs_are_written(self, src: str):
        export = src.index("_export_client_ca\n")
        first_writer = src.index("_phase6_cursor_mcp  &")
        assert export < first_writer, (
            "a config pointing at a CA file that does not exist yet is worse "
            "than no config"
        )

    def test_ca_export_is_gated_on_tls(self, src: str):
        body = src[src.index("_export_client_ca() {") :]
        body = body[: body.index("\n}\n")]
        assert '[ "$TLS_AUTO" = "1" ] || return 0' in body
        # Copying from a container that was never created must not abort the run.
        assert "|| true" in body or "|| return" in body
