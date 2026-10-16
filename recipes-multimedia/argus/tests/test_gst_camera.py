#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Host-only CLI regression tests for gst_camera.sh.

Run from any working directory with Python 3 and standard POSIX tools:

    python3 path/to/recipes-multimedia/argus/tests/test_gst_camera.py

Optional unittest selectors work normally, for example:

    python3 path/to/tests/test_gst_camera.py \\
        CameraLauncherTests.test_live_root_reexec_retains_sensor_id_and_preset

No Jetson, GStreamer installation, root privileges, or third-party Python
packages are needed. Camera/GStreamer/service/user-switch commands are
mocked. Only a temporary copy has its fixed PATH and /run/user directory
redirected to fixtures; production shell logic and files stay untouched.
These tests verify CLI behavior, not real image quality or camera timing.
"""
import json
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import unittest

SOURCE = Path(__file__).resolve().parents[1] / "files" / "gst_camera.sh"

# Each executable fixture receives this standalone program, using the
# current Python interpreter so a host-specific interpreter path is not
# embedded in the repository.
MOCK_PROGRAM = r'''"""Host-only dependency mock; never talks to camera hardware."""
import json
import os
from pathlib import Path
import sys

command = Path(sys.argv[0]).name
try:
    fd3 = os.readlink("/proc/self/fd/3")
except OSError:
    fd3 = None
with open(os.environ["MOCK_CALLS"], "a") as output:
    output.write(json.dumps({"command": command, "argv": sys.argv[1:],
                             "cwd": os.getcwd(), "fd3": fd3}) + "\n")
if os.environ.get("MOCK_FORBID_ALL") == "1":
    print("forbidden mock dependency invoked", command, file=sys.stderr)
    sys.exit(97)
if command == "id":
    if sys.argv[1:] == ["-u"]:
        print(os.environ.get("MOCK_UID", "1000"))
    elif sys.argv[1:] == ["-un"]:
        print("weston")
    elif sys.argv[1:] == ["-u", "weston"]:
        print("1000")
    elif sys.argv[1:] == ["weston"]:
        print("uid=1000(weston) gid=1000(weston)")
    else:
        sys.exit(96)
    sys.exit(0)
if command in {"argus_camera.sh", "argus_camera", "argus_oneshot"}:
    sys.stdout.write(Path(os.environ["MOCK_CAMERA_INFO"]).read_text())
    sys.exit(int(os.environ.get("MOCK_INFO_EXIT", "0")))
if command in {"su", "runuser"}:
    args = sys.argv[1:]
    if "-c" in args:
        os.environ["MOCK_UID"] = "1000"
        index = args.index("-c")
        shell_command = args[index + 1]
        trailing = args[index + 2:]
        if trailing and trailing[0] == "--":
            trailing = trailing[1:]
        os.execv("/bin/sh", ["/bin/sh", "-c", shell_command] + trailing)
    print("unsupported mock su syntax", args, file=sys.stderr)
    sys.exit(98)
if command == "gst-launch-1.0":
    sys.exit(int(os.environ.get("MOCK_GST_EXIT", "0")))
if command == "gst-inspect-1.0":
    if os.environ.get("MOCK_RACE_FILE") and sys.argv[1:] == ["fdsink"]:
        Path(os.environ["MOCK_RACE_FILE"]).write_text("THIRD PARTY")
    if os.environ.get("MOCK_RACE_DIR") and sys.argv[1:] == ["multifilesink"]:
        directory = Path(os.environ["MOCK_RACE_DIR"])
        directory.mkdir()
        (directory / "existing.jpg").write_text("THIRD PARTY")
    sys.exit(int(os.environ.get("MOCK_INSPECT_EXIT", "0")))
sys.exit(0)
'''


class CameraLauncherTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="gst-camera-case-")
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.bin = self.base / "bin"
        self.bin.mkdir()
        for name in ("gst-launch-1.0", "gst-inspect-1.0", "argus_camera.sh", "argus_oneshot",
                     "argus_camera", "su", "runuser", "systemctl", "reboot", "shutdown", "id"):
            target = self.bin / name
            target.write_text("#!" + sys.executable + "\n" + MOCK_PROGRAM)
            target.chmod(0o755)
        self.calls_path = self.base / "calls.jsonl"
        self.camera_info = self.base / "camera-info.txt"
        self.camera_info.write_text("""2 Available CameraDevices:
  ==== CameraDevice 0: imx678_port3_framos ====
    SensorMode 0:
        Resolution: 3856x2180
        FrameDurationRange: [100000000, 100000008]
        InputBitDepth: 12
        OutputBitDepth: 12
        SensorModeType: SENSOR_MODE_TYPE_BAYER
    SensorMode 1:
        Resolution: 3856x2180
        FrameDurationRange: [33333333, 33333336]
        InputBitDepth: 12
        OutputBitDepth: 12
        SensorModeType: SENSOR_MODE_TYPE_BAYER
    SensorMode 2:
        Resolution: 2608x1964
        FrameDurationRange: [33333333, 33333334]
        InputBitDepth: 12
        OutputBitDepth: 12
        SensorModeType: SENSOR_MODE_TYPE_BAYER
    SensorMode 3:
        Resolution: 1920x1080
        FrameDurationRange: [33333333, 33333334]
        InputBitDepth: 12
        OutputBitDepth: 12
        SensorModeType: SENSOR_MODE_TYPE_BAYER
  ==== CameraDevice 1: imx676_port0_framos ====
    SensorMode 0:
        Resolution: 3552x3556
        FrameDurationRange: [100000000, 100000008]
        InputBitDepth: 12
        OutputBitDepth: 12
        SensorModeType: SENSOR_MODE_TYPE_BAYER
    SensorMode 1:
        Resolution: 3552x3556
        FrameDurationRange: [66666667, 66666668]
        InputBitDepth: 12
        OutputBitDepth: 12
        SensorModeType: SENSOR_MODE_TYPE_BAYER
    SensorMode 2:
        Resolution: 3552x2160
        FrameDurationRange: [40000000, 40000004]
        InputBitDepth: 12
        OutputBitDepth: 12
        SensorModeType: SENSOR_MODE_TYPE_BAYER
