#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Temp-only post-generation checks; no flashing, sudo or USB operations."""
import ast
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock


SOURCE = Path(__file__).resolve().parents[1] / "tools/check-deployment-images.py"
SPEC = importlib.util.spec_from_file_location("deployment_images", SOURCE)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class DeploymentImagesTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="deployment-images-")
        self.addCleanup(temporary.cleanup)
        self.sdk = Path(temporary.name)
        self.target = "edge-ai-nx-16g"
        self.device = "nvme0n1p1"
        self.logo = "clab-logo"
        self.write("flash.sh", "# never execute this fixture\n")
        self.write(MODULE.LAYOUT, "<partition_layout/>\n")
        self.before = MODULE.snapshot(self.sdk)
        self.generate()

    def write(self, relative, data):
        path = self.sdk / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(data)
        return path

    def generate(self):
        self.write(MODULE.PARAMETERS,
                   '--external-device %s -c "%s" --network usb0 %s external\n' %
                   (self.device, MODULE.LAYOUT, self.target))
        self.write(MODULE.MAPPING, "flashimg0=boot0.img\n")
        self.write("bootloader/boot0.img", "fixture flashing initrd\n")
        self.write("bootloader/flashcmd.txt",
                   './tegraflash.py --bl compulab-%s-%s-rcm_with_dtb.bin '
                   '--cmd "rcmboot"\n' % (self.target, self.logo))
        self.index("internal", 3, "A_cpu-bootloader", "uefi.bin")
        self.index("external", 9, "APP", "system.img")

    def index(self, storage, device, partition, filename):
        parent = "tools/kernel_flash/images/" + storage
        self.write(parent + "/flash.idx",
                   "0, %d:0:%s, 0, 4096, %s, 8, fixed-1, %s\n" %
                   (device, partition, filename, "0" * 40))
        payload = "fixture payload\n"
        self.write(parent + "/" + filename, payload)
        config = "CHIPID=0x23\n"
        if partition == "APP":
            config += "APP_ext=%s\nexternal_device=nvme0n1p1\n" % filename
            self.write(parent + "/" + filename + ".sha1sum",
                       hashlib.sha1(payload.encode()).hexdigest() + "\n")
        self.write(parent + "/flash.cfg", config)

    def native_app_index(self):
        self.write(MODULE.EXTERNAL,
                   "0, 9:0:APP, 0, 4096, , , expand-1, \n")

    def validate(self, **changes):
        arguments = dict(sdk_root=self.sdk, target=self.target,
                         external_device=self.device, logo=self.logo,
                         before=self.before)
        return MODULE.validate_images(**(arguments | changes))

    def image_snapshot(self):
        return {str(p.relative_to(self.sdk)): (p.read_bytes(), p.stat().st_mode)
                for p in self.sdk.rglob("*") if p.is_file()}

    def rejected(self, **changes):
        before = self.image_snapshot()
        with self.assertRaises((ValueError, OSError)):
            self.validate(**changes)
        self.assertEqual(before, self.image_snapshot())

    def test_snapshot_allows_missing_previous_outputs(self):
        self.assertEqual(self.before["format_version"], 1)
        self.assertEqual(set(self.before["files"]), set(MODULE.SNAPSHOT_FILES))
        self.assertTrue(all(value is None for value in self.before["files"].values()))

    def test_fresh_images_validate_without_modifying_inputs(self):
        before = self.image_snapshot()
        report = self.validate()
        self.assertEqual(report["status"], "verified")
        self.assertEqual(report["external_device"], self.device)
        self.assertEqual(report["internal_partitions"], 1)
        self.assertEqual(report["external_partitions"], 1)
        self.assertEqual(before, self.image_snapshot())

    def test_native_blank_app_index_uses_cfg_payload_without_mutation(self):
        self.native_app_index()
        before = self.image_snapshot()
        report = self.validate()
        self.assertEqual(report["status"], "verified")
        self.assertEqual(report["external_partitions"], 1)
        self.assertEqual(before, self.image_snapshot())

    def test_cfg_mapping_does_not_replace_required_app_partition(self):
        self.write(MODULE.EXTERNAL,
                   "0, 9:0:reserved, 0, 4096, , , fixed-1, \n")
        self.rejected()

    def test_native_app_requires_nonempty_safe_unique_cfg_mapping(self):
        self.native_app_index()
        relative = "tools/kernel_flash/images/external/flash.cfg"
        for text in ("CHIPID=0x23\n", "APP_ext=\nCHIPID=0x23\n",
                     "APP_ext=../system.img\n", "APP_ext=/tmp/system.img\n",
                     "APP_ext=$(touch /tmp/not-executed)\n",
                     "APP_ext=system.img;touch /tmp/not-executed\n",
                     "APP_ext=system.img\nAPP_ext=system.img\n"):
            with self.subTest(text=text):
                self.write(relative, text)
                self.rejected()

    def test_native_app_requires_payload_and_sha1_sidecar(self):
        self.native_app_index()
        for name in ("system.img", "system.img.sha1sum"):
            with self.subTest(name=name):
                path = self.sdk / "tools/kernel_flash/images/external" / name
                previous = path.read_bytes()
                path.unlink()
                self.rejected()
                path.write_bytes(previous)

    def test_native_app_rejects_bad_or_mismatched_checksum(self):
        self.native_app_index()
        sidecar = "tools/kernel_flash/images/external/system.img.sha1sum"
        for value in ("0" * 40 + "\n", "not-a-checksum\n", ""):
            with self.subTest(value=value):
                self.write(sidecar, value)
                self.rejected()

    def test_inline_app_filename_must_match_cfg_mapping(self):
        directory = "tools/kernel_flash/images/external/"
        payload = "other valid APP payload\n"
        self.write(directory + "other.img", payload)
        self.write(directory + "other.img.sha1sum",
                   hashlib.sha1(payload.encode()).hexdigest() + "\n")
        self.write(directory + "flash.cfg",
                   "APP_ext=other.img\nCHIPID=0x23\n")
        self.rejected()

    def test_native_app_cfg_device_must_match_selected_nvme(self):
        self.native_app_index()
        config = self.sdk / "tools/kernel_flash/images/external/flash.cfg"
        config.write_text(config.read_text().replace("nvme0n1p1", "nvme1n1p1"))
        self.rejected()

    def test_stale_generation_is_rejected(self):
        self.rejected(before=MODULE.snapshot(self.sdk))

    def test_both_params_and_mapping_must_be_refreshed(self):
        for unchanged in (MODULE.PARAMETERS, MODULE.MAPPING):
            with self.subTest(unchanged=unchanged):
                before = json.loads(json.dumps(self.before))
                before["files"][unchanged] = MODULE.snapshot(self.sdk)["files"][unchanged]
                self.rejected(before=before)

    def test_file_signatures_do_not_compare_host_clock_time(self):
        before = MODULE.snapshot(self.sdk)
        for relative in (MODULE.PARAMETERS, MODULE.MAPPING):
            path = self.sdk / relative
            os.utime(path, ns=(1_000_000_000, 1_000_000_000))
        self.assertEqual(self.validate(before=before)["status"], "verified")

    def test_foreign_nfs_uid_is_not_an_authorization_requirement(self):
        self.native_app_index()
        with mock.patch.object(MODULE.os if hasattr(MODULE, "os") else os,
                               "getuid", return_value=987654):
            self.assertEqual(self.validate()["status"], "verified")

    def test_saved_target_device_layout_and_network_are_checked(self):
        path = self.sdk / MODULE.PARAMETERS
        original = path.read_text()
        for old, new in ((self.target, "edge-ai-nx-8g"),
                         (self.device, "nvme1n1p1"),
                         (MODULE.LAYOUT, "other.xml"),
                         ("usb0", "eth0")):
            with self.subTest(new=new):
                path.write_text(original.replace(old, new))
                self.rejected()
        path.write_text(original)

    def test_unsupported_and_injected_saved_options_are_rejected(self):
        path = self.sdk / MODULE.PARAMETERS
        original = path.read_text()
        for argument in ("--direct sda", "--external-only", "--no-flash",
                         "--initrd", "-k APP", "--network usb0",
                         "--network 'usb0;touch /tmp/not-run'"):
            with self.subTest(argument=argument):
                path.write_text(argument + " " + original)
                self.rejected()

    def test_selected_target_and_logo_must_match_rcm_bootloader(self):
        self.rejected(logo="no-logo")
        self.write("bootloader/flashcmd.txt",
                   './tegraflash.py --bl compulab-%s-%s-rcm.bin --cmd flash\n' %
                   (self.target, self.logo))
        self.rejected()

    def test_only_one_slot_zero_mapping_is_accepted(self):
        for text in ("flashimg1=boot0.img\n", "flashimg0=../boot0.img\n",
                     "flashimg0=boot0.img\nflashimg1=boot0.img\n", ""):
            with self.subTest(text=text):
                self.write(MODULE.MAPPING, text)
                self.rejected()

    def test_missing_initrd_or_partition_payload_is_rejected(self):
        for relative in ("bootloader/boot0.img",
                         "tools/kernel_flash/images/internal/uefi.bin",
                         "tools/kernel_flash/images/external/system.img"):
            with self.subTest(relative=relative):
                path = self.sdk / relative
                previous = path.read_bytes()
                path.unlink()
                self.rejected()
                path.write_bytes(previous)

    def test_storage_types_and_nvme_app_are_checked(self):
        self.index("internal", 9, "A_cpu-bootloader", "uefi.bin")
        self.rejected()
        self.index("internal", 3, "A_cpu-bootloader", "uefi.bin")
        self.index("external", 9, "reserved", "system.img")
        self.rejected()

    def test_symlinked_inputs_and_parents_are_rejected(self):
        path = self.sdk / MODULE.PARAMETERS
        original = self.sdk / "parameters-original"
        path.rename(original)
        path.symlink_to(original)
        self.rejected()
        with self.assertRaises(ValueError):
            MODULE.snapshot(self.sdk)

    def test_hardlinked_metadata_is_rejected(self):
        os.link(self.sdk / MODULE.MAPPING, self.sdk / "hardlinked-map")
        self.rejected()

    def test_snapshot_schema_and_sdk_identity_are_checked(self):
        for before in ({}, {**self.before, "sdk_root": "/other/sdk"},
                       {**self.before, "format_version": True},
                       {**self.before, "files": {}}):
            with self.subTest(before=before):
                self.rejected(before=before)
        bad = json.loads(json.dumps(self.before))
        bad["files"][MODULE.MAPPING] = [True] * 5
        self.rejected(before=bad)

    def test_cli_and_python310_syntax(self):
        ast.parse(SOURCE.read_text(), feature_version=(3, 10))
        command = ["/usr/bin/python3", "-B", str(SOURCE), "--sdk-root", str(self.sdk)]
        result = subprocess.run(command + ["--snapshot"], capture_output=True,
                                text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["sdk_root"], str(self.sdk))
        result = subprocess.run(command + ["--target", self.target,
            "--external-device", self.device, "--logo", self.logo,
            "--before-json", json.dumps(self.before)], capture_output=True,
            text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["status"], "verified")


if __name__ == "__main__":
    unittest.main()
