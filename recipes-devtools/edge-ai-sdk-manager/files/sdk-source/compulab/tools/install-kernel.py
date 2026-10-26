#!/usr/bin/env python3
"""Install a matched Yocto Noble kernel into the NVIDIA Ubuntu SDK.

The default is a read-only source check. --apply requires root and a saved
vendor baseline; it never flashes a device or installs Yocto user libraries.
"""
# SPDX-License-Identifier: MIT

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile


EXPECTED_RELEASE = "6.8.12-l4t-r39.2.1-1021.21-clab-adi-v18"


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def digest(path):
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def run(*command, cwd=None):
    subprocess.run(command, cwd=cwd, check=True)


def image_release(path):
    match = re.search(rb"Linux version ([0-9A-Za-z.+-]+) ", path.read_bytes())
    require(match is not None, f"No kernel release found in {path}")
    return match[1].decode("ascii")


def find_dtb(rootfs, name):
    candidates = [rootfs / "boot" / folder / name for folder in ("dtb", "devicetree")]
    available = [path for path in candidates if path.is_file()]
    require(available, f"Missing device tree: {name}")
    require(len({digest(path) for path in available}) == 1,
            f"Conflicting installed copies of device tree: {name}")
    return available[0]


def find_dtb_companion(rootfs, name, extension):
    # find_dtb first guarantees that every same-named raw input is identical.
    # A companion may only follow that exact raw input, never replace it.
    find_dtb(rootfs, name)
    candidates = [rootfs / "boot" / folder / name
                  for folder in ("dtb", "devicetree")]
    available = [path.with_name(name + extension) for path in candidates
                 if path.is_file() and path.with_name(name + extension).is_file()]
    if not available:
        return None
    require(len({digest(path) for path in available}) == 1,
            f"Conflicting companions of identical device trees: {name}{extension}")
    return available[0]


def atomic_copy(source, destination):
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + ".compulab-new")
    require(not temporary.exists() and not temporary.is_symlink(),
            f"Unfinished installation file exists: {temporary}")
    shutil.copyfile(source, temporary)
    temporary.chmod(0o644)
    os.replace(temporary, destination)


def write_text(destination, value):
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="w", dir=destination.parent,
                                     prefix=".compulab-", delete=False) as stream:
        stream.write(value)
        temporary = Path(stream.name)
    temporary.chmod(0o644)
    os.replace(temporary, destination)


def check_module(path):
    data = path.read_bytes()
    require(data[:4] == b"\x7fELF" and data[18:20] == b"\xb7\x00",
            f"Not an aarch64 ELF module: {path}")
    match = re.search(rb"\x00vermagic=([^\x00]+)\x00", data)
    require(match is not None, f"Module has no vermagic: {path}")
    require(match[1].split()[0].decode() == EXPECTED_RELEASE,
            f"Mismatched module ABI: {path}: {match[1]!r}")


def inspect_sources(build, sdk):
    # Consume recipe-owned deploy exports, including after sstate restoration.
    # Never inspect another recipe's WORKDIR or require an image do_rootfs.
    release_file = build / "metadata/kernel.release"
    require(release_file.read_text().strip() == EXPECTED_RELEASE,
            "Build artifacts do not contain the expected Noble kernel")
    rootfs = build
    image = rootfs / "boot/Image"
    require(image_release(image) == EXPECTED_RELEASE,
            "Yocto rootfs Image does not match the kernel build artifacts")
    modules = rootfs / "usr/lib/modules" / EXPECTED_RELEASE
    module_files = sorted(modules.rglob("*.ko"))
    require(len(module_files) > 100, "Incomplete kernel/module rootfs")
    for module in module_files:
        check_module(module)
    # Identical vermagic alone does not prove structure/symbol compatibility.
    # NVIDIA deliberately replaces complete host1x/DRM export providers.
    checker = sdk / "compulab/tools/check-module-abi.py"
    base_symbols = build / "metadata/base-Module.symvers"
    oot_symbols = build / "metadata/oot-Module.symvers"
    require(checker.is_file() and base_symbols.is_file() and oot_symbols.is_file(),
            "The ABI checker and complete base/OOT Module.symvers are required")
    run(sys.executable, "-B", str(checker), "--modules", str(modules.parent),
        "--symvers", str(base_symbols), "--symvers", str(oot_symbols),
        "--release", EXPECTED_RELEASE)
    for name in ("i2c-atr", "max-serdes", "max96717", "max96724", "max9296a",
                 "tegra-camera", "fr_imx676", "fr_imx678", "nvethernet",
                 "nvidia", "nvme", "pcie-tegra194"):
        require(any(p.name == name + ".ko" for p in module_files),
                f"Required kernel or NVIDIA OOT module missing: {name}")
    dtbs = rootfs / "boot/dtb"
    for name in ("tegra234-p3768-0000+p3767-0000-nv-super.dtb",
                 "tegra234-p3768-0000+p3767-0001-nv-super.dtb",
                 "tegra234-p3768-0000+p3767-0003-nv-super.dtb",
                 "tegra234-p3768-0000+p3767-0004-nv-super.dtb",
                 "edgedes-adi-v18-framos-imx676-4port.dtb",
                 "edgedes-adi-v18-framos-imx678-4port.dtb"):
        find_dtb(rootfs, name)
    overlays = rootfs / "boot/devicetree"
    require((overlays / "edgedes-adi-v18-transport-4port.dtbo").is_file(),
            "Missing ADI transport overlay")
    for model in ("imx676", "imx678"):
        for port in range(4):
            require((overlays / f"edgedes-adi-v18-camera-{model}-port{port}.dtbo").is_file(),
                    f"Missing {model} port {port} overlay")
    baseline = json.loads((sdk / "SDK_BASELINE.json").read_text())
    backup = Path(baseline["vendor_backup"])
    require((backup / "rootfs/boot/Image").is_file(), "Vendor backup unavailable")
    require(digest(backup / "kernel/Image") == baseline["sha256"]["kernel/Image"],
            "Vendor backup Image checksum mismatch")
    require(re.search(r"# R39 .*REVISION: 2\.1,", (sdk / "rootfs/etc/nv_tegra_release").read_text()),
            "Only the R39.2.1 NVIDIA Ubuntu SDK is supported")
    require('ID=ubuntu' in (sdk / "rootfs/etc/os-release").read_text(),
            "The destination must remain NVIDIA Ubuntu")
    subprocess.run(["git", "-c", "safe.directory=" + str(sdk), "rev-parse", "--verify", "HEAD"], cwd=sdk,
                   check=True, stdout=subprocess.DEVNULL)
    print(f"Verified {len(module_files)} matched aarch64 modules and camera DTs")
    return rootfs, modules, backup


