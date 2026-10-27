#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Temporary-only simple payload fixtures; no SDK/rootfs installation."""
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import struct
import tempfile
import unittest
import uuid


DIRECTORY = Path(__file__).resolve().parents[1]
LAYER = DIRECTORY.parents[1]
SDK_FILES = DIRECTORY.parent / "edge-ai-sdk-manager/files"
SPEC = importlib.util.spec_from_file_location(
    "data_payloads_under_test", DIRECTORY / "files/build-data-payloads.py")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def capsule(version=0x00270201, lowest=0x00270201,
            guid="bf0d4599-20d4-414e-b2c5-3595b1cda402"):
    """Valid structural FMP fixture, deliberately not flashable firmware."""
    certificate = struct.pack("<IHH16s", 24, 0x0200, 0x0EF1,
                              uuid.UUID("4aafd29d-68df-49ee-8aa9-347d375665a7").bytes_le)
    payload = struct.pack("<Q", 1) + certificate + struct.pack(
        "<4sIII", b"MSS1", 16, version, lowest) + b"non-flashable test fixture"
    image = struct.pack("<I16sB3sIIQQ", 3, uuid.UUID(guid).bytes_le,
                        1, b"\0" * 3, len(payload), 0, 0, 1)
    management = struct.pack("<IHHQ", 1, 0, 1, 16)
    total = 32 + len(management) + len(image) + len(payload)
    header = struct.pack("<16sIII", uuid.UUID(
        "6dcbd5ed-e82d-4c44-bda1-7194199ad92a").bytes_le, 32, 0, total) + b"\0" * 4
    return header + management + image + payload


def snapshot(directory):
    return {path.relative_to(directory).as_posix():
            ("link", str(path.readlink())) if path.is_symlink() else
            ("file", path.read_bytes(), path.stat().st_mode)
            for path in directory.rglob("*") if path.is_symlink() or path.is_file()}


class DataPayloadTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="edge-ai-data-payload-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.sources = self.root / "sources"
        self.sources.mkdir()
        shutil.copytree(SDK_FILES / "sdk-source", self.sources / "sdk-source",
                        ignore=shutil.ignore_patterns("__pycache__"))
        for name in ("runtime-assets.json", "package-rootfs.py"):
            shutil.copyfile(SDK_FILES / name, self.sources / name)
        for name in ("edge-ai-uefi-update", "apply-uefi-capsule"):
            shutil.copyfile(LAYER / "recipes-bsp/uefi/edge-ai-uefi-update-capsules" / name,
                            self.sources / name)
        self.bundle = self.sources / "runtime"
        shutil.copytree(SDK_FILES / "runtime", self.bundle,
                        ignore=shutil.ignore_patterns("__pycache__", "scratch"))
        self.sdk = self.root / "SDK"
        self.sdk.mkdir()
        backup = self.sdk / "vendor-backup"
        self.vendor_menu = backup / "rootfs/boot/extlinux/extlinux.conf"
        self.vendor_menu.parent.mkdir(parents=True)
        self.vendor_menu.write_text("DEFAULT primary\nTIMEOUT 30\nLABEL primary\n"
                                    "  LINUX /boot/Image\n  INITRD /boot/initrd\n"
                                    "  APPEND ${cbootargs} console=tty0\n")
        self.baseline = dict(vendor_backup=str(backup), sha256={
            "rootfs/boot/extlinux/extlinux.conf": MODULE.digest(self.vendor_menu)})
        (self.sdk / "SDK_BASELINE.json").write_text(json.dumps(self.baseline))
        stale = self.sdk / "rootfs/usr/sbin/edge-ai-uefi-update"
        stale.parent.mkdir(parents=True)
        stale.write_text("STALE SDK CUSTOM FILE MUST NOT BE PACKAGED\n")
        self.deploy = self.root / "deploy"
        self.capsules = self.deploy / "edge-ai-uefi-update-capsules"
        self.capsules.mkdir(parents=True)
        for machine in MODULE.MACHINES:
            for style in MODULE.STYLES:
                (self.capsules / f"{machine}-uefi-{style}.cap").write_bytes(capsule())
        self.rehash_capsules()
        manifest = json.loads((self.sources / "runtime-assets.json").read_text())
        self.assets = {row["id"]: LAYER / "recipes-multimedia/argus/files" / row["path"]
                       for row in manifest["assets"] if row.get("role") == "nito"}
        self.config = dict(component="camera-support", sources=self.sources,
                           bundle=self.bundle, sdk=self.sdk, deploy=self.deploy,
                           assets=self.assets, imx676_extended="1", imx678_extended="0",
                           version="39.2.1+compulab1", versions={}, jobs=2)
        self.run = self.root / "run"
        self.run.mkdir()

    def rehash_capsules(self):
        (self.capsules / "SHA256SUMS").write_text("".join(
            MODULE.digest(path) + "  " + path.name + "\n"
            for path in sorted(self.capsules.glob("*.cap"))))

    def build(self, component, **changes):
        return MODULE.build_payload(dict(self.config, component=component, **changes), self.run)

    def test_camera_default_profiles_are_current_selected_sources_with_stable_names(self):
        before = snapshot(self.sdk)
        payload, metadata = self.build("camera-support")
        for sensor, identity in (("676", "nito676ext"), ("678", "nito678")):
            path = payload / f"var/nvidia/nvcam/settings/edgedes-imx{sensor}-demo.nito"
            self.assertEqual(MODULE.digest(path), MODULE.digest(self.assets[identity]))
        self.assertEqual(snapshot(self.sdk), before)
        self.assertEqual(metadata["package_overrides"]["conffiles"], ["/" + MODULE.DROPIN])
        self.assertIn("edge-ai-desktop-exec", (payload / "opt/compulab/bin/argus_camera.sh").read_text())
        self.assertFalse(any(path.name.endswith("extended-demo.nito") for path in payload.rglob("*")))

    def test_camera_alternate_profiles_and_nito_selection_render_without_tokens(self):
        payload, _ = self.build("camera-support", imx676_extended="0",
                                imx678_extended="1", nito_selection="per-camera")
        for sensor, identity in (("676", "nito676"), ("678", "nito678ext")):
            path = payload / f"var/nvidia/nvcam/settings/edgedes-imx{sensor}-demo.nito"
            self.assertEqual(MODULE.digest(path), MODULE.digest(self.assets[identity]))
        self.assertIn('nito_selection_requested="per-camera"',
                      (payload / "usr/libexec/edge-ai-argus-framos-demo-check").read_text())
        for relative in (MODULE.DROPIN, "usr/libexec/edge-ai-argus-framos-demo-check"):
            self.assertNotIn("@", (payload / relative).read_text())

    def test_camera_bad_selected_nito_fails_before_creating_payload(self):
        bad = self.root / "bad.nito"
        bad.write_bytes(b"wrong NITO")
        assets = dict(self.assets, nito676ext=bad)
        with self.assertRaisesRegex(ValueError, "checksum"):
            self.build("camera-support", assets=assets)
        self.assertFalse((self.run / "payload").exists())

    def test_camera_rejects_invalid_extended_flag(self):
        with self.assertRaises(ValueError):
            self.build("camera-support", imx676_extended="yes")

    def test_camera_rejects_unrecognized_nito_selection(self):
        with self.assertRaises(ValueError):
            self.build("camera-support", nito_selection="guess")

    def test_camera_provenance_changes_with_profile_without_writing_sources(self):
        before = snapshot(self.sources)
        first = MODULE.input_provenance(self.config)
        second = MODULE.input_provenance(dict(self.config, imx678_extended="1"))
        self.assertNotEqual(first, second)
        self.assertEqual(snapshot(self.sources), before)

    def test_boot_menu_preserves_verified_vendor_primary_and_adds_current_source_labels(self):
        before = snapshot(self.sdk)
        payload, metadata = self.build("boot-tools")
        menu = (payload / "boot/extlinux/extlinux.conf").read_text()
        self.assertTrue(menu.startswith(self.vendor_menu.read_text().rstrip()))
        self.assertIn("# CompuLab camera entries below", menu)
        self.assertIn("LABEL camera-imx676", menu)
        self.assertIn("LABEL camera-imx678", menu)
        self.assertEqual(metadata["package_overrides"]["conffiles"], ["/boot/extlinux/extlinux.conf"])
        updater = (payload / "usr/sbin/edge-ai-uefi-update").read_text()
        self.assertNotIn("STALE SDK", updater)
        self.assertIn('/usr/share/compulab/uefi-update-capsules', updater)
        self.assertNotIn("@CAPSULE_DIR@", updater)
        self.assertEqual(snapshot(self.sdk), before)

    def test_boot_menu_rejects_modified_vendor_baseline(self):
        self.vendor_menu.write_text(self.vendor_menu.read_text() + "modified\n")
        with self.assertRaisesRegex(ValueError, "checksum"):
            self.build("boot-tools")
        self.assertFalse((self.run / "payload").exists())

    def test_boot_menu_rejects_duplicate_source_labels(self):
        sample = self.sources / "sdk-source/compulab/rootfs/boot/extlinux/extlinux.conf.imx67x.sample"
        sample.write_text(sample.read_text() + "\nLABEL primary\n LINUX /boot/Image\n")
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            self.build("boot-tools")

    def test_boot_baseline_backup_must_remain_confined_to_reference_sdk(self):
        self.baseline["vendor_backup"] = str(self.root)
        (self.sdk / "SDK_BASELINE.json").write_text(json.dumps(self.baseline))
        with self.assertRaises(ValueError):
            self.build("boot-tools")

    def test_policy_payload_has_only_desired_state_and_exact_pins_no_private_hold_state(self):
        payload, metadata = self.build("bsp-policy")
        files = {path.relative_to(payload).as_posix() for path in payload.rglob("*") if path.is_file()}
        self.assertEqual(files, {MODULE.POLICY_CONFIG, MODULE.POLICY_PREFERENCES, MODULE.POLICY_HELPER})
        policy = json.loads((payload / MODULE.POLICY_CONFIG).read_text())
        self.assertEqual(policy["l4t_version"], "39.2.1")
        self.assertEqual(len(policy["hold_packages"]), 16)
        pins = (payload / MODULE.POLICY_PREFERENCES).read_text()
        self.assertIn("Package: nvidia-l4t-kernel\nPin: version " + MODULE.KERNEL_VERSION, pins)
        self.assertIn("Package: nvidia-l4t-kernel-partitions\nPin: version " + MODULE.NVIDIA_VERSION, pins)
        self.assertEqual(metadata["package_overrides"]["conffiles"],
                         ["/" + MODULE.POLICY_CONFIG, "/" + MODULE.POLICY_PREFERENCES])
        scripts = metadata["package_overrides"]["scripts"]
        self.assertIn("bsp-policy configure", scripts["postinst"])
        self.assertIn("bsp-policy restore-config", scripts["prerm"])
        for script in scripts.values():
            self.assertNotIn("apt-mark", script)
            self.assertNotIn("--set-selections", script)
            self.assertNotIn("reboot", script)

    def test_capsules_have_all12_current_machine_style_payloads_and_fresh_helper(self):
        before = snapshot(self.deploy)
        payload, metadata = self.build("uefi-capsules")
        directory = payload / "usr/share/compulab/uefi-update-capsules"
        self.assertEqual(len(list(directory.glob("*.cap"))), 12)
        self.assertEqual(metadata["provenance"]["capsule_count"], 12)
        self.assertEqual((directory / "apply-uefi-capsule").read_bytes(),
                         (self.sources / "apply-uefi-capsule").read_bytes())
        for line in (directory / "SHA256SUMS").read_text().splitlines():
            checksum, name = line.split("  ")
            self.assertEqual(MODULE.digest(directory / name), checksum)
        self.assertEqual(snapshot(self.deploy), before)

    def test_capsules_reject_stale_version_even_with_updated_checksums(self):
        path = next(self.capsules.glob("*.cap"))
        path.write_bytes(capsule(version=0x00270100, lowest=0x00270100))
        self.rehash_capsules()
        with self.assertRaisesRegex(ValueError, "Stale"):
            self.build("uefi-capsules")

    def test_capsules_require_all_machine_style_identities_not_arbitrary_twelve(self):
        path = next(self.capsules.glob("*.cap"))
        path.rename(self.capsules / "unrelated.cap")
        self.rehash_capsules()
        with self.assertRaises(ValueError):
            self.build("uefi-capsules")

    def test_capsules_reject_payload_tampering_without_rehash(self):
        path = next(self.capsules.glob("*.cap"))
        path.write_bytes(capsule(lowest=0x00270100))
        with self.assertRaisesRegex(ValueError, "checksum"):
            self.build("uefi-capsules")

    def test_capsules_reject_inconsistent_current_fmp_guid(self):
        path = next(self.capsules.glob("*.cap"))
        path.write_bytes(capsule(guid="12345678-1234-1234-1234-123456789abc"))
        self.rehash_capsules()
        with self.assertRaisesRegex(ValueError, "GUID"):
            self.build("uefi-capsules")

    def test_capsules_reject_a_future_lowest_supported_version(self):
        path = next(self.capsules.glob("*.cap"))
        path.write_bytes(capsule(lowest=0x00270300))
        self.rehash_capsules()
        with self.assertRaisesRegex(ValueError, "Stale"):
            self.build("uefi-capsules")

    def test_capsules_reject_truncated_payload(self):
        path = next(self.capsules.glob("*.cap"))
        path.write_bytes(b"MSS1 is not a capsule")
        self.rehash_capsules()
        with self.assertRaises(ValueError):
            self.build("uefi-capsules")

    def test_capsules_reject_duplicate_checksum_entries(self):
        sums = self.capsules / "SHA256SUMS"
        sums.write_text(sums.read_text() + sums.read_text().splitlines()[0] + "\n")
        with self.assertRaises(ValueError):
            self.build("uefi-capsules")

    def test_capsules_reject_wrong_outer_guid_even_with_recomputed_checksums(self):
        path = next(self.capsules.glob("*.cap"))
        data = path.read_bytes()
        path.write_bytes(b"\0" * 16 + data[16:])
        self.rehash_capsules()
        with self.assertRaisesRegex(ValueError, "GUID"):
            self.build("uefi-capsules")

    def test_explicit_legacy_guid_bundle_requires_all12_matching_headers(self):
        legacy = "12345678-1234-1234-1234-123456789abc"
        for machine in MODULE.MACHINES:
            for style in MODULE.STYLES:
                name = f"{machine}-uefi-{style}-from-{legacy}.cap"
                (self.capsules / name).write_bytes(capsule(guid=legacy))
        self.rehash_capsules()
        payload, metadata = self.build("uefi-capsules", legacy_guids=[legacy])
        self.assertEqual(metadata["provenance"]["capsule_count"], 24)
        self.assertEqual(len(list(payload.rglob("*.cap"))), 24)

    def test_input_provenance_rejects_unknown_component(self):
        with self.assertRaises(ValueError):
            MODULE.input_provenance(dict(self.config, component="unexpected"))

    def test_payload_will_not_adopt_an_existing_work_tree(self):
        (self.run / "payload").mkdir()
        marker = self.run / "payload/unrelated"
        marker.write_text("preserve me\n")
        with self.assertRaises(ValueError):
            self.build("bsp-policy")
        self.assertEqual(marker.read_text(), "preserve me\n")


if __name__ == "__main__":
    unittest.main()
