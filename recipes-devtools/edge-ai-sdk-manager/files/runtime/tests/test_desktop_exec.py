#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Host-only tests of explicit desktop delegation and literal discovery."""

import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest


SOURCE = Path(__file__).resolve().parents[1] / "files/edge-ai-desktop-exec"
MOCK_PROGRAM = r'''import json
import os
from pathlib import Path
import sys

command = Path(sys.argv[0]).name
with open(os.environ["MOCK_CALLS"], "a") as stream:
    stream.write(json.dumps({
        "command": command,
        "args": sys.argv[1:],
        "DISPLAY": os.environ.get("DISPLAY"),
        "XAUTHORITY": os.environ.get("XAUTHORITY"),
        "UNRELATED": os.environ.get("UNRELATED"),
        "GDK_BACKEND": os.environ.get("GDK_BACKEND"),
        "XDG_RUNTIME_DIR": os.environ.get("XDG_RUNTIME_DIR"),
        "DBUS_SESSION_BUS_ADDRESS": os.environ.get("DBUS_SESSION_BUS_ADDRESS"),
    }) + "\n")
if command == "id":
    if len(sys.argv) > 2:
        if os.environ.get("MOCK_UNKNOWN_USER") == "1":
            sys.exit(1)
        print(os.environ.get("MOCK_DESKTOP_UID", "1000"))
    else:
        print(os.environ.get("MOCK_UID", "1000"))
elif command == "systemctl":
    print(os.environ.get("MOCK_DESKTOP_ENV", ""))
    sys.exit(int(os.environ.get("MOCK_SYSTEMCTL_EXIT", "0")))
elif command == "sample-command":
    sys.exit(int(os.environ.get("MOCK_COMMAND_EXIT", "0")))
'''


class DesktopExecTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="desktop-exec-test-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.calls_path = self.root / "calls.jsonl"
        for command in ("id", "systemctl", "runuser", "sample-command"):
            path = self.bin / command
            path.write_text("#!" + sys.executable + "\n" + MOCK_PROGRAM)
            path.chmod(0o755)
        source = re.sub(
            r"(?m)^((?:export )?PATH=)[^\n]+$",
            lambda match: match[1] + '"' + str(self.bin) + ':/usr/bin:/bin"',
            SOURCE.read_text())
        source = source.replace("/run/user/", str(self.root / "runtime") + "/")
        self.script = self.root / "edge-ai-desktop-exec"
        self.script.write_text(source)
        self.script.chmod(0o755)
        self.runtime = self.root / "runtime/1000"
        self.runtime.mkdir(parents=True)
        self.authority = self.root / "Xauthority"
        self.authority.write_text("fixture only, not a real cookie")
        self.environment = dict(os.environ)
        for name in ("DISPLAY", "XAUTHORITY", "WAYLAND_DISPLAY",
                     "EDGE_AI_DESKTOP_USER", "EDGE_AI_DISPLAY",
                     "EDGE_AI_XAUTHORITY", "EDGE_AI_WAYLAND_DISPLAY",
                     "UNRELATED"):
            self.environment.pop(name, None)
        self.environment.update({
            "PATH": str(self.bin) + ":/usr/bin:/bin",
            "MOCK_CALLS": str(self.calls_path),
            "XDG_RUNTIME_DIR": str(self.runtime),
            "DBUS_SESSION_BUS_ADDRESS": "unix:path=/fixture/ssh-session-bus",
        })

    def run_helper(self, *args, **environment):
        return subprocess.run(
            ["/bin/sh", str(self.script), *map(str, args)],
            cwd=self.root, env=dict(self.environment, **environment),
            capture_output=True, text=True, timeout=5)

    def calls(self, command):
        records = ([json.loads(line) for line in
                    self.calls_path.read_text().splitlines()]
                   if self.calls_path.exists() else [])
        return [record for record in records if record["command"] == command]

    def assert_success(self, result):
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def assert_rejected(self, result):
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.calls("sample-command"), [])

    def test_x11_discovers_only_calling_users_literal_desktop_metadata(self):
        marker = self.root / "SHOULD_NOT_EXIST"
        display = ":fixture$(touch " + str(marker) + ")"
        result = self.run_helper(
            "--x11", "sample-command", "literal argument; $(false)",
            MOCK_DESKTOP_ENV=("DISPLAY=" + display + "\nXAUTHORITY=" +
                              str(self.authority) + "\nUNRELATED=unsafe\n" +
                              "PATH=/invalid\nexport BAD=unsafe"))
        self.assert_success(result)
        desktop = self.calls("systemctl")
        self.assertEqual(len(desktop), 1)
        self.assertEqual(desktop[0]["args"], ["--user", "show-environment"])
        call = self.calls("sample-command")[0]
        self.assertEqual(call["DISPLAY"], display)
        self.assertEqual(call["XAUTHORITY"], str(self.authority))
        self.assertEqual(call["GDK_BACKEND"], "x11")
        self.assertEqual(call["args"], ["literal argument; $(false)"])
        self.assertIsNone(call["UNRELATED"])
        self.assertFalse(marker.exists())

    def test_explicit_display_and_authority_do_not_query_user_manager(self):
        result = self.run_helper(
            "--x11", "sample-command", DISPLAY=":explicit",
            XAUTHORITY=str(self.authority),
            MOCK_DESKTOP_ENV="DISPLAY=:wrong\nXAUTHORITY=/wrong")
        self.assert_success(result)
        self.assertEqual(self.calls("systemctl"), [])
        call = self.calls("sample-command")[0]
        self.assertEqual(call["DISPLAY"], ":explicit")
        self.assertEqual(call["XAUTHORITY"], str(self.authority))

    def test_matching_explicit_display_can_import_its_missing_authority(self):
        result = self.run_helper(
            "--x11", "sample-command", DISPLAY=":matching",
            MOCK_DESKTOP_ENV="DISPLAY=:matching\nXAUTHORITY=" +
            str(self.authority))
        self.assert_success(result)
        call = self.calls("sample-command")[0]
        self.assertEqual(call["DISPLAY"], ":matching")
        self.assertEqual(call["XAUTHORITY"], str(self.authority))

    def test_forwarded_display_never_inherits_local_desktop_authority(self):
        result = self.run_helper(
            "--x11", "sample-command", DISPLAY="localhost:10.0",
            MOCK_DESKTOP_ENV="DISPLAY=:local\nXAUTHORITY=" +
            str(self.authority))
        self.assert_success(result)
        call = self.calls("sample-command")[0]
        self.assertEqual(call["DISPLAY"], "localhost:10.0")
        self.assertFalse(call["XAUTHORITY"])

    def test_no_logged_in_desktop_is_rejected_without_guessing_a_display(self):
        result = self.run_helper("--x11", "sample-command")
        self.assert_rejected(result)
        self.assertIn("desktop", result.stderr.lower())
        self.assertEqual(self.calls("runuser"), [])

    def test_failed_user_manager_does_not_import_its_stdout(self):
        result = self.run_helper(
            "--x11", "sample-command", MOCK_SYSTEMCTL_EXIT="1",
            MOCK_DESKTOP_ENV="DISPLAY=:failed\nXAUTHORITY=" +
            str(self.authority))
        self.assert_rejected(result)

    def test_unreadable_explicit_authority_fails_before_starting_application(self):
        result = self.run_helper(
            "--x11", "sample-command", DISPLAY=":explicit",
            XAUTHORITY=str(self.root / "nonexistent-authority"))
        self.assert_rejected(result)
        self.assertIn("xauthority", result.stderr.lower())
        self.assertEqual(self.calls("systemctl"), [])

    def test_unreadable_discovered_authority_is_rejected(self):
        result = self.run_helper(
            "--x11", "sample-command",
            MOCK_DESKTOP_ENV="DISPLAY=:local\nXAUTHORITY=" +
            str(self.root / "nonexistent-authority"))
        self.assert_rejected(result)

    def test_command_arguments_and_exit_status_are_preserved(self):
        marker = 'literal $(touch SHOULD_NOT_EXIST); "quoted value"'
        result = self.run_helper(
            "--x11", "sample-command", marker, "", "--flag=value with spaces",
            DISPLAY=":explicit", XAUTHORITY=str(self.authority),
            MOCK_COMMAND_EXIT="37")
        self.assertEqual(result.returncode, 37)
        self.assertEqual(self.calls("sample-command")[0]["args"],
                         [marker, "", "--flag=value with spaces"])
        self.assertFalse((self.root / "SHOULD_NOT_EXIST").exists())

    def test_root_requires_explicit_selected_desktop_user(self):
        result = self.run_helper("--x11", "sample-command", MOCK_UID="0")
        self.assert_rejected(result)
        self.assertIn("EDGE_AI_DESKTOP_USER", result.stderr)
        self.assertEqual(self.calls("runuser"), [])
        self.assertEqual(self.calls("systemctl"), [])

    def test_root_delegates_discovery_to_selected_users_runtime_and_bus(self):
        literal = "literal $(false); argument"
        result = self.run_helper(
            "--x11", "sample-command", literal, MOCK_UID="0",
            EDGE_AI_DESKTOP_USER="selected-desktop")
        self.assert_success(result)
        calls = self.calls("runuser")
        self.assertEqual(len(calls), 1)
        args = calls[0]["args"]
        self.assertEqual(args[:4], ["-u", "selected-desktop", "--", "env"])
        self.assertIn("XDG_RUNTIME_DIR=" + str(self.runtime), args)
        self.assertIn("DBUS_SESSION_BUS_ADDRESS=unix:path=" +
                      str(self.runtime / "bus"), args)
        self.assertEqual(args[-3:], ["--x11", "sample-command", literal])
        self.assertEqual(self.calls("systemctl"), [])

    def test_root_explicit_display_overrides_are_passed_as_literal_arguments(self):
        result = self.run_helper(
            "--x11", "sample-command", MOCK_UID="0",
            EDGE_AI_DESKTOP_USER="selected-desktop",
            EDGE_AI_DISPLAY=":selected", EDGE_AI_XAUTHORITY=str(self.authority),
            DISPLAY=":inherited", XAUTHORITY="/wrong/inherited-authority")
        self.assert_success(result)
        args = self.calls("runuser")[0]["args"]
        self.assertIn("DISPLAY=:selected", args)
        self.assertIn("XAUTHORITY=" + str(self.authority), args)
        self.assertNotIn("DISPLAY=:inherited", args)

    def test_root_does_not_select_root_or_an_unknown_user(self):
        for extras in ({"MOCK_DESKTOP_UID": "0"}, {"MOCK_UNKNOWN_USER": "1"}):
            with self.subTest(extras=extras):
                result = self.run_helper(
                    "--x11", "sample-command", MOCK_UID="0",
                    EDGE_AI_DESKTOP_USER="selected-desktop", **extras)
                self.assert_rejected(result)
        self.assertEqual(self.calls("runuser"), [])

    def test_nonroot_auto_and_wayland_do_not_change_x11_discovery_behavior(self):
        for backend in ("--auto", "--wayland"):
            with self.subTest(backend=backend):
                result = self.run_helper(backend, "sample-command")
                self.assert_success(result)
        self.assertEqual(self.calls("systemctl"), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
