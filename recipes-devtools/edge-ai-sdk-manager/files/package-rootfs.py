#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Publish and install native Debian packages for staged CompuLab additions.

The converted SDK rootfs is a build staging tree until this step completes.
Never modify the running host, stage a capsule, flash firmware or reboot.
"""
import argparse
import base64
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import signal
import shutil
import stat
import struct
import subprocess
import sys
import tempfile


RELEASE = "6.8.12-l4t-r39.2.1-1021.21-clab-adi-v18"
L4T_VERSION = "39.2.1"
FIRMWARE_VERSION = 0x00270201
POLICY_PACKAGES = (
    "nvidia-l4t-bootloader", "nvidia-l4t-bootloader-utils", "nvidia-l4t-kernel",
    "nvidia-l4t-kernel-dtbs", "nvidia-l4t-kernel-partitions", "nvidia-l4t-initrd",
    "nvidia-l4t-extlinux", "nvidia-l4t-firmware", "nvidia-l4t-kernel-oot-modules",
    "nvidia-l4t-display-kernel", "nvidia-l4t-kernel-nvgpu",
    "nvidia-l4t-kernel-openrm", "nvidia-l4t-kernel-module-configs",
    "nvidia-l4t-kernel-headers", "nvidia-l4t-kernel-oot-headers",
    "nvidia-l4t-gstreamer",
)
POLICY_CONFIG = "etc/compulab/edge-ai-bsp-policy.json"
POLICY_PREFERENCES = "etc/apt/preferences.d/compulab-edge-ai-bsp"
POLICY_HELPER = "usr/libexec/compulab-edge-ai-bsp-policy"
POLICY_STATE = "var/lib/compulab-edge-ai-bsp-policy/state.json"


def require(condition, message):
    if not condition:
        raise ValueError(message)


def load_module(path, name):
    specification = importlib.util.spec_from_file_location(name, path)
    require(specification and specification.loader, "Missing helper: " + str(path))
    module = importlib.util.module_from_spec(specification)
    sys.modules[name] = module
    specification.loader.exec_module(module)
    return module


def digest(path, algorithm="sha256"):
    result = hashlib.new(algorithm)
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def regular(path):
    information = path.lstat()
    require(stat.S_ISREG(information.st_mode) and path.resolve() == path,
            "Expected a canonical regular file: " + str(path))
    return information


def run(command, **options):
    result = subprocess.run([str(value) for value in command], check=True,
                            text=True, capture_output=True, **options)
    return result.stdout


def checked_sdk(value):
    sdk = Path(value)
    require(sdk.is_absolute() and sdk != Path("/") and sdk.is_dir() and
            sdk.resolve() == sdk, "An explicit canonical SDK directory is required")
    root = sdk / "rootfs"
    require(root.is_dir() and root.resolve() == root,
            "The SDK rootfs must not be a symlink")
    require((root / "var/lib/dpkg").is_dir() and
            (root / "var/lib/dpkg").resolve() == root / "var/lib/dpkg" and
            (root / "var/lib/dpkg").resolve() != Path("/var/lib/dpkg").resolve(),
            "Refusing the running host package database")
    regular(sdk / "flash.sh")
    regular(sdk / "SDK_BASELINE.json")
    require(re.search(r"# R39 .*REVISION: 2\.1,",
                      (root / "etc/nv_tegra_release").read_text()),
            "Only the matching R39.2.1 SDK is supported")
    require('ID=ubuntu' in (root / "etc/os-release").read_text(),
            "The target must remain NVIDIA Ubuntu")
    return sdk


def relative(value):
    path = Path(value)
    require(value and not path.is_absolute() and ".." not in path.parts and
            path.as_posix() == value and "\n" not in value,
            "Invalid package payload path: " + value)
    return path


def owners(root, paths):
    """Query the real target database, never create or edit dpkg file lists."""
    result = {}
    requested = {"/" + str(relative(path)) for path in paths}
    for start in range(0, len(paths), 100):
        values = ["/" + path for path in paths[start:start + 100]]
        query = subprocess.run([
            "dpkg-query", "--admindir=" + str(root / "var/lib/dpkg"),
            "--search", *values], text=True, capture_output=True)
        require(query.returncode in (0, 1), "Cannot query target package ownership")
        for line in query.stdout.splitlines():
            require(": " in line and not line.startswith("diversion "),
                    "Unexpected existing diversion or ownership: " + line)
            packages, path = line.rsplit(": ", 1)
            require(path in requested, "Unexpected dpkg-query path: " + path)
            names = packages.split(", ")
            require(len(names) == 1, "Ambiguous package ownership: " + path)
            result[path.lstrip("/")] = names[0]
    return result


def firmware_version(path):
    """Read the authenticated FMP payload header, not a README or random magic."""
    data = path.read_bytes()
    require(len(data) >= 48, "Truncated capsule: " + path.name)
    header, _flags, length = struct.unpack_from("<III", data, 16)
    require(length == len(data) and 28 <= header <= len(data) - 16,
            "Malformed capsule header: " + path.name)
    version, embedded, payloads = struct.unpack_from("<IHH", data, header)
    require(version == 1 and embedded == 0 and payloads == 1,
            "Expected one FMP capsule payload: " + path.name)
    offset = header + struct.unpack_from("<Q", data, header + 8)[0]
    require(offset + 48 + 32 <= len(data), "Truncated FMP image: " + path.name)
    require(struct.unpack_from("<I", data, offset)[0] == 3,
            "Unsupported FMP image header: " + path.name)
    image_size = struct.unpack_from("<I", data, offset + 24)[0]
    begin = offset + 48
    require(begin + image_size <= len(data), "Invalid FMP payload length")
    certificate_size = struct.unpack_from("<I", data, begin + 8)[0]
    payload = begin + 8 + certificate_size
    require(certificate_size >= 24 and payload + 16 <= begin + image_size,
            "Invalid capsule authentication header: " + path.name)
    magic, size, current, lowest = struct.unpack_from("<4sIII", data, payload)
    require(magic == b"MSS1" and size == 16,
            "Missing FMP firmware-version header: " + path.name)
    return current, lowest


def check_capsules(root):
    directory = root / "usr/share/compulab/uefi-update-capsules"
    regular(directory / "SHA256SUMS")
    files = sorted(directory.glob("*.cap"))
    require(len(files) >= 12, "A complete four-module capsule bundle is required")
    checksums = {}
    for line in (directory / "SHA256SUMS").read_text().splitlines():
        match = re.fullmatch(r"([0-9a-f]{64}) [ *]([A-Za-z0-9_.+-]+\.cap)", line)
        require(match is not None and match[2] not in checksums,
                "Unsafe or duplicate capsule checksum entry")
        checksums[match[2]] = match[1]
    require(set(checksums) == {path.name for path in files},
            "Capsule checksum manifest does not cover the complete bundle")
    for path in files:
        regular(path)
        require(digest(path) == checksums[path.name],
                "Capsule checksum mismatch: " + path.name)
        current, lowest = firmware_version(path)
        require(current == FIRMWARE_VERSION and lowest <= current,
                "Stale/incompatible capsule %s: 0x%x; require R39.2.1" %
                (path.name, current))


def vendor_backup(sdk, path, owner):
    """Locate and verify pristine bytes before a first package diversion."""
    baseline = json.loads((sdk / "SDK_BASELINE.json").read_text())
    backup = Path(baseline["vendor_backup"])
    require(backup.resolve() == backup and backup.is_relative_to(sdk),
            "Invalid SDK vendor-backup path")
    key = None
    if path in ("boot/Image", "boot/initrd"):
        key = "rootfs/" + path
    elif path.startswith("boot/dtb/"):
        key = "kernel/dtb/" + Path(path).name
    if key is not None and key in baseline["sha256"]:
        source = backup / key
        regular(source)
        require(digest(source) == baseline["sha256"][key],
                "Vendor baseline checksum mismatch: " + path)
        return source
    if path.startswith("usr/lib/aarch64-linux-gnu/gstreamer-1.0/"):
        source = (sdk / "compulab/receipts/runtime-provision/pre-stage-backup" /
                  path)
        regular(source)
        information = sdk / "rootfs/var/lib/dpkg/info"
        base = owner.split(":")[0]
        candidates = {information / (name + ".md5sums")
                      for name in (owner, base, base + ":arm64")}
        available = [path for path in sorted(candidates) if path.is_file()]
        require(available and len({digest(path) for path in available}) == 1,
                "Missing/conflicting NVIDIA package checksums: " + owner)
        checksum_file = available[0]
        regular(checksum_file)
        entries = {}
        for line in checksum_file.read_text().splitlines():
            checksum, name = line.split(None, 1)
            entries[name.lstrip("./")] = checksum
        require(path in entries and digest(source, "md5") == entries[path],
                "Original NVIDIA plugin backup is not verified: " + path)
        return source
    raise ValueError("No verified pristine backup for package-owned path: " + path)


def copy_payload(source, destination):
    information = regular(source)
    destination.parent.mkdir(parents=True, exist_ok=True)
    require(not destination.exists() and not destination.is_symlink(),
            "Refusing an existing package-staging destination")
    shutil.copyfile(source, destination)
    destination.chmod(stat.S_IMODE(information.st_mode) & 0o777)


def seeded_policy_state(sdk):
    """Carry original holds/configuration into native package lifecycle state."""
    directory = sdk / "compulab/policy/receipts"
    pointer = json.loads((directory / "active.json").read_text())["receipt"]
    require(Path(pointer).name == pointer, "Unsafe policy receipt name")
    original = json.loads((directory / pointer).read_text())
    require(original["state"] == "active", "SDK BSP policy is not active")
    name = original["original_config"]
    require(Path(name).name == name, "Unsafe original policy configuration")
    source = directory / name
    regular(source)
    require(digest(source) == original["original_config_sha256"],
            "Original BSP policy configuration checksum mismatch")
    packages = [dict(name=row["name"], version=row["version"],
                     selection=row["selection"]) for row in original["packages"]]
    runtime = json.loads((sdk / "compulab/receipts/runtime-provision/receipt.json")
                         .read_text())
    if not any(row["name"].split(":")[0] == "nvidia-l4t-gstreamer"
               for row in packages):
        found = run(["dpkg-query", "--admindir=" + str(sdk / "rootfs/var/lib/dpkg"),
                     "-W", "-f=${binary:Package}\t${Version}",
                     "nvidia-l4t-gstreamer"]).strip().split("\t")
        require(len(found) == 2 and found[0] in
                ("nvidia-l4t-gstreamer", "nvidia-l4t-gstreamer:arm64"),
                "Unexpected NVIDIA GStreamer package identity")
        binary_name, version = found
        held = any(name.split(":")[0] == "nvidia-l4t-gstreamer"
                   for name in runtime["holds_before"])
        packages.append(dict(name=binary_name, version=version,
                             selection="hold" if held else "install"))
    return dict(schema=1, original_config=base64.b64encode(source.read_bytes()).decode(),
                original_config_sha256=original["original_config_sha256"],
                applied_config_sha256=original["applied_config_sha256"],
                config_mode=original["config_mode"], packages=packages)


def create_packages(sdk, artifacts, work, output, version):
    require(re.fullmatch(r"39\.2\.1[+~.A-Za-z0-9-]*", version),
            "Use a valid R39.2.1 Debian package version")
    require(not work.exists() and not work.is_symlink(),
            "Package work directory must be new")
    require(work.is_absolute() and work != Path("/") and work.resolve() == work,
            "Package work directory must be canonical and absolute")
    require(not output.exists() and not output.is_symlink(),
            "Package output directory must be new")
    root = sdk / "rootfs"
    check_capsules(root)
    tools = sdk / "compulab/tools"
    builder = load_module(tools / "deb_packages.py", "compulab_deb_packages")
    inventory = load_module(tools / "rootfs_package_inventory.py",
                            "compulab_rootfs_package_inventory")
    specifications = inventory.collect_packages(sdk, artifacts, version)
    all_paths = [path for item in specifications for path in item["paths"]]
    require(len(all_paths) == len(set(all_paths)), "Overlapping package payloads")
    existing = owners(root, all_paths)
    policy_state = seeded_policy_state(sdk)
    work.mkdir(parents=True, mode=0o700)
    output.mkdir(parents=True, mode=0o755)
    result = []
    originals = {}
    for item in specifications:
        payload = work / item["name"]
        payload.mkdir()
        files = {}
        diversions = []
        for path in item["paths"]:
            relative(path)
            source = root / path
            copy_payload(source, payload / path)
            files[path] = digest(source)
            if path in existing:
                require(not existing[path].split(":")[0].startswith("compulab-"),
                        "An existing packaged SDK must not be silently adopted")
                require(path not in item["conffiles"],
                        "Refusing to divert a vendor conffile: " + path)
                stock = vendor_backup(sdk, path, existing[path])
                saved = work / "pristine" / path
                copy_payload(stock, saved)
                originals[path] = dict(source=str(saved), sha256=digest(saved),
                                       staged_sha256=files[path], owner=existing[path])
                diversions.append(("/" + path, "/" + path + ".compulab-distrib"))
        archive = builder.build_package(
            payload, output, item["name"], version,
            architecture=item["architecture"], depends=item["depends"],
            conffiles=tuple("/" + path for path in item["conffiles"]),
            diversions=tuple(diversions))
        result.append(dict(name=item["name"], version=version,
                           architecture=item["architecture"], filename=archive.name,
                           sha256=digest(archive), files=files,
                           conffiles=list(item["conffiles"]),
                           diversions=diversions))
    policy_payload = work / "compulab-edge-ai-bsp-policy"
    policy = policy_payload / POLICY_CONFIG
    policy.parent.mkdir(parents=True)
    policy.write_text(json.dumps(dict(schema=1, l4t_version=L4T_VERSION,
                                      hold_packages=POLICY_PACKAGES), indent=2) + "\n")
    policy.chmod(0o644)
    copy_payload(tools / "package-bsp-policy.py", policy_payload / POLICY_HELPER)
    (policy_payload / POLICY_HELPER).chmod(0o755)
    preferences = policy_payload / POLICY_PREFERENCES
    preferences.parent.mkdir(parents=True)
    preferences.write_text("\n".join(
        "Package: %s\nPin: version %s\nPin-Priority: 1000\n" %
        (row["name"].split(":")[0], row["version"])
        for row in policy_state["packages"]))
    preferences.chmod(0o644)
    postinst = ('#!/bin/sh\nset -eu\n'
                'if [ "${1-}" = configure ]; then\n'
                '    /usr/libexec/compulab-edge-ai-bsp-policy configure\nfi\n')
    prerm = ('#!/bin/sh\nset -eu\n'
             'if [ "${1-}" = remove ]; then\n'
             '    /usr/libexec/compulab-edge-ai-bsp-policy restore-config\nfi\n')
    archive = builder.build_package(
        policy_payload, output, "compulab-edge-ai-bsp-policy", version,
        architecture="all", depends=("python3", "dpkg"),
        conffiles=("/" + POLICY_CONFIG, "/" + POLICY_PREFERENCES),
        scripts={"postinst": postinst, "prerm": prerm})
    result.append(dict(name="compulab-edge-ai-bsp-policy", version=version,
                       architecture="all", filename=archive.name,
                       sha256=digest(archive),
                       files={path: digest(policy_payload / path)
                              for path in (POLICY_CONFIG, POLICY_HELPER, POLICY_PREFERENCES)},
                       conffiles=[POLICY_CONFIG, POLICY_PREFERENCES], diversions=[]))
    meta_payload = work / "compulab-edge-ai"
    summary = meta_payload / "usr/share/compulab/addons.json"
    summary.parent.mkdir(parents=True)
    summary.write_text(json.dumps(dict(l4t_version=L4T_VERSION,
                                      packages={row["name"]: version for row in result}),
                                  indent=2, sort_keys=True) + "\n")
    summary.chmod(0o644)
    archive = builder.build_package(
        meta_payload, output, "compulab-edge-ai", version,
        architecture="all", depends=tuple(
            row["name"] + (" (>= " + version + ")" if
                           row["name"] == "compulab-edge-ai-uefi-capsules"
                           else " (= " + version + ")") for row in result))
    result.append(dict(name="compulab-edge-ai", version=version,
                       architecture="all", filename=archive.name,
                       sha256=digest(archive),
                       files={"usr/share/compulab/addons.json": digest(summary)},
                       conffiles=[], diversions=[]))
    receipt = dict(schema=1, l4t_version=L4T_VERSION, version=version,
                   kernel_release=RELEASE, sdk_root=str(sdk),
                   output=str(output), packages=result, pristine=originals,
                   policy_state=policy_state, installed=False)
    (work / "prepared.json").write_text(json.dumps(receipt, indent=2) + "\n")
    return receipt


def verify_packages(sdk, manifest):
    root = sdk / "rootfs"
    paths = []
    for item in manifest["packages"]:
        found = run(["dpkg-query", "--admindir=" + str(root / "var/lib/dpkg"),
                     "-W", "-f=${Status}\t${Version}\t${Architecture}", item["name"]])
        require(found.strip() == "install ok installed\t%s\t%s" %
                (item["version"], item["architecture"]),
                "Package is not fully installed at the expected version: " + item["name"])
        installed_paths = set(run([
            "dpkg-query", "--admindir=" + str(root / "var/lib/dpkg"),
            "--listfiles", item["name"]]).splitlines())
        for path, checksum in item["files"].items():
            relative(path)
            regular(root / path)
            require(digest(root / path) == checksum,
                    "Installed package payload changed: " + path)
            require("/" + path in installed_paths,
                    "An addon payload is not owned by its package: " + path)
            paths.append(path)
    return dict(packages=len(manifest["packages"]), payloads=len(paths))


def install_packages(sdk, receipt, work):
    require(os.geteuid() == 0, "Package installation requires explicit root privileges")
    root = sdk / "rootfs"
    output = Path(receipt["output"])
    require(receipt.get("schema") == 1 and receipt.get("sdk_root") == str(sdk) and
            output == sdk / "compulab/packages" and output.resolve() == output,
            "Prepared package receipt does not match this SDK")
    require(receipt.get("installed") is False and len(receipt["packages"]) == 9,
            "Expected a complete, not-yet-installed package set")
    state = root / POLICY_STATE
    require(not state.exists() and not state.is_symlink(), "Policy state already exists")
    require(state.resolve() == state, "Symlinked policy state directory")
    require((root / "tmp").is_dir() and (root / "tmp").resolve() == root / "tmp",
            "Target temporary directory is missing or symlinked")
    provision = load_module(Path(__file__).with_name("provision-runtime.py"),
                            "compulab_deb_provision")
    require(provision.persistent_binfmt(Path("/proc/sys/fs/binfmt_misc/qemu-aarch64")),
            "Preconfigured persistent ARM64 binfmt is required for target dpkg")
    for item in receipt["packages"]:
        require(Path(item["filename"]).name == item["filename"],
                "Unsafe prepared Debian package filename")
        archive = output / item["filename"]
        regular(archive)
        require(digest(archive) == item["sha256"], "Package changed before installation")
        for path, checksum in item["files"].items():
            relative(path)
            # Policy/metapackage payloads are new; existing staged payloads
            # must not change between package construction and installation.
            if item["name"] in ("compulab-edge-ai-bsp-policy", "compulab-edge-ai"):
                continue
            regular(root / path)
            require(digest(root / path) == checksum,
                    "Staged package payload changed before installation: " + path)
    # Verify every replacement BEFORE restoring any original byte. The new
    # .deb then takes ownership through dpkg and preserves stock via diversion.
    for path, value in receipt["pristine"].items():
        relative(path)
        require(Path(value["source"]) == work / "pristine" / path,
                "Pristine backup is outside the owned package work directory")
        regular(root / path)
        regular(Path(value["source"]))
        require(digest(root / path) == value["staged_sha256"] and
                digest(Path(value["source"])) == value["sha256"],
                "Vendor/custom replacement drift before packaging: " + path)
        require(not (root / (path + ".compulab-distrib")).exists() and
                not (root / (path + ".compulab-distrib")).is_symlink(),
                "A diversion destination already exists: " + path)
    for path, value in receipt["pristine"].items():
        shutil.copyfile(value["source"], root / path)
        shutil.copymode(value["source"], root / path)
    state.parent.mkdir(parents=True, mode=0o700)
    require(state.parent.resolve() == state.parent, "Symlinked policy state directory")
    state.write_text(json.dumps(receipt["policy_state"], indent=2) + "\n")
    state.chmod(0o600)
    with tempfile.TemporaryDirectory(prefix="compulab-debs-", dir=root / "tmp") as stage:
        inside = Path(stage)
        paths = []
        for item in receipt["packages"]:
            target = inside / item["filename"]
            shutil.copyfile(output / item["filename"], target)
            paths.append("/" + str(target.relative_to(root)))
        with provision.target_context(root):
            provision.chroot(root, ["dpkg", "--force-confold", "--install", *paths],
                             work / "dpkg-install.log")
            audit = provision.chroot(root, ["dpkg", "--audit"], work / "dpkg-audit.log")
    require(not audit.strip(), "Target dpkg reports incomplete packages")
    verify_packages(sdk, receipt)
    public = {key: value for key, value in receipt.items()
              if key not in ("pristine", "policy_state")}
    public["installed"] = True
    (output / "manifest.json").write_text(json.dumps(public, indent=2, sort_keys=True) + "\n")
    (output / "SHA256SUMS").write_text("".join(
        item["sha256"] + "  " + item["filename"] + "\n" for item in receipt["packages"]))
    return public


def main(arguments=None):
    def interrupted(_signum, _frame):
        # Unwind target_context so only our owned mounts/policy are restored.
        raise SystemExit("Package preparation interrupted; incomplete SDK retained")

    signal.signal(signal.SIGTERM, interrupted)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sdk-root", type=Path, required=True)
    parser.add_argument("--artifacts", type=Path)
    parser.add_argument("--work-dir", type=Path)
    parser.add_argument("--version", default="39.2.1+compulab1")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args(arguments)
    try:
        sdk = checked_sdk(args.sdk_root)
        output = sdk / "compulab/packages"
        if args.verify:
            require(not args.execute, "Verification cannot be combined with installation")
            manifest = json.loads((output / "manifest.json").read_text())
            require(manifest["installed"], "Package installation did not complete")
            print(json.dumps(verify_packages(sdk, manifest), sort_keys=True))
        else:
            require(args.artifacts is not None and args.work_dir is not None,
                    "Packaging requires explicit --artifacts and --work-dir")
            if not args.execute:
                tools = sdk / "compulab/tools"
                inventory = load_module(tools / "rootfs_package_inventory.py",
                                        "compulab_rootfs_package_inventory")
                print(json.dumps(inventory.collect_packages(sdk, args.artifacts, args.version),
                                 indent=2))
                return 0
            require(os.geteuid() == 0, "--execute requires explicit root privileges")
            receipt = create_packages(sdk, args.artifacts, args.work_dir, output, args.version)
            install_packages(sdk, receipt, args.work_dir)
            print("CompuLab addons installed and verified through target dpkg; no device accessed")
    except (OSError, ValueError, KeyError, RuntimeError,
            subprocess.CalledProcessError) as error:
        print("Package preparation failed: " + str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
