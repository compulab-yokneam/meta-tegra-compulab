#!/usr/bin/env python3
"""Offline safety/fixture tests. Never executes a camera or modifies an SDK."""
from pathlib import Path
import os
import shlex
import subprocess
import tempfile
import unittest

BUNDLE = Path(__file__).resolve().parents[1]


class RuntimeBundleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        (BUNDLE / "scratch").mkdir(exist_ok=True)

    def run_script(self, name, *args, env=None):
        return subprocess.run(["bash", str(BUNDLE / name), *map(str, args)],
                              capture_output=True, text=True, env=env)

    def camera_fixture(self, *args, sku=None, model=None, boot=None, compatible=None):
        """Replace only fixed metadata paths in an isolated script copy."""
        with tempfile.TemporaryDirectory(dir=BUNDLE / "scratch") as directory:
            root = Path(directory)
            dt = root / "device-tree"
            dt.mkdir()
            if sku is not None:
                compatible = [f"nvidia,p3768-0000+p3767-{sku}-super",
                              f"nvidia,p3767-{sku}", "nvidia,tegra234"]
            if compatible is not None:
                (dt / "compatible").write_bytes(
                    b"\0".join(value.encode() for value in compatible) + b"\0")
            if model is not None:
                (dt / "model").write_bytes(model.encode() + b"\0")
            control = root / "nv_boot_control.conf"
            if boot is not None:
                control.write_text(boot)
            source = (BUNDLE / "files/gst_camera.sh").read_text()
            anchor = "platform_class /proc/device-tree /etc/nv_boot_control.conf"
            self.assertEqual(source.count(anchor), 1)
            source = source.replace(anchor,
                f"platform_class {shlex.quote(str(dt))} {shlex.quote(str(control))}")
            script = root / "gst_camera.sh"
            script.write_text(source)
            output = root / "record $(touch NOT_EXECUTED); quoted.mp4"
            result = subprocess.run(["sh", str(script), *args,
                                     "--sensor", "imx676", "--dry-run",
                                     *([] if args[0] != "record" else
                                       ["--output", str(output)])],
                                    capture_output=True, text=True)
            self.assertFalse(output.exists(), "dry-run must not create output")
            self.assertFalse((root / "NOT_EXECUTED").exists())
            return result

    def test_default_action_is_read_only_bundle_check(self):
        result = self.run_script("runtime-port.sh")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("no runtime rootfs was audited", result.stdout)

    def test_gst_default_is_check(self):
        result = self.run_script("gst-port.sh")
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_cross_build_default_is_check(self):
        result = self.run_script("cross-build-argus.sh")
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_cross_plugin_default_is_check(self):
        result = self.run_script("cross-build-gst.sh")
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_invalid_mode_switch_rejected(self):
        result = self.run_script("runtime-port.sh", "check", "--imx676-extended", "yes")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("must be 0 or 1", result.stderr)

    def test_invalid_argus_suite_rejected(self):
        result = self.run_script("cross-build-argus.sh", "check", "--suite", "unknown")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("minimal or full", result.stderr)

    def test_full_argus_manifest_has_exactly_23_unique_basenames(self):
        names = (BUNDLE / "files/argus-full-suite.txt").read_text().splitlines()
        self.assertEqual(len(names), 23)
        self.assertEqual(len(set(names)), 23)
        self.assertTrue(all(name.startswith("argus_") and "/" not in name for name in names))

    def test_staging_running_host_is_rejected(self):
        result = self.run_script("runtime-port.sh", "stage", "--rootfs", "/",
                                 "--work-dir", BUNDLE)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("never the running host", result.stderr)

    def test_stage_requires_explicit_arguments(self):
        result = self.run_script("runtime-port.sh", "stage")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("stage needs", result.stderr)

    @unittest.skipUnless(os.uname().machine != "aarch64", "x86 refusal fixture")
    def test_native_build_refuses_x86_without_creating_workdir(self):
        with tempfile.TemporaryDirectory(dir=BUNDLE / "scratch") as directory:
            work = Path(directory) / "must-not-exist"
            result = self.run_script("runtime-port.sh", "build", "--work-dir", work)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("aarch64", result.stderr)
            self.assertFalse(work.exists())

    @unittest.skipUnless(os.uname().machine != "aarch64", "x86 refusal fixture")
    def test_native_plugin_build_refuses_x86(self):
        with tempfile.TemporaryDirectory(dir=BUNDLE / "scratch") as directory:
            work = Path(directory) / "must-not-exist"
            result = self.run_script("gst-port.sh", "build", "--work-dir", work)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("aarch64", result.stderr)
            self.assertFalse(work.exists())

    @unittest.skipUnless((BUNDLE / "sources").is_dir(),
                         "recipe assembles licensed fetched sources before build")
    def test_explicit_gst_prepare_applies_runtime_patches(self):
        with tempfile.TemporaryDirectory(dir=BUNDLE / "scratch") as directory:
            work = Path(directory) / "source-work"
            result = self.run_script("gst-port.sh", "prepare", "--work-dir", work)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("not compiled", result.stdout)
            caps = (work / "source/gst-nvvidconv/gstnvvconv.c").read_text()
            self.assertIn("gst_caps_filter_and_map_in_place", caps)

    def test_rootfs_package_audit_fails_closed_without_runtime(self):
        with tempfile.TemporaryDirectory(dir=BUNDLE / "scratch") as directory:
            root = Path(directory)
            (root / "etc").mkdir()
            (root / "etc/os-release").write_text('ID=ubuntu\nVERSION_ID="24.04"\n')
            (root / "var/lib/dpkg").mkdir(parents=True)
            (root / "var/lib/dpkg/status").write_text("")
            result = self.run_script("runtime-port.sh", "check", "--rootfs", root)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("nvidia-l4t-gstreamer", result.stderr)
            self.assertIn("runtime dependencies incomplete", result.stderr)

    def test_rootfs_package_audit_accepts_complete_metadata_fixture(self):
        with tempfile.TemporaryDirectory(dir=BUNDLE / "scratch") as directory:
            root = Path(directory)
            (root / "etc").mkdir()
            (root / "etc/os-release").write_text('ID=ubuntu\nVERSION_ID="24.04"\n')
            (root / "var/lib/dpkg").mkdir(parents=True)
            packages = {
                name: "39.2.1-20260806224157" for name in
                ("nvidia-l4t-camera", "nvidia-l4t-gstreamer", "nvidia-l4t-multimedia")
            }
            packages.update({name: "1.0" for name in (
                "gstreamer1.0-tools", "gstreamer1.0-plugins-good",
                "gstreamer1.0-plugins-bad", "gstreamer1.0-plugins-ugly",
                "libx264-164", "libgtk-3-0t64", "libx11-6")})
            status = "".join(
                "Package: %s\nStatus: install ok installed\nArchitecture: arm64\n"
                "Version: %s\nMaintainer: Fixture <nobody@example.invalid>\n"
                "Description: fixture only\n\n" % item for item in packages.items())
            (root / "var/lib/dpkg/status").write_text(status)
            result = self.run_script("runtime-port.sh", "check", "--rootfs", root)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("not GPU qualification", result.stdout)

    def test_all_sensor_presets_keep_offline_dry_run(self):
        for sensor, modes in (("imx676", 3), ("imx678", 4)):
            for mode in range(modes):
                with self.subTest(sensor=sensor, mode=mode):
                    result = self.run_script("files/gst_camera.sh", "capture",
                                             "--sensor", sensor, "--sensor-mode", mode,
                                             "--dry-run")
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertIn("sensor-mode=%d" % mode, result.stdout)

    def test_encoder_auto_selects_software_for_both_nano_skus(self):
        for sku in ("0003", "0004"):
            with self.subTest(sku=sku):
                result = self.camera_fixture("record", sku=sku)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn("Recording encoder: software", result.stdout)
                self.assertIn("video/x-raw,format=I420", result.stdout)
                self.assertIn("'x264enc' 'bitrate=8000'", result.stdout)
                self.assertNotIn("'nvv4l2h264enc'", result.stdout)

    def test_encoder_auto_keeps_hardware_on_both_nx_skus(self):
        for sku in ("0000", "0001"):
            with self.subTest(sku=sku):
                result = self.camera_fixture("record", sku=sku)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn("Recording encoder: hardware", result.stdout)
                self.assertIn("video/x-raw(memory:NVMM),format=NV12,width=1080", result.stdout)
                self.assertIn("'nvv4l2h264enc' 'bitrate=8000000'", result.stdout)
                self.assertNotIn("'x264enc'", result.stdout)

    def test_nano_rejects_hardware_without_considering_plugin_presence(self):
        result = self.camera_fixture("record", "--encoder", "hardware", sku="0003")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Nano has no NVENC engine", result.stderr)

    def test_unknown_auto_platform_fails_before_output(self):
        result = self.camera_fixture("record")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("--encoder software", result.stderr)

    def test_explicit_encoders_permit_unknown_platform_offline(self):
        for encoder in ("software", "hardware"):
            with self.subTest(encoder=encoder):
                result = self.camera_fixture("record", "--encoder", encoder)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn(f"Recording encoder: {encoder}", result.stdout)

    def test_nx_can_explicitly_choose_software(self):
        result = self.camera_fixture("record", "--encoder=software", sku="0000")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("'x264enc'", result.stdout)

    def test_read_only_boot_control_fallback_detects_nano(self):
        for key in ("TNSPEC", "COMPATIBLE_SPEC"):
            with self.subTest(key=key):
                result = self.camera_fixture("record", boot=f"{key} 3767--0004--1--edge-ai-nano\n")
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn("Recording encoder: software", result.stdout)

    def test_model_fallback_detects_nx_and_nano(self):
        for model, encoder in (("NVIDIA Jetson Orin NX EdgeAI-ORN", "hardware"),
                               ("NVIDIA Jetson Orin Nano EdgeAI-ORN", "software")):
            with self.subTest(model=model):
                result = self.camera_fixture("record", model=model)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn(f"Recording encoder: {encoder}", result.stdout)

    def test_conflicting_dt_and_boot_metadata_does_not_guess_encoder(self):
        result = self.camera_fixture("record", sku="0000", boot="TNSPEC 3767--0003--1--edge-ai\n")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("unambiguous", result.stderr)

    def test_conflicting_dt_skus_and_model_are_rejected(self):
        for metadata in (
            {"compatible": ["nvidia,p3767-0000", "nvidia,p3767-0004"]},
            {"sku": "0000", "model": "NVIDIA Jetson Orin Nano"},
            {"sku": "9999"},
        ):
            with self.subTest(metadata=metadata):
                result = self.camera_fixture("record", **metadata)
                self.assertNotEqual(result.returncode, 0)

    def test_software_duration_bounds_sensor_frames_and_preserves_mux(self):
        result = self.camera_fixture("record", "--encoder", "software", "--duration", "2")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("'num-buffers=20'", result.stdout)
        self.assertIn("'speed-preset=ultrafast' 'tune=zerolatency'", result.stdout)
        self.assertIn("'h264parse' '!' 'mp4mux' '!' 'fdsink' 'fd=3'", result.stdout)

    def test_encoder_is_record_only_and_validated(self):
        for args in (("live", "--encoder", "software"),
                     ("capture", "--encoder", "hardware"),
                     ("record", "--encoder", "invalid"),
                     ("record", "--encoder", "software", "--encoder", "hardware")):
            with self.subTest(args=args):
                result = self.camera_fixture(*args)
                self.assertNotEqual(result.returncode, 0)

    def test_unknown_platform_fullscreen_live_is_unchanged(self):
        result = self.camera_fixture("live", "--fullscreen")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("'waylandsink' 'sync=false' 'fullscreen=true'", result.stdout)

    @unittest.skipIf(os.geteuid() == 0, "uses the calling non-root desktop branch")
    def test_desktop_helper_keeps_arguments_literal(self):
        env = dict(os.environ, DISPLAY=":fixture")
        marker = 'literal $(touch SHOULD_NOT_EXIST); quoted text'
        result = self.run_script("files/edge-ai-desktop-exec", "--x11",
                                 "printf", "%s", marker, env=env)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, marker)

    @unittest.skipIf(os.geteuid() == 0, "uses the calling non-root desktop branch")
    def test_missing_x11_session_is_not_guessed(self):
        env = dict(os.environ)
        env.pop("DISPLAY", None)
        result = self.run_script("files/edge-ai-desktop-exec", "--x11", "true", env=env)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("run from the desktop", result.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
