#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Temporary APP metadata fixtures; no sudo, image generation or flashing."""
import ast
import hashlib
import importlib.util
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock


SOURCE = Path(__file__).resolve().parents[1] / "tools/flash_app_metadata.py"
SPEC = importlib.util.spec_from_file_location("flash_app_metadata_tests", SOURCE)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class FlashAppMetadataTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="flash-app-metadata-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.directory = self.root / "external"
        self.directory.mkdir()
        self.name = "system.img"
        self.payload = b"native APP fixture payload\n"
        self.prepare()

    def prepare(self, filename=None, content=None):
        self.name = filename or self.name
        self.payload = self.payload if content is None else content
        (self.directory / "flash.cfg").write_text(
            "APP_ext=%s\nexternal_device=nvme0n1p1\nCHIPID=0x23\n" % self.name)
        (self.directory / self.name).write_bytes(self.payload)
        value = hashlib.sha1(self.payload, usedforsecurity=False).hexdigest()
        (self.directory / (self.name + ".sha1sum")).write_text(value + "\n")

    def snapshot(self):
        values = {}
        for path in self.root.rglob("*"):
            relative = str(path.relative_to(self.root))
            if path.is_symlink():
                values[relative] = ("link", os.readlink(path))
            elif path.is_dir():
                values[relative] = ("directory",)
            else:
                values[relative] = ("file", path.read_bytes(),
                                    path.stat().st_mode)
        return values

    def rejects_without_writes(self, directory=None):
        before = self.snapshot()
        with self.assertRaises((OSError, ValueError)):
            MODULE.validate_app_payload(directory or self.directory)
        self.assertEqual(before, self.snapshot())

    def test_native_app_ext_layout_validates_without_mutation(self):
        before = self.snapshot()
        result = MODULE.validate_app_payload(self.directory)
        self.assertEqual(result["filename"], self.name)
        self.assertEqual(result["size"], len(self.payload))
        self.assertEqual(result["sha1"],
                         hashlib.sha1(self.payload).hexdigest())
        self.assertEqual(result["configuration"]["external_device"],
                         "nvme0n1p1")
        self.assertEqual(before, self.snapshot())

    def test_zst_payload_and_literal_quotes_are_supported(self):
        self.prepare(filename="system.img.zst")
        config = self.directory / "flash.cfg"
        for value in (self.name, "'" + self.name + "'", '"' + self.name + '"'):
            with self.subTest(value=value):
                config.write_text("# native generated metadata\n\n"
                                  "APP_ext=%s\nUDA_ext=''\nCHIPID=0x23\n" % value)
                result = MODULE.validate_app_payload(self.directory)
                self.assertEqual(result["filename"], self.name)

    def test_foreign_nfs_uid_does_not_prevent_readonly_verification(self):
        with mock.patch.object(MODULE.os, "getuid", return_value=987654):
            self.assertEqual(MODULE.validate_app_payload(self.directory)["size"],
                             len(self.payload))

    def test_checksum_is_streamed_in_bounded_chunks(self):
        self.prepare(content=b"abcdefghi" * 100)
        digest = mock.Mock(wraps=hashlib.sha1(usedforsecurity=False))
        with mock.patch.object(MODULE, "CHUNK_SIZE", 7), \
             mock.patch.object(MODULE.hashlib, "sha1", return_value=digest):
            result = MODULE.validate_app_payload(self.directory)
        self.assertEqual(result["size"], len(self.payload))
        self.assertGreater(digest.update.call_count, 100)
        self.assertTrue(all(len(call.args[0]) <= 7
                            for call in digest.update.call_args_list))

    def test_missing_or_empty_app_mapping_is_rejected(self):
        config = self.directory / "flash.cfg"
        for text in ("CHIPID=0x23\n", "APP_ext=\n", "APP_ext=''\n",
                     'APP_ext=""\n'):
            with self.subTest(text=text):
                config.write_text(text)
                self.rejects_without_writes()

    def test_app_mapping_must_be_a_safe_local_basename(self):
        config = self.directory / "flash.cfg"
        for value in (".", "..", "../system.img", "/tmp/system.img",
                      "folder/system.img", "system.img;id", "$(id)",
                      "`id`", "${APP}", "system*.img", "system image.img"):
            with self.subTest(value=value):
                config.write_text("APP_ext=%s\n" % value)
                self.rejects_without_writes()

    def test_shell_syntax_is_rejected_in_all_configuration_fields(self):
        config = self.directory / "flash.cfg"
        for line in ("external_device=$(id)", "external_device=`id`",
                     "CHIPID=0x23;id", "export CHIPID=0x23",
                     "source /tmp/input", "CHIPID=${OTHER}",
                     "CHIPID=\"$(id)\"", "CHIPID =0x23",
                     "CHIPID= 0x23", "[ -f /tmp/input ]", "CHIPID=0x23 # x"):
            with self.subTest(line=line):
                config.write_text("APP_ext=system.img\n" + line + "\n")
                self.rejects_without_writes()

    def test_duplicate_configuration_keys_are_rejected(self):
        config = self.directory / "flash.cfg"
        for text in ("APP_ext=system.img\nAPP_ext=system.img\n",
                     "APP_ext=system.img\nCHIPID=0x23\nCHIPID=0x23\n"):
            with self.subTest(text=text):
                config.write_text(text)
                self.rejects_without_writes()

    def test_nonascii_or_oversized_configuration_is_rejected(self):
        config = self.directory / "flash.cfg"
        for payload in (b"APP_ext=system.img\n#\xff\n",
                        b"#" + b"a" * MODULE.CONFIG_LIMIT):
            with self.subTest(size=len(payload)):
                config.write_bytes(payload)
                self.rejects_without_writes()

    def test_missing_payload_and_checksum_are_rejected(self):
        for path in (self.directory / self.name,
                     self.directory / (self.name + ".sha1sum"),
                     self.directory / "flash.cfg"):
            with self.subTest(path=path.name):
                previous = path.read_bytes()
                path.unlink()
                self.rejects_without_writes()
                path.write_bytes(previous)

    def test_empty_payload_is_rejected(self):
        (self.directory / self.name).write_bytes(b"")
        self.rejects_without_writes()

    def test_malformed_or_mismatched_checksum_is_rejected(self):
        checksum = self.directory / (self.name + ".sha1sum")
        for value in ("", "0" * 39, "g" * 40, "0" * 40,
                      "0" * 40 + "  system.img", "0" * 129):
            with self.subTest(value=value):
                checksum.write_text(value)
                self.rejects_without_writes()

    def test_uppercase_checksum_is_accepted(self):
        checksum = self.directory / (self.name + ".sha1sum")
        checksum.write_text(hashlib.sha1(self.payload).hexdigest().upper() + "\n")
        self.assertEqual(MODULE.validate_app_payload(self.directory)["size"],
                         len(self.payload))

    def test_symlinked_inputs_are_rejected(self):
        outside = self.root / "outside"
        for path in (self.directory / "flash.cfg", self.directory / self.name,
                     self.directory / (self.name + ".sha1sum")):
            with self.subTest(path=path.name):
                path.rename(outside)
                path.symlink_to(outside)
                try:
                    self.rejects_without_writes()
                finally:
                    path.unlink()
                    outside.rename(path)

    def test_hardlinked_inputs_are_rejected(self):
        outside = self.root / "hardlink"
        for path in (self.directory / "flash.cfg", self.directory / self.name,
                     self.directory / (self.name + ".sha1sum")):
            with self.subTest(path=path.name):
                os.link(path, outside)
                try:
                    self.rejects_without_writes()
                finally:
                    outside.unlink()

    def test_directory_and_parent_aliases_are_rejected(self):
        alias = self.root / "alias"
        alias.symlink_to(self.directory, target_is_directory=True)
        self.rejects_without_writes(alias)
        self.rejects_without_writes(Path("relative-path"))
        self.rejects_without_writes(self.directory / ".." / "external")

    def test_payload_replacement_or_modification_during_hashing_is_rejected(self):
        payload = self.directory / self.name
        original_hash = hashlib.sha1(usedforsecurity=False)
        digest = mock.Mock(wraps=original_hash)

        def modify(block):
            original_hash.update(block)
            payload.write_bytes(self.payload + b"changed")

        digest.update.side_effect = modify
        with mock.patch.object(MODULE.hashlib, "sha1", return_value=digest):
            with self.assertRaisesRegex(ValueError, "changed"):
                MODULE.validate_app_payload(self.directory)
        self.assertEqual(payload.read_bytes(), self.payload + b"changed")
        self.assertEqual((self.directory / (self.name + ".sha1sum")).read_text(),
                         hashlib.sha1(self.payload).hexdigest() + "\n")

    def test_python310_syntax(self):
        ast.parse(SOURCE.read_text(), feature_version=(3, 10))


if __name__ == "__main__":
    unittest.main()
