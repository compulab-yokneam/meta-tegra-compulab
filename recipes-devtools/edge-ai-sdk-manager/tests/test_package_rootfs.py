#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Native .deb fixtures without target code, mounts or host dpkg writes."""

import base64
from contextlib import contextmanager
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import struct
import subprocess
import uuid
from types import SimpleNamespace
import unittest
from unittest import mock


DIRECTORY = Path(__file__).resolve().parents[1]
FILES = DIRECTORY / "files"
TOOLS = FILES / "sdk-source/compulab/tools"


def load(path, name):
    specification = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


MODULE = load(FILES / "package-rootfs.py", "rootfs_packages_under_test")
FIXTURES = load(FILES / "sdk-source/compulab/tests/" /
                "test_rootfs_package_inventory.py", "inventory_fixture_only")


def capsule(version=0x00270201, lowest=0x00270201):
    """Structurally valid FMP v3/auth/MSS1 fixture, not a flashable capsule."""
    certificate = struct.pack(
        "<IHH16s", 24, 0x0200, 0x0EF1,
        uuid.UUID("4aafd29d-68df-49ee-8aa9-347d375665a7").bytes_le)
    authentication = struct.pack("<Q", 1) + certificate
    payload = authentication + struct.pack(
        "<4sIII", b"MSS1", 16, version, lowest) + b"fixture only"
    image = struct.pack(
        "<I16sB3sIIQQ", 3,
        uuid.UUID("bf0d4599-20d4-414e-b2c5-3595b1cda402").bytes_le,
        1, b"\0" * 3, len(payload), 0, 0, 1)
    management = struct.pack("<IHHQ", 1, 0, 1, 16)
    total = 32 + len(management) + len(image) + len(payload)
    header = struct.pack(
        "<16sIII", uuid.UUID(
            "6dcbd5ed-e82d-4c44-bda1-7194199ad92a").bytes_le,
        32, 0, total) + b"\0" * 4
    return header + management + image + payload