def module_key(path):
    return Path(path).name.removesuffix(".ko").replace("-", "_")


def prepare_initrd_list(sdk, module_root):
    """Keep Ubuntu binaries/security policy and resolve actual module paths.

    The vendor list expects its packaged config; some modules are built-in or
    relocated in this kernel. Include the dependency closure of every available
    vendor-listed module, and require all boot-storage drivers explicitly.
    """
    dependencies = {}
    for line in (module_root / "modules.dep").read_text().splitlines():
        module, following = line.split(":", 1)
        dependencies[module] = following.split()
    available = {}
    for relative in dependencies:
        available.setdefault(module_key(relative), []).append(relative)
    builtin = {module_key(line) for line in
               (module_root / "modules.builtin").read_text().splitlines()}
    selected = set()
    skipped = []

    def add(relative):
        if relative in selected:
            return
        require((module_root / relative).is_file(), f"Broken dependency: {relative}")
        selected.add(relative)
        for dependency in dependencies[relative]:
            add(dependency)

    def select(name, mandatory=False):
        key = module_key(name)
        candidates = available.get(key, [])
        # depmod's updates/ replacement must win over a same-named in-tree module.
        candidates = sorted(candidates, key=lambda value: not value.startswith("updates/"))
        if candidates:
            add(candidates[0])
        elif key not in builtin:
            require(not mandatory, f"Mandatory initrd driver missing: {name}")
            skipped.append(name)

    list_dir = sdk / "rootfs/etc/nv-update-initrd/list.d"
    vendor = list_dir / "modules_k6.8"
    for line in vendor.read_text().splitlines():
        if line.startswith("/") and ".ko:" in line:
            select(line.split(":", 1)[0])
    for name in ("nvme", "nvme-core", "pcie-tegra194", "phy-tegra194-p2u",
                 "tegra-xudc", "nvethernet", "ext4"):
        select(name, mandatory=True)
    output = ["# Generated CompuLab R39.2.1 Noble initrd module closure.",
              "/lib/modules/<KERNEL_VERSION>/modules*:/lib/modules/<KERNEL_VERSION>/"]
    # Preserve all non-module vendor inputs, including .disable_initrd_bash.
    for path in sorted(list_dir.iterdir()):
        if path.name.startswith("modules") or not path.is_file():
            continue
        output.extend(line for line in path.read_text().splitlines()
                      if line.startswith("/"))
    for relative in sorted(selected):
        path = "/lib/modules/<KERNEL_VERSION>/" + relative
        output.append(f"{path}:{path}")
    write_text(list_dir / "modules.override", "\n".join(output) + "\n")
    print(f"Initrd: {len(selected)} module files; absent optional vendor drivers: {skipped}")


