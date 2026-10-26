#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Temporary-fixture checks; no mounts, target code, sudo or USB operations."""
import gzip
import hashlib
import importlib.util
import json
from pathlib import Path
import stat
import tempfile
import unittest
from unittest import mock

SOURCE = Path(__file__).resolve().parents[1] / "tools/verify-flash-inputs.py"
SPEC = importlib.util.spec_from_file_location("flash_inputs_fixture", SOURCE)
VERIFY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VERIFY)
RELEASE = "6.8.12-l4t-r39.2.1-1021.21-clab-adi-v18"


def checksum(data):
    return hashlib.sha256(data).hexdigest()


def cpio(entries):
    output = bytearray()
    for index, (name, data, mode) in enumerate([
            *entries, ("TRAILER!!!", b"", stat.S_IFREG | 0o644)]):
        encoded = name.encode() + b"\0"
        fields = (index, mode, 0, 0, 1, 0, len(data), 0, 0, 0, 0,
                  len(encoded), 0)
        output.extend(b"070701" + "".join("%08x" % v for v in fields).encode())
        output.extend(encoded)
        output.extend(b"\0" * ((-len(output)) % 4))
        output.extend(data)
        output.extend(b"\0" * ((-len(output)) % 4))
    return bytes(output)


def regular(name, data):
    return (name, data, stat.S_IFREG | 0o644)


class FlashInputTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="edge-ai-flash-inputs-")
        self.addCleanup(temporary.cleanup)
        self.sdk = Path(temporary.name)
        self.root = self.sdk / "rootfs"
        self.stock = self.root / "boot/initrd.nvidia-stock"
        self.runtime = self.root / "boot/initrd"
        self.base_entries = [regular("init", b"trusted-init"),
                             regular("usr/bin/busybox", b"trusted-busybox")]
        self.modules = {"kernel/" + name: checksum(name.encode())
                        for name in VERIFY.REQUIRED_MODULES}
        self.module_entries = [regular("usr/lib/modules/" + RELEASE + "/" + path,
                                       Path(path).name.encode())
                               for path in sorted(self.modules)]
        for path in self.modules:
            self.write("rootfs/usr/lib/modules/" + RELEASE + "/" + path, Path(path).name)
        self.entries = self.base_entries + self.module_entries
        self.write("rootfs/boot/initrd.nvidia-stock", gzip.compress(cpio(self.base_entries), mtime=1))
        self.update_initrd(self.entries)

    def write(self, name, data):
        path = self.sdk / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data.encode() if isinstance(data, str) else data)
        path.chmod(0o644)
        return path

    def update_initrd(self, entries, mtime=77):
        self.entries = entries
        data = gzip.compress(cpio(entries), mtime=mtime)
        self.write("rootfs/boot/initrd", data)
        self.write("bootloader/l4t_initrd.img", data)

    def initrd_check(self):
        return VERIFY.verify_initrd(self.runtime, RELEASE, self.modules,
                                    self.stock, self.root)

    def firmware(self):
        images, capsules = {}, {}
        for machine in VERIFY.MACHINES:
            for style in VERIFY.STYLES:
                stem = "compulab-%s-%s" % (machine, style)
                for name in ("bootloader/uefi_bins/" + stem + "-uefi.bin",
                             "bootloader/uefi_bins/" + stem + "-rcm.bin",
                             "bootloader/" + stem + "-tos.img",
                             "bootloader/" + stem + "-BOOTAA64.efi"):
                    data = name.encode()
                    self.write(name, data)
                    images[name] = checksum(data)
                name = machine + "-uefi-" + style + ".cap"
                capsules[name] = checksum(name.encode())
                self.write("rootfs/usr/share/compulab/uefi-update-capsules/" + name, name)
        self.write("compulab/boot/SHA256SUMS.firmware", "".join(
            "%s  %s\n" % (value, name) for name, value in images.items()))
        self.write("rootfs/usr/share/compulab/uefi-update-capsules/SHA256SUMS", "".join(
            "%s  %s\n" % (value, name) for name, value in capsules.items()))

    def full_sdk(self, old=False):
        self.write("flash.sh", "fixture, never executed\n")
        self.write("rootfs/etc/os-release", 'ID=ubuntu\nVERSION_ID="24.04"\n')
        self.write("rootfs/etc/nv_tegra_release", "# R39 (release), REVISION: 2.1, EABI: aarch64\n")
        image = self.write("kernel/Image", b"matched-image")
        self.write("rootfs/boot/Image", image.read_bytes())
        self.write("compulab/kernel-release.txt", RELEASE + "\n")
        receipt = {"l4t_version": "39.2.1", "kernel_release": RELEASE,
                   "image_sha256": VERIFY.digest(image), "modules": self.modules,
                   "module_count": len(self.modules), "initrd_sha256": "0" * 64}
        manifest = self.write("compulab/kernel-manifest.json", json.dumps(receipt))
        for path in self.modules:
            self.write("rootfs/usr/lib/modules/" + RELEASE + "/" + path, Path(path).name)
        checker = self.write("compulab/tools/check-module-abi.py",
            "def audit(*args):\n    return {'errors': [], 'imports': 17}\n")
        suffix = ".txt" if old else ""
        for name in ("base-Module.symvers", "oot-Module.symvers"):
            (self.sdk / "compulab/kernel" / (name + ("" if old else ".txt"))).unlink(missing_ok=True)
        symvers = [self.write("compulab/kernel/" + name + suffix, "fixture\n")
                   for name in ("base-Module.symvers", "oot-Module.symvers")]
        baseline = self.write("SDK_BASELINE.json", json.dumps({"sha256": {
            "rootfs/boot/initrd": VERIFY.digest(self.stock),
            "flash.sh": VERIFY.digest(self.sdk / "flash.sh")}}))
        self.write("rootfs/boot/extlinux/extlinux.conf",
                   "DEFAULT primary\nLABEL primary\nLINUX /boot/Image\n"
                   "INITRD /boot/initrd\nAPPEND ${cbootargs} root=PARTUUID=new\n")
        self.firmware()
        files = [manifest, checker, baseline, image, *symvers]
        recorded = {str(path.relative_to(self.sdk)): VERIFY.digest(path) for path in files}
        recorded.update({name: "f" * 64 for name in VERIFY.MUTABLE})
        if old:
            self.write("compulab/kernel/verification.json", json.dumps({
                "source_sha256": recorded,
                "installed_sha256": {"rootfs/boot/Image": VERIFY.digest(image)}}))
        else:
            self.write("compulab/integration-files.json", json.dumps(recorded))

    def digest_without_file_digest(self, data):
        path = self.write("digest-payload.bin", data)
        expected = hashlib.sha256(data).hexdigest()
        with mock.patch.dict(hashlib.__dict__):
            # Simulate the standard-library API available on Python 3.10.
            hashlib.__dict__.pop("file_digest", None)
            self.assertFalse(hasattr(hashlib, "file_digest"))
            self.assertEqual(VERIFY.digest(path), expected)

    def test_digest_empty_file_without_python311_helper(self):
        self.digest_without_file_digest(b"")

    def test_digest_binary_file_without_python311_helper(self):
        self.digest_without_file_digest(bytes(range(256)) + b"\0\xff\r\n")

    def test_digest_multichunk_file_without_python311_helper(self):
        # Cross two 1-MiB read boundaries and include an incomplete last chunk.
        self.digest_without_file_digest(bytes(range(256)) * 8192 + b"tail\0")

    def test_complete_verification_without_python311_hashlib_api(self):
        available_before = hasattr(hashlib, "file_digest")
        with mock.patch.dict(hashlib.__dict__):
            hashlib.__dict__.pop("file_digest", None)
            for old in (False, True):
                with self.subTest(old=old):
                    self.full_sdk(old)
                    result = VERIFY.verify(self.sdk)
                    self.assertEqual(result["module_count"], 5)
                    self.assertEqual(result["initrd_modules"], 5)
                    if not old:
                        (self.sdk / "compulab/integration-files.json").unlink()
        self.assertEqual(hasattr(hashlib, "file_digest"), available_before)

    def test_regenerated_container_metadata_is_allowed(self):
        before = self.runtime.read_bytes()
        self.update_initrd(self.entries, mtime=900)
        self.assertNotEqual(before, self.runtime.read_bytes())
        self.assertEqual(self.initrd_check(), 5)

    def test_module_payload_corruption_rejected(self):
        changed = self.entries[:-1] + [regular(self.entries[-1][0], b"bad")]
        self.update_initrd(changed)
        with self.assertRaisesRegex(ValueError, "module checksum"):
            self.initrd_check()

    def test_unrecorded_or_wrong_release_modules_rejected(self):
        for name in ("usr/lib/modules/" + RELEASE + "/kernel/evil.ko",
                     "usr/lib/modules/stock/kernel/evil.ko"):
            with self.subTest(name=name):
                self.update_initrd(self.base_entries + self.module_entries + [regular(name, b"evil")])
                with self.assertRaises(ValueError):
                    self.initrd_check()

    def test_required_boot_modules_cannot_disappear(self):
        self.update_initrd(self.entries[:-1])
        with self.assertRaisesRegex(ValueError, "required"):
            self.initrd_check()

    def test_initrd_boot_program_cannot_be_replaced_by_rootfs_copy(self):
        self.write("rootfs/init", b"evil-init")
        self.update_initrd([regular("init", b"evil-init"), *self.entries[1:]])
        with self.assertRaisesRegex(ValueError, "userspace payload"):
            self.initrd_check()

    def test_initrd_boot_program_permissions_cannot_silently_change(self):
        self.update_initrd([("init", b"trusted-init", stat.S_IFREG | 0o777),
                            *self.entries[1:]])
        with self.assertRaisesRegex(ValueError, "mode/ownership"):
            self.initrd_check()

    def test_unknown_userspace_additions_rejected_even_if_rootfs_has_file(self):
        self.write("rootfs/usr/bin/extra", b"extra")
        self.update_initrd(self.entries + [regular("usr/bin/extra", b"extra")])
        with self.assertRaisesRegex(ValueError, "userspace payload"):
            self.initrd_check()

    def test_stock_boot_payload_cannot_disappear(self):
        self.update_initrd(self.entries[1:])
        with self.assertRaisesRegex(ValueError, "Missing stock"):
            self.initrd_check()

    def test_native_nvluks_and_modprobe_refresh_matches_rootfs(self):
        self.write("rootfs/usr/sbin/nvluks-srv-app", b"native-nvluks")
        self.write("rootfs/etc/modprobe.d/custom.conf", b"options nvethernet debug=0\n")
        self.update_initrd(self.entries + [regular("usr/sbin/nvluks-srv-app", b"native-nvluks"),
            regular("etc/modprobe.d/custom.conf", b"options nvethernet debug=0\n")])
        self.assertEqual(self.initrd_check(), 5)
        self.write("rootfs/etc/modprobe.d/custom.conf", b"changed")
        with self.assertRaises(ValueError):
            self.initrd_check()

    def test_native_absolute_to_relative_modprobe_symlink_rewrite(self):
        path = self.write("rootfs/usr/lib/linux-sound-base/noOSS.modprobe.conf", b"blacklist foo\n")
        link = self.sdk / "rootfs/etc/modprobe.d/blacklist-oss.conf"
        link.parent.mkdir(parents=True)
        link.symlink_to("/lib/linux-sound-base/noOSS.modprobe.conf")
        self.update_initrd(self.entries + [
            ("etc/modprobe.d/blacklist-oss.conf",
             b"../../usr/lib/linux-sound-base/noOSS.modprobe.conf", stat.S_IFLNK | 0o777),
            regular("usr/lib/linux-sound-base/noOSS.modprobe.conf", path.read_bytes())])
        self.assertEqual(self.initrd_check(), 5)

    def test_module_indices_must_match_current_module_tree(self):
        name = "usr/lib/modules/" + RELEASE + "/modules.dep"
        self.write("rootfs/" + name, b"module deps\n")
        self.update_initrd(self.entries + [regular(name, b"module deps\n")])
        self.assertEqual(self.initrd_check(), 5)
        self.write("rootfs/" + name, b"different\n")
        with self.assertRaisesRegex(ValueError, "module index"):
            self.initrd_check()

    def test_parser_rejects_escaping_names_duplicate_files_and_extra_archive(self):
        for entries in ([regular("../outside", b"x")], [regular("/outside", b"x")],
                        [regular("init", b"x"), regular("init", b"x")]):
            with self.subTest(entries=entries):
                with self.assertRaises(ValueError):
                    VERIFY.read_cpio(cpio(entries))
        with self.assertRaisesRegex(ValueError, "after initrd"):
            VERIFY.read_cpio(cpio([regular("init", b"x")]) + b"hidden")

    def test_parser_allows_only_identical_empty_directory_duplicates(self):
        directory = (".", b"", stat.S_IFDIR | 0o755)
        self.assertEqual(len(VERIFY.read_cpio(cpio([directory, directory]))), 1)
        with self.assertRaises(ValueError):
            VERIFY.read_cpio(cpio([directory, regular(".", b"x")]))

    def test_parser_rejects_hardlink_aliasing_checked_payloads(self):
        archive = bytearray(cpio([regular("init", b"trusted-init")]))
        archive[38:46] = b"00000002"  # c_nlink, not the payload/checksum.
        with self.assertRaisesRegex(ValueError, "hardlink"):
            VERIFY.read_cpio(bytes(archive))

    def test_all_firmware_and_capsules_are_required(self):
        self.firmware()
        self.assertEqual(VERIFY.verify_firmware(self.sdk), (48, 12))
        capsule = next((self.root / "usr/share/compulab/uefi-update-capsules").glob("*.cap"))
        capsule.write_bytes(b"bad")
        with self.assertRaises(ValueError):
            VERIFY.verify_firmware(self.sdk)

    def test_static_checks_skip_only_the_three_native_mutable_paths(self):
        self.write("rootfs/boot/extlinux/extlinux.conf", b"native append changed")
        self.assertEqual(VERIFY.verify_hashes(self.sdk,
            {"rootfs/boot/extlinux/extlinux.conf": "0" * 64}, VERIFY.MUTABLE), 0)
        self.write("rootfs/boot/initrd.other", b"not mutable")
        with self.assertRaises(ValueError):
            VERIFY.verify_hashes(self.sdk, {"rootfs/boot/initrd.other": "0" * 64}, VERIFY.MUTABLE)

    def test_old_and_generated_sdk_formats_verify_without_rewriting_receipts(self):
        for old in (False, True):
            with self.subTest(old=old):
                self.full_sdk(old)
                before = (self.sdk / "compulab/kernel-manifest.json").read_bytes()
                result = VERIFY.verify(self.sdk)
                self.assertEqual(result["module_count"], 5)
                self.assertEqual(result["initrd_modules"], 5)
                self.assertEqual(before, (self.sdk / "compulab/kernel-manifest.json").read_bytes())
                if not old:
                    (self.sdk / "compulab/integration-files.json").unlink()

    def test_massflash_fix_check_accepts_older_sdk_without_helper(self):
        self.assertEqual(VERIFY.verify_massflash_fix(self.sdk), 0)

    def test_massflash_fix_helper_is_invoked_read_only_with_sdk_argument(self):
        self.write("compulab/tools/apply-massflash-initrd-fix.py",
                   "from pathlib import Path\n"
                   "def verify_fix(sdk):\n"
                   "    if sdk != Path(%r):\n"
                   "        raise ValueError('wrong SDK passed to fix verifier')\n"
                   "    return {'reviewed_native_fix': True}\n" % str(self.sdk))
        before = {str(path.relative_to(self.sdk)): path.read_bytes()
                  for path in self.sdk.rglob("*") if path.is_file()}
        self.assertEqual(VERIFY.verify_massflash_fix(self.sdk), 1)
        self.assertEqual(before, {
            str(path.relative_to(self.sdk)): path.read_bytes()
            for path in self.sdk.rglob("*") if path.is_file()})

    def test_massflash_fix_verification_failure_propagates(self):
        self.write("compulab/tools/apply-massflash-initrd-fix.py",
                   "def verify_fix(sdk):\n"
                   "    raise ValueError('reviewed native hash mismatch')\n")
        with self.assertRaisesRegex(ValueError, "reviewed native hash mismatch"):
            VERIFY.verify_massflash_fix(self.sdk)

    def test_massflash_fix_helper_symlink_is_rejected(self):
        helper = self.sdk / "compulab/tools/apply-massflash-initrd-fix.py"
        helper.parent.mkdir(parents=True)
        other = self.write("fixture-massflash-fix.py",
                           "def verify_fix(sdk):\n"
                           "    raise RuntimeError('symlink must not execute')\n")
        helper.symlink_to(other)
        with self.assertRaises(ValueError):
            VERIFY.verify_massflash_fix(self.sdk)

    def test_massflash_fix_dangling_helper_symlink_is_not_an_older_sdk(self):
        helper = self.sdk / "compulab/tools/apply-massflash-initrd-fix.py"
        helper.parent.mkdir(parents=True)
        helper.symlink_to(self.sdk / "missing-massflash-fix.py")
        with self.assertRaises(ValueError):
            VERIFY.verify_massflash_fix(self.sdk)

    def test_full_flash_input_verification_checks_native_massflash_fix(self):
        self.full_sdk()
        self.write("compulab/tools/apply-massflash-initrd-fix.py",
                   "def verify_fix(sdk):\n"
                   "    raise ValueError('native massflash fix is not verified')\n")
        with self.assertRaisesRegex(ValueError, "native massflash fix"):
            VERIFY.verify(self.sdk)

    def test_mismatched_runtime_recovery_and_unrelated_static_drift_fail(self):
        self.full_sdk()
        recovery = self.sdk / "bootloader/l4t_initrd.img"
        original = recovery.read_bytes()
        recovery.write_bytes(b"different")
        with self.assertRaisesRegex(ValueError, "initrds differ"):
            VERIFY.verify(self.sdk)
        recovery.write_bytes(original)
        self.write("kernel/Image", b"bad")
        with self.assertRaisesRegex(ValueError, "checksum mismatch"):
            VERIFY.verify(self.sdk)

    def test_menu_default_and_each_boot_entry_are_checked(self):
        self.full_sdk()
        path = self.root / "boot/extlinux/extlinux.conf"
        self.assertEqual(VERIFY.verify_menu(self.root), 2)
        for text in ("DEFAULT missing\nLABEL primary\nLINUX /boot/Image\nINITRD /boot/initrd\n",
                     "DEFAULT primary\nLABEL primary\nLINUX /boot/Image\n",
                     "DEFAULT primary\nLABEL primary\nLINUX /etc/passwd\nINITRD /boot/initrd\n"):
            with self.subTest(text=text):
                path.write_text(text)
                with self.assertRaises(ValueError):
                    VERIFY.verify_menu(self.root)


if __name__ == "__main__":
    unittest.main()
