#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Convert a fresh SDK from checked deploy exports; never access target devices."""
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import signal
import shutil
import subprocess
import sys
import tarfile

SDK_RELATIVE = Path("JetPack_7.2.1_Linux_JETSON_ORIN_NX_TARGETS/Linux_for_Tegra")
RELEASE = "6.8.12-l4t-r39.2.1-1021.21-clab-adi-v18"
SKUS = {"edge-ai-nx-16g": "0000", "edge-ai-nx-8g": "0001",
        "edge-ai-nano-8g": "0003", "edge-ai-nano-4g": "0004"}


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def run(*command, cwd=None):
    subprocess.run([str(c) for c in command], check=True, cwd=cwd,
                   stdin=subprocess.DEVNULL)


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def copy(source, destination, executable=False):
    require(source.is_file(), "Missing input: " + str(source))
    require(not destination.is_symlink(), "Refusing to write through symlink: " + str(destination))
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, destination)
    destination.chmod(0o755 if executable else 0o644)


def extract(archive, destination):
    """Extract only regular files/directories and confined relative symlinks."""
    destination.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive) as stream:
        members = stream.getmembers()
        for member in members:
            path = PurePosixPath(member.name)
            require(not path.is_absolute() and ".." not in path.parts,
                    "Unsafe archive member: " + member.name)
            target = destination / member.name
            require(target.resolve().is_relative_to(destination.resolve()),
                    "Archive member escapes destination: " + member.name)
            require(member.isfile() or member.isdir() or member.issym(),
                    "Unsupported archive member: " + member.name)
            if member.issym():
                require(not PurePosixPath(member.linkname).is_absolute() and
                        (target.parent / member.linkname).resolve().is_relative_to(destination.resolve()),
                        "Unsafe archive symlink: " + member.name)
        # data_filter rejects traversal through earlier symlink members too.
        stream.extractall(destination, members=members, filter="data")


def checked_export(deploy, name, target):
    archive = deploy / "edge-ai-sdk" / (name + ".tar.xz")
    manifest = json.loads((archive.parent / (name + ".json")).read_text())
    require(manifest["component"] == name and manifest["kernel_release"] == RELEASE,
            "Export component/release mismatch: " + name)
    require(manifest["archive_sha256"] == digest(archive), "Export checksum mismatch: " + name)
    extract(archive, target)
    for relative, expected in manifest["files"].items():
        path = target / relative
        require(path.is_file() and not path.is_symlink() and digest(path) == expected,
                "Export file checksum mismatch: " + relative)
    return manifest


def merge_modules(base, oot):
    policy = (oot / "metadata/replacement-drivers.txt").read_text().split()
    modules = base / "usr/lib/modules" / RELEASE
    replacements = oot / "usr/lib/modules" / RELEASE
    for name in policy:
        # This is the same removal performed by kernel image packaging.
        require(re.fullmatch(r"[A-Za-z0-9_-]+", name), "Invalid replacement module name")
        key = name.replace("-", "_")
        if any(p.stem.replace("-", "_") == key for p in replacements.rglob("*.ko")):
            for candidate in modules.rglob("*.ko"):
                if candidate.stem.replace("-", "_") == key:
                    candidate.unlink()
    shutil.copytree(oot, base, dirs_exist_ok=True, symlinks=True)


def prepare_module_indexes(artifacts):
    """Expose usrmerged exports at depmod's portable /lib/modules path."""
    require(artifacts.is_absolute() and artifacts != Path("/") and
            artifacts.is_dir() and artifacts.resolve() == artifacts,
            "Module staging must be a canonical absolute directory")
    modules = artifacts / "usr/lib/modules" / RELEASE
    require(modules.is_dir() and modules.resolve() == modules,
            "Missing or symlinked staged module directory: " + str(modules))
    lib = artifacts / "lib"
    if lib.is_symlink():
        require(lib.readlink() == Path("usr/lib"),
                "Unexpected staged lib symlink: " + str(lib))
    else:
        require(not lib.exists(),
                "Refusing to replace staged lib entry: " + str(lib))
        lib.symlink_to("usr/lib", target_is_directory=True)
    # Older host kmod versions cannot select /usr/lib/modules with -m.
    # The relative alias also matches the NVIDIA Ubuntu rootfs layout.
    run("depmod", "-b", artifacts, RELEASE)