""")
        original = SOURCE.read_text()
        original = original.replace("/run/user/", str(self.base / "runtime") + "/")
        original = re.sub(r"(?m)^(\s*(?:export )?PATH=)[^\n]+$",
                          lambda m: m[1] + '"' + str(self.bin) + ':/usr/bin:/bin"',
                          original)
        self.script = self.base / "gst_camera.sh"
        self.script.write_text(original)
        self.script.chmod(0o755)
        self.env = dict(os.environ, PATH=str(self.bin) + ":/usr/bin:/bin",
                        MOCK_CALLS=str(self.calls_path),
                        MOCK_CAMERA_INFO=str(self.camera_info))

    def run_script(self, *args, **environment):
        env = dict(self.env, **environment)
        return subprocess.run(["/bin/sh", str(self.script), *map(str, args)],
                              cwd=self.base, env=env, text=True,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              timeout=4)

    def calls(self, command=None):
        calls = [json.loads(line) for line in self.calls_path.read_text().splitlines()] \
            if self.calls_path.exists() else []
        return [call for call in calls if command is None or call["command"] == command]

    def wayland_socket(self, name="wayland-1"):
        runtime = self.base / "runtime" / "1000"
        runtime.mkdir(parents=True, exist_ok=True)
        endpoint = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        endpoint.bind(str(runtime / name))
        self.addCleanup(endpoint.close)
        return runtime

    def assert_success(self, result):
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def assert_failure(self, result):
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.calls("gst-launch-1.0"), [])

    def dry(self, mode="live", sensor="imx678", *args):
        return self.run_script(mode, "--sensor-id", "0", "--sensor", sensor,
                               "--dry-run", *args, MOCK_FORBID_ALL="1")

    def test_help_does_not_launch_or_enumerate(self):
        self.assert_success(self.run_script("--help", MOCK_FORBID_ALL="1"))
        self.assertEqual(self.calls(), [])

    def test_help_documents_live_fullscreen_option(self):
        result = self.run_script("--help", MOCK_FORBID_ALL="1")
        self.assert_success(result)
        self.assertIn("--fullscreen", result.stdout)
        self.assertEqual(self.calls(), [])

    def test_unknown_mode_rejected(self):
        self.assert_failure(self.run_script("nonsense"))

    def test_unknown_option_rejected(self):
        self.assert_failure(self.run_script("live", "--whoops"))

    def test_list_modes_is_headless_and_only_enumerates_selected_index(self):
        result = self.run_script("--list-modes", "--sensor-id", "0",
                                 DISPLAY="", WAYLAND_DISPLAY="")
        self.assert_success(result)
        self.assertIn("SensorMode 0:", result.stdout)
        self.assertIn("SensorMode 3:", result.stdout)
        self.assertIn("2608x1964", result.stdout)
        self.assertNotIn("3552x3556", result.stdout)
        self.assertEqual([call["command"] for call in self.calls()], ["argus_oneshot"])
        self.assertEqual(self.calls("argus_oneshot")[0]["argv"], ["--listdevices"])

    def test_list_modes_rejects_missing_index(self):
        self.assert_failure(self.run_script("--list-modes", "--sensor-id", "8"))

    def test_list_modes_rejects_empty_device_modes(self):
        self.camera_info.write_text("  ==== CameraDevice 0: ====\n")
        self.assert_failure(self.run_script("--list-modes"))

    def test_list_modes_rejects_capture_and_offline_options(self):
        for options in (("--output", "unused"), ("--frames", "1"),
                        ("--duration", "1"), ("--sensor", "imx678"),
                        ("--sensor-mode", "1"), ("--keep-all",), ("--dry-run",)):
            with self.subTest(options=options):
                self.assert_failure(self.run_script("--list-modes", *options))
        self.assertEqual(self.calls(), [])

    def test_missing_option_values_rejected(self):
        for option in ("--sensor-id", "--sensor", "--sensor-mode", "--output",
                       "--frames", "--duration"):
            with self.subTest(option=option):
                self.assert_failure(self.run_script("live", option))

    def test_invalid_sensor_ids_rejected(self):
        for value in ("-1", "", "1.5", "x", "0;touch injected", "$(touch injected)"):
            with self.subTest(value=value):
                self.assert_failure(self.run_script("live", "--sensor-id", value,
                                                    "--sensor", "imx678", "--dry-run"))
        self.assertFalse((self.base / "injected").exists())

    def test_invalid_sensor_names_rejected(self):
        for sensor in ("imx675", "IMX678", "imx678;touch injected", ""):
            with self.subTest(sensor=sensor):
                self.assert_failure(self.dry("live", sensor))
        self.assertFalse((self.base / "injected").exists())

    def test_invalid_sensor_mode_numbers_rejected(self):
        for value in ("-1", "256", "1.5", "", "x", "2;touch injected"):
            with self.subTest(value=value):
                self.assert_failure(self.dry("capture", "imx678", "--sensor-mode", value))
        self.assertFalse((self.base / "injected").exists())

    def test_duplicate_sensor_mode_rejected(self):
        self.assert_failure(self.dry("capture", "imx678", "--sensor-mode", "1",
                                    "--sensor-mode=2"))

    def test_unsupported_model_mode_pair_rejected_offline(self):
        for sensor, mode in (("imx676", "3"), ("imx676", "4"), ("imx678", "4")):
            with self.subTest(sensor=sensor, mode=mode):
                self.assert_failure(self.dry("capture", sensor, "--sensor-mode", mode))
        self.assertEqual(self.calls(), [])

    def test_invalid_frame_counts_rejected(self):
        for count in ("0", "-1", "1.5", "x", "1;touch injected"):
            with self.subTest(count=count):
                self.assert_failure(self.dry("capture", "imx678", "--frames", count))
        self.assertFalse((self.base / "injected").exists())

    def test_invalid_durations_rejected(self):
        for duration in ("0", "-1", "nan", "1;touch injected"):
            with self.subTest(duration=duration):
                self.assert_failure(self.dry("record", "imx678", "--duration", duration))

    def test_explicit_dry_run_has_no_dependency_calls_or_output_writes(self):
        for mode in ("live", "record", "capture"):
            output = self.base / ("new " + mode + " output")
            with self.subTest(mode=mode):
                result = self.dry(mode, "imx678", "--output", output) \
                    if mode != "live" else self.dry(mode)
                self.assert_success(result)
                self.assertFalse(output.exists())
        self.assertEqual(self.calls(), [])

    def test_explicit_dry_run_works_without_camera_or_gstreamer_dependencies(self):
        for name in ("argus_camera.sh", "argus_camera", "argus_oneshot",
                     "gst-launch-1.0", "gst-inspect-1.0"):
            (self.bin / name).unlink()
        self.assert_success(self.dry())
        self.assertEqual(self.calls(), [])

    def test_native_caps_in_capture_dry_run(self):
        for sensor, width, height in (("imx676", 3552, 3556), ("imx678", 3856, 2180)):
            with self.subTest(sensor=sensor):
                result = self.dry("capture", sensor)
                self.assert_success(result)
                text = result.stdout + result.stderr
                self.assertIn(str(width), text)
                self.assertIn(str(height), text)
                self.assertIn("10/1", text)
                self.assertIn("100", text)

    def test_all_imx678_mode_presets_work_offline(self):
        for mode, width, height, fps in ((0, 3856, 2180, 10),
                                         (1, 3856, 2180, 30),
                                         (2, 2608, 1964, 30),
                                         (3, 1920, 1080, 30)):
            with self.subTest(mode=mode):
                result = self.dry("capture", "imx678", "--sensor-mode", str(mode))
                self.assert_success(result)
                self.assertIn("'sensor-mode=" + str(mode) + "'", result.stdout)
                self.assertIn(f"width={width},height={height},framerate={fps}/1", result.stdout)
                self.assertIn("'num-buffers=" + str(fps * 10) + "'", result.stdout)
        self.assertEqual(self.calls(), [])

    def test_all_imx676_mode_presets_work_offline(self):
        for mode, height, fps in ((0, 3556, 10), (1, 3556, 15), (2, 2160, 25)):
            for operation in ("live", "record", "capture"):
                with self.subTest(mode=mode, operation=operation):
                    result = self.dry(operation, "imx676", "--sensor-mode", mode)
                    self.assert_success(result)
                    self.assertIn(f"'sensor-mode={mode}'", result.stdout)
                    self.assertIn(f"width=3552,height={height},framerate={fps}/1",
                                  result.stdout)
                    if operation == "capture":
                        self.assertIn(f"'num-buffers={fps * 10}'", result.stdout)
        self.assertEqual(self.calls(), [])

    def test_imx676_crop_auto_detects_model_from_mode_zero(self):
        result = self.run_script("capture", "--sensor-id", "1", "--sensor-mode", "2",
                                 "--frames", "1", "--output", self.base / "imx676-crop")
        self.assert_success(result)
        self.assertIn("preset: imx676; sensor-mode: 2; native: 3552x2160 at 25 FPS",
                      result.stdout)
        self.assertIn("sensor-mode=2", self.calls("gst-launch-1.0")[-1]["argv"])

    def test_imx676_extended_recording_counts_selected_rate(self):
        for mode, fps in ((1, 15), (2, 25)):
            with self.subTest(mode=mode):
                result = self.dry("record", "imx676", "--sensor-mode", mode,
                                  "--duration", "3")
                self.assert_success(result)
                self.assertIn(f"'num-buffers={fps * 3}'", result.stdout)
        self.assertEqual(self.calls(), [])

    def test_imx676_crop_preview_and_recording_preserve_aspect(self):
        for operation, scaled in (("live", "width=1184,height=720"),
                                  ("record", "width=1776,height=1080")):
            with self.subTest(operation=operation):
                result = self.dry(operation, "imx676", "--sensor-mode", "2")
                self.assert_success(result)
                self.assertIn("native: 3552x2160", result.stdout)
                self.assertIn(scaled, result.stdout)

    def test_imx676_extended_mode_requires_correct_fixed_rate(self):
        self.camera_info.write_text(self.camera_info.read_text().replace(
            "[66666667, 66666668]", "[33333334, 33333336]"))
        result = self.run_script("capture", "--sensor-id", "1", "--sensor-mode", "1",
                                 "--output", self.base / "bad-imx676-rate")
        self.assert_failure(result)
        self.assertFalse((self.base / "bad-imx676-rate").exists())

    def test_imx676_crop_rejects_wrong_geometry(self):
        self.camera_info.write_text(self.camera_info.read_text().replace(
            "Resolution: 3552x2160", "Resolution: 1776x1080"))
        self.assert_failure(self.run_script("capture", "--sensor-id", "1",
                                            "--sensor-mode", "2", "--output",
                                            self.base / "bad-imx676-geometry"))

    def test_imx676_extended_mode_requires_advertisement(self):
        self.camera_info.write_text(self.camera_info.read_text().split(
            "    SensorMode 1:\n        Resolution: 3552x3556", 1)[0])
        self.assert_failure(self.run_script("capture", "--sensor-id", "1",
                                            "--sensor-mode", "1", "--output",
                                            self.base / "missing-imx676-mode"))

    def test_imx676_crop_root_fullscreen_reexec_retains_mode(self):
        self.wayland_socket()
        result = self.run_script("live", "--sensor-id", "1", "--sensor-mode", "2",
                                 "--fullscreen", MOCK_UID="0", WAYLAND_DISPLAY="")
        self.assert_success(result)
        self.assertEqual(len(self.calls("su")), 1)
        argv = self.calls("gst-launch-1.0")[-1]["argv"]
        self.assertIn("sensor-id=1", argv)
        self.assertIn("sensor-mode=2", argv)
        self.assertIn("fullscreen=true", argv)
        self.assertIn("width=3552,height=2160,framerate=25/1", " ".join(argv))

    def test_explicit_frames_override_thirty_fps_settling_default(self):
        result = self.dry("capture", "imx678", "--sensor-mode", "2", "--frames", "7")
        self.assert_success(result)
        self.assertIn("'num-buffers=7'", result.stdout)
        self.assertNotIn("'num-buffers=300'", result.stdout)

    def test_record_duration_uses_selected_native_frame_rate(self):
        result = self.dry("record", "imx678", "--sensor-mode", "3", "--duration", "3")
        self.assert_success(result)
        self.assertIn("'num-buffers=90'", result.stdout)
        self.assertNotIn("'num-buffers=30'", result.stdout)

    def test_crop_output_sizes_are_distinct_from_native_acquisition(self):
        for operation, mode, native, output in (
                ("live", 2, "2608x1964", "width=1304,height=982"),
                ("record", 2, "2608x1964", "width=1434,height=1080"),
                ("live", 3, "1920x1080", "width=1280,height=720")):
            with self.subTest(operation=operation, mode=mode):
                result = self.dry(operation, "imx678", "--sensor-mode", str(mode))
                self.assert_success(result)
                self.assertIn("native: " + native, result.stdout)
                self.assertIn(output, result.stdout)

    def test_live_scaled_caps(self):
        for sensor, width, height in (("imx676", 720, 720), ("imx678", 1280, 724)):
            with self.subTest(sensor=sensor):
                result = self.dry("live", sensor)
                self.assert_success(result)
                self.assertIn(str(width), result.stdout)
                self.assertIn(str(height), result.stdout)
                native = (3552, 3556) if sensor == "imx676" else (3856, 2180)
                self.assertIn(str(native[0]), result.stdout)
                self.assertIn(str(native[1]), result.stdout)

    def test_live_default_does_not_set_fullscreen_property(self):
        result = self.dry("live", "imx678")
        self.assert_success(result)
        self.assertIn("'waylandsink' 'sync=false'", result.stdout)
        self.assertNotIn("'fullscreen=", result.stdout)
        self.assertEqual(self.calls(), [])

    def test_live_fullscreen_preserves_all_native_sensor_mode_presets(self):
        for sensor, mode, width, height, fps in (
                ("imx676", 0, 3552, 3556, 10),
                ("imx678", 0, 3856, 2180, 10),
                ("imx678", 1, 3856, 2180, 30),
                ("imx678", 2, 2608, 1964, 30),
                ("imx678", 3, 1920, 1080, 30)):
            with self.subTest(sensor=sensor, mode=mode):
                result = self.dry("live", sensor, "--sensor-mode", str(mode),
                                  "--fullscreen")
                self.assert_success(result)
                self.assertIn("'sensor-mode=" + str(mode) + "'", result.stdout)
                self.assertIn(f"width={width},height={height},framerate={fps}/1",
                              result.stdout)
                self.assertIn("'waylandsink' 'sync=false' 'fullscreen=true'",
                              result.stdout)
        self.assertEqual(self.calls(), [])

    def test_fullscreen_repeated_flag_is_idempotent(self):
        result = self.dry("live", "imx678", "--fullscreen", "--fullscreen")
        self.assert_success(result)
        self.assertEqual(result.stdout.count("'fullscreen=true'"), 1)
        self.assertEqual(self.calls(), [])

    def test_fullscreen_with_value_is_not_a_supported_option(self):
        for value in ("true", "false", "", "1;touch injected"):
            with self.subTest(value=value):
                self.assert_failure(self.dry("live", "imx678",
                                             "--fullscreen=" + value))
        self.assertEqual(self.calls(), [])
        self.assertFalse((self.base / "injected").exists())

    def test_fullscreen_rejects_non_live_modes_without_side_effects(self):
        for mode in ("record", "capture", "--list-modes"):
            with self.subTest(mode=mode):
                output = self.base / ("forbidden-fullscreen-" + mode)
                options = ("--output", output) if mode != "--list-modes" else ()
                result = self.run_script(mode, "--fullscreen", *options,
                                         MOCK_FORBID_ALL="1")
                self.assert_failure(result)
                self.assertFalse(output.exists())
        self.assertEqual(self.calls(), [])

    def test_fullscreen_does_not_bypass_invalid_sensor_mode(self):
        self.assert_failure(self.dry("live", "imx676", "--fullscreen",
                                    "--sensor-mode", "3"))
        self.assert_failure(self.dry("live", "imx678", "--fullscreen",
                                     "--sensor-mode", "4"))
        self.assertEqual(self.calls(), [])

    def test_record_scaled_caps(self):
        for sensor, width, height in (("imx676", 1080, 1080), ("imx678", 1920, 1080)):
            with self.subTest(sensor=sensor):
                result = self.dry("record", sensor)
                self.assert_success(result)
                self.assertIn(str(width), result.stdout)
                self.assertIn(str(height), result.stdout)
                native = (3552, 3556) if sensor == "imx676" else (3856, 2180)
                self.assertIn(str(native[0]), result.stdout)
                self.assertIn(str(native[1]), result.stdout)

    def test_existing_record_file_not_overwritten(self):
        output = self.base / "existing.mp4"
        output.write_text("KEEP ME")
        self.assert_failure(self.run_script("record", "--sensor-id", "0", "--sensor",
                                            "imx678", "--output", output))
        self.assertEqual(output.read_text(), "KEEP ME")

    def test_existing_capture_directory_rejected(self):
        output = self.base / "existing-capture"
        output.mkdir()
        marker = output / "existing.jpg"
        marker.write_text("KEEP ME")
        self.assert_failure(self.run_script("capture", "--sensor-id", "0", "--sensor",
                                            "imx678", "--output", output))
        self.assertEqual(marker.read_text(), "KEEP ME")

    def test_record_spaced_path_is_one_argument(self):
        output = self.base / 'video with spaces.mp4'
        result = self.run_script("record", "--sensor-id", "0", "--sensor", "imx678",
                                 "--output", output)
        self.assert_success(result)
        gst = self.calls("gst-launch-1.0")
        self.assertEqual(len(gst), 1)
        self.assertIn("fdsink", gst[0]["argv"])
        self.assertIn("fd=3", gst[0]["argv"])
        self.assertEqual(gst[0]["fd3"], str(output))
        self.assertFalse((self.base / "injected").exists())

    def test_capture_spaced_path_is_one_argument(self):
        output = self.base / 'photos with spaces'
        result = self.run_script("capture", "--sensor-id", "0", "--sensor", "imx678",
                                 "--output", output, "--frames", "7")
        self.assert_success(result)
        gst = self.calls("gst-launch-1.0")
        self.assertEqual(len(gst), 1)
        locations = [arg for arg in gst[0]["argv"] if arg.startswith("location=")]
        self.assertEqual(len(locations), 1)
        self.assertEqual(gst[0]["cwd"], str(output))
        self.assertEqual(locations, ["location=still-%03d.jpg"])
        self.assertIn("num-buffers=7", gst[0]["argv"])
        self.assertFalse((self.base / "injected").exists())

    def test_hostile_path_rejected_or_safely_quoted(self):
        for mode in ("record", "capture"):
            with self.subTest(mode=mode):
                output = self.base / ('hostile-' + mode + ' $(touch injected) ; "quote"')
                result = self.run_script(mode, "--sensor-id", "0", "--sensor", "imx678",
                                         "--output", output)
                if result.returncode == 0:
                    gst = self.calls("gst-launch-1.0")[-1]
                    self.assertFalse(any(str(output) in arg for arg in gst["argv"]),
                                     "user paths must not enter GStreamer grammar")
                    if mode == "record":
                        self.assertEqual(gst["fd3"], str(output))
                    else:
                        self.assertEqual(gst["cwd"], str(output))
                self.assertFalse((self.base / "injected").exists())

    def test_capture_format_string_path_rejected_or_escaped(self):
        output = self.base / "capture-%n-%04d"
        result = self.run_script("capture", "--sensor-id", "0", "--sensor", "imx678",
                                 "--output", output)
        if result.returncode == 0:
            gst = self.calls("gst-launch-1.0")[-1]
            location = next(arg for arg in gst["argv"] if arg.startswith("location="))
            self.assertEqual(location, "location=still-%03d.jpg")
            self.assertEqual(gst["cwd"], str(output))

    def test_dangling_record_symlink_rejected(self):
        output = self.base / "existing-symlink.mp4"
        output.symlink_to(self.base / "not-yet-existing-target")
        self.assert_failure(self.run_script("record", "--sensor-id", "0", "--sensor", "imx678",
                                            "--output", output))
        self.assertTrue(output.is_symlink())

    def test_gstreamer_failure_propagates(self):
        result = self.run_script("capture", "--sensor-id", "0", "--sensor", "imx678",
                                 "--output", self.base / "photos", MOCK_GST_EXIT="23")
        self.assertNotEqual(result.returncode, 0)

    def test_auto_uses_compact_argus_id_not_physical_port(self):
        for sensor_id, width, height in ((0, 3856, 2180), (1, 3552, 3556)):
            with self.subTest(sensor_id=sensor_id):
                result = self.run_script("capture", "--sensor-id", sensor_id,
                                         "--frames", "1", "--output",
                                         self.base / ("auto" + str(sensor_id)))
                self.assert_success(result)
                gst = self.calls("gst-launch-1.0")[-1]
                self.assertIn("sensor-id=" + str(sensor_id), gst["argv"])
                pipeline = " ".join(gst["argv"])
                self.assertIn(str(width), pipeline)
                self.assertIn(str(height), pipeline)

    def test_auto_missing_compact_index_rejected(self):
        self.assert_failure(self.run_script("capture", "--sensor-id", "2",
                                            "--output", self.base / "missing"))

    def test_auto_crop_mode_uses_native_mode_zero_for_model_detection(self):
        result = self.run_script("capture", "--sensor-mode", "2", "--frames", "1",
                                 "--output", self.base / "auto-crop")
        self.assert_success(result)
        self.assertIn("preset: imx678; sensor-mode: 2; native: 2608x1964 at 30 FPS",
                      result.stdout)
        self.assertIn("sensor-mode=2", self.calls("gst-launch-1.0")[-1]["argv"])

    def test_real_explicit_mode_requires_matching_advertisement(self):
        for mode in (0, 1, 2, 3):
            with self.subTest(mode=mode):
                result = self.run_script("capture", "--sensor", "imx678",
                                         "--sensor-mode", str(mode), "--frames", "1",
                                         "--output", self.base / ("explicit-mode-" + str(mode)))
                self.assert_success(result)
                self.assertIn("sensor-mode=" + str(mode),
                              self.calls("gst-launch-1.0")[-1]["argv"])
        self.assertEqual(len(self.calls("argus_oneshot")), 4)

    def test_real_explicit_sensor_does_not_bypass_missing_index(self):
        self.assert_failure(self.run_script("capture", "--sensor", "imx678",
                                            "--sensor-id", "8", "--output", self.base / "none"))
        self.assertFalse((self.base / "none").exists())

    def test_explicit_sensor_must_match_native_mode_zero(self):
        self.assert_failure(self.run_script("capture", "--sensor", "imx676",
                                            "--sensor-id", "0", "--output", self.base / "wrong-model"))

    def test_missing_selected_mode_rejected_even_with_explicit_sensor(self):
        original = self.camera_info.read_text()
        self.camera_info.write_text(re.sub(r"    SensorMode 2:.*?(?=    SensorMode 3:)",
                                           "", original, count=1, flags=re.S))
        self.assert_failure(self.run_script("capture", "--sensor", "imx678",
                                            "--sensor-mode", "2", "--output", self.base / "missing-mode"))
        self.assertFalse((self.base / "missing-mode").exists())

    def test_auto_dry_run_validates_selected_advertised_mode(self):
        self.camera_info.write_text(self.camera_info.read_text().replace(
            "Resolution: 2608x1964", "Resolution: 2600x1964"))
        self.assert_failure(self.run_script("capture", "--sensor-mode", "2", "--dry-run"))

    def test_selected_mode_must_be_expected_raw12_bayer_geometry_and_fps(self):
        original = self.camera_info.read_text()
        header = original.index("    SensorMode 2:")
        end = original.index("    SensorMode 3:", header)
        mode = original[header:end]
        changes = (("2608x1964", "2608x1960"),
                   ("InputBitDepth: 12", "InputBitDepth: 10"),
                   ("OutputBitDepth: 12", "OutputBitDepth: 10"),
                   ("SENSOR_MODE_TYPE_BAYER", "SENSOR_MODE_TYPE_BAYER_PWL"),
                   ("[33333333, 33333334]", "[100000000, 100000008]"),
                   ("[33333333, 33333334]", "[33333333, 100000000]"))
        for index, (before, after) in enumerate(changes):
            with self.subTest(before=before):
                self.camera_info.write_text(original[:header] + mode.replace(before, after) + original[end:])
                self.assert_failure(self.run_script("capture", "--sensor", "imx678",
                                                    "--sensor-mode", "2", "--output",
                                                    self.base / ("invalid-selected-" + str(index))))

    def test_duplicate_selected_mode_is_rejected(self):
        text = self.camera_info.read_text()
        self.camera_info.write_text(text.replace("    SensorMode 3:", "    SensorMode 2:", 1))
        self.assert_failure(self.run_script("capture", "--sensor-mode", "2", "--dry-run"))

    def test_duplicate_duration_field_is_rejected_even_if_one_is_malformed(self):
        text = self.camera_info.read_text().replace(
            "Resolution: 2608x1964\n", "Resolution: 2608x1964\n"
            "        FrameDurationRange: malformed\n", 1)
        self.camera_info.write_text(text)
        self.assert_failure(self.run_script("capture", "--sensor-mode", "2", "--dry-run"))

    def test_fixed_thirty_fps_period_rounding_is_symmetric(self):
        text = self.camera_info.read_text().replace(
            "[33333333, 33333334]", "[33333332, 33333336]")
        self.camera_info.write_text(text)
        self.assert_success(self.run_script("capture", "--sensor-mode", "2", "--dry-run"))

    def test_fixed_thirty_fps_period_outside_rounding_tolerance_is_rejected(self):
        original = self.camera_info.read_text()
        for period in ("[33333322, 33333336]", "[33333332, 33333344]"):
            with self.subTest(period=period):
                self.camera_info.write_text(original.replace("[33333333, 33333334]", period))
                self.assert_failure(self.run_script("capture", "--sensor-mode", "2", "--dry-run"))

    def test_auto_detection_with_busybox_awk(self):
        busybox = shutil.which("busybox")
        if busybox is None:
            self.skipTest("BusyBox is not installed")
        probe = subprocess.run([busybox, "awk", "BEGIN { exit 0 }"],
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               timeout=4)
        if probe.returncode:
            self.skipTest("BusyBox has no awk applet")
        # Run the actual launcher parser with the target's awk family,
        # not just the host's default implementation.
        wrapper = self.bin / "awk"
        wrapper.write_text('#!/bin/sh\nexec "' + busybox + '" awk "$@"\n')
        wrapper.chmod(0o755)
        for sensor_id, model in ((0, "imx678"), (1, "imx676")):
            with self.subTest(sensor_id=sensor_id):
                result = self.run_script("capture", "--sensor-id", sensor_id,
                                         "--dry-run")
                self.assert_success(result)
                self.assertIn("preset: " + model, result.stdout)
        for mode in (1, 2, 3):
            with self.subTest(sensor_mode=mode):
                result = self.run_script("capture", "--sensor-mode", str(mode), "--dry-run")
                self.assert_success(result)
                self.assertIn("at 30 FPS", result.stdout)
        self.camera_info.write_text(self.camera_info.read_text().replace(
            "[100000000, 100000008]", "[200000000, 200000008]"))
        self.assert_failure(self.run_script("capture", "--dry-run"))

    def test_auto_unknown_native_geometry_rejected(self):
        text = self.camera_info.read_text().replace("3856x2180", "3840x2160")
        self.camera_info.write_text(text)
        self.assert_failure(self.run_script("capture", "--sensor-id", "0",
                                            "--output", self.base / "mismatch"))

    def test_auto_enumeration_failure_propagates(self):
        self.assert_failure(self.run_script("capture", "--sensor-id", "0",
                                            "--output", self.base / "failed-info",
                                            MOCK_INFO_EXIT="7"))

    def test_auto_mode0_must_be_twelve_bit_bayer_at_ten_fps(self):
        original = self.camera_info.read_text()
        replacements = (("InputBitDepth: 12", "InputBitDepth: 10"),
                        ("OutputBitDepth: 12", "OutputBitDepth: 10"),
                        ("SENSOR_MODE_TYPE_BAYER", "SENSOR_MODE_TYPE_BAYER_PWL"),
                        ("[100000000, 100000008]", "[200000000, 200000008]"))
        for index, (before, after) in enumerate(replacements):
            with self.subTest(before=before):
                self.camera_info.write_text(original.replace(before, after, 1))
                self.assert_failure(self.run_script("capture", "--sensor-id", "0",
                                                    "--output", self.base / ("badmode" + str(index))))

    def test_decimal_leading_zeros_are_normalized(self):
        result = self.run_script("record", "--sensor", "imx678", "--sensor-id", "000",
                                 "--duration", "003", "--output", self.base / "decimal.mp4")
        self.assert_success(result)
        argv = self.calls("gst-launch-1.0")[-1]["argv"]
        self.assertIn("sensor-id=0", argv)
        self.assertIn("num-buffers=30", argv)

    def test_capture_default_keeps_latest_only(self):
        self.assert_success(self.run_script("capture", "--sensor", "imx678",
                                            "--output", self.base / "latest"))
        self.assertIn("max-files=1", self.calls("gst-launch-1.0")[-1]["argv"])

    def test_capture_keep_all_disables_rotation(self):
        self.assert_success(self.run_script("capture", "--sensor", "imx678", "--keep-all",
                                            "--output", self.base / "all"))
        self.assertIn("max-files=0", self.calls("gst-launch-1.0")[-1]["argv"])

    def test_record_duration_counts_frames_after_camera_startup(self):
        for duration in (1, 3, 86400):
            with self.subTest(duration=duration):
                self.assert_success(self.run_script(
                    "record", "--sensor", "imx678", "--duration", duration,
                    "--output", self.base / (str(duration) + "-seconds.mp4")))
                argv = self.calls("gst-launch-1.0")[-1]["argv"]
                self.assertIn("num-buffers=" + str(duration * 10), argv)
                self.assertFalse(any(arg.startswith("timeout=") for arg in argv))

    def test_out_of_range_numbers_rejected(self):
        for mode, option, value in (("live", "--sensor-id", "256"),
                                    ("capture", "--frames", "1000001"),
                                    ("record", "--duration", "86401")):
            with self.subTest(option=option):
                self.assert_failure(self.run_script(mode, "--sensor", "imx678", option,
                                                    value, "--dry-run"))

    def test_mode_specific_options_rejected(self):
        for mode, options in (("live", ["--output", "no"]),
                               ("live", ["--frames", "1"]),
                               ("live", ["--duration", "1"]),
                               ("live", ["--keep-all"]),
                               ("record", ["--frames", "1"]),
                               ("record", ["--keep-all"]),
                               ("capture", ["--duration", "1"])):
            with self.subTest(mode=mode, options=options):
                self.assert_failure(self.run_script(mode, "--sensor", "imx678",
                                                    "--dry-run", *options))

    def test_live_uses_one_actual_wayland_socket(self):
        runtime = self.wayland_socket()
        (runtime / "wayland-1.lock").touch()
        self.assert_success(self.run_script("live", "--sensor", "imx678",
                                            XDG_RUNTIME_DIR=str(runtime), WAYLAND_DISPLAY=""))
        self.assertEqual(len(self.calls("gst-launch-1.0")), 1)

    def test_live_fullscreen_reaches_real_nonroot_pipeline(self):
        runtime = self.wayland_socket()
        result = self.run_script("live", "--sensor-id", "0", "--sensor-mode", "3",
                                 "--fullscreen", XDG_RUNTIME_DIR=str(runtime),
                                 WAYLAND_DISPLAY="")
        self.assert_success(result)
        gst = self.calls("gst-launch-1.0")
        self.assertEqual(len(gst), 1)
        self.assertIn("sensor-id=0", gst[0]["argv"])
        self.assertIn("sensor-mode=3", gst[0]["argv"])
        self.assertEqual(gst[0]["argv"][-3:],
                         ["waylandsink", "sync=false", "fullscreen=true"])
        self.assertEqual(self.calls("su"), [])

    def test_live_ambiguous_wayland_socket_rejected(self):
        runtime = self.wayland_socket("wayland-0")
        self.wayland_socket("wayland-1")
        self.assert_failure(self.run_script("live", "--sensor", "imx678",
                                            XDG_RUNTIME_DIR=str(runtime), WAYLAND_DISPLAY=""))

    def test_live_missing_display_rejected(self):
        self.assert_failure(self.run_script("live", "--sensor", "imx678",
                                            XDG_RUNTIME_DIR=str(self.base), WAYLAND_DISPLAY=""))

    def test_live_explicit_display_resolves_ambiguity(self):
        runtime = self.wayland_socket("wayland-0")
        self.wayland_socket("wayland-1")
        self.assert_success(self.run_script("live", "--sensor", "imx678",
                                            XDG_RUNTIME_DIR=str(runtime), WAYLAND_DISPLAY="wayland-1"))

    def test_live_root_reexec_retains_sensor_id_and_preset(self):
        self.wayland_socket()
        result = self.run_script("live", "--sensor-id", "1", "--sensor", "imx676",
                                 MOCK_UID="0", XDG_RUNTIME_DIR="ignored-root-runtime",
                                 WAYLAND_DISPLAY="")
        self.assert_success(result)
        self.assertEqual(len(self.calls("su")), 1)
        gst = self.calls("gst-launch-1.0")
        self.assertEqual(len(gst), 1)
        self.assertIn("sensor-id=1", gst[0]["argv"])
        self.assertIn("3552", " ".join(gst[0]["argv"]))

    def test_live_root_reexec_retains_selected_crop_mode(self):
        self.wayland_socket()
        result = self.run_script("live", "--sensor-id", "0", "--sensor", "imx678",
                                 "--sensor-mode", "2", MOCK_UID="0",
                                 XDG_RUNTIME_DIR="ignored-root-runtime", WAYLAND_DISPLAY="")
        self.assert_success(result)
        self.assertEqual(len(self.calls("su")), 1)
        gst = self.calls("gst-launch-1.0")
        self.assertEqual(len(gst), 1)
        self.assertIn("sensor-mode=2", gst[0]["argv"])
        self.assertIn("width=2608,height=1964,framerate=30/1", " ".join(gst[0]["argv"]))
        self.assertIn("width=1304,height=982", " ".join(gst[0]["argv"]))

    def test_live_root_reexec_retains_fullscreen_id_model_and_mode(self):
        self.wayland_socket()
        for sensor_id, sensor, mode in ((1, "imx676", 0), (0, "imx678", 2)):
            with self.subTest(sensor_id=sensor_id, sensor=sensor, mode=mode):
                before = len(self.calls("gst-launch-1.0"))
                result = self.run_script(
                    "live", "--sensor-id", sensor_id, "--sensor", sensor,
                    "--sensor-mode", mode, "--fullscreen", MOCK_UID="0",
                    XDG_RUNTIME_DIR="ignored-root-runtime", WAYLAND_DISPLAY="")
                self.assert_success(result)
                gst = self.calls("gst-launch-1.0")
                self.assertEqual(len(gst), before + 1)
                self.assertIn("sensor-id=" + str(sensor_id), gst[-1]["argv"])
                self.assertIn("sensor-mode=" + str(mode), gst[-1]["argv"])
                self.assertEqual(gst[-1]["argv"][-3:],
                                 ["waylandsink", "sync=false", "fullscreen=true"])
                self.assertIn("preset: " + sensor, result.stdout)
        self.assertEqual(len(self.calls("su")), 2)

    def test_plugin_failure_does_not_create_outputs(self):
        for mode in ("record", "capture"):
            with self.subTest(mode=mode):
                output = self.base / ("missing-plugin-" + mode)
                self.assert_failure(self.run_script(mode, "--sensor", "imx678", "--output", output,
                                                    MOCK_INSPECT_EXIT="9"))
                self.assertFalse(output.exists())

    def test_record_creation_race_does_not_overwrite(self):
        output = self.base / "record-race.mp4"
        self.assert_failure(self.run_script("record", "--sensor", "imx678", "--output", output,
                                            MOCK_RACE_FILE=str(output)))
        self.assertEqual(output.read_text(), "THIRD PARTY")

    def test_capture_creation_race_does_not_enter_existing_directory(self):
        output = self.base / "capture-race"
        self.assert_failure(self.run_script("capture", "--sensor", "imx678", "--output", output,
                                            MOCK_RACE_DIR=str(output)))
        self.assertEqual((output / "existing.jpg").read_text(), "THIRD PARTY")


if __name__ == "__main__":
    unittest.main(verbosity=2)
