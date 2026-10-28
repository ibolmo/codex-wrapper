import json
import os
import shutil
import subprocess
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path


WRAPPER = Path(
    os.environ.get(
        "CODEX_WRAPPER_EXECUTABLE", Path(sys.executable).parent / "codex-wrapper"
    )
)


DEFAULT_CONFIG = '''\
model = "default-model"

[agents.coder]
description = "default coder"

[agents.coder.sandbox]
mode = "workspace"

[agents.default_sibling]
description = "from default config"

[mcp_servers.default_server]
command = "default-mcp"
args = ["--default"]

[[hooks.SessionStart]]
matcher = "startup"

[[hooks.SessionStart.hooks]]
type = "command"
command = "default-start"

[hooks.state."/tmp/default-hook-state"]
installed = true
'''

MANAGER_CONFIG = '''\
[agents]
max_threads = 4

[agents.coder]
model = "manager-model"

[agents.manager_reviewer]
description = "from manager config"

[mcp_servers.manager_server]
command = "manager-mcp"
args = ["--manager"]

[[hooks.PreToolUse]]
matcher = "Bash"

[[hooks.PreToolUse.hooks]]
type = "command"
command = "manager-pre-tool"

[hooks.state."/tmp/manager-hook-state"]
last_applied = "manager"
'''


class CodexWrapperAcceptanceTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.root = Path(self.temp_dir.name)
        self.codex_home = self.root / "codex-home"
        self.codex_home.mkdir()
        self.fake_bin = self.root / "fake-bin"
        self.fake_bin.mkdir()
        self.record_path = self.root / "codex-record.json"

        (self.codex_home / "config.toml").write_text(DEFAULT_CONFIG, encoding="utf-8")
        (self.codex_home / "manager.config.toml").write_text(MANAGER_CONFIG, encoding="utf-8")
        self.config_snapshots = {
            self.codex_home / name: (self.codex_home / name).read_bytes()
            for name in ("config.toml", "manager.config.toml")
        }

        fake_codex = self.fake_bin / "codex"
        fake_codex.write_text(
            "#!/usr/bin/env python3\n"
            "import json, os, sys\n"
            "with open(os.environ['FAKE_CODEX_RECORD'], 'w', encoding='utf-8') as record:\n"
            "    json.dump({'argv': sys.argv[1:], 'codex_home': os.environ.get('CODEX_HOME')}, record)\n"
            "sys.stdout.write(os.environ.get('FAKE_CODEX_STDOUT', ''))\n"
            "sys.stderr.write(os.environ.get('FAKE_CODEX_STDERR', ''))\n"
            "raise SystemExit(int(os.environ.get('FAKE_CODEX_STATUS', '0')))\n",
            encoding="utf-8",
        )
        fake_codex.chmod(0o755)

    def write_profile(self, name, contents):
        path = self.codex_home / f"{name}.config.toml"
        path.write_text(contents, encoding="utf-8")
        self.config_snapshots[path] = path.read_bytes()
        return path

    def write_datadog_profiles(self):
        self.write_profile(
            "datadog",
            '''\
[agents.coder]
temperature = 0.2

[mcp_servers.datadog]
command = "npx"
args = ["--initial", "version-1"]

[mcp_servers.datadog.env]
DD_API_KEY = "test-key"
DD_SITE = "us5.datadoghq.com"
''',
        )
        self.write_profile(
            "datadog-final",
            '''\
[mcp_servers.datadog]
args = ["--latest", "version-2"]

[mcp_servers."X-Datadog.MCP"]
command = "node"
args = ["--x-datadog"]
''',
        )

    def run_wrapper(
        self,
        arguments,
        *,
        status=0,
        stdout="",
        stderr="",
        path=None,
        executable=WRAPPER,
    ):
        environment = os.environ.copy()
        environment.update(
            {
                "CODEX_HOME": str(self.codex_home),
                "FAKE_CODEX_RECORD": str(self.record_path),
                "FAKE_CODEX_STATUS": str(status),
                "FAKE_CODEX_STDOUT": stdout,
                "FAKE_CODEX_STDERR": stderr,
                "PATH": path
                if path is not None
                else os.pathsep.join((str(self.fake_bin), environment.get("PATH", ""))),
            }
        )
        return subprocess.run(
            [str(executable), *arguments],
            check=False,
            capture_output=True,
            text=True,
            env=environment,
            timeout=10,
        )

    def recorded_invocation(self):
        return json.loads(self.record_path.read_text(encoding="utf-8"))

    def assert_config_files_unchanged(self):
        for path, original_bytes in self.config_snapshots.items():
            self.assertEqual(path.read_bytes(), original_bytes, str(path))

    def test_without_profile_forwards_arguments_and_preserves_codex_home_and_configs(self):
        arguments = [
            "exec",
            "--model",
            "o4-mini",
            "-c",
            "model='user-model'",
            "explain this",
            "--",
            "-p",
            "prompt data",
        ]

        result = self.run_wrapper(arguments)

        self.assertEqual(result.returncode, 0, result.stderr)
        invocation = self.recorded_invocation()
        self.assertEqual(invocation["argv"], arguments)
        self.assertEqual(invocation["codex_home"], str(self.codex_home))
        effective = self.effective_config(invocation["argv"])
        self.assertEqual(effective["model"], "user-model")
        self.assertNotIn("manager_reviewer", effective["agents"])
        self.assertNotIn("manager_server", effective["mcp_servers"])
        self.assert_config_files_unchanged()

    def test_one_profile_forwards_arguments_and_preserves_codex_home_and_configs(self):
        self.write_profile("solo", 'model = "solo-model"\n')
        arguments = [
            "--profile=solo",
            "--model",
            "o4-mini",
            "-c",
            "model='explicit-model'",
            "work on this",
        ]

        result = self.run_wrapper(arguments)

        self.assertEqual(result.returncode, 0, result.stderr)
        invocation = self.recorded_invocation()
        self.assertEqual(invocation["argv"], arguments)
        self.assertEqual(invocation["codex_home"], str(self.codex_home))
        self.assert_config_files_unchanged()

    def test_profile_flags_compose_in_order_with_recursive_table_merge(self):
        self.write_datadog_profiles()
        arguments = [
            "-p", "manager",
            "--profile", "datadog",
            "--profile=datadog-final",
        ]

        result = self.run_wrapper(arguments)

        self.assertEqual(result.returncode, 0, result.stderr)
        forwarded = self.recorded_invocation()["argv"]
        self.assertEqual(forwarded[0:2], ["-p", "manager"])
        self.assertNotIn("datadog", forwarded)
        self.assertNotIn("datadog-final", forwarded)

        effective = self.effective_config(forwarded)
        self.assertEqual(effective["agents"]["coder"]["model"], "manager-model")
        self.assertEqual(
            effective["agents"]["default_sibling"], {"description": "from default config"}
        )
        self.assertEqual(effective["mcp_servers"]["default_server"]["args"], ["--default"])
        self.assertEqual(effective["mcp_servers"]["manager_server"]["args"], ["--manager"])
        self.assertEqual(
            effective["mcp_servers"]["datadog"]["args"], ["--latest", "version-2"]
        )
        self.assertEqual(
            effective["mcp_servers"]["datadog"]["env"],
            {"DD_API_KEY": "test-key", "DD_SITE": "us5.datadoghq.com"},
        )
        self.assertEqual(
            effective["mcp_servers"]["X-Datadog.MCP"],
            {"command": "node", "args": ["--x-datadog"]},
        )
        self.assert_config_files_unchanged()

    def test_user_config_before_and_after_profile_flags_overrides_profile_in_user_order(self):
        self.write_profile("native", '[settings]\nsource = "native"\n')
        self.write_profile(
            "overlay",
            '''\
[settings]
before = "profile-before"
after = "profile-after"
''',
        )
        arguments = [
            "-c",
            'settings.before="user-before"',
            "-p",
            "native",
            "--profile=overlay",
            "--config=settings.after=\"user-after\"",
            "task",
        ]

        result = self.run_wrapper(arguments)

        self.assertEqual(result.returncode, 0, result.stderr)
        forwarded = self.recorded_invocation()["argv"]
        early_config_index = forwarded.index("-c")
        late_config_index = next(
            index for index, argument in enumerate(forwarded) if argument.startswith("--config=")
        )
        self.assertLess(
            max(index for index, argument in enumerate(forwarded) if argument == "--config"),
            early_config_index,
        )
        self.assertLess(early_config_index, forwarded.index("-p"))
        self.assertLess(forwarded.index("-p"), late_config_index)
        self.assertLess(early_config_index, late_config_index)
        self.assertEqual(forwarded[early_config_index + 1], 'settings.before="user-before"')
        self.assertEqual(forwarded[late_config_index], '--config=settings.after="user-after"')

        effective = self.effective_config(forwarded)
        self.assertEqual(effective["settings"]["before"], "user-before")
        self.assertEqual(effective["settings"]["after"], "user-after")

    def test_profile_scanner_preserves_config_values_that_look_like_profile_flags(self):
        self.write_profile("overlay", '[settings]\nsource = "overlay"\n')
        cases = (
            ["-p", "manager", "-c", "--profile=missing", "-p", "overlay", "task"],
            ["-p", "manager", "--config", "-p", "-p", "overlay", "task"],
            ["-p", "manager", "--config=--profile=missing", "-p", "overlay", "task"],
        )

        for arguments in cases:
            with self.subTest(arguments=arguments):
                result = self.run_wrapper(arguments)

                self.assertEqual(result.returncode, 0, result.stderr)
                forwarded = self.recorded_invocation()["argv"]
                self.assertEqual(forwarded[0:2], ["-p", "manager"])
                if "--config=--profile=missing" in arguments:
                    self.assertIn("--config=--profile=missing", forwarded)
                elif "--config" in arguments:
                    self.assertIn(["--config", "-p"], [
                        forwarded[index:index + 2]
                        for index in range(len(forwarded) - 1)
                    ])
                else:
                    self.assertIn(["-c", "--profile=missing"], [
                        forwarded[index:index + 2]
                        for index in range(len(forwarded) - 1)
                    ])
                self.assertNotIn("missing", forwarded)

    def test_attached_config_option_keeps_explicit_setting_after_composed_profile(self):
        self.write_profile("native", '[settings]\nsource = "native"\n')
        self.write_profile("overlay", '[settings]\nchoice = "profile"\n')
        arguments = [
            "-p", "native",
            '-csettings.choice="explicit"',
            "--profile=overlay",
            "task",
        ]

        result = self.run_wrapper(arguments)

        self.assertEqual(result.returncode, 0, result.stderr)
        forwarded = self.recorded_invocation()["argv"]
        effective = self.effective_config(forwarded)
        self.assertEqual(effective["settings"]["choice"], "explicit")

    def test_attached_short_profile_forms_participate_in_composition(self):
        self.write_profile("base", '[settings]\nbase = true\n')
        self.write_profile("overlay", '[settings]\nchoice = "overlay"\n')
        cases = (
            ("-pbase", "--profile=overlay"),
            ("-p=base", "--profile=overlay"),
            ("-p", "base", "-poverlay"),
            ("-p", "base", "-p=overlay"),
        )

        for profile_arguments in cases:
            with self.subTest(profile_arguments=profile_arguments):
                arguments = [*profile_arguments, "task"]
                result = self.run_wrapper(arguments)

                self.assertEqual(result.returncode, 0, result.stderr)
                forwarded = self.recorded_invocation()["argv"]
                self.assertEqual(self.profile_names(forwarded), ["base"])
                effective = self.effective_config(forwarded)
                self.assertEqual(effective["settings"]["base"], True)
                self.assertEqual(effective["settings"].get("choice"), "overlay")
                self.assertNotIn("--profile=overlay", forwarded)
                self.assertNotIn("-poverlay", forwarded)
                self.assertNotIn("-p=overlay", forwarded)

    def test_invalid_utf8_overlay_reports_error_without_launching_codex(self):
        self.write_profile("native", 'model = "native-model"\n')
        self.record_path.unlink(missing_ok=True)
        (self.codex_home / "invalid-utf8.config.toml").write_bytes(
            b'model = "invalid-\xff"\n'
        )

        result = self.run_wrapper(
            ["-p", "native", "-p", "invalid-utf8", "task"]
        )

        self.assertEqual(result.returncode, 2)
        self.assertIn("could not read profile 'invalid-utf8'", result.stderr)
        self.assertNotIn("Traceback", result.stderr)
        self.assertFalse(self.record_path.exists(), "fake Codex must not launch")

    def test_sandbox_without_profiles_forwards_profile_like_child_arguments(self):
        child_arguments = [
            "sandbox",
            "/usr/bin/printf",
            "%s\\n",
            "-pbase",
            "-poverlay",
            "--profile=child",
            "-cmodel=child",
            "--",
        ]

        result = self.run_wrapper(child_arguments)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.recorded_invocation()["argv"], child_arguments)

    def test_sandbox_composes_profiles_before_preserving_child_arguments(self):
        self.write_profile("native", 'model = "native-model"\n')
        self.write_profile("overlay", 'model = "overlay-model"\n')
        self.write_profile("child", "")
        arguments = [
            "-p", "native",
            "-p", "overlay",
            "sandbox",
            "--cd", str(self.root),
            "/usr/bin/printf",
            "%s\\n",
            "-pchild",
            "--profile=child",
            "-cmodel=child",
            "--",
        ]

        result = self.run_wrapper(arguments)

        self.assertEqual(result.returncode, 0, result.stderr)
        forwarded = self.recorded_invocation()["argv"]
        self.assertEqual(
            forwarded[:4],
            ["-p", "native", "--config", 'model="overlay-model"'],
        )
        self.assertEqual(
            forwarded[4:],
            [
                "sandbox",
                "--cd", str(self.root),
                "/usr/bin/printf",
                "%s\\n",
                "-pchild",
                "--profile=child",
                "-cmodel=child",
                "--",
            ],
        )

    def test_sandbox_word_in_option_value_or_prompt_does_not_start_sandbox_parsing(self):
        self.write_profile("native", 'model = "native-model"\n')
        self.write_profile("overlay", 'model = "overlay-model"\n')
        cases = (
            (
                ["-m", "sandbox", "exec", "-p", "native", "-p", "overlay", "prompt"],
                ["-m", "sandbox", "exec", "prompt"],
            ),
            (
                ["exec", "sandbox", "--model", "some-model", "-pnative", "-poverlay"],
                ["exec", "sandbox", "--model", "some-model"],
            ),
        )

        for arguments, preserved_arguments in cases:
            with self.subTest(arguments=arguments):
                self.record_path.unlink(missing_ok=True)

                result = self.run_wrapper(arguments)

                self.assertEqual(result.returncode, 0, result.stderr)
                forwarded = self.recorded_invocation()["argv"]
                self.assertEqual(self.profile_names(forwarded), ["native"])
                self.assertEqual(
                    [argument for argument in forwarded if argument in preserved_arguments],
                    preserved_arguments,
                )
                effective = self.effective_config(forwarded)
                self.assertEqual(effective["model"], "overlay-model")

    def test_root_prompt_before_sandbox_keeps_child_profile_flags_opaque(self):
        arguments = [
            "hello",
            "sandbox",
            "/usr/bin/printf",
            "%s\\n",
            "-pbase",
            "-poverlay",
        ]

        result = self.run_wrapper(arguments)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.recorded_invocation()["argv"], arguments)

    def test_separated_variadic_image_values_do_not_hide_later_profiles(self):
        self.write_profile("base", '[settings]\nbase = true\n')
        self.write_profile("overlay", '[settings]\nchoice = "overlay"\n')
        cases = (
            ["--image", "img", "sandbox", "child", "-pbase", "-poverlay", "--help"],
            ["-i", "img", "sandbox", "child", "-pbase", "-poverlay", "--help"],
        )

        for arguments in cases:
            with self.subTest(arguments=arguments):
                self.record_path.unlink(missing_ok=True)

                result = self.run_wrapper(arguments)

                self.assertEqual(result.returncode, 0, result.stderr)
                forwarded = self.recorded_invocation()["argv"]
                self.assertEqual(self.profile_names(forwarded), ["base"])
                self.assertEqual(
                    [item for item in forwarded if item in ("--image", "-i", "img", "sandbox", "child")],
                    [item for item in arguments if item in ("--image", "-i", "img", "sandbox", "child")],
                )
                self.assertEqual(self.effective_config(forwarded)["settings"]["choice"], "overlay")

    def test_attached_image_values_keep_sandbox_child_profile_flags_opaque(self):
        cases = (
            ["--image=img", "sandbox", "/usr/bin/printf", "%s\\n", "-pbase", "-poverlay"],
            ["-iimg", "sandbox", "/usr/bin/printf", "%s\\n", "-pbase", "-poverlay"],
        )

        for arguments in cases:
            with self.subTest(arguments=arguments):
                result = self.run_wrapper(arguments)

                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(self.recorded_invocation()["argv"], arguments)

    def test_mcp_add_command_arguments_are_opaque_without_root_profiles(self):
        arguments = [
            "mcp",
            "add",
            "probe",
            "/usr/bin/printf",
            "-pbase",
            "-poverlay",
            "--profile=child",
            "-cmodel=child",
        ]

        result = self.run_wrapper(arguments)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.recorded_invocation()["argv"], arguments)

    def test_mcp_add_composes_root_profiles_and_preserves_command_arguments(self):
        self.write_profile("base", '[settings]\nbase = true\n')
        self.write_profile("overlay", '[settings]\nchoice = "overlay"\n')
        arguments = [
            "-p", "base",
            "-p", "overlay",
            "mcp",
            "add",
            "probe",
            "/usr/bin/printf",
            "-pchild",
            "--profile=child",
            "-cmodel=child",
        ]

        result = self.run_wrapper(arguments)

        self.assertEqual(result.returncode, 0, result.stderr)
        forwarded = self.recorded_invocation()["argv"]
        self.assertEqual(forwarded[:3], ["-p", "base", "--config"])
        self.assertEqual(
            forwarded[4:],
            [
                "mcp",
                "add",
                "probe",
                "/usr/bin/printf",
                "-pchild",
                "--profile=child",
                "-cmodel=child",
            ],
        )
        self.assertEqual(tomllib.loads(forwarded[3]), {"settings": {"choice": "overlay"}})

    def test_execpolicy_check_command_arguments_are_opaque(self):
        rules = self.root / "empty-rules.json"
        rules.write_text("[]\n", encoding="utf-8")
        cases = (
            [
                "execpolicy",
                "check",
                "--rules",
                str(rules),
                "/usr/bin/printf",
                "-pbase",
                "-poverlay",
            ],
            ["execpolicy", "check", "--rules", str(rules), "-pbase", "-poverlay"],
        )

        for arguments in cases:
            with self.subTest(arguments=arguments):
                result = self.run_wrapper(arguments)

                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(self.recorded_invocation()["argv"], arguments)

    def test_execpolicy_global_options_before_check_leave_child_arguments_opaque(self):
        rules = self.root / "empty-rules.json"
        rules.write_text("[]\n", encoding="utf-8")
        global_option_forms = (
            ("separate short config", ["-c", 'model="x"']),
            ("attached short config", ['-cmodel="x"']),
            ("separate long config", ["--config", 'model="x"']),
            ("attached long config", ['--config=model="x"']),
            ("enable", ["--enable", "multi_agent"]),
            ("disable", ["--disable", "multi_agent"]),
        )

        for name, global_options in global_option_forms:
            with self.subTest(global_option=name):
                arguments = [
                    "execpolicy",
                    *global_options,
                    "check",
                    "--rules",
                    str(rules),
                    "/usr/bin/printf",
                    "-pbase",
                    "-poverlay",
                ]

                result = self.run_wrapper(arguments)

                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(self.recorded_invocation()["argv"], arguments)

    def test_escaped_del_roundtrips_in_override_values_and_quoted_keys(self):
        self.write_profile("native", '[settings]\nbase = true\n')
        cases = (
            (
                "string value",
                '''\
developer_instructions = "a\\u007fb"
''',
                {"developer_instructions": "a\x7fb"},
            ),
            (
                "quoted nested key",
                '''\
[mcp_servers."quoted\\u007fkey"]
command = "unused"
''',
                {"mcp_servers": {"quoted\x7fkey": {"command": "unused"}}},
            ),
        )

        for case, contents, expected_config in cases:
            with self.subTest(case=case):
                self.record_path.unlink(missing_ok=True)
                self.write_profile("overlay", contents)
                result = self.run_wrapper(["-p", "native", "-p", "overlay", "task"])

                self.assertEqual(result.returncode, 0, result.stderr)
                forwarded = self.recorded_invocation()["argv"]
                effective = {}
                for setting in self.config_settings(forwarded):
                    try:
                        parsed_setting = tomllib.loads(setting)
                    except tomllib.TOMLDecodeError as exc:
                        self.fail(f"composed profile setting is invalid TOML: {exc}")
                    self.merge_tables(effective, parsed_setting)

                self.assertEqual(effective, expected_config)

    def test_missing_codex_and_self_referential_codex_report_diagnostics(self):
        missing = self.run_wrapper(["status"], path=str(self.root))

        self.assertEqual(missing.returncode, 2)
        self.assertIn("could not find the underlying codex executable", missing.stderr)
        self.assertNotIn("Traceback", missing.stderr)

        self_bin = self.root / "self-bin"
        self_bin.mkdir()
        (self_bin / "codex").symlink_to(WRAPPER)
        recursive = self.run_wrapper(["status"], path=str(self_bin))

        self.assertEqual(recursive.returncode, 2)
        self.assertIn("resolves to codex-wrapper itself", recursive.stderr)
        self.assertNotIn("Traceback", recursive.stderr)

        hardlink_bin = self.root / "hardlink-bin"
        hardlink_bin.mkdir()
        local_wrapper = hardlink_bin / "codex-wrapper"
        shutil.copy2(WRAPPER, local_wrapper)
        os.link(local_wrapper, hardlink_bin / "codex")
        hardlinked = self.run_wrapper(
            ["status"], path=str(hardlink_bin), executable=local_wrapper
        )

        self.assertEqual(hardlinked.returncode, 2)
        self.assertIn("resolves to codex-wrapper itself", hardlinked.stderr)
        self.assertNotIn("Traceback", hardlinked.stderr)

    def test_invalid_codex_executable_format_reports_diagnostic(self):
        codex = self.fake_bin / "codex"
        codex.write_bytes(b"this is not an executable format")
        codex.chmod(0o755)

        result = self.run_wrapper(["status"])

        self.assertEqual(result.returncode, 2)
        self.assertIn("codex-wrapper:", result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def test_manager_config_and_profile_overrides_preserve_nested_codex_configuration(self):
        self.write_datadog_profiles()
        policy_instructions = '''Follow policy’s “least privilege” guidance.
Use the exact label "résumé" for 東京.
'''
        self.write_profile(
            "policy",
            '''\
developer_instructions = """Follow policy’s “least privilege” guidance.
Use the exact label "résumé" for 東京.
"""

[agents.policy_reviewer]
description = "added by policy profile"

[[hooks.PostToolUse]]
matcher = "Write"

[[hooks.PostToolUse.hooks]]
type = "command"
command = "policy-post-tool"

[hooks.state."/tmp/policy-hook-state"]
last_applied = "policy"
''',
        )
        arguments = [
            "-p", "manager",
            "--profile", "datadog",
            "--profile", "datadog-final",
            "--profile=policy",
        ]

        result = self.run_wrapper(arguments)

        self.assertEqual(result.returncode, 0, result.stderr)
        forwarded = self.recorded_invocation()["argv"]
        self.assertEqual(forwarded[0:2], ["-p", "manager"])
        self.assertNotIn("datadog", forwarded)
        self.assertNotIn("datadog-final", forwarded)
        self.assertNotIn("policy", forwarded)
        effective = self.effective_config(forwarded)

        self.assertEqual(
            effective["developer_instructions"],
            policy_instructions,
        )
        self.assertEqual(effective["agents"]["coder"]["description"], "default coder")
        self.assertEqual(effective["agents"]["coder"]["model"], "manager-model")
        self.assertEqual(effective["agents"]["coder"]["temperature"], 0.2)
        self.assertEqual(effective["agents"]["coder"]["sandbox"], {"mode": "workspace"})
        self.assertEqual(
            effective["agents"]["default_sibling"], {"description": "from default config"}
        )
        self.assertEqual(
            effective["agents"]["manager_reviewer"], {"description": "from manager config"}
        )
        self.assertEqual(
            effective["agents"]["policy_reviewer"], {"description": "added by policy profile"}
        )
        self.assertEqual(effective["mcp_servers"]["default_server"]["args"], ["--default"])
        self.assertEqual(effective["mcp_servers"]["manager_server"]["args"], ["--manager"])
        self.assertEqual(effective["mcp_servers"]["datadog"]["args"], ["--latest", "version-2"])
        self.assertEqual(
            effective["mcp_servers"]["datadog"]["env"],
            {"DD_API_KEY": "test-key", "DD_SITE": "us5.datadoghq.com"},
        )
        self.assertEqual(
            effective["mcp_servers"]["X-Datadog.MCP"],
            {"command": "node", "args": ["--x-datadog"]},
        )
        self.assertEqual(
            effective["hooks"]["SessionStart"],
            [{"matcher": "startup", "hooks": [{"type": "command", "command": "default-start"}]}],
        )
        self.assertEqual(
            effective["hooks"]["PreToolUse"],
            [{"matcher": "Bash", "hooks": [{"type": "command", "command": "manager-pre-tool"}]}],
        )
        self.assertEqual(
            effective["hooks"]["PostToolUse"],
            [{"matcher": "Write", "hooks": [{"type": "command", "command": "policy-post-tool"}]}],
        )
        self.assertEqual(
            effective["hooks"]["state"],
            {
                "/tmp/default-hook-state": {"installed": True},
                "/tmp/manager-hook-state": {"last_applied": "manager"},
                "/tmp/policy-hook-state": {"last_applied": "policy"},
            },
        )
        self.assert_config_files_unchanged()

    def test_profile_flags_after_standalone_double_dash_are_prompt_data(self):
        arguments = [
            "--profile",
            "manager",
            "--",
            "-p",
            "missing",
            "--profile=also-missing",
            "prompt text",
        ]

        result = self.run_wrapper(arguments)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.recorded_invocation()["argv"], arguments)

    def test_missing_or_malformed_later_profile_fails_before_codex_launch(self):
        cases = (
            ("missing", None),
            ("malformed", "[settings\nvalue = \"broken\"\n"),
        )
        for profile_name, contents in cases:
            with self.subTest(profile=profile_name):
                self.record_path.unlink(missing_ok=True)
                self.write_profile("native", '[settings]\nsource = "native"\n')
                if contents is not None:
                    self.write_profile(profile_name, contents)

                result = self.run_wrapper(["-p", "native", "--profile", profile_name, "task"])

                self.assertEqual(result.returncode, 2)
                self.assertIn(profile_name, result.stderr)
                self.assertFalse(self.record_path.exists(), "fake Codex must not launch")

    def test_native_output_and_exit_status_pass_through(self):
        stdout = "native stdout: ✓\n"
        stderr = "native stderr: diagnostic\n"

        result = self.run_wrapper(["status", "--json"], status=23, stdout=stdout, stderr=stderr)

        self.assertEqual(result.returncode, 23)
        self.assertEqual(result.stdout, stdout)
        self.assertEqual(result.stderr, stderr)

    def effective_config(self, forwarded_arguments):
        default_config = self.codex_home / "config.toml"
        effective = tomllib.loads(default_config.read_text("utf-8"))

        profiles = self.profile_names(forwarded_arguments)
        if profiles:
            native_profile = self.codex_home / f"{profiles[0]}.config.toml"
            self.merge_tables(effective, tomllib.loads(native_profile.read_text("utf-8")))

        for setting in self.config_settings(forwarded_arguments):
            self.merge_tables(effective, tomllib.loads(setting))
        return effective

    @staticmethod
    def profile_names(arguments):
        end = arguments.index("--") if "--" in arguments else len(arguments)
        names = []
        index = 0
        while index < end:
            argument = arguments[index]
            if argument in ("-p", "--profile") and index + 1 < end:
                names.append(arguments[index + 1])
                index += 2
            elif argument.startswith("--profile="):
                names.append(argument.partition("=")[2])
                index += 1
            elif argument.startswith("-p"):
                profile = argument[2:]
                names.append(profile[1:] if profile.startswith("=") else profile)
                index += 1
            else:
                index += 1
        return names

    @staticmethod
    def config_settings(arguments):
        end = arguments.index("--") if "--" in arguments else len(arguments)
        settings = []
        index = 0
        while index < end:
            argument = arguments[index]
            if argument in ("-c", "--config") and index + 1 < end:
                settings.append(arguments[index + 1])
                index += 2
            elif argument.startswith("--config="):
                settings.append(argument.partition("=")[2])
                index += 1
            elif argument.startswith("-c="):
                settings.append(argument.partition("=")[2])
                index += 1
            elif argument.startswith("-c"):
                settings.append(argument[2:])
                index += 1
            else:
                index += 1
        return settings

    @classmethod
    def merge_tables(cls, target, overlay):
        for key, value in overlay.items():
            existing = target.get(key)
            if isinstance(existing, dict) and isinstance(value, dict):
                cls.merge_tables(existing, value)
            else:
                target[key] = value


if __name__ == "__main__":
    unittest.main()