def prepare_artifacts(configuration):
    deploy = Path(configuration["deploy"])
    work = Path(configuration["work"])
    artifacts = work / "matched-artifacts"
    oot = work / "oot-export"
    require(not artifacts.exists() and not oot.exists(), "Artifact staging already exists; use a fresh work directory")
    base_manifest = checked_export(deploy, "kernel", artifacts)
    require(base_manifest["metadata"]["kernel_provider"] == "linux-noble-nvidia-tegra" and
            len(base_manifest["metadata"]["config_requests"]) == 109,
            "SDK requires the full Noble/ADI kernel configuration (109 requests)")
    oot_manifest = checked_export(deploy, "nvidia-kernel-oot", oot)
    merge_modules(artifacts, oot)
    dtb = artifacts / "boot/dtb"
    overlays = artifacts / "boot/devicetree"
    dtb.mkdir(parents=True, exist_ok=True)
    overlays.mkdir(parents=True, exist_ok=True)
    for source in sorted((deploy / "devicetree").glob("*")):
        if source.name.endswith((".dtb", ".dtbo", ".dtb.sig", ".dtbo.sig",
                                 ".dtb.signed", ".dtbo.signed")) and source.is_file():
            if source.suffix in (".sig", ".signed"):
                require(source.with_suffix("").is_file(),
                        "Device-tree companion lacks its raw input: " + source.name)
            copy(source, overlays / source.name)
            if source.name.endswith((".dtb", ".dtb.sig", ".dtb.signed")):
                copy(source, dtb / source.name)
    for sku in SKUS.values():
        name = "tegra234-p3768-0000+p3767-%s-nv-super.dtb" % sku
        matches = [p for p in (deploy / name, deploy / "devicetree" / name) if p.is_file()]
        require(matches and len({digest(p) for p in matches}) == 1,
                "Missing/conflicting module DTB: " + name)
        copy(matches[0], dtb / name)
        for extension in (".sig", ".signed"):
            companions = [path.with_name(name + extension) for path in matches
                          if path.with_name(name + extension).is_file()]
            if companions:
                require(len({digest(path) for path in companions}) == 1,
                        "Conflicting companions of identical module DTBs: " + name + extension)
                copy(companions[0], dtb / (name + extension))
    prepare_module_indexes(artifacts)
    return artifacts, {"kernel": base_manifest, "nvidia-kernel-oot": oot_manifest}


