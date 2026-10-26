#!/usr/bin/env python3
"""Read-only ABI audit of NVIDIA Noble arm64 modules.

Pass --symvers in provider-precedence order: the kernel table first, then
NVIDIA's OOT table. A later table replaces *all* exports of a same-name module,
not just CRCs listed in both tables. This deliberately does not accept a CRC
union, which could hide a module compiled against an inactive provider.

Noble uses packed variable-length modversion_info records (u32 next, u32 crc,
NUL-terminated name), unlike upstream's older fixed 64-byte records. Nothing
is loaded, installed, written, or flashed. Duplicate module names are reported
because kernel/ and updates/ copies can intentionally coexist; --strict-duplicates
makes those reports fatal. This checks CRC compatibility, not depmod selection
or hardware operation. Duplicate symbol providers are also reported: NVIDIA
ships mutually exclusive nvidia/nvidia-p2p alternatives. An import is checked
against one provider, uniquely selected by its compiled modinfo dependencies;
ambiguous imports fail instead of accepting either CRC.
"""
# SPDX-License-Identifier: MIT

import argparse
from collections import Counter, defaultdict
from dataclasses import dataclass
import gzip
import lzma
from pathlib import Path
import struct
import subprocess
import sys


class AuditError(ValueError):
    """An invalid input or incompatible module."""


@dataclass(frozen=True)
class Export:
    crc: int
    provider: str


def canonical_name(value):
    return Path(value).name.replace("-", "_")


def load_symvers(paths):
    exports = {}
    replacements = set()
    for path in paths:
        rows = {}
        providers = set()
        for number, line in enumerate(path.read_text().splitlines(), 1):
            if not line.strip():
                continue
            fields = line.split()
            try:
                crc = int(fields[0], 16)
                symbol = fields[1]
                provider = canonical_name(fields[2])
                if len(fields) < 4 or not 0 <= crc <= 0xffffffff:
                    raise ValueError
            except (ValueError, IndexError) as error:
                raise AuditError(f"{path}:{number}: invalid symvers row") from error
            if provider in rows.get(symbol, {}):
                raise AuditError(f"{path}:{number}: duplicate export {symbol}")
            rows.setdefault(symbol, {})[provider] = Export(crc, provider)
            providers.add(provider)
        if not rows:
            raise AuditError(f"Empty symbol table: {path}")
        old_providers = {value.provider for values in exports.values()
                         for value in values}
        replacements.update(old_providers & providers)
        exports = {name: [value for value in values
                          if value.provider not in providers]
                   for name, values in exports.items()}
        exports = {name: values for name, values in exports.items() if values}
        for name, values in rows.items():
            exports.setdefault(name, []).extend(values.values())
    return exports, replacements


def slice_checked(data, offset, size, description):
    if offset < 0 or size < 0 or offset + size > len(data):
        raise AuditError(f"Truncated ELF {description}")
    return data[offset:offset + size]


def elf_sections(data):
    if data[:6] != b"\x7fELF\x02\x01" or len(data) < 64:
        raise AuditError("Expected an ELF64 little-endian module")
    header = struct.unpack_from("<HHIQQQIHHHHHH", data, 16)
    if header[0] != 1 or header[1] != 183:
        raise AuditError("Expected an AArch64 relocatable module")
    offset, stride, count, names_index = (
        header[5], header[10], header[11], header[12])
    if stride != 64 or not count or not 0 <= names_index < count:
        raise AuditError("Invalid ELF section table")
    table = slice_checked(data, offset, stride * count, "section table")
    sections = [struct.unpack_from("<IIQQQQIIQQ", table, i * stride)
                for i in range(count)]
    name_header = sections[names_index]
    names = slice_checked(data, name_header[4], name_header[5], "section names")
    result = {}
    for section in sections:
        name_offset = section[0]
        if name_offset >= len(names):
            raise AuditError("Invalid ELF section name offset")
        try:
            name = names[name_offset:].split(b"\0", 1)[0].decode("ascii")
        except UnicodeDecodeError as error:
            raise AuditError("Non-ASCII ELF section name") from error
        # SHT_NOBITS does not occupy bytes in the module file.
        if section[1] == 8:
            continue
        # Repeated .group and .note.GNU-stack sections are valid in ET_REL.
        if name in result and name in {".modinfo", "__versions"}:
            raise AuditError(f"Duplicate ELF section: {name}")
        result[name] = slice_checked(data, section[4], section[5], name)
    return result


def noble_versions(data):
    """Mirror Noble kernel/module/version.c's packed next-offset walk."""
    offset = 0
    seen = set()
    while offset + 8 <= len(data):
        size, crc = struct.unpack_from("<II", data, offset)
        if size == 0:
            if crc or any(data[offset + 8:]):
                raise AuditError("Malformed modversion terminator")
            return
        if size < 12 or size % 4 or offset + size > len(data):
            raise AuditError(f"Invalid packed modversion offset: {size}")
        name = data[offset + 8:offset + size]
        if b"\0" not in name:
            raise AuditError("Unterminated modversion symbol")
        try:
            symbol = name.split(b"\0", 1)[0].decode("ascii")
        except UnicodeDecodeError as error:
            raise AuditError("Non-ASCII modversion symbol") from error
        if not symbol or symbol in seen:
            raise AuditError(f"Empty or duplicate modversion symbol: {symbol}")
        seen.add(symbol)
        yield symbol, crc
        offset += size
    raise AuditError("Missing packed modversion terminator")


