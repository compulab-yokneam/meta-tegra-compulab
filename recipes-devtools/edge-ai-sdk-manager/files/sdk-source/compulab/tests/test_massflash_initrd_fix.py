#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Pinned patch and Bash-instance fixtures; no real flashing, sudo or devices."""
import ast
import hashlib
import importlib.util
import os
from pathlib import Path
import stat
import subprocess
import tempfile
import unittest
from unittest import mock


SOURCE = Path(__file__).resolve().parents[1] / \
    "tools/apply-massflash-initrd-fix.py"
SPEC = importlib.util.spec_from_file_location("massflash_initrd_fix", SOURCE)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
PATCH = Path(__file__).resolve().parents[2] / MODULE.PATCH_FILE

# Preserve the vendor hunk verbatim, but replace all actual extraction,
# hardware, signing and image-building operations with tiny fixture commands.
FUNCTION = b'''generate_flash_initrd()
{
\tlocal dev_instance="$1"

\tpushd "${working_dir}"

    mkdir -p "${working_dir}/initrd/usr/share"
    mkdir "${working_dir}/initrd/usr/share/misc"
    printf 'instance=%s\\n' "$dev_instance" >> \
        "${working_dir}/initrd/initrd_flash.cfg"
    mock_sign_bootimg
    printf '%s\\n' "$working_dir" >> "$RECORDINGS"
    popd
}
'''


class MassflashInitrdFixTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="massflash-initrd-fix-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.sdk = self.root / "sdk"
        self.sdk.mkdir()
        self.target = self.sdk / MODULE.VENDOR_FILE
        self.target.parent.mkdir(parents=True)
        self.target.write_bytes(FUNCTION)
        self.target.chmod(0o775)
        self.patch = self.sdk / MODULE.PATCH_FILE
        self.patch.parent.mkdir(parents=True)
        self.patch.write_bytes(PATCH.read_bytes())
        self.backup = self.sdk / MODULE.BACKUP_FILE
        self.original = FUNCTION
        self.updated = MODULE.patched_payload(FUNCTION, self.patch.read_bytes())
        # The production constants still pin the complete proprietary vendor
        # script. Unit fixtures use a tiny substitute, never ship that script.
        hashes = mock.patch.multiple(
            MODULE, BEFORE_SHA256=hashlib.sha256(FUNCTION).hexdigest(),
            AFTER_SHA256=hashlib.sha256(self.updated).hexdigest())
        hashes.start()
        self.addCleanup(hashes.stop)

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

    def rejects_without_mutation(self, operation, *arguments):
        before = self.snapshot()
        with self.assertRaises((OSError, ValueError)):
            operation(*(arguments or (self.sdk,)))
        self.assertEqual(before, self.snapshot())

    def shell(self, function, operations):
        script = function.decode() + r'''
set -euo pipefail
working_dir="$FIXTURE_ROOT/work"
mkdir -p "$working_dir"
parent_working_dir=$working_dir
mock_sign_bootimg() {
    printf '%s\n' "$working_dir" >> "$SIGN_RECORDINGS"
}
''' + operations
        return subprocess.run(
            ["/bin/bash", "--noprofile", "--norc", "-c", script],
            env={"PATH": "/usr/bin:/bin", "LC_ALL": "C",
                 "FIXTURE_ROOT": str(self.root),
                 "RECORDINGS": str(self.root / "trees.txt"),
                 "SIGN_RECORDINGS": str(self.root / "sign-trees.txt")},
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            timeout=10)

    def test_patch_has_the_reviewed_hash_and_one_hunk(self):
        self.assertEqual(hashlib.sha256(self.patch.read_bytes()).hexdigest(),
                         MODULE.PATCH_SHA256)
        self.assertEqual(self.patch.read_bytes().count(b"\n@@ "), 1)

    def test_original_reproduces_second_instance_directory_failure(self):
        result = self.shell(FUNCTION, "generate_flash_initrd 0\n"
                            "generate_flash_initrd 1\n")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("File exists", result.stderr)

    def test_patch_isolates_distinct_and_repeated_instance_numbers(self):
        result = self.shell(self.updated, r'''
generate_flash_initrd 0
generate_flash_initrd 1
generate_flash_initrd 0
test "$working_dir" = "$parent_working_dir"
''')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        paths = (self.root / "trees.txt").read_text().splitlines()
        self.assertEqual(len(paths), 3)
        self.assertEqual(len(set(paths)), 3)
        self.assertEqual(paths,
                         (self.root / "sign-trees.txt").read_text().splitlines())
        for path, number in zip(paths, (0, 1, 0)):
            directory = Path(path)
            self.assertEqual(directory.parent, self.root / "work")
            self.assertEqual((directory / "initrd/initrd_flash.cfg").read_text(),
                             "instance=%d\n" % number)

    def test_one_instance_remains_supported(self):
        result = self.shell(self.updated, "generate_flash_initrd 0\n")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_default_five_device_batch_has_independent_configs(self):
        result = self.shell(self.updated, r'''
for instance in 0 1 2 3 4; do generate_flash_initrd "$instance"; done
test "$working_dir" = "$parent_working_dir"
''')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        paths = (self.root / "trees.txt").read_text().splitlines()
        self.assertEqual(len(set(paths)), 5)
        for number, path in enumerate(paths):
            config = Path(path) / "initrd/initrd_flash.cfg"
            self.assertEqual(config.read_text(), "instance=%d\n" % number)

    def test_failed_mktemp_does_not_change_global_working_directory(self):
        result = self.shell(self.updated, r'''
mktemp() { return 73; }
before_pwd=$PWD
if generate_flash_initrd 0; then exit 71; else status=$?; fi
test "$status" = 73
test "$PWD" = "$before_pwd"
test "$working_dir" = "$parent_working_dir"
''')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse((self.root / "trees.txt").exists())

    def test_apply_preserves_vendor_backup_and_executable_mode(self):
        result = MODULE.apply_fix(self.sdk)
        self.assertEqual(result["status"], "applied")
        self.assertEqual(self.target.read_bytes(), self.updated)
        self.assertEqual(self.backup.read_bytes(), self.original)
        self.assertEqual(stat.S_IMODE(self.backup.stat().st_mode), 0o444)
        self.assertEqual(stat.S_IMODE(self.target.stat().st_mode), 0o775)
        self.assertEqual(MODULE.verify_fix(self.sdk)["status"], "verified")

    def test_apply_is_idempotent(self):
        MODULE.apply_fix(self.sdk)
        before = self.snapshot()
        self.assertEqual(MODULE.apply_fix(self.sdk)["status"], "verified")
        self.assertEqual(before, self.snapshot())

    def test_readonly_verify_accepts_foreign_nfs_owners_without_writes(self):
        MODULE.apply_fix(self.sdk)
        before = self.snapshot()
        # Every fixture file now has an owner unknown to the verifier,
        # modeling mismatched client/server numeric UIDs without chown.
        with mock.patch.object(MODULE, "owners", return_value=set()):
            result = MODULE.verify_fix(self.sdk)
        self.assertEqual(result["status"], "verified")
        self.assertEqual(before, self.snapshot())

    def test_readonly_foreign_owner_does_not_bypass_checksums(self):
        MODULE.apply_fix(self.sdk)
        for path in (self.target, self.patch, self.backup):
            with self.subTest(path=path.name):
                original = path.read_bytes()
                mode = stat.S_IMODE(path.stat().st_mode)
                path.chmod(mode | stat.S_IWUSR)
                path.write_bytes(original + b"# changed content\n")
                try:
                    with mock.patch.object(MODULE, "owners",
                                           return_value=set()):
                        self.rejects_without_mutation(MODULE.verify_fix)
                finally:
                    path.write_bytes(original)
                    path.chmod(mode)

    def test_readonly_foreign_owner_does_not_allow_symlinks(self):
        MODULE.apply_fix(self.sdk)
        outside = self.root / "linked-sdk-input"
        for path in (self.target, self.patch, self.backup):
            with self.subTest(path=path.name):
                path.rename(outside)
                path.symlink_to(outside)
                try:
                    with mock.patch.object(MODULE, "owners",
                                           return_value=set()):
                        self.rejects_without_mutation(MODULE.verify_fix)
                finally:
                    path.unlink()
                    outside.rename(path)

    def test_readonly_foreign_owner_does_not_allow_hardlinks(self):
        MODULE.apply_fix(self.sdk)
        outside = self.root / "hardlinked-sdk-input"
        for path in (self.target, self.patch, self.backup):
            with self.subTest(path=path.name):
                os.link(path, outside)
                try:
                    with mock.patch.object(MODULE, "owners",
                                           return_value=set()):
                        self.rejects_without_mutation(MODULE.verify_fix)
                finally:
                    outside.unlink()

    def test_apply_rejects_foreign_owners_before_writes(self):
        with mock.patch.object(MODULE, "owners", return_value=set()):
            self.rejects_without_mutation(MODULE.apply_fix)
        self.assertFalse(self.backup.exists())

    def test_apply_still_checks_owners_for_already_patched_script(self):
        MODULE.apply_fix(self.sdk)
        with mock.patch.object(MODULE, "owners", return_value=set()):
            self.rejects_without_mutation(MODULE.apply_fix)

    def test_already_patched_apply_still_checks_backup_owner(self):
        MODULE.apply_fix(self.sdk)
        regular = MODULE.regular

        def foreign_backup(path, *, check_owner=True):
            if path == self.backup and check_owner:
                raise ValueError("Unexpected owner of SDK patch input")
            return regular(path, check_owner=check_owner)

        with mock.patch.object(MODULE, "regular", side_effect=foreign_backup):
            self.assertEqual(MODULE.verify_fix(self.sdk)["status"], "verified")
            self.rejects_without_mutation(MODULE.apply_fix)

    def test_verify_rejects_unpatched_script_without_writes(self):
        self.rejects_without_mutation(MODULE.verify_fix)

    def test_unrecognized_vendor_script_is_not_patched(self):
        self.target.write_bytes(FUNCTION + b"# unexpected vendor update\n")
        self.rejects_without_mutation(MODULE.apply_fix)

    def test_patch_tampering_is_rejected_without_writes(self):
        self.patch.write_bytes(self.patch.read_bytes() + b"# tampering\n")
        self.rejects_without_mutation(MODULE.apply_fix)

    def test_existing_unknown_backup_is_not_overwritten(self):
        self.backup.write_bytes(b"unrecognized backup\n")
        self.rejects_without_mutation(MODULE.apply_fix)

    def test_existing_valid_backup_can_finish_interrupted_install(self):
        self.backup.write_bytes(self.original)
        MODULE.apply_fix(self.sdk)
        self.assertEqual(self.backup.read_bytes(), self.original)
        self.assertEqual(self.target.read_bytes(), self.updated)

    def test_modified_patched_script_is_not_accepted(self):
        MODULE.apply_fix(self.sdk)
        self.target.write_bytes(self.updated + b"# unexpected modification\n")
        self.rejects_without_mutation(MODULE.verify_fix)
        self.rejects_without_mutation(MODULE.apply_fix)

    def test_patched_script_requires_matching_original_backup(self):
        self.target.write_bytes(self.updated)
        self.rejects_without_mutation(MODULE.verify_fix)
        self.rejects_without_mutation(MODULE.apply_fix)

    def test_symlinked_sdk_target_and_backup_are_rejected(self):
        alias = self.root / "sdk-alias"
        alias.symlink_to(self.sdk, target_is_directory=True)
        self.rejects_without_mutation(MODULE.apply_fix, alias)
        outside = self.root / "original.sh"
        self.target.rename(outside)
        self.target.symlink_to(outside)
        self.rejects_without_mutation(MODULE.apply_fix)
        self.target.unlink()
        self.target.write_bytes(self.original)
        self.backup.symlink_to(outside)
        self.rejects_without_mutation(MODULE.apply_fix)

    def test_atomic_target_replace_failure_retains_original_and_backup(self):
        original_replace = MODULE.os.replace

        def fail_target_replace(source, destination):
            if Path(destination) == self.target:
                raise OSError("fixture replacement failure")
            return original_replace(source, destination)

        with mock.patch.object(MODULE.os, "replace",
                               side_effect=fail_target_replace):
            with self.assertRaisesRegex(OSError, "replacement failure"):
                MODULE.apply_fix(self.sdk)
        self.assertEqual(self.target.read_bytes(), self.original)
        self.assertEqual(self.backup.read_bytes(), self.original)
        self.assertFalse(list(self.sdk.rglob(".compulab-massflash-initrd-*")))

    def test_python310_syntax_and_cli_requires_explicit_action(self):
        ast.parse(SOURCE.read_text(), feature_version=(3, 10))
        before = self.snapshot()
        result = subprocess.run(
            ["/usr/bin/python3", "-B", str(SOURCE), "--sdk-root", str(self.sdk)],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            timeout=10)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(before, self.snapshot())


if __name__ == "__main__":
    unittest.main()