def baseline(sdk):
    require(not (sdk / ".git").exists() and not (sdk / "compulab").exists(),
            "Conversion requires a pristine, unmodified SDK")
    require(re.search(r"# R39 .*REVISION: 2\.1,", (sdk / "rootfs/etc/nv_tegra_release").read_text()),
            "Only NVIDIA L4T R39.2.1 is supported")
    require('ID=ubuntu' in (sdk / "rootfs/etc/os-release").read_text(), "NVIDIA Ubuntu required")
    backup = sdk / "compulab/vendor-backup"
    paths = ["flash.sh", "tools/kernel_flash/l4t_flash_from_kernel.sh",
             "tools/kernel_flash/l4t_initrd_flash_internal.sh", "kernel/Image",
             "rootfs/boot/Image", "rootfs/boot/initrd", "rootfs/boot/extlinux/extlinux.conf"]
    paths.extend("kernel/dtb/tegra234-p3768-0000+p3767-%s-nv-super.dtb" % sku
                 for sku in SKUS.values())
    # Unsigned SDKs need no companions. Preserve existing stock signatures as
    # rollback data, without generating or substituting any signed payload.
    paths.extend(relative + extension for relative in list(paths)
                 if relative.endswith(".dtb") for extension in (".sig", ".signed")
                 if (sdk / (relative + extension)).is_file())
    hashes = {}
    for relative in paths:
        source = sdk / relative
        hashes[relative] = digest(source)
        copy(source, backup / relative)
    write_json(sdk / "SDK_BASELINE.json", {
        "format_version": 1, "l4t_version": "39.2.1", "vendor_backup": str(backup),
        "sha256": hashes, "note": "Private stock boot files; no authentication data included"})
    # Track small vendor sources/configs, not rootfs, binaries or credentials.
    (sdk / ".gitignore").write_text(
        "/*\n!/*.conf\n!/flash.sh\n!/compulab-l4t.env\n!/SDK_BASELINE.json\n!/.gitignore\n!/compulab/\n"
        "/compulab/vendor-backup/\n/compulab/receipts/\n/compulab/kernel/*.tar.xz\n"
        "/compulab/packages/*.deb\n"
        "/compulab/boot/provenance/\n/compulab/runtime/sources/\n/compulab/runtime/nito/*.nito\n")
    run("git", "-c", "safe.directory=" + str(sdk), "init", "-b", "compulab/jetpack-7.2.1", cwd=sdk)
    run("git", "-c", "safe.directory=" + str(sdk), "add", ".gitignore", "SDK_BASELINE.json",
        "flash.sh", *[p.name for p in sdk.glob("*.conf")], cwd=sdk)
    run("git", "-c", "safe.directory=" + str(sdk), "-c", "user.name=SDK vendor import", "-c", "user.email=sdk-import@localhost",
        "commit", "-m", "sdk: record pristine NVIDIA JetPack 7.2.1 inputs", cwd=sdk)