def module_data(path):
    if path.name.endswith(".ko.gz"):
        return gzip.decompress(path.read_bytes())
    if path.name.endswith(".ko.xz"):
        return lzma.decompress(path.read_bytes())
    if path.name.endswith(".ko.zst"):
        return subprocess.run(["zstd", "-q", "-d", "-c", str(path)],
                              check=True, stdout=subprocess.PIPE).stdout
    return path.read_bytes()


def module_name(path):
    name = path.name
    for suffix in (".gz", ".xz", ".zst"):
        if name.endswith(suffix):
            name = name[:-len(suffix)]
    return canonical_name(name.removesuffix(".ko"))


def audit(roots, tables, release, strict_duplicates=False):
    exports, replacements = load_symvers(tables)
    paths = set()
    for root in roots:
        if not root.is_dir():
            raise AuditError(f"Module root is not a directory: {root}")
        for pattern in ("*.ko", "*.ko.gz", "*.ko.xz", "*.ko.zst"):
            paths.update(path.resolve() for path in root.rglob(pattern))
    if not paths:
        raise AuditError("No kernel modules found")
    problems = []
    names = defaultdict(list)
    vermagics = Counter()
    imports = 0
    for path in sorted(paths):
        names[module_name(path)].append(str(path))
        try:
            sections = elf_sections(module_data(path))
            metadata = sections.get(".modinfo", b"").split(b"\0")
            magic = [item.split(b"=", 1)[1].decode("ascii")
                     for item in metadata if item.startswith(b"vermagic=")]
            if len(magic) != 1 or not magic[0].split():
                raise AuditError("Missing or ambiguous vermagic")
            vermagics[magic[0]] += 1
            if magic[0].split()[0] != release:
                raise AuditError(f"Expected release {release}, got {magic[0]}")
            if "modversions" not in magic[0].split():
                raise AuditError("Module was built without modversions")
            dependencies = {canonical_name(name)
                            for item in metadata if item.startswith(b"depends=")
                            for name in item.split(b"=", 1)[1].decode("ascii").split(",")
                            if name}
            versions = list(noble_versions(sections.get("__versions", b"")))
            if not versions:
                raise AuditError("No imported symbol CRCs")
            for symbol, crc in versions:
                imports += 1
                if symbol not in exports:
                    problems.append(f"{path}: unknown symbol {symbol}")
                    continue
                candidates = exports[symbol]
                if len(candidates) > 1:
                    candidates = [value for value in candidates
                                  if value.provider in dependencies or
                                  value.provider == "vmlinux"]
                if len(candidates) != 1:
                    providers = ", ".join(value.provider
                                          for value in exports[symbol])
                    problems.append(f"{path}: ambiguous symbol provider for "
                                    f"{symbol}: {providers}")
                elif candidates[0].crc != crc:
                    wanted = candidates[0]
                    problems.append(f"{path}: {symbol}: module 0x{crc:08x}, "
                                    f"provider {wanted.provider} "
                                    f"0x{wanted.crc:08x}")
        except (AuditError, OSError, lzma.LZMAError, UnicodeError, struct.error,
                subprocess.SubprocessError) as error:
            problems.append(f"{path}: {error}")
    duplicates = {name: values for name, values in names.items()
                  if len(values) > 1}
    duplicate_exports = {name: [value.provider for value in values]
                         for name, values in exports.items() if len(values) > 1}
    if len(vermagics) > 1:
        problems.append("Modules have inconsistent full vermagic strings")
    if strict_duplicates and (duplicates or duplicate_exports):
        problems.append("Duplicate module names or symbol providers present")
    return {"modules": len(paths), "imports": imports,
            "vermagics": dict(vermagics), "duplicates": duplicates,
            "duplicate_exports": duplicate_exports,
            "replaced_providers": sorted(replacements), "errors": problems}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--modules", action="append", type=Path, required=True,
                        help="module-tree root; repeat for additional roots")
    parser.add_argument("--symvers", action="append", type=Path, required=True,
                        help="symbol table; repeat, lowest precedence first")
    parser.add_argument("--release", required=True,
                        help="exact expected kernel release")
    parser.add_argument("--strict-duplicates", action="store_true",
                        help="fail also on intentional kernel/updates shadows")
    args = parser.parse_args(argv)
    try:
        result = audit(args.modules, args.symvers, args.release,
                       args.strict_duplicates)
    except (AuditError, OSError) as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1
    for name, paths in result["duplicates"].items():
        print(f"DUPLICATE {name}: {', '.join(paths)}", file=sys.stderr)
    for name, providers in result["duplicate_exports"].items():
        print(f"DUPLICATE EXPORT {name}: {', '.join(providers)}", file=sys.stderr)
    for problem in result["errors"]:
        print(f"FAIL: {problem}", file=sys.stderr)
    if result["errors"]:
        return 1
    print(f"PASS: {result['modules']} modules; {result['imports']} imported "
          f"CRCs; release {args.release}; "
          f"{len(result['duplicates'])} duplicate names reported")
    if result["replaced_providers"]:
        print("Later-table provider replacements: " +
              ", ".join(result["replaced_providers"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
