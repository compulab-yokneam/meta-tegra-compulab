#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Host-only desktop selection tests; no display, camera or sudo is used."""

import json
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
import tempfile
import unittest


SOURCE = Path(__file__).resolve().parents[1] / "files/gst_camera.sh"
MOCK_PROGRAM = r'''import json
import os
from pathlib import Path
import sys

command = Path(sys.argv[0]).name
with open(os.environ["MOCK_CALLS"], "a") as stream:
    stream.write(json.dumps({
        "command": command, "args": sys.argv[1:],
        "DISPLAY": os.environ.get("DISPLAY"),
        "XAUTHORITY": os.environ.get("XAUTHORITY"),
        "WAYLAND_DISPLAY": os.environ.get("WAYLAND_DISPLAY"),
        "UNRELATED": os.environ.get("UNRELATED"),
    }) + "\n")
if command == "id":
    print(os.environ.get("MOCK_UID", "1000"))
elif command == "argus_oneshot":
    print("""1 Available CameraDevices:
  ==== CameraDevice 0: imx678_port0_framos ====
    SensorMode 0:
        Resolution: 3856x2180
        FrameDurationRange: [100000000, 100000008]
        InputBitDepth: 12
        OutputBitDepth: 12
        SensorModeType: SENSOR_MODE_TYPE_BAYER
""")
elif command == "systemctl":
    if os.environ.get("MOCK_FORBID_SYSTEMCTL") == "1":
        sys.exit(95)
    print(os.environ.get("MOCK_DESKTOP_ENV", ""))
    sys.exit(int(os.environ.get("MOCK_SYSTEMCTL_EXIT", "0")))
elif command == "gst-inspect-1.0":
    sys.exit(int(os.environ.get("MOCK_INSPECT_EXIT", "0")))
elif command == "gst-launch-1.0":
    sys.exit(int(os.environ.get("MOCK_GST_EXIT", "0")))
'''


class GstDesktopTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="gst-desktop-test-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.calls_path = self.root / "calls.jsonl"
        for command in ("id", "argus_oneshot", "gst-launch-1.0",
                        "gst-inspect-1.0", "systemctl",
                        "edge-ai-desktop-exec",
                        "edge-ai-gst-x11-preview"):
            path = self.bin / command
            path.write_text("#!" + sys.executable + "\n" + MOCK_PROGRAM)
            path.chmod(0o755)
        source = SOURCE.read_text()
        source = re.sub(r"(?m)^(\s*(?:export )?PATH=)[^\n]+$",
                        lambda match: match[1] + '"' + str(self.bin) +
                        ':/usr/bin:/bin"', source)
        source = source.replace("/usr/libexec/edge-ai-desktop-exec",
                                str(self.bin / "edge-ai-desktop-exec"))
        source = source.replace("/usr/libexec/edge-ai-gst-x11-preview",
                                str(self.bin / "edge-ai-gst-x11-preview"))
        source = source.replace("/run/user/", str(self.root / "runtime") +
                                "/")
        self.script = self.root / "gst_camera.sh"
        self.script.write_text(source)
        self.script.chmod(0o755)
        self.runtime = self.root / "runtime/1000"
        self.runtime.mkdir(parents=True)
        self.authority = self.root / "Xauthority"
        self.authority.write_text("fixture only, not a real cookie")
        self.environment = dict(os.environ)
        for name in ("DISPLAY", "WAYLAND_DISPLAY", "XAUTHORITY",
                     "EDGE_AI_DISPLAY", "EDGE_AI_WAYLAND_DISPLAY",
                     "EDGE_AI_XAUTHORITY", "EDGE_AI_DESKTOP_USER",
                     "UNRELATED"):
            self.environment.pop(name, None)
        self.environment.update({
            "PATH": str(self.bin) + ":/usr/bin:/bin",
            "XDG_RUNTIME_DIR": str(self.runtime),
            "XDG_SESSION_TYPE": "tty",
            "MOCK_CALLS": str(self.calls_path),
        })

    def run_script(self, *args, **environment):
        return subprocess.run(
            ["/bin/sh", str(self.script), *map(str, args)],
            cwd=self.root, env=dict(self.environment, **environment),
            text=True, capture_output=True, timeout=5)

    def calls(self, command):
        records = ([json.loads(line) for line in
                    self.calls_path.read_text().splitlines()]
                   if self.calls_path.exists() else [])
        return [record for record in records if record["command"] == command]

    def socket(self, name="wayland-0"):
        endpoint = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        endpoint.bind(str(self.runtime / name))
        self.addCleanup(endpoint.close)
        return name

    def assert_success(self, result):
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def assert_rejected(self, result):
        self.assertNotEqual(result.returncode, 0,
                            result.stdout + result.stderr)
        self.assertEqual(self.calls("gst-launch-1.0"), [])

    def test_help_documents_backend_selection(self):
        result = self.run_script("--help")
        self.assert_success(result)
        self.assertIn("--display-backend", result.stdout)
        self.assertEqual(self.calls("systemctl"), [])

    def test_explicit_x11_dry_run_needs_no_desktop_or_camera(self):
        result = self.run_script(
            "live", "--sensor", "imx678", "--dry-run",
            "--display-backend", "x11", MOCK_FORBID_SYSTEMCTL="1")
        self.assert_success(result)
        self.assertIn("'nv3dsink'", result.stdout)
        self.assertNotIn("'waylandsink'", result.stdout)
        for command in ("systemctl", "argus_oneshot", "gst-launch-1.0"):
            self.assertEqual(self.calls(command), [])

    def test_headless_default_dry_run_preserves_wayland_pipeline(self):
        result = self.run_script("live", "--sensor", "imx678", "--dry-run",
                                 "--fullscreen", MOCK_FORBID_SYSTEMCTL="1")
        self.assert_success(result)
        self.assertIn("'waylandsink' 'sync=false' 'fullscreen=true'",
                      result.stdout)
        self.assertEqual(self.calls("systemctl"), [])

    def test_x11_session_selects_nv3dsink_and_preserves_environment(self):
        result = self.run_script(
            "live", "--sensor-id", "0", XDG_SESSION_TYPE="x11",
            DISPLAY=":fixture", XAUTHORITY=str(self.authority))
        self.assert_success(result)
        pipeline = self.calls("gst-launch-1.0")[-1]
        self.assertIn("nv3dsink", pipeline["args"])
        self.assertNotIn("waylandsink", pipeline["args"])
        self.assertEqual(pipeline["DISPLAY"], ":fixture")
        self.assertEqual(pipeline["XAUTHORITY"], str(self.authority))
        self.assertIsNone(pipeline["UNRELATED"])

    def test_explicit_wayland_overrides_x11_session(self):
        name = self.socket()
        result = self.run_script(
            "live", "--display-backend", "wayland",
            XDG_SESSION_TYPE="x11", DISPLAY=":fixture",
            WAYLAND_DISPLAY=name)
        self.assert_success(result)
        pipeline = self.calls("gst-launch-1.0")[-1]
        self.assertIn("waylandsink", pipeline["args"])
        self.assertEqual(pipeline["WAYLAND_DISPLAY"], name)

    def test_x11_session_wins_over_an_inherited_wayland_socket(self):
        name = self.socket()
        result = self.run_script(
            "live", XDG_SESSION_TYPE="x11", DISPLAY=":fixture",
            XAUTHORITY=str(self.authority), WAYLAND_DISPLAY=name)
        self.assert_success(result)
        self.assertIn("nv3dsink", self.calls("gst-launch-1.0")[-1]["args"])

    def test_x11_fullscreen_uses_window_host_not_fake_sink_property(self):
        result = self.run_script(
            "live", "--fullscreen", XDG_SESSION_TYPE="x11",
            DISPLAY=":fixture", XAUTHORITY=str(self.authority))
        self.assert_success(result)
        helper = self.calls("edge-ai-gst-x11-preview")[-1]["args"]
        self.assertIn("--fullscreen", helper)
        self.assertIn("videoscale", helper)
        self.assertIn("add-borders=true", helper)
        self.assertIn("ximagesink", helper)
        self.assertIn("name=edge_ai_preview", helper)
        self.assertNotIn("fullscreen=true", helper)
        self.assertNotIn("gst-launch-1.0", helper)
        self.assertNotIn("-e", helper)
        self.assertEqual(self.calls("gst-launch-1.0"), [])

    def test_unique_wayland_socket_is_discovered_without_x11(self):
        name = self.socket()
        result = self.run_script("live", "--fullscreen")
        self.assert_success(result)
        pipeline = self.calls("gst-launch-1.0")[-1]
        self.assertIn("waylandsink", pipeline["args"])
        self.assertIn("fullscreen=true", pipeline["args"])
        self.assertEqual(pipeline["WAYLAND_DISPLAY"], name)

    def test_ambiguous_wayland_requires_explicit_display(self):
        self.socket("wayland-0")
        self.socket("wayland-1")
        result = self.run_script("live", "--display-backend", "wayland")
        self.assert_rejected(result)
        self.assertIn("WAYLAND_DISPLAY", result.stderr)

    def test_missing_x11_display_is_rejected_before_launch(self):
        result = self.run_script("live", "--display-backend", "x11")
        self.assert_rejected(result)
        self.assertIn("DISPLAY", result.stderr)

    def test_ssh_discovers_only_callers_user_manager_environment(self):
        desktop = ("DISPLAY=:fixture\nXAUTHORITY=" + str(self.authority) +
                   "\nXDG_SESSION_TYPE=x11\nUNRELATED=do-not-import")
        result = self.run_script("live", MOCK_DESKTOP_ENV=desktop)
        self.assert_success(result)
        self.assertTrue(self.calls("systemctl"))
        self.assertTrue(any("--user" in record["args"] and
                            "show-environment" in record["args"]
                            for record in self.calls("systemctl")))
        pipeline = self.calls("gst-launch-1.0")[-1]
        self.assertIn("nv3dsink", pipeline["args"])
        self.assertEqual(pipeline["DISPLAY"], ":fixture")
        self.assertEqual(pipeline["XAUTHORITY"], str(self.authority))

    def test_imported_environment_is_data_not_shell_code(self):
        authority = self.root / "auth $(touch INJECTED); literal"
        authority.write_text("not a real cookie")
        desktop = ("DISPLAY=:fixture\nXAUTHORITY=" + str(authority) +
                   "\nXDG_SESSION_TYPE=x11\n"
                   "UNRELATED=$(touch UNRELATED_INJECTED)")
        result = self.run_script("live", MOCK_DESKTOP_ENV=desktop)
        self.assert_success(result)
        pipeline = self.calls("gst-launch-1.0")[-1]
        self.assertEqual(pipeline["XAUTHORITY"], str(authority))
        self.assertIsNone(pipeline["UNRELATED"])
        self.assertFalse((self.root / "INJECTED").exists())
        self.assertFalse((self.root / "UNRELATED_INJECTED").exists())

    def test_forwarded_display_does_not_import_another_displays_authority(self):
        desktop = ("DISPLAY=:fixture\nXAUTHORITY=" + str(self.authority) +
                   "\nXDG_SESSION_TYPE=x11\n"
                   "UNRELATED=$(touch UNRELATED_INJECTED)")
        result = self.run_script("live", DISPLAY=":forwarded",
                                 MOCK_DESKTOP_ENV=desktop)
        self.assert_success(result)
        pipeline = self.calls("gst-launch-1.0")[-1]
        self.assertEqual(pipeline["DISPLAY"], ":forwarded")
        self.assertIn(pipeline["XAUTHORITY"], (None, ""))
        self.assertIsNone(pipeline["UNRELATED"])
        self.assertFalse((self.root / "UNRELATED_INJECTED").exists())

    def test_backend_option_is_live_only_and_validated(self):
        for args in (("record", "--display-backend", "x11"),
                     ("capture", "--display-backend", "wayland"),
                     ("--list-modes", "--display-backend", "auto"),
                     ("live", "--display-backend", "unknown"),
                     ("live", "--display-backend", "x11",
                      "--display-backend", "wayland")):
            with self.subTest(args=args):
                self.assert_rejected(self.run_script(*args))
        self.assertEqual(self.calls("systemctl"), [])

    def test_record_and_capture_still_work_without_a_desktop(self):
        for operation, options in (
                ("record", ("--encoder", "software", "--duration", "1")),
                ("capture", ("--frames", "1"))):
            with self.subTest(operation=operation):
                output = self.root / ("new-" + operation)
                result = self.run_script(
                    operation, *options, "--output", output,
                    MOCK_FORBID_SYSTEMCTL="1")
                self.assert_success(result)
        self.assertEqual(self.calls("systemctl"), [])

    def test_root_x11_delegation_retains_backend_and_camera_arguments(self):
        result = self.run_script(
            "live", "--sensor-id", "0", "--sensor", "imx678",
            "--sensor-mode", "0", "--display-backend", "x11",
            MOCK_UID="0", EDGE_AI_DESKTOP_USER="clab",
            EDGE_AI_DISPLAY=":fixture",
            EDGE_AI_XAUTHORITY=str(self.authority))
        self.assert_success(result)
        helper = self.calls("edge-ai-desktop-exec")[-1]["args"]
        self.assertEqual(helper[0], "--x11")
        for option, value in (("--sensor-id", "0"),
                              ("--sensor", "imx678"),
                              ("--sensor-mode", "0"),
                              ("--display-backend", "x11")):
            self.assertEqual(helper[helper.index(option) + 1], value)
        self.assertEqual(self.calls("gst-launch-1.0"), [])

    def test_root_auto_leaves_backend_selection_to_desktop_user(self):
        result = self.run_script(
            "live", "--sensor-id", "0", "--sensor", "imx678",
            "--sensor-mode", "0", "--display-backend", "auto",
            MOCK_UID="0", EDGE_AI_DESKTOP_USER="clab")
        self.assert_success(result)
        helper = self.calls("edge-ai-desktop-exec")[-1]["args"]
        self.assertEqual(helper[0], "--auto")
        self.assertEqual(helper[helper.index("--display-backend") + 1], "auto")
        self.assertEqual(helper[helper.index("--sensor-id") + 1], "0")
        self.assertEqual(helper[helper.index("--sensor") + 1], "imx678")
        self.assertEqual(helper[helper.index("--sensor-mode") + 1], "0")
        self.assertEqual(self.calls("systemctl"), [])
        self.assertEqual(self.calls("gst-launch-1.0"), [])


if __name__ == "__main__":
    unittest.main()