def carrier_files(sources, sdk):
    shutil.copytree(sources / "sdk-source", sdk, dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo"))
    bct = sdk / "bootloader/generic/BCT"
    for name in ("tegra234-edge-ai-gpio-default.dtsi", "tegra234-edge-ai-pinmux.dtsi",
                 "tegra234-edge-ai-padvoltage-default.dtsi",
                 "tegra234-edge-ai-mb2-bct-misc-p3767-0000.dts"):
        copy(sources / name, bct / name)
    (bct / "tegra234-edge-ai-mb1-bct-misc-p3767-0000.dts").write_text(
        '// SPDX-License-Identifier: MIT\n'
        '#include "tegra234-mb1-bct-misc-p3767-0000.dts"\n'
        '/ { misc { debug { enable_wdt = <1>; }; }; };\n')


def checked_firmware_export(directory, recipe, item):
    specifications = {
        "edk2-firmware-tegra": ("general", {"uefi.bin", "BOOTAA64.efi", "general.cfg",
            "fmp-image-type-id.txt", "L4TConfiguration.dtbo", "L4TConfiguration-rcmboot.dtbo"}),
        "edk2-firmware-tegra-rcmboot": ("rcm", {"uefi-rcm.bin", "minimal.cfg"}),
        "tos-optee": ("tos", {"tos.img", "tegra234-optee.dtb"}),
        "edk2-nvidia-standalone-mm": ("standalone-mm", {"standalone_mm_optee.bin", "StandaloneMmOptee.dsc"}),
    }
    role, required = specifications[recipe]
    manifest = json.loads((directory / "manifest.json").read_text())
    require(manifest["schema"] == 1 and manifest["recipe"] == recipe and
            manifest["machine"] == item["machine"] and manifest["multiconfig"] == item["mc"] and
            manifest["l4t_version"] == "39.2.1" and manifest["role"] == role,
            "Firmware provenance mismatch: " + recipe)
    names = set()
    for entry in manifest["files"]:
        relative = PurePosixPath(entry["path"])
        require(not relative.is_absolute() and ".." not in relative.parts and
                entry["path"] not in names, "Unsafe/duplicate firmware manifest path")
        names.add(entry["path"])
        path = directory / entry["path"]
        require(path.is_file() and not path.is_symlink() and
                path.resolve().is_relative_to(directory.resolve()) and
                re.fullmatch(r"[0-9a-f]{64}", entry["sha256"]) and digest(path) == entry["sha256"],
                "Firmware checksum mismatch: " + entry["path"])
    require(required.issubset(names) and any(name.startswith("licenses/") for name in names),
            "Required firmware payload/license absent from manifest: " + recipe)
    return manifest


def firmware(configuration, sdk):
    provenance = []
    sums = {}
    config = None
    for item in configuration["firmware"]:
        machine, style = item["machine"], item["style"]
        require(machine in SKUS and style in ("nvidia-logo", "clab-logo", "no-logo"),
                "Invalid firmware input selection")
        root = Path(item["deploy"]) / "edge-ai-sdk/firmware"
        manifests = {}
        for recipe in ("edk2-firmware-tegra", "edk2-firmware-tegra-rcmboot",
                       "tos-optee", "edk2-nvidia-standalone-mm"):
            directory = root / recipe
            manifest = checked_firmware_export(directory, recipe, item)
            manifests[recipe] = manifest
            receipt = sdk / "compulab/boot/provenance" / machine / style / recipe
            shutil.copytree(directory, receipt)
        general = manifests["edk2-firmware-tegra"]
        require(general["logo_style"] == style, "Firmware logo selection mismatch")
        mm = root / "edk2-nvidia-standalone-mm/standalone_mm_optee.bin"
        tos = manifests["tos-optee"]["matched_trusted_os"]
        require(tos["standalone_mm_sha256"] == digest(mm), "TOS/StandaloneMM build mismatch")
        stem = "compulab-%s-%s" % (machine, style)
        pairs = ((root / "edk2-firmware-tegra/uefi.bin", "bootloader/uefi_bins/" + stem + "-uefi.bin"),
                 (root / "edk2-firmware-tegra-rcmboot/uefi-rcm.bin", "bootloader/uefi_bins/" + stem + "-rcm.bin"),
                 (root / "tos-optee/tos.img", "bootloader/" + stem + "-tos.img"),
                 (root / "edk2-firmware-tegra/BOOTAA64.efi", "bootloader/" + stem + "-BOOTAA64.efi"))
        for source, destination in pairs:
            copy(source, sdk / destination)
            sums[destination] = digest(source)
        for recipe, name, suffix in (("edk2-firmware-tegra", "general.cfg", ""),
                                     ("edk2-firmware-tegra-rcmboot", "minimal.cfg", "-rcm")):
            copy(root / recipe / name, sdk / "compulab/boot/source-configs" / (machine + "-" + style + suffix + ".cfg"))
        source_config = root / "edk2-firmware-tegra/L4TConfiguration.dtbo"
        if config is None:
            config = source_config
        else:
            require(digest(config) == digest(source_config), "Conflicting normal L4T config templates")
        provenance.append(dict(machine=machine, style=style, recipes=manifests))
    require(len(provenance) == 12 and len(sums) == 48, "All 12 matched firmware sets are required")
    (sdk / "compulab/boot/SHA256SUMS.firmware").write_text(
        "".join("%s  %s\n" % (sums[name], name) for name in sorted(sums)))
    write_json(sdk / "compulab/boot/firmware-provenance.json", provenance)
    run("bash", sdk / "compulab/boot/prepare-l4t-config.sh", config,
        sdk / "kernel/dtb/compulab-L4TConfiguration.dtbo")


def headers(configuration, sdk):
    destination = sdk / "compulab/kernel"
    destination.mkdir(parents=True, exist_ok=True)
    deploy = Path(configuration["deploy"])
    devsrc = Path(configuration["work"]) / "devsrc-export"
    checked_export(deploy, "kernel-devsrc", devsrc)
    # Keep these as source-only archives; stock Ubuntu headers are incompatible.
    copy(deploy / "edge-ai-sdk/kernel-devsrc.tar.xz",
         destination / ("compulab-kernel-devsrc-" + RELEASE + ".tar.xz"))
    oot = Path(configuration["work"]) / "oot-export"
    archive = destination / ("compulab-nvidia-oot-headers-" + RELEASE + ".tar.xz")
    with tarfile.open(archive, "w:xz") as stream:
        for folder in ("usr/include/nvidia-kernel-oot", "metadata/licenses"):
            stream.add(oot / folder, arcname=folder)
    (destination / "README.txt").write_text(
        "Matched source-only headers; stock kernel_headers.tbz2 remains stock.\n"
        "External module builds need the matching GCC 16 compiler/plugin tooling.\n"
        "No Yocto userland ELF or compiler executable is installed in Ubuntu.\n")


def capsule_support(configuration, sdk):
    sources = Path(configuration["sources"])
    deploy = Path(configuration["deploy"])
    target = sdk / "rootfs/usr/share/compulab/uefi-update-capsules"
    shutil.copytree(deploy / "edge-ai-uefi-update-capsules", target)
    require(len(list(target.glob("*-uefi-*.cap"))) >= 12, "Incomplete capsule bundle")
    updater = (sources / "edge-ai-uefi-update").read_text().replace(
        "@CAPSULE_DIR@", "/usr/share/compulab/uefi-update-capsules")
    path = sdk / "rootfs/usr/sbin/edge-ai-uefi-update"
    path.write_text(updater)
    path.chmod(0o755)
    copy(sources / "apply-uefi-capsule", target / "apply-uefi-capsule", executable=True)
    helpers = sdk / "compulab/boot/rootfs-support"
    copy(helpers / "oe4t-set-uefi-OSIndications.sh", sdk / "rootfs/usr/bin/oe4t-set-uefi-OSIndications", executable=True)
    copy(helpers / "uefi_common.func", sdk / "rootfs/usr/bin/uefi_common.func")
    payload = sdk / "compulab/rootfs"
    shutil.copytree(payload, sdk / "rootfs", dirs_exist_ok=True)
    menu = sdk / "rootfs/boot/extlinux/extlinux.conf"
    original = json.loads((sdk / "SDK_BASELINE.json").read_text())
    prefix = (Path(original["vendor_backup"]) / "rootfs/boot/extlinux/extlinux.conf").read_text()
    sample = (payload / "boot/extlinux/extlinux.conf.imx67x.sample").read_text()
    marker = "# CompuLab camera entries below"
    require(marker in sample and re.search(r"(?m)^DEFAULT\s+primary\s*$", prefix),
            "Unexpected vendor or sample extlinux menu")
    menu.write_text(prefix.rstrip() + "\n\n" + marker + sample.split(marker, 1)[1])


def verify(sdk):
    require((sdk / "compulab/kernel-release.txt").read_text().strip() == RELEASE,
            "Matched-kernel readiness marker missing")
    require(digest(sdk / "kernel/Image") == digest(sdk / "rootfs/boot/Image"), "Kernel image mismatch")
    require(digest(sdk / "rootfs/boot/initrd") == digest(sdk / "bootloader/l4t_initrd.img"), "Initrd mismatch")
    baseline_data = json.loads((sdk / "SDK_BASELINE.json").read_text())
    for name in ("flash.sh", "tools/kernel_flash/l4t_flash_from_kernel.sh"):
        require(digest(sdk / name) == baseline_data["sha256"][name], "Vendor flashing tool changed: " + name)
    run(sys.executable, "-B", sdk / "compulab/tools/apply-massflash-initrd-fix.py",
        "--sdk-root", sdk, "--verify")
    expected = json.loads((sdk / "compulab/integration-files.json").read_text())
    for relative, checksum in expected.items():
        require(digest(sdk / relative) == checksum, "SDK integration drift: " + relative)
    for machine in SKUS:
        require((sdk / (machine + ".conf")).is_file(), "Missing board profile: " + machine)
    run("sha256sum", "-c", "compulab/boot/SHA256SUMS.firmware", cwd=sdk)
    run("sha256sum", "-c", "SHA256SUMS", cwd=sdk / "rootfs/usr/share/compulab/uefi-update-capsules")
    kernel = sdk / "compulab/kernel"
    run(sys.executable, "-B", sdk / "compulab/tools/check-module-abi.py", "--modules",
        sdk / "rootfs/usr/lib/modules" / RELEASE, "--symvers", kernel / "base-Module.symvers",
        "--symvers", kernel / "oot-Module.symvers", "--release", RELEASE)
    runtime = json.loads((sdk / "compulab/receipts/runtime-provision/receipt.json").read_text())
    require(len(runtime["installed_elf_sha256"]) == 26, "Incomplete native Ubuntu runtime receipt")
    for relative, expected_hash in runtime["installed_elf_sha256"].items():
        require(digest(sdk / "rootfs" / relative) == expected_hash,
                "Ubuntu runtime ELF changed: " + relative)
    package_manifest = sdk / "compulab/packages/manifest.json"
    require(package_manifest.is_file(), "Native CompuLab package manifest missing")
    package_receipt = json.loads(package_manifest.read_text())
    require(package_receipt.get("installed") and len(package_receipt["packages"]) == 9,
            "CompuLab Debian package installation is incomplete")
    for package in package_receipt["packages"]:
        archive = sdk / "compulab/packages" / package["filename"]
        require(archive.is_file() and digest(archive) == package["sha256"],
                "Native CompuLab package changed: " + package["name"])
        status = subprocess.check_output([
            "dpkg-query", "--admindir=" + str(sdk / "rootfs/var/lib/dpkg"),
            "-W", "-f=${Status}\t${Version}", package["name"]], text=True)
        require(status.strip() == "install ok installed\t" + package["version"],
                "Native CompuLab package is not installed: " + package["name"])
        installed = set(subprocess.check_output([
            "dpkg-query", "--admindir=" + str(sdk / "rootfs/var/lib/dpkg"),
            "--listfiles", package["name"]], text=True).splitlines())
        for relative, expected_hash in package["files"].items():
            require("/" + relative in installed and
                    digest(sdk / "rootfs" / relative) == expected_hash,
                    "Unowned or changed CompuLab package file: " + relative)
    result = subprocess.check_output([sys.executable, "-B", str(sdk / "compulab/policy/bsp-protection.py"),
                                      "--sdk", str(sdk)], text=True)
    require(json.loads(result)["protected"], "Ubuntu BSP hold/update policy is not active")
    listing = subprocess.check_output(["lsinitramfs", str(sdk / "rootfs/boot/initrd")], text=True)
    require(RELEASE in listing and "6.8.12-1021-tegra/" not in listing, "Invalid Ubuntu initrd ABI")
    print("SDK verification passed; hardware has not been flashed or tested")


def assemble(configuration, sdk):
    sources = Path(configuration["sources"])
    baseline(sdk)
    carrier_files(sources, sdk)
    run(sys.executable, "-B", sdk / "compulab/tools/apply-massflash-initrd-fix.py",
        "--sdk-root", sdk, "--apply")
    copy(sources / "assemble-sdk.py", sdk / "compulab/tools/verify-sdk.py", executable=True)
    artifacts, provenance = prepare_artifacts(configuration)
    firmware(configuration, sdk)
    run(sys.executable, "-B", sdk / "compulab/tools/install-kernel.py", "--artifacts", artifacts,
        "--sdk", sdk, "--apply")
    for name in ("base-Module.symvers", "oot-Module.symvers", "kernel.config"):
        copy(artifacts / "metadata" / name, sdk / "compulab/kernel" / name)
    headers(configuration, sdk)
    capsule_support(configuration, sdk)
    # Capture ORIGINAL selections before runtime provisioning protects the BSP.
    run(sys.executable, "-B", sdk / "compulab/policy/bsp-protection.py", "apply", "--sdk", sdk)
    run(sys.executable, "-B", sources / "provision-runtime.py", "--sdk-root", sdk,
        "--work-dir", Path(configuration["work"]) / "ubuntu-runtime",
        "--assets-dir", configuration["assets"], "--bundle-source", sources / "runtime",
        "--imx676-extended", configuration["imx676_extended"],
        "--imx678-extended", configuration["imx678_extended"], "--execute")
    run(sys.executable, "-B", sources / "package-rootfs.py", "--sdk-root", sdk,
        "--artifacts", artifacts,
        "--work-dir", Path(configuration["work"]) / "ubuntu-debs",
        "--version", configuration.get("deb_version", "39.2.1+compulab1"),
        "--execute")
    write_json(sdk / "compulab/export-provenance.json", provenance)
    tracked = [p for p in (sdk / "compulab").rglob("*") if p.is_file()
               and "vendor-backup" not in p.parts and "receipts" not in p.parts
               and "__pycache__" not in p.parts and p.suffix not in (".pyc", ".pyo")]
    tracked += [sdk / (name + ".conf") for name in ("edge-ai-common", "edge-ai", *SKUS)]
    for folder in (sdk / "rootfs/usr/lib/modules" / RELEASE, sdk / "rootfs/boot/dtb",
                   sdk / "rootfs/boot/devicetree", sdk / "rootfs/opt/compulab/bin",
                   sdk / "rootfs/usr/share/compulab/uefi-update-capsules"):
        tracked += [p for p in folder.rglob("*") if p.is_file()]
    tracked += [sdk / name for name in ("kernel/Image", "rootfs/boot/Image", "rootfs/boot/initrd",
                 "bootloader/l4t_initrd.img", "rootfs/boot/extlinux/extlinux.conf",
                 "compulab-l4t.env",
                 "tools/kernel_flash/l4t_initrd_flash_internal.sh",
                 "rootfs/usr/sbin/edge-ai-uefi-update", "rootfs/usr/sbin/edge-ai-select-fdt",
                 "rootfs/usr/bin/oe4t-set-uefi-OSIndications", "rootfs/usr/bin/uefi_common.func")]
    tracked.append(sdk / "compulab/receipts/runtime-provision/receipt.json")
    write_json(sdk / "compulab/integration-files.json",
               {str(p.relative_to(sdk)): digest(p) for p in sorted(set(tracked))})
    verify(sdk)
    # The rootfs stays root-owned. The new source repository belongs to the
    # ordinary SDK user so future Git edits/commits do not require sudo.
    uid, gid = configuration["uid"], configuration["gid"]
    require(isinstance(uid, int) and uid > 0 and isinstance(gid, int) and gid >= 0,
            "Invalid SDK repository owner")
    for folder in (sdk / ".git", sdk / "compulab"):
        for path in [folder, *folder.rglob("*")]:
            os.chown(path, uid, gid, follow_symlinks=False)
    for name in (".gitignore", "SDK_BASELINE.json", "compulab-l4t.env", "edge-ai-common.conf", "edge-ai.conf",
                 *(machine + ".conf" for machine in SKUS)):
        os.chown(sdk / name, uid, gid, follow_symlinks=False)


def main():
    def interrupted(signum, frame):
        raise SystemExit("SDK conversion interrupted; incomplete output retained")
    signal.signal(signal.SIGTERM, interrupted)
    require(sys.version_info >= (3, 12), "SDK conversion requires host Python 3.12+")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path)
    parser.add_argument("--sdk-root", type=Path, help="standalone read-only verification")
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--execute", action="store_true")
    action.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    if args.config:
        require(args.sdk_root is None, "Choose --config or --sdk-root, not both")
        configuration = json.loads(args.config.read_text())
        output = Path(configuration["output"])
        require(output.is_absolute() and not output.is_symlink(), "Unsafe SDK output directory")
        sdk = output / SDK_RELATIVE
    else:
        require(args.verify and args.sdk_root is not None,
                "Use --config for conversion or --sdk-root with --verify")
        sdk = args.sdk_root.resolve()
    require(sdk.is_dir() and (sdk / "flash.sh").is_file() and not (sdk / "rootfs").is_symlink(),
            "Explicit SDK/rootfs required")
    if args.verify:
        verify(sdk)
    else:
        require(os.geteuid() == 0, "Explicit privileged SDK conversion required")
        require((output / ".edge-ai-sdk-incomplete").is_file(), "Missing SDK ownership marker")
        assemble(configuration, sdk)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, RuntimeError, subprocess.SubprocessError, ValueError, KeyError) as error:
        print("CompuLab conversion stopped: " + str(error), file=sys.stderr)
        sys.exit(1)
