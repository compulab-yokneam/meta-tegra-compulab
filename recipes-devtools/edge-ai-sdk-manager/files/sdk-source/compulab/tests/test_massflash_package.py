#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Fixture-only massflash finalization; never invoke flashing or sudo."""
import ast
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tarfile
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock


SOURCE = Path(__file__).resolve().parents[1] / \
    "tools/prepare-massflash-package.py"
SPEC = importlib.util.spec_from_file_location("prepare_massflash_package", SOURCE)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class MassflashPackageTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="massflash-package-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.sdk = self.root / "sdk"
        self.sdk.mkdir()
        self.target = "edge-ai-nx-16g"
        self.scope = "bootloader"
        self.count = 2
        self.package = self.sdk / ("mfi_" + self.target)
        self.package.mkdir()
        self.archive = self.sdk / (self.package.name + ".tar.gz")
        self.kernel_flash = self.package / "tools/kernel_flash"
        self.profile = self.package / (self.target + ".conf")
        self.write(self.sdk / "flash.sh", "#!/bin/bash\nexit 97\n")
        self.write(self.sdk / (self.target + ".conf"),
                   'source "${LDK_DIR}/edge-ai-common.conf"\n')
        self.write(self.profile, 'source "${LDK_DIR}/edge-ai-common.conf"\n')
        for name in MODULE.SCRIPTS:
            self.write(self.kernel_flash / name, "# native fixture\n")
        self.write(self.package / "bootloader/flashcmd.txt",
                   "./tegraflash.py --chip 0x23 --cmd rcmboot\n")
        self.write(self.kernel_flash / "images/l4t_flash_from_kernel.sh",
                   "# native image writer fixture\n")
        self.parameters = self.kernel_flash / "initrdflashparam.txt"
        self.write(self.parameters, "--network usb0 %s external\n" % self.target)
        self.write(self.kernel_flash / "initrdflashimgmap.txt",
                   "flashimg0=boot0.img\nflashimg1=boot1.img\n")
        for number in range(self.count):
            self.write(self.package / ("bootloader/boot%d.img" % number),
                       "flash initrd fixture\n")
        self.index("internal", 3, "A_cpu-bootloader", "uefi.bin")
        with tarfile.open(self.archive, "w:gz") as stream:
            stream.add(self.package, arcname=self.package.name)

    def write(self, path, text):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)

    def index(self, storage, device, partition, image):
        directory = self.kernel_flash / "images" / storage
        payload = "image fixture\n"
        self.write(directory / image, payload)
        self.write(directory / "flash.idx",
                   "0, %d:0:%s, 0, 4096, %s, 14, fixed-1, %s\n" %
                   (device, partition, image, "0" * 40))
        config = "CHIPID=0x23\n"
        if partition == "APP":
            config += "APP_ext=%s\nexternal_device=nvme0n1p1\n" % image
            self.write(directory / (image + ".sha1sum"),
                       hashlib.sha1(payload.encode()).hexdigest() + "\n")
        self.write(directory / "flash.cfg", config)

    def full(self):
        self.scope = "full"
        self.write(self.parameters,
                   '--external-device nvme0n1p1 -c "nvme.xml" '
                   '--network usb0 %s external\n' % self.target)
        self.index("external", 9, "APP", "system.img")

    def native_app_index(self):
        self.write(self.kernel_flash / "images/external/flash.idx",
                   "0, 9:0:APP, 0, 4096, , , expand-1, \n")

    def finalize(self, **changes):
        arguments = dict(sdk_root=self.sdk, target=self.target,
                         scope=self.scope, massflash=self.count,
                         logo="nvidia-logo", early_tty1="1")
        return MODULE.prepare_package(**(arguments | changes))

    def snapshot(self):
        result = {}
        for path in self.sdk.rglob("*"):
            name = str(path.relative_to(self.sdk))
            if path.is_symlink():
                result[name] = ("link", os.readlink(path))
            elif path.is_dir():
                result[name] = ("directory",)
            else:
                result[name] = ("file", path.stat().st_mode,
                                hashlib.sha256(path.read_bytes()).hexdigest())
        return result

    def rejects_without_mutation(self, **changes):
        before = self.snapshot()
        with self.assertRaises((OSError, ValueError)):
            self.finalize(**changes)
        self.assertEqual(before, self.snapshot())

    def foreign_owners(self, paths):
        """Model NFS numeric UID mismatch without privileged chown."""
        selected = set(paths)
        native_lstat = Path.lstat
        foreign_uid = max(MODULE.allowed_owners()) + 1000

        def nfs_lstat(path, *arguments, **keywords):
            metadata = native_lstat(path, *arguments, **keywords)
            if path in selected:
                # Reconstructing stat_result from its tuple loses ns fields.
                # Only the UID differs on NFS; preserve the other metadata.
                fields = {name: getattr(metadata, name) for name in dir(metadata)
                          if name.startswith("st_")}
                fields["st_uid"] = foreign_uid
                return SimpleNamespace(**fields)
            return metadata

        return mock.patch.object(Path, "lstat", new=nfs_lstat)

    def test_repack_is_standalone_and_does_not_modify_sdk_profile(self):
        original = (self.sdk / (self.target + ".conf")).read_bytes()
        result = self.finalize()
        self.assertEqual(original,
                         (self.sdk / (self.target + ".conf")).read_bytes())
        config = self.profile.read_text()
        self.assertIn("CHIPID=0x23\n", config)
        self.assertIn("MAX_MASSFLASH=2\n", config)
        self.assertIn("UNIFIED_FLASH=\n", config)
        self.assertNotIn("source ", config)
        receipt = json.loads((self.package / MODULE.RECEIPT).read_text())
        self.assertEqual(receipt["scope"], "bootloader")
        self.assertEqual(receipt["logo"], "nvidia-logo")
        self.assertEqual(receipt["early_tty1"], 1)
        self.assertTrue(result["prebuilt_only"])
        self.assertIn("WARNING", (self.package / MODULE.GUIDE).read_text())
        self.assertIn("--flash-only --massflash 2",
                      (self.package / MODULE.GUIDE).read_text())
        with tarfile.open(self.archive) as stream:
            packed = stream.extractfile(self.package.name + "/" +
                                        self.profile.name).read()
            self.assertEqual(packed, config.encode())
            self.assertIsNotNone(stream.getmember(self.package.name + "/" +
                                                  MODULE.RECEIPT))
            self.assertIsNotNone(stream.getmember(self.package.name + "/" +
                                                  MODULE.GUIDE))

    def test_full_package_includes_nvme_app_payload(self):
        self.full()
        self.finalize()
        with tarfile.open(self.archive) as stream:
            data = stream.extractfile(self.package.name +
                                      "/tools/kernel_flash/images/external/"
                                      "system.img").read()
        self.assertEqual(data, b"image fixture\n")
        self.assertIn("including its APP filesystem",
                      (self.package / MODULE.GUIDE).read_text())

    def test_native_blank_app_index_repack_keeps_payload_and_sidecar(self):
        self.full()
        self.native_app_index()
        source_profile = (self.sdk / (self.target + ".conf")).read_bytes()
        self.finalize()
        expected = hashlib.sha1(b"image fixture\n").hexdigest() + "\n"
        with tarfile.open(self.archive) as stream:
            prefix = self.package.name + "/tools/kernel_flash/images/external/"
            self.assertEqual(stream.extractfile(prefix + "system.img").read(),
                             b"image fixture\n")
            self.assertEqual(stream.extractfile(prefix +
                                               "system.img.sha1sum").read(),
                             expected.encode())
            config = stream.extractfile(prefix + "flash.cfg").read()
            self.assertIn(b"APP_ext=system.img\n", config)
        self.assertEqual((self.sdk / (self.target + ".conf")).read_bytes(),
                         source_profile)

    def test_cfg_mapping_does_not_replace_required_app_partition(self):
        self.full()
        self.write(self.kernel_flash / "images/external/flash.idx",
                   "0, 9:0:reserved, 0, 4096, , , fixed-1, \n")
        self.rejects_without_mutation()

    def test_native_app_requires_safe_nonempty_unique_cfg_mapping(self):
        self.full()
        self.native_app_index()
        config = self.kernel_flash / "images/external/flash.cfg"
        for text in ("CHIPID=0x23\n", "APP_ext=\nCHIPID=0x23\n",
                     "APP_ext=../system.img\n", "APP_ext=/tmp/system.img\n",
                     "APP_ext=$(touch /tmp/not-executed)\n",
                     "APP_ext=system.img;touch /tmp/not-executed\n",
                     "APP_ext=system.img\nAPP_ext=system.img\n"):
            with self.subTest(text=text):
                self.write(config, text)
                self.rejects_without_mutation()

    def test_native_app_requires_payload_and_sha1_sidecar(self):
        self.full()
        self.native_app_index()
        for name in ("system.img", "system.img.sha1sum"):
            with self.subTest(name=name):
                path = self.kernel_flash / "images/external" / name
                previous = path.read_bytes()
                path.unlink()
                self.rejects_without_mutation()
                path.write_bytes(previous)

    def test_native_app_rejects_bad_or_mismatched_checksum(self):
        self.full()
        self.native_app_index()
        sidecar = self.kernel_flash / "images/external/system.img.sha1sum"
        for value in ("0" * 40 + "\n", "not-a-checksum\n", ""):
            with self.subTest(value=value):
                self.write(sidecar, value)
                self.rejects_without_mutation()

    def test_inline_app_filename_must_match_cfg_mapping(self):
        self.full()
        directory = self.kernel_flash / "images/external"
        payload = "other valid APP payload\n"
        self.write(directory / "other.img", payload)
        self.write(directory / "other.img.sha1sum",
                   hashlib.sha1(payload.encode()).hexdigest() + "\n")
        self.write(directory / "flash.cfg",
                   "APP_ext=other.img\nCHIPID=0x23\n")
        self.rejects_without_mutation()

    def test_native_app_cfg_device_must_match_selected_nvme(self):
        self.full()
        self.native_app_index()
        config = self.kernel_flash / "images/external/flash.cfg"
        config.write_text(config.read_text().replace("nvme0n1p1", "nvme1n1p1"))
        self.rejects_without_mutation()

    def test_repack_accepts_foreign_readonly_sdk_and_package_inputs(self):
        self.full()
        self.native_app_index()
        sdk_sources = (self.sdk / "flash.sh",
                       self.sdk / (self.target + ".conf"))
        sources_before = {path: path.read_bytes() for path in sdk_sources}
        readonly = list(sdk_sources) + [
            path for path in self.package.rglob("*")
            if path.is_file() and path != self.profile]
        copied_script = self.kernel_flash / MODULE.SCRIPTS[0]
        script_before = copied_script.read_bytes()
        with self.foreign_owners(readonly):
            result = self.finalize()
        self.assertTrue(result["prebuilt_only"])
        for path, original in sources_before.items():
            self.assertEqual(path.read_bytes(), original)
        self.assertEqual(copied_script.read_bytes(), script_before)
        with tarfile.open(self.archive) as stream:
            member = self.package.name + "/" + str(
                copied_script.relative_to(self.package))
            self.assertEqual(stream.extractfile(member).read(), script_before)

    def test_repack_rejects_foreign_owned_mutation_targets(self):
        for path in (self.package, self.archive, self.profile):
            with self.subTest(path=path.name):
                with self.foreign_owners((path,)):
                    self.rejects_without_mutation()

    def test_foreign_readonly_sdk_source_still_rejects_symlinks(self):
        source = self.sdk / "flash.sh"
        outside = self.root / "outside-flash.sh"
        source.rename(outside)
        source.symlink_to(outside)
        with self.foreign_owners((source,)):
            self.rejects_without_mutation()

    def test_repack_preserves_private_archive_permissions(self):
        self.archive.chmod(0o600)
        self.finalize()
        self.assertEqual(self.archive.stat().st_mode & 0o777, 0o600)

    def test_invalid_arguments_do_not_modify_sdk(self):
        for changes in ({"target": "../../outside"}, {"scope": "anything"},
                        {"massflash": 0}, {"massflash": 65},
                        {"massflash": True}, {"massflash": "5"},
                        {"logo": "bogus"}, {"early_tty1": "2"}):
            with self.subTest(changes=changes):
                self.rejects_without_mutation(**changes)

    def test_noncanonical_sdk_root_is_rejected(self):
        alias = self.root / "sdk-alias"
        alias.symlink_to(self.sdk, target_is_directory=True)
        self.rejects_without_mutation(sdk_root=alias)
        self.rejects_without_mutation(sdk_root=Path("relative-sdk"))

    def test_symlinked_archive_is_rejected(self):
        original = self.root / "original.tar.gz"
        self.archive.rename(original)
        self.archive.symlink_to(original)
        self.rejects_without_mutation()

    def test_symlinked_package_directory_is_rejected(self):
        original = self.root / "original-package"
        self.package.rename(original)
        self.package.symlink_to(original, target_is_directory=True)
        self.rejects_without_mutation()

    def test_symlinked_profile_is_rejected(self):
        self.profile.unlink()
        self.profile.symlink_to(self.sdk / (self.target + ".conf"))
        self.rejects_without_mutation()

    def test_hardlinked_profile_is_rejected(self):
        self.profile.unlink()
        os.link(self.sdk / (self.target + ".conf"), self.profile)
        self.rejects_without_mutation()

    def test_mismatched_native_profile_is_rejected(self):
        self.write(self.profile, "# stale package profile\n")
        self.rejects_without_mutation()

    def test_sudo_invoking_uid_is_allowed_only_when_running_as_root(self):
        with mock.patch.dict(os.environ, {"SUDO_UID": "12345"}):
            with mock.patch.object(MODULE.os, "getuid", return_value=0):
                self.assertEqual(MODULE.allowed_owners(), {0, 12345})
            with mock.patch.object(MODULE.os, "getuid", return_value=22222):
                self.assertEqual(MODULE.allowed_owners(), {0, 22222})

    def test_missing_parameters_are_rejected_before_writes(self):
        self.parameters.unlink()
        self.rejects_without_mutation()

    def test_saved_target_and_direct_device_are_checked(self):
        for text in ("--network usb0 edge-ai-nano-8g external\n",
                     "--direct sda %s external\n" % self.target,
                     "--network 'usb0;touch /tmp/unwanted' %s external\n" %
                     self.target,
                     "--external-only %s external\n" % self.target):
            with self.subTest(text=text):
                self.write(self.parameters, text)
                self.rejects_without_mutation()

    def test_bootloader_scope_rejects_external_images(self):
        self.index("external", 9, "APP", "system.img")
        self.rejects_without_mutation()

    def test_wrong_storage_type_is_rejected(self):
        self.index("internal", 9, "APP", "system.img")
        self.rejects_without_mutation()

    def test_full_scope_requires_nvme_app_and_payload(self):
        self.full()
        payload = self.kernel_flash / "images/external/system.img"
        payload.unlink()
        self.rejects_without_mutation()
        self.write(payload, "payload\n")
        self.write(self.parameters,
                   "--external-device sda1 %s external\n" % self.target)
        self.rejects_without_mutation()

    def test_initrd_count_is_checked(self):
        self.rejects_without_mutation(massflash=3)
        (self.package / "bootloader/boot1.img").unlink()
        self.rejects_without_mutation()

    def test_internal_symlink_is_preserved_not_dereferenced(self):
        link = self.kernel_flash / "l4t_create_flash_package.sh"
        link.symlink_to("l4t_initrd_flash.sh")
        self.finalize()
        with tarfile.open(self.archive) as stream:
            member = stream.getmember(self.package.name + "/" +
                                      str(link.relative_to(self.package)))
            self.assertTrue(member.issym())
            self.assertEqual(member.linkname, "l4t_initrd_flash.sh")

    def test_escaping_symlink_is_rejected(self):
        (self.package / "escape").symlink_to(self.sdk / "flash.sh")
        self.rejects_without_mutation()

    def test_repack_failure_restores_directory_and_original_archive(self):
        before = self.snapshot()
        native_open = MODULE.tarfile.open

        def broken_repack(*arguments, **kwargs):
            if len(arguments) > 1 and arguments[1] == "w:gz":
                raise OSError("fixture disk full")
            return native_open(*arguments, **kwargs)

        with mock.patch.object(MODULE.tarfile, "open", side_effect=broken_repack):
            with self.assertRaisesRegex(OSError, "disk full"):
                self.finalize()
        self.assertEqual(before, self.snapshot())

    def test_already_finalized_package_is_not_overwritten(self):
        self.finalize()
        self.rejects_without_mutation()

    def test_cli_and_python310_syntax(self):
        ast.parse(SOURCE.read_text(), feature_version=(3, 10))
        result = subprocess.run(
            ["/usr/bin/python3", "-B", str(SOURCE), "--sdk-root", str(self.sdk),
             "--target", self.target, "--scope", self.scope, "--massflash", "2",
             "--logo", "clab-logo", "--early-tty1", "0"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["massflash"], 2)


if __name__ == "__main__":
    unittest.main()
