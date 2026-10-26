#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Read-only flash-input checks, allowing native initrd/menu regeneration.

The immutable SDK snapshot verifier remains unchanged. This check validates
its static inventories plus the actual regenerated initrd payload; it never
updates a receipt, mounts a filesystem, runs target code or accesses a DUT.
"""
import argparse
import gzip
import hashlib
import importlib.util
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import sys

MACHINES = ("edge-ai-nx-16g", "edge-ai-nx-8g", "edge-ai-nano-8g", "edge-ai-nano-4g")
STYLES = ("clab-logo", "nvidia-logo", "no-logo")
MUTABLE = frozenset(("rootfs/boot/initrd", "bootloader/l4t_initrd.img",
                     "rootfs/boot/extlinux/extlinux.conf"))
REQUIRED_MODULES = frozenset(("nvme.ko", "nvme-core.ko", "pcie-tegra194.ko",
                              "phy-tegra194-p2u.ko", "nvethernet.ko"))


def require(value, message):
    if not value:
        raise ValueError(message)


def digest(path):
    # Flash hosts may use Python 3.10, before hashlib.file_digest was added.
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def relative_name(name):
    require(isinstance(name, str) and name and "\x00" not in name,
            "Invalid relative input name")
    value = PurePosixPath(name)
    require(not value.is_absolute() and ".." not in value.parts,
            "Input path escapes its root: " + name)
    return value.as_posix()


def safe_path(root, name):
    path = root / relative_name(name)
    require(path.resolve().is_relative_to(root.resolve()),
            "Input symlink escapes its root: " + name)
    return path


def verify_hashes(root, inventory, mutable=()):
    require(isinstance(inventory, dict) and inventory, "Missing checksum inventory")
    count = 0
    for name, expected in inventory.items():
        relative_name(name)
        require(isinstance(expected, str) and re.fullmatch(r"[0-9a-f]{64}", expected),
                "Invalid checksum: " + name)
        if name in mutable:
            continue
        path = safe_path(root, name)
        require(path.is_file() and digest(path) == expected,
                "Static input checksum mismatch: " + name)
        count += 1
    return count


def read_cpio(data):
    """Parse one newc archive without extracting or trusting its paths."""
    result = {}
    offset = 0
    while offset + 110 <= len(data):
        require(data[offset:offset + 6] in (b"070701", b"070702"),
                "Unsupported or malformed initrd cpio header")
        try:
            values = [int(data[offset + 6 + i * 8:offset + 14 + i * 8], 16)
                      for i in range(13)]
        except ValueError as error:
            raise ValueError("Malformed initrd cpio fields") from error
        size, length = values[6], values[11]
        require(length > 0 and offset + 110 + length <= len(data),
                "Truncated initrd cpio filename")
        raw_name = data[offset + 110:offset + 110 + length]
        require(raw_name[-1:] == b"\0", "Unterminated initrd cpio filename")
        name = raw_name[:-1].decode("utf-8")
        begin = (offset + 110 + length + 3) & ~3
        require(begin + size <= len(data), "Truncated initrd member: " + name)
        offset = (begin + size + 3) & ~3
        if name == "TRAILER!!!":
            require(size == 0, "Invalid initrd cpio trailer")
            require(not any(data[offset:]), "Unexpected data after initrd archive")
            return result
        name = relative_name(name.removeprefix("./"))
        kind = stat.S_IFMT(values[1])
        require(kind in (stat.S_IFREG, stat.S_IFDIR, stat.S_IFLNK,
                         stat.S_IFCHR, stat.S_IFBLK, stat.S_IFIFO),
                "Unsupported initrd member type: " + name)
        require(kind == stat.S_IFDIR or values[4] == 1,
                "Unsupported initrd hardlink: " + name)
        entry = {"kind": kind, "data": data[begin:begin + size],
                 "device": (values[9], values[10]),
                 "mode": stat.S_IMODE(values[1]), "uid": values[2], "gid": values[3]}
        if name in result:
            # NVIDIA's original archive repeats some empty directory entries.
            # Duplicate files/links or type changes could shadow checked data.
            require(kind == stat.S_IFDIR and not entry["data"] and
                    entry == result[name], "Duplicate initrd member: " + name)
        result[name] = entry
    raise ValueError("Missing initrd cpio trailer")


def canonical(name):
    return "usr/" + name if name.startswith(("lib/", "bin/", "sbin/")) else name


def link_destination(name, payload):
    link = payload.decode("utf-8")
    require(link and "\x00" not in link, "Invalid initrd symlink")
    target = PurePosixPath(link.lstrip("/")) if link.startswith("/") else \
        PurePosixPath(name).parent / link
    parts = []
    for part in target.parts:
        if part == "..":
            require(parts, "Initrd symlink escapes root")
            parts.pop()
        elif part != ".":
            parts.append(part)
    return canonical("/".join(parts))


def rootfs_member(root, name):
    """Get a known rootfs payload without following an absolute leaf link."""
    path = root / relative_name(name)
    require(path.parent.resolve().is_relative_to(root.resolve()),
            "Rootfs parent escapes SDK: " + name)
    attributes = path.lstat() if path.exists() or path.is_symlink() else None
    metadata = {"mode": stat.S_IMODE(attributes.st_mode), "uid": 0, "gid": 0} \
        if attributes else {}
    if path.is_symlink():
        return {"kind": stat.S_IFLNK, "data": os.readlink(path).encode(), **metadata}
    if path.is_file():
        require(path.resolve().is_relative_to(root.resolve()), "External rootfs file: " + name)
        return {"kind": stat.S_IFREG, "data": path.read_bytes(), **metadata}
    if path.is_dir():
        return {"kind": stat.S_IFDIR, "data": b"", **metadata}
    return None


def verify_initrd(path, release, modules, stock, rootfs):
    """Check modules, unchanged stock userspace and specific native refreshes."""
    current = read_cpio(gzip.decompress(path.read_bytes()))
    baseline = read_cpio(gzip.decompress(stock.read_bytes()))
    baseline_names = {canonical(name): entry for name, entry in baseline.items()}
    seen = set()
    # nv-update-initrd refreshes modprobe configs. Symlink targets such as
    # linux-sound-base/noOSS.modprobe.conf may be copied by hook-functions too.
    refreshed = {"usr/sbin/nvluks-srv-app"}
    for folder in ("etc/modprobe.d", "usr/lib/modprobe.d"):
        refreshed.add(folder)
        for source in (rootfs / folder).glob("*.conf"):
            name = str(source.relative_to(rootfs))
            refreshed.add(name)
            if source.is_symlink():
                target_name = link_destination(name, os.readlink(source).encode())
                refreshed.add(target_name)
                refreshed.update(str(parent) for parent in PurePosixPath(target_name).parents
                                 if str(parent) != ".")
    for name, entry in current.items():
        normalized = canonical(name)
        if normalized == "usr/lib/modules":
            require(entry["kind"] == stat.S_IFDIR and not entry["data"],
                    "Unexpected initrd module container")
            continue
        if "/modules/" in normalized:
            match = re.fullmatch(r"usr/lib/modules/([^/]+)(?:/(.+))?", normalized)
            require(match and match[1] == release, "Wrong initrd module release: " + name)
            relative = match[2]
            if entry["kind"] == stat.S_IFDIR:
                require(not entry["data"], "Unexpected directory payload: " + name)
                continue
            require(relative, "Invalid module tree entry")
            if relative.endswith(".ko"):
                require(entry["kind"] == stat.S_IFREG and relative in modules,
                        "Unrecorded initrd module: " + name)
                require(hashlib.sha256(entry["data"]).hexdigest() == modules[relative],
                        "Initrd module checksum mismatch: " + name)
                require(entry["uid"] == 0 and entry["gid"] == 0 and
                        entry["mode"] == stat.S_IMODE((rootfs / normalized).stat().st_mode),
                        "Initrd module mode/ownership mismatch: " + name)
                seen.add(Path(relative).name)
            else:
                require("/" not in relative and relative.startswith("modules."),
                        "Unexpected non-module file in initrd module tree: " + name)
                expected = rootfs_member(rootfs, normalized)
                require(expected and entry["kind"] == expected["kind"] and
                        entry["data"] == expected["data"],
                        "Initrd module index mismatch: " + name)
            continue
        if normalized in refreshed:
            expected = rootfs_member(rootfs, normalized)
        else:
            expected = baseline_names.get(normalized)
        payload_matches = expected and entry["data"] == expected["data"]
        if expected and normalized in refreshed and entry["kind"] == stat.S_IFLNK:
            # initramfs-tools rewrites absolute links into relative usrmerge
            # links. Compare their confined semantic destination, not spelling.
            payload_matches = link_destination(normalized, entry["data"]) == \
                link_destination(normalized, expected["data"])
        require(expected is not None and entry["kind"] == expected["kind"] and
                payload_matches,
                "Unexpected or changed initrd userspace payload: " + name)
        if entry["kind"] != stat.S_IFDIR:
            require(all(entry[key] == expected[key] for key in ("mode", "uid", "gid")),
                    "Initrd mode/ownership mismatch: " + name)
        if entry["kind"] in (stat.S_IFCHR, stat.S_IFBLK):
            require(entry["device"] == expected.get("device"), "Initrd device mismatch: " + name)
    require(REQUIRED_MODULES.issubset(seen), "Initrd lacks required NVMe/PCIe/network drivers")
    # Original boot logic/binaries must not disappear during regeneration.
    current_names = {canonical(name) for name in current}
    for name, entry in baseline_names.items():
        if "/modules/" not in name and name not in refreshed:
            require(name in current_names, "Missing stock initrd payload: " + name)
    return len(seen)


def checksum_manifest(path):
    result = {}
    for line in path.read_text().splitlines():
        require(re.fullmatch(r"[0-9a-f]{64} [ *].+", line), "Malformed checksum manifest: " + str(path))
        value, name = line[:64], line[66:]
        require(name not in result, "Duplicate checksum member: " + name)
        result[relative_name(name)] = value
    require(result, "Empty checksum manifest")
    return result


def verify_firmware(sdk):
    hashes = checksum_manifest(sdk / "compulab/boot/SHA256SUMS.firmware")
    expected = set()
    capsules = set()
    for machine in MACHINES:
        for style in STYLES:
            stem = "compulab-%s-%s" % (machine, style)
            expected.update(("bootloader/uefi_bins/" + stem + "-uefi.bin",
                             "bootloader/uefi_bins/" + stem + "-rcm.bin",
                             "bootloader/" + stem + "-tos.img",
                             "bootloader/" + stem + "-BOOTAA64.efi"))
            capsules.add(machine + "-uefi-" + style + ".cap")
    require(set(hashes) == expected, "All 48 matched firmware assets must be recorded")
    verify_hashes(sdk, hashes)
    directory = sdk / "rootfs/usr/share/compulab/uefi-update-capsules"
    capsule_hashes = checksum_manifest(directory / "SHA256SUMS")
    require(capsules.issubset(capsule_hashes), "Missing required module/logo capsules")
    for name in set(capsule_hashes) - capsules:
        require(any(re.fullmatch(re.escape(base[:-4]) + r"-from-[0-9a-fA-F-]{36}\.cap", name)
                    for base in capsules), "Unexpected capsule checksum member: " + name)
    verify_hashes(directory, capsule_hashes)
    return len(expected), len(capsule_hashes)


def verify_menu(rootfs):
    count = 0
    labels = {}
    default = None
    current = None
    for line in (rootfs / "boot/extlinux/extlinux.conf").read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        label = re.fullmatch(r"LABEL\s+([A-Za-z0-9_.+-]+)", line, re.I)
        if label:
            current = label[1]
            require(current not in labels, "Duplicate extlinux label: " + current)
            labels[current] = set()
            continue
        selected = re.fullmatch(r"DEFAULT\s+([A-Za-z0-9_.+-]+)", line, re.I)
        if selected:
            require(default is None, "Duplicate extlinux DEFAULT")
            default = selected[1]
            continue
        match = re.match(r"\s*(LINUX|INITRD|FDT|OVERLAYS)\s+(.+)$", line)
        if not match:
            continue
        require(current is not None and match[1] not in labels[current],
                "Duplicate or unscoped extlinux boot reference")
        labels[current].add(match[1])
        for name in match[2].split(","):
            require(name.startswith("/boot/") and safe_path(rootfs, name[1:]).is_file(),
                    "Missing or unsafe boot menu reference: " + name)
            count += 1
    require(count and default in labels, "Missing extlinux DEFAULT label")
    for label, fields in labels.items():
        require({"LINUX", "INITRD"}.issubset(fields),
                "Extlinux entry lacks kernel/initrd: " + label)
    return count


def verify_massflash_fix(sdk):
    helper = sdk / "compulab/tools/apply-massflash-initrd-fix.py"
    # Original manually prepared SDKs predate this fix. The current wrapper
    # requires the helper; their immutable inventories remain unchanged.
    if not helper.exists() and not helper.is_symlink():
        return 0
    require(helper.is_file() and not helper.is_symlink(),
            "Missing or unsafe massflash initrd fix verifier")
    specification = importlib.util.spec_from_file_location(
        "compulab_massflash_initrd_fix", helper)
    require(specification and specification.loader,
            "Massflash initrd fix verifier unavailable")
    module = importlib.util.module_from_spec(specification)
    sys.modules[specification.name] = module
    specification.loader.exec_module(module)
    module.verify_fix(sdk)
    return 1


def verify(sdk):
    sdk = sdk.resolve()
    require(sdk != Path("/") and (sdk / "flash.sh").is_file() and
            not (sdk / "rootfs").is_symlink(), "Explicit prepared SDK required")
    snapshots = 0
    old = sdk / "compulab/kernel/verification.json"
    if old.is_file():
        metadata = json.loads(old.read_text())
        snapshots += verify_hashes(sdk, metadata["source_sha256"], MUTABLE)
        snapshots += verify_hashes(sdk, metadata["installed_sha256"], MUTABLE)
    generated = sdk / "compulab/integration-files.json"
    if generated.is_file():
        snapshots += verify_hashes(sdk, json.loads(generated.read_text()), MUTABLE)
    require(snapshots, "Missing SDK static input inventory")
    rootfs = sdk / "rootfs"
    os_release = (rootfs / "etc/os-release").read_text()
    require(re.search(r"(?m)^ID=ubuntu$", os_release) and
            re.search(r'(?m)^VERSION_ID="24\.04"$', os_release), "Ubuntu Noble rootfs required")
    require(re.search(r"# R39 .*REVISION: 2\.1,", (rootfs / "etc/nv_tegra_release").read_text()),
            "L4T R39.2.1 rootfs required")
    receipt = json.loads((sdk / "compulab/kernel-manifest.json").read_text())
    release = receipt["kernel_release"]
    require(receipt["l4t_version"] == "39.2.1" and
            re.fullmatch(r"[A-Za-z0-9_.+-]+", release) and release not in (".", ".."),
            "Invalid matched kernel release")
    require((sdk / "compulab/kernel-release.txt").read_text().strip() == release,
            "Kernel readiness marker mismatch")
    verify_hashes(sdk, {"kernel/Image": receipt["image_sha256"],
                        "rootfs/boot/Image": receipt["image_sha256"]})
    modules = receipt["modules"]
    module_root = rootfs / "usr/lib/modules" / release
    actual = {str(path.relative_to(module_root)) for path in module_root.rglob("*.ko*")
              if path.is_file()}
    require(actual == set(modules) and len(actual) == receipt["module_count"],
            "Installed module inventory differs from receipt")
    verify_hashes(module_root, modules)
    kernel = sdk / "compulab/kernel"
    symvers = []
    for name in ("base-Module.symvers", "oot-Module.symvers"):
        matches = [path for path in (kernel / name, kernel / (name + ".txt")) if path.is_file()]
        require(len(matches) == 1, "Missing or ambiguous symbol table: " + name)
        symvers.append(matches[0])
    checker = sdk / "compulab/tools/check-module-abi.py"
    specification = importlib.util.spec_from_file_location("compulab_flash_abi", checker)
    require(specification and specification.loader, "ABI checker unavailable")
    abi = importlib.util.module_from_spec(specification)
    sys.modules[specification.name] = abi
    specification.loader.exec_module(abi)
    report = abi.audit([module_root], symvers, release)
    require(not report["errors"], "Module symbol CRC validation failed: " +
            "; ".join(report["errors"][:10]))
    runtime, recovery = rootfs / "boot/initrd", sdk / "bootloader/l4t_initrd.img"
    require(digest(runtime) == digest(recovery), "Runtime/recovery initrds differ")
    baseline = json.loads((sdk / "SDK_BASELINE.json").read_text())
    native = {"flash.sh": baseline["sha256"]["flash.sh"]}
    helper = "tools/kernel_flash/l4t_flash_from_kernel.sh"
    if helper in baseline["sha256"]:
        native[helper] = baseline["sha256"][helper]
    snapshots += verify_hashes(sdk, native)
    snapshots += verify_massflash_fix(sdk)
    stock = rootfs / "boot/initrd.nvidia-stock"
    expected_stock = baseline["sha256"]["rootfs/boot/initrd"]
    require(stock.is_file() and digest(stock) == expected_stock, "Stock initrd reference changed")
    initrd_modules = verify_initrd(runtime, release, modules, stock, rootfs)
    firmware_files, capsule_files = verify_firmware(sdk)
    boot_references = verify_menu(rootfs)
    return {"mode": "read-only flash inputs, not immutable snapshot",
            "kernel_release": release, "module_count": len(modules),
            "imported_crcs": report["imports"], "static_files": snapshots,
            "initrd_modules": initrd_modules, "firmware_files": firmware_files,
            "capsules": capsule_files, "boot_references": boot_references,
            "hardware_validation": "Not performed"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sdk-root", required=True, type=Path)
    args = parser.parse_args()
    try:
        print(json.dumps(verify(args.sdk_root), indent=2, sort_keys=True))
    except (ValueError, OSError, KeyError, UnicodeError, EOFError) as error:
        print("Flash input verification failed: " + str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