@unittest.skipUnless(shutil.which("dpkg-deb"), "dpkg-deb is required")
class RootfsPackageTests(unittest.TestCase):
    def setUp(self):
        # Reuse only fixture construction, never inherit/discover its tests.
        fixture = FIXTURES.RootfsPackageInventoryTests(
            "test_collects_complete_nonoverlapping_package_groups")
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        self.fixture = fixture
        self.directory = fixture.directory
        self.sdk = fixture.sdk
        self.root = fixture.root
        self.artifacts = fixture.artifacts
        self.version = fixture.version
        self.work = self.directory / "package-work"
        self.output = self.sdk / "compulab/packages"
        self.tools = self.sdk / "compulab/tools"
        self.tools.mkdir(parents=True)
        for name in ("deb_packages.py", "rootfs_package_inventory.py",
                     "package-bsp-policy.py"):
            shutil.copy2(TOOLS / name, self.tools / name)
        self.put(self.sdk / "flash.sh", b"#!/bin/sh\nexit 97\n")
        self.put(self.root / "etc/nv_tegra_release",
                 b"# R39 (release), REVISION: 2.1, BOARD: generic\n")
        self.put(self.root / "etc/os-release",
                 b'ID=ubuntu\nVERSION_ID="24.04"\n')
        self.put(self.root / "var/lib/dpkg/status", b"")
        (self.root / "tmp").mkdir()
        self.backup = self.sdk / "compulab/vendor-backup"
        self.put(self.backup / "rootfs/boot/Image", b"pristine NVIDIA Image\n")
        self.put(self.backup / "rootfs/boot/initrd",
                 b"pristine NVIDIA initrd\n")
        self.baseline = {
            "vendor_backup": str(self.backup),
            "sha256": {
                path: MODULE.digest(self.backup / path)
                for path in ("rootfs/boot/Image", "rootfs/boot/initrd")},
        }
        self.put(self.sdk / "SDK_BASELINE.json",
                 json.dumps(self.baseline).encode())
        original = b"".join((name + '=\"1\"\n').encode() for name in (
            "ENABLE_SPEC_GENERATION", "ENABLE_UEFI_SPEC_VAR_UPDATE",
            "ENABLE_PARTITION_UPDATE", "ENABLE_ESP_AUTOMOUNT",
            "ENABLE_AUTO_QSPI_UPDATE"))
        applied = original.replace(b'ENABLE_AUTO_QSPI_UPDATE="1"',
                                   b'ENABLE_AUTO_QSPI_UPDATE="0"')
        self.policy_state = {
            "schema": 1,
            "original_config": base64.b64encode(original).decode(),
            "original_config_sha256": hashlib.sha256(original).hexdigest(),
            "applied_config_sha256": hashlib.sha256(applied).hexdigest(),
            "config_mode": 0o644,
            "packages": [{"name": "nvidia-l4t-kernel:arm64",
                          "version": "6.8.12-tegra-39.2.1-20260806224157",
                          "selection": "install"}],
        }
        self.write_capsules()

    def put(self, path, data=b"fixture\n"):
        self.fixture.put(path, data)

    def write_capsules(self, version=0x00270201, lowest=0x00270201):
        directory = self.root / self.fixture.capsules
        for path in directory.glob("*.cap"):
            path.write_bytes(capsule(version, lowest))
        (directory / "SHA256SUMS").write_text("".join(
            MODULE.digest(path) + "  " + path.name + "\n"
            for path in sorted(directory.glob("*.cap"))))

    def build(self, ownership=None):
        state = copy.deepcopy(self.policy_state)
        with mock.patch.object(MODULE, "owners",
                               return_value=ownership or {}), \
                mock.patch.object(MODULE, "seeded_policy_state",
                                  return_value=state):
            return MODULE.create_packages(self.sdk, self.artifacts, self.work,
                                          self.output, self.version)

    def unpack(self, receipt):
        for item in receipt["packages"]:
            subprocess.run(["dpkg-deb", "--extract",
                            self.output / item["filename"], self.root],
                           check=True, capture_output=True, text=True)

    def query(self, receipt, *, wrong_version=False, missing_path=None):
        packages = {item["name"]: item for item in receipt["packages"]}

        def result(command, **_options):
            self.assertEqual(command[0], "dpkg-query")
            self.assertIn("--admindir=" + str(self.root / "var/lib/dpkg"),
                          command)
            item = packages[command[-1]]
            if "-W" in command:
                version = "0" if wrong_version else item["version"]
                return "install ok installed\t%s\t%s\n" % (
                    version, item["architecture"])
            self.assertIn("--listfiles", command)
            return "\n".join("/" + path for path in item["files"]
                             if path != missing_path) + "\n"

        return result

    @contextmanager
    def fake_installation(self, *, binfmt=True):
        contexts = []
        calls = []

        @contextmanager
        def context(root):
            self.assertEqual(root, self.root)
            contexts.append(root)
            yield

        def chroot(root, arguments, log=None):
            self.assertEqual(root, self.root)
            calls.append((arguments, log))
            return ""

        provision = SimpleNamespace(
            target_context=context, chroot=chroot,
            persistent_binfmt=lambda _path: binfmt)
        with mock.patch.object(MODULE.os, "geteuid", return_value=0), \
                mock.patch.object(MODULE, "load_module",
                                  return_value=provision), \
                mock.patch.object(MODULE, "verify_packages", return_value={}) \
                as verification:
            yield contexts, calls, verification

    def test_create_builds_nine_real_debs_with_ownership_metadata(self):
        receipt = self.build()
        self.assertEqual(len(receipt["packages"]), 9)
        self.assertEqual(len(list(self.output.glob("*.deb"))), 9)
        self.assertFalse(receipt["installed"])
        packages = {item["name"]: item for item in receipt["packages"]}
        for name, item in packages.items():
            archive = self.output / item["filename"]
            metadata = subprocess.run(
                ["dpkg-deb", "--field", archive, "Package", "Version",
                 "Architecture"], check=True, capture_output=True,
                text=True).stdout
            self.assertIn("Package: " + name, metadata)
            self.assertIn("Version: " + self.version, metadata)
            self.assertIn("Architecture: " + item["architecture"], metadata)
            control = self.directory / ("control-" + name)
            subprocess.run(["dpkg-deb", "--control", archive, control],
                           check=True, capture_output=True, text=True)
            for script in ("preinst", "postinst", "prerm", "postrm"):
                if (control / script).is_file():
                    self.assertNotRegex((control / script).read_text(),
                        r"(?m)^\s*(?:reboot|shutdown|efibootmgr|efivar|"
                        r"edge-ai-uefi-update|apply-uefi-capsule)\b")
            if item["conffiles"]:
                actual = (control / "conffiles").read_text().splitlines()
                expected = sorted("/" + path for path in item["conffiles"])
                self.assertEqual(actual, expected)
        capsule_item = packages["compulab-edge-ai-uefi-capsules"]
        extracted = self.directory / "capsule-extracted"
        subprocess.run(["dpkg-deb", "--extract",
                        self.output / capsule_item["filename"], extracted],
                       check=True, capture_output=True, text=True)
        capsule_directory = extracted / self.fixture.capsules
        self.assertTrue(capsule_directory.is_dir())
        self.assertTrue((capsule_directory / "SHA256SUMS").is_file())
        self.assertEqual(len(list(capsule_directory.glob("*.cap"))), 12)
        kernel_control = self.directory / "control-compulab-edge-ai-kernel"
        self.assertIn("nvidia-l4t-kernel (= "
                      "6.8.12-tegra-39.2.1-20260806224157)",
                      (kernel_control / "control").read_text())
        meta_control = self.directory / "control-compulab-edge-ai"
        self.assertIn("compulab-edge-ai-uefi-capsules (>= " +
                      self.version + ")",
                      (meta_control / "control").read_text())

    @unittest.skipUnless(shutil.which("fakeroot") and shutil.which("dpkg"),
                         "fakeroot and dpkg are required")
    def test_real_disposable_dpkg_owns_capsule_directory_and_payload(self):
        receipt = self.build()
        item = next(item for item in receipt["packages"]
                    if item["name"] == "compulab-edge-ai-uefi-capsules")
        destination = self.directory / "disposable-dpkg-target"
        self.put(destination / "var/lib/dpkg/status", b"")
        result = subprocess.run(
            ["fakeroot", "dpkg", "--root=" + str(destination), "--install",
             self.output / item["filename"]],
            check=True, capture_output=True, text=True)
        self.assertIn("Setting up compulab-edge-ai-uefi-capsules",
                      result.stdout)
        directory = "/usr/share/compulab/uefi-update-capsules"
        query = subprocess.run(
            ["dpkg-query", "--admindir=" +
             str(destination / "var/lib/dpkg"), "--search", directory],
            check=True, capture_output=True, text=True).stdout
        self.assertIn("compulab-edge-ai-uefi-capsules: " + directory, query)
        query = subprocess.run(
            ["dpkg-query", "--admindir=" +
             str(destination / "var/lib/dpkg"), "--search",
             directory + "/edge-ai-nx-16g-uefi-nvidia-logo.cap"],
            check=True, capture_output=True, text=True).stdout
        self.assertIn("compulab-edge-ai-uefi-capsules:", query)

    def test_stale_capsules_fail_before_package_work_or_output_creation(self):
        for current, lowest in ((0x00270200, 0x00270200),
                                (0x00270201, 0x00270202)):
            with self.subTest(current=current, lowest=lowest):
                self.write_capsules(version=current, lowest=lowest)
                with self.assertRaisesRegex(ValueError, "Stale/incompatible"):
                    self.build()
                self.assertFalse(self.work.exists())
                self.assertFalse(self.output.exists())

    def test_capsule_checksum_failure_is_not_accepted(self):
        path = next((self.root / self.fixture.capsules).glob("*.cap"))
        path.write_bytes(path.read_bytes() + b"changed")
        with self.assertRaisesRegex(ValueError, "checksum mismatch"):
            MODULE.check_capsules(self.root)

    def test_capsule_manifest_must_cover_every_installed_capsule(self):
        manifest = self.root / self.fixture.capsules / "SHA256SUMS"
        lines = manifest.read_text().splitlines()
        manifest.write_text("\n".join(lines[:-1]) + "\n")
        with mock.patch.object(MODULE, "digest") as digest:
            with self.assertRaisesRegex(ValueError, "complete bundle"):
                MODULE.check_capsules(self.root)
        digest.assert_not_called()

    def test_capsule_manifest_rejects_duplicate_and_escaping_paths(self):
        manifest = self.root / self.fixture.capsules / "SHA256SUMS"
        original = manifest.read_text()
        cases = (original + original.splitlines()[0] + "\n",
                 original + "0" * 64 + "  ../outside.cap\n",
                 original + "0" * 64 + "  /outside.cap\n")
        for value in cases:
            with self.subTest(entry=value.splitlines()[-1]):
                manifest.write_text(value)
                with mock.patch.object(MODULE, "digest") as digest:
                    with self.assertRaisesRegex(ValueError,
                                                "Unsafe or duplicate"):
                        MODULE.check_capsules(self.root)
                digest.assert_not_called()

    def test_firmware_parser_reads_authentication_bounded_version(self):
        path = self.directory / "test.cap"
        path.write_bytes(capsule())
        self.assertEqual(MODULE.firmware_version(path),
                         (0x00270201, 0x00270201))
        self.assertEqual(MODULE.firmware_version(path),
                         (MODULE.FIRMWARE_VERSION, MODULE.FIRMWARE_VERSION))

    def test_firmware_parser_rejects_truncated_and_malformed_headers(self):
        original = capsule()
        cases = [b"", original[:30]]
        for offset, value in ((16, 0), (24, len(original) + 1), (32, 7),
                              (40, 0xFFFFFF00), (48, 2),
                              (72, len(original)), (104, 0), (132, 12)):
            value_bytes = bytearray(original)
            struct.pack_into("<I", value_bytes, offset, value)
            cases.append(bytes(value_bytes))
        bad_magic = bytearray(original)
        bad_magic[128:132] = b"BAD!"
        cases.append(bytes(bad_magic))
        path = self.directory / "malformed.cap"
        for number, value in enumerate(cases):
            with self.subTest(case=number):
                path.write_bytes(value)
                with self.assertRaises((ValueError, struct.error)):
                    MODULE.firmware_version(path)

    def test_vendor_kernel_backup_is_original_not_staged_custom_image(self):
        original = MODULE.vendor_backup(self.sdk, "boot/Image",
                                        "nvidia-l4t-kernel:arm64")
        self.assertEqual(original, self.backup / "rootfs/boot/Image")
        self.assertNotEqual(original.read_bytes(),
                            (self.root / "boot/Image").read_bytes())
        original.write_bytes(b"modified stock copy")
        with self.assertRaisesRegex(ValueError, "checksum mismatch"):
            MODULE.vendor_backup(self.sdk, "boot/Image",
                                 "nvidia-l4t-kernel:arm64")

    def test_plugin_backup_must_match_vendor_dpkg_checksum(self):
        relative = "usr/lib/aarch64-linux-gnu/gstreamer-1.0/" + \
                   "libgstnvarguscamerasrc.so"
        backup = self.sdk / \
            "compulab/receipts/runtime-provision/pre-stage-backup" / relative
        self.put(backup, b"verified vendor plugin")
        checksum = hashlib.md5(backup.read_bytes()).hexdigest()
        self.put(self.root / "var/lib/dpkg/info/" /
                 "nvidia-l4t-gstreamer.md5sums",
                 (checksum + "  " + relative + "\n").encode())
        # dpkg-query may qualify the owner although its info file is not.
        self.assertEqual(MODULE.vendor_backup(
            self.sdk, relative, "nvidia-l4t-gstreamer:arm64"), backup)
        conflict = self.root / "var/lib/dpkg/info/" / \
            "nvidia-l4t-gstreamer:arm64.md5sums"
        self.put(conflict, ("0" * 32 + "  " + relative + "\n").encode())
        with self.assertRaisesRegex(ValueError, "conflicting"):
            MODULE.vendor_backup(self.sdk, relative,
                                 "nvidia-l4t-gstreamer:arm64")
        conflict.unlink()
        backup.write_bytes(b"custom plugin must not become vendor backup")
        with self.assertRaisesRegex(ValueError, "not verified"):
            MODULE.vendor_backup(self.sdk, relative,
                                 "nvidia-l4t-gstreamer:arm64")

    def test_policy_receipt_drift_fails_before_creating_package_trees(self):
        with mock.patch.object(MODULE, "owners", return_value={}), \
                mock.patch.object(MODULE, "seeded_policy_state",
                                  side_effect=ValueError("policy drift")):
            with self.assertRaisesRegex(ValueError, "policy drift"):
                MODULE.create_packages(self.sdk, self.artifacts, self.work,
                                       self.output, self.version)
        self.assertFalse(self.work.exists())
        self.assertFalse(self.output.exists())

    def test_checked_sdk_rejects_host_and_symlinked_package_database(self):
        self.assertEqual(MODULE.checked_sdk(self.sdk), self.sdk)
        with self.assertRaises(ValueError):
            MODULE.checked_sdk(Path("/"))
        alias = self.directory / "alias"
        alias.symlink_to(self.sdk, target_is_directory=True)
        with self.assertRaises(ValueError):
            MODULE.checked_sdk(alias)
        database = self.root / "var/lib/dpkg"
        database.rename(self.directory / "saved-dpkg")
        database.symlink_to("/var/lib/dpkg", target_is_directory=True)
        with self.assertRaises(ValueError):
            MODULE.checked_sdk(self.sdk)

    def test_verify_requires_real_ownership_version_and_payload_hashes(self):
        receipt = self.build()
        self.unpack(receipt)
        with mock.patch.object(MODULE, "run", side_effect=self.query(receipt)):
            result = MODULE.verify_packages(self.sdk, receipt)
        self.assertEqual(result["packages"], 9)
        with mock.patch.object(MODULE, "run",
                               side_effect=self.query(receipt,
                                                      wrong_version=True)):
            with self.assertRaisesRegex(ValueError, "expected version"):
                MODULE.verify_packages(self.sdk, receipt)
        with mock.patch.object(MODULE, "run", side_effect=self.query(
                receipt, missing_path="boot/Image")):
            with self.assertRaisesRegex(ValueError, "not owned"):
                MODULE.verify_packages(self.sdk, receipt)
        (self.root / "boot/Image").write_bytes(b"payload drift")
        with mock.patch.object(MODULE, "run", side_effect=self.query(receipt)):
            with self.assertRaisesRegex(ValueError, "payload changed"):
                MODULE.verify_packages(self.sdk, receipt)

    def test_install_uses_only_target_dpkg_and_preserves_policy_rollback(self):
        receipt = self.build()
        with self.fake_installation() as (contexts, calls, verification):
            result = MODULE.install_packages(self.sdk, receipt, self.work)
        self.assertEqual(contexts, [self.root])
        installation = [args for args, _log in calls if "--install" in args]
        self.assertEqual(len(installation), 1)
        self.assertEqual(installation[0][:3],
                         ["dpkg", "--force-confold", "--install"])
        self.assertTrue(all(path.startswith("/tmp/compulab-debs-")
                            for path in installation[0][3:]))
        self.assertEqual(len(installation[0][3:]), 9)
        self.assertNotIn("--force-overwrite", installation[0])
        self.assertNotIn("--force-script-chrootless", installation[0])
        verification.assert_called_once_with(self.sdk, receipt)
        state = self.root / MODULE.POLICY_STATE
        self.assertEqual(json.loads(state.read_text()), self.policy_state)
        self.assertEqual(state.stat().st_mode & 0o777, 0o600)
        self.assertTrue(result["installed"])
        self.assertNotIn("policy_state", result)
        self.assertNotIn("pristine", result)
        self.assertTrue((self.output / "manifest.json").is_file())

    def test_install_preflights_all_payloads_before_restoring_originals(self):
        receipt = self.build({"boot/Image": "nvidia-l4t-kernel:arm64"})
        custom = (self.root / "boot/Image").read_bytes()
        (self.root / "opt/compulab/bin/gst_camera.sh").write_bytes(b"drift")
        with self.fake_installation() as (_contexts, calls, _verification):
            with self.assertRaisesRegex(ValueError, "payload changed"):
                MODULE.install_packages(self.sdk, receipt, self.work)
        self.assertEqual((self.root / "boot/Image").read_bytes(), custom)
        self.assertFalse((self.root / MODULE.POLICY_STATE).exists())
        self.assertEqual(calls, [])

    def test_install_rejects_invalid_receipt_before_any_target_write(self):
        receipt = self.build({"boot/Image": "nvidia-l4t-kernel:arm64"})
        original = (self.root / "boot/Image").read_bytes()
        for key, value in (("sdk_root", "/"), ("schema", 2),
                           ("installed", True), ("output", "/"),
                           ("packages", receipt["packages"][:-1])):
            with self.subTest(field=key):
                invalid = dict(receipt, **{key: value})
                with self.fake_installation() as (_context, calls, _verify):
                    with self.assertRaises(ValueError):
                        MODULE.install_packages(self.sdk, invalid, self.work)
                self.assertEqual(calls, [])
                self.assertEqual((self.root / "boot/Image").read_bytes(),
                                 original)
                self.assertFalse((self.root / MODULE.POLICY_STATE).exists())

    def test_install_pristine_backup_must_remain_in_owned_work_directory(self):
        receipt = self.build({"boot/Image": "nvidia-l4t-kernel:arm64"})
        original = (self.root / "boot/Image").read_bytes()
        outside = self.directory / "unowned-backup"
        self.put(outside, (self.backup / "rootfs/boot/Image").read_bytes())
        receipt["pristine"]["boot/Image"]["source"] = str(outside)
        with self.fake_installation() as (_contexts, calls, _verification):
            with self.assertRaisesRegex(ValueError, "outside the owned"):
                MODULE.install_packages(self.sdk, receipt, self.work)
        self.assertEqual((self.root / "boot/Image").read_bytes(), original)
        self.assertFalse((self.root / MODULE.POLICY_STATE).exists())
        self.assertEqual(calls, [])

    def test_install_changed_archive_fails_before_restoring_originals(self):
        receipt = self.build({"boot/Image": "nvidia-l4t-kernel:arm64"})
        original = (self.root / "boot/Image").read_bytes()
        archive = self.output / receipt["packages"][-1]["filename"]
        archive.write_bytes(archive.read_bytes() + b"archive drift")
        with self.fake_installation() as (_contexts, calls, _verification):
            with self.assertRaisesRegex(ValueError, "Package changed"):
                MODULE.install_packages(self.sdk, receipt, self.work)
        self.assertEqual((self.root / "boot/Image").read_bytes(), original)
        self.assertFalse((self.root / MODULE.POLICY_STATE).exists())
        self.assertEqual(calls, [])

    def test_install_rejects_preexisting_state_before_restoring_originals(self):
        receipt = self.build({"boot/Image": "nvidia-l4t-kernel:arm64"})
        original = (self.root / "boot/Image").read_bytes()
        state = self.root / MODULE.POLICY_STATE
        self.put(state, b"existing policy state must be preserved")
        with self.fake_installation() as (_contexts, calls, _verification):
            with self.assertRaisesRegex(ValueError, "state already exists"):
                MODULE.install_packages(self.sdk, receipt, self.work)
        self.assertEqual((self.root / "boot/Image").read_bytes(), original)
        self.assertEqual(state.read_bytes(),
                         b"existing policy state must be preserved")
        self.assertEqual(calls, [])

    def test_install_rejects_missing_binfmt_before_restoring_originals(self):
        receipt = self.build({"boot/Image": "nvidia-l4t-kernel:arm64"})
        original = (self.root / "boot/Image").read_bytes()
        with self.fake_installation(binfmt=False) as (_context, calls, _verify):
            with self.assertRaisesRegex(ValueError, "binfmt"):
                MODULE.install_packages(self.sdk, receipt, self.work)
        self.assertEqual((self.root / "boot/Image").read_bytes(), original)
        self.assertFalse((self.root / MODULE.POLICY_STATE).exists())
        self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()