def install(build, sdk, rootfs, modules, backup):
    require(os.geteuid() == 0, "--apply requires root (sudo)")
    for transient in ("etc/resolv.conf.saved", "usr/bin/qemu-aarch64-static"):
        path = sdk / "rootfs" / transient
        require(not path.exists() and not path.is_symlink(),
                f"Refusing to overwrite pre-existing initrd-tool state: {path}")
    marker = sdk / "compulab/kernel-release.txt"
    require(not marker.exists(), "Installation marker already exists; verify before replacing")
    destination = sdk / "rootfs/usr/lib/modules" / EXPECTED_RELEASE
    require(not destination.exists(), f"Destination module tree already exists: {destination}")
    # Keep the stock modules and boot files for explicit fallback and rollback.
    for name in ("Image", "initrd"):
        fallback = sdk / "rootfs/boot" / (name + ".nvidia-stock")
        require(not fallback.exists(), f"Stock fallback already exists: {fallback}")
        atomic_copy(backup / "rootfs/boot" / name, fallback)
    shutil.copytree(modules, destination, symlinks=True,
                    ignore=shutil.ignore_patterns("build", "source"))
    atomic_copy(rootfs / "boot/Image", sdk / "kernel/Image")
    atomic_copy(rootfs / "boot/Image", sdk / "rootfs/boot/Image")
    config = build / "metadata/kernel.config"
    atomic_copy(config, sdk / "rootfs/boot" / ("config-" + EXPECTED_RELEASE))
    for folder in ("dtb", "devicetree"):
        for source in sorted((rootfs / "boot" / folder).iterdir()):
            if not source.name.endswith((".dtb", ".dtbo", ".dtb.sig", ".dtbo.sig",
                                         ".dtb.signed", ".dtbo.signed")):
                continue
            if source.suffix in (".sig", ".signed"):
                require(source.with_suffix("").is_file(),
                        f"Device-tree companion lacks its raw input: {source}")
            atomic_copy(source, sdk / "rootfs/boot" / folder / source.name)
            if source.name.startswith("edgedes-"):
                atomic_copy(source, sdk / "kernel/dtb" / source.name)
    for sku, model in (("0000", "nx-16g"), ("0001", "nx-8g"),
                       ("0003", "nano-8g"), ("0004", "nano-4g")):
        source = find_dtb(rootfs, f"tegra234-p3768-0000+p3767-{sku}-nv-super.dtb")
        alias = f"tegra234-edge-ai-{model}-nv-super.dtb"
        atomic_copy(source, sdk / "kernel/dtb" / alias)
        atomic_copy(source, sdk / "rootfs/boot/dtb" / alias)
        for extension in (".sig", ".signed"):
            companion = find_dtb_companion(rootfs, source.name, extension)
            if companion is not None:
                atomic_copy(companion, sdk / "kernel/dtb" / (alias + extension))
                atomic_copy(companion, sdk / "rootfs/boot/dtb" / (alias + extension))
        atomic_copy(backup / "kernel/dtb" / source.name,
                    sdk / "rootfs/boot/dtb" / ("nvidia-stock-" + source.name))
        for extension in (".sig", ".signed"):
            companion = backup / "kernel/dtb" / (source.name + extension)
            if companion.is_file():
                atomic_copy(companion, sdk / "rootfs/boot/dtb" /
                            ("nvidia-stock-" + source.name + extension))
    run("depmod", "-b", str(sdk / "rootfs"), EXPECTED_RELEASE)
    prepare_initrd_list(sdk, destination)
    # The NVIDIA tool rebuilds BOTH runtime and recovery Ubuntu initrds.
    run(str(sdk / "tools/l4t_update_initrd.sh"), cwd=sdk)
    require(digest(sdk / "rootfs/boot/initrd") == digest(sdk / "bootloader/l4t_initrd.img"),
            "Runtime/recovery initrd payloads differ")
    listing = subprocess.check_output(["lsinitramfs", str(sdk / "rootfs/boot/initrd")], text=True)
    require(EXPECTED_RELEASE in listing, "Ubuntu initrd lacks the new kernel modules")
    require("6.8.12-1021-tegra/" not in listing, "Ubuntu initrd retains stock-ABI modules")
    for name in ("nvme.ko", "pcie-tegra194.ko", "phy-tegra194-p2u.ko"):
        require(name in listing, f"Ubuntu initrd lacks boot driver {name}")
    manifest = {
        "format_version": 1, "l4t_version": "39.2.1", "kernel_release": EXPECTED_RELEASE,
        "source": "matched recipe deploy exports", "rootfs_os": "NVIDIA Ubuntu 24.04",
        "module_count": len(list(destination.rglob("*.ko"))),
        "image_sha256": digest(sdk / "kernel/Image"),
        "initrd_sha256": digest(sdk / "rootfs/boot/initrd"),
        "modules": {str(p.relative_to(destination)): digest(p)
                    for p in sorted(destination.rglob("*.ko"))},
        "hardware_validation": "Not performed; no target was flashed or rebooted."
    }
    write_text(sdk / "compulab/kernel-manifest.json", json.dumps(manifest, indent=2) + "\n")
    # Publish readiness last: board profiles refuse incomplete installation.
    write_text(marker, EXPECTED_RELEASE + "\n")
    print("Matched kernel, modules, DTs and Ubuntu initrds installed; no device touched")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifacts", required=True, type=Path)
    parser.add_argument("--sdk", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--apply", action="store_true", help="install after read-only checks")
    args = parser.parse_args()
    build, sdk = args.artifacts.resolve(), args.sdk.resolve()
    try:
        rootfs, modules, backup = inspect_sources(build, sdk)
        if args.apply:
            install(build, sdk, rootfs, modules, backup)
        else:
            print("Read-only checks passed. Use sudo and --apply to install.")
    except (OSError, RuntimeError, subprocess.CalledProcessError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
