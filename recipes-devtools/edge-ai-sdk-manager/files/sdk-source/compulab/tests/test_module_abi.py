#!/usr/bin/env python3
"""Synthetic ELF fixtures for the read-only Noble module ABI checker."""
# SPDX-License-Identifier: MIT

import importlib.util
import gzip
import lzma
from pathlib import Path
import struct
import sys
import tempfile
import unittest


TOOL = Path(__file__).resolve().parents[1] / "tools/check-module-abi.py"
SPEC = importlib.util.spec_from_file_location("module_abi", TOOL)
ABI = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = ABI
SPEC.loader.exec_module(ABI)
RELEASE = "6.8.12-test-clab"


def packed_versions(values):
    output = bytearray()
    for name, crc in values:
        name = name.encode() + b"\0"
        name += b"\0" * (-len(name) % 4)
        output.extend(struct.pack("<II", len(name) + 8, crc) + name)
    return bytes(output) + b"\0" * 9


def elf_module(values, release=RELEASE, machine=183, depends="", extras=()):
    sections = [("", b""), (".shstrtab", b""),
                (".modinfo", (f"vermagic={release} SMP modversions aarch64\0"
                              f"depends={depends}\0").encode()),
                ("__versions", packed_versions(values))]
    sections.extend(extras)
    names = b"\0"
    offsets = {}
    for name, _ in sections[1:]:
        offsets[name] = len(names)
        names += name.encode() + b"\0"
    sections[1] = (".shstrtab", names)
    content = bytearray(b"\0" * 64)
    headers = []
    for name, data in sections:
        headers.append(struct.pack("<IIQQQQIIQQ", offsets.get(name, 0),
                                   3 if name == ".shstrtab" else 1,
                                   0, 0, len(content), len(data), 0, 0, 1, 0))
        content.extend(data)
    table = len(content)
    content.extend(b"".join(headers))
    content[:16] = b"\x7fELF\x02\x01\x01" + b"\0" * 9
    struct.pack_into("<HHIQQQIHHHHHH", content, 16,
                     1, machine, 1, 0, 0, table, 0, 64, 0, 0, 64,
                     len(headers), 1)
    return bytes(content)


class ModuleAbiTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.modules = self.root / "modules"
        self.modules.mkdir()
        self.table = self.root / "Module.symvers"
        self.table.write_text("0x12345678\tmodule_layout\tvmlinux\tEXPORT_SYMBOL\n")

    def module(self, values=None, name="test.ko", **kwargs):
        path = self.modules / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(elf_module(values or [("module_layout", 0x12345678)],
                                    **kwargs))
        return path

    def check(self, tables=None, strict=False):
        return ABI.audit([self.modules], tables or [self.table], RELEASE, strict)

    def test_valid_noble_module(self):
        self.module()
        result = self.check()
        self.assertEqual(result["errors"], [])
        self.assertEqual((result["modules"], result["imports"]), (1, 1))

    def test_variable_record_lengths_and_long_symbols(self):
        values = [("a", 1), ("symbol_" + "x" * 100, 2)]
        self.assertEqual(list(ABI.noble_versions(packed_versions(values))), values)

    def test_missing_terminator(self):
        with self.assertRaisesRegex(ABI.AuditError, "terminator"):
            list(ABI.noble_versions(packed_versions([("a", 1)])[:-9]))

    def test_invalid_record_offsets(self):
        for size in (1, 10, 4096):
            with self.subTest(size=size), self.assertRaises(ABI.AuditError):
                list(ABI.noble_versions(struct.pack("<II", size, 1) + b"a\0\0\0"))

    def test_duplicate_import_symbols(self):
        with self.assertRaisesRegex(ABI.AuditError, "duplicate"):
            list(ABI.noble_versions(packed_versions([("a", 1), ("a", 1)])))

    def test_unknown_symbol_fails(self):
        self.module([("unknown", 1)])
        self.assertIn("unknown symbol unknown", self.check()["errors"][0])

    def test_wrong_crc_fails(self):
        self.module([("module_layout", 1)])
        self.assertIn("module 0x00000001", self.check()["errors"][0])

    def test_release_mismatch_fails(self):
        self.module(release="6.18.39-old")
        self.assertIn("Expected release", self.check()["errors"][0])

    def test_wrong_architecture_fails(self):
        self.module(machine=62)
        self.assertIn("AArch64", self.check()["errors"][0])

    def test_repeated_non_metadata_sections_are_valid(self):
        self.module(extras=((".group", b"one"), (".group", b"two")))
        self.assertEqual(self.check()["errors"], [])

    def test_duplicate_metadata_sections_fail(self):
        self.module(extras=(("__versions", b"\0" * 9),))
        self.assertIn("Duplicate ELF section", self.check()["errors"][0])

    def test_compressed_modules(self):
        payload = elf_module([("module_layout", 0x12345678)])
        (self.modules / "one.ko.gz").write_bytes(gzip.compress(payload))
        (self.modules / "two.ko.xz").write_bytes(lzma.compress(payload))
        result = self.check()
        self.assertEqual(result["modules"], 2)
        self.assertEqual(result["errors"], [])

    def test_truncated_elf_fails(self):
        (self.modules / "bad.ko").write_bytes(b"\x7fELF")
        self.assertIn("ELF64", self.check()["errors"][0])

    def test_duplicate_module_names_reported_and_optionally_fatal(self):
        self.module(name="kernel/test.ko")
        self.module(name="updates/test.ko")
        self.assertIn("test", self.check()["duplicates"])
        self.assertEqual(self.check()["errors"], [])
        self.assertIn("Duplicate module names or symbol providers present",
                      self.check(strict=True)["errors"])

    def test_later_provider_replaces_crc_not_union(self):
        oot = self.root / "oot.symvers"
        oot.write_text("0x00000002\tmodule_layout\tvmlinux\tEXPORT_SYMBOL\n")
        self.module()
        self.assertIn("provider vmlinux 0x00000002",
                      self.check([self.table, oot])["errors"][0])

    def test_replaced_provider_drops_retired_exports(self):
        self.table.write_text("0x1\tretired\tdrivers/host1x\tEXPORT_SYMBOL\n"
                              "0x2\tcurrent\tdrivers/host1x\tEXPORT_SYMBOL\n")
        oot = self.root / "oot.symvers"
        oot.write_text("0x3\tcurrent\toot/host1x\tEXPORT_SYMBOL\n")
        exports, replaced = ABI.load_symvers([self.table, oot])
        self.assertNotIn("retired", exports)
        self.assertEqual(exports["current"][0].crc, 3)
        self.assertEqual(replaced, {"host1x"})

    def test_duplicate_export_provider_requires_unambiguous_dependency(self):
        oot = self.root / "oot.symvers"
        self.table.write_text("0x1\tshared\tdisplay\tEXPORT_SYMBOL\n")
        oot.write_text("0x2\tshared\tlegacy\tEXPORT_SYMBOL\n")
        self.module([("shared", 1)])
        result = self.check([self.table, oot])
        self.assertIn("ambiguous symbol provider", result["errors"][0])
        self.assertEqual(result["duplicate_exports"], {"shared": ["display", "legacy"]})
        self.module([("shared", 1)], depends="display")
        self.assertEqual(self.check([self.table, oot])["errors"], [])
        self.module([("shared", 2)], depends="display")
        self.assertIn("provider display 0x00000001",
                      self.check([self.table, oot])["errors"][0])

    def test_duplicate_symvers_rows_fail(self):
        self.table.write_text(self.table.read_text() * 2)
        with self.assertRaisesRegex(ABI.AuditError, "duplicate export"):
            ABI.load_symvers([self.table])

    def test_empty_module_tree_fails(self):
        with self.assertRaisesRegex(ABI.AuditError, "No kernel modules"):
            self.check()


if __name__ == "__main__":
    unittest.main()
