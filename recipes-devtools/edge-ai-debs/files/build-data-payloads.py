#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Fresh architecture-independent Debian payloads; no installation or devices.

Input inspection is read-only. Payload construction writes only below the new
private run directory supplied by the common component publisher.
"""
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import stat
import struct
import uuid


NVIDIA_VERSION = "39.2.1-20260806224157"
KERNEL_VERSION = "6.8.12-tegra-" + NVIDIA_VERSION
FIRMWARE_VERSION = 0x00270201
MACHINES = ("edge-ai-nx-16g", "edge-ai-nx-8g", "edge-ai-nano-8g", "edge-ai-nano-4g")
STYLES = ("nvidia-logo", "clab-logo", "no-logo")
KERNEL_VERSION_PACKAGES = {
    "nvidia-l4t-kernel", "nvidia-l4t-kernel-dtbs", "nvidia-l4t-kernel-headers",
    "nvidia-l4t-kernel-module-configs", "nvidia-l4t-kernel-nvgpu",
    "nvidia-l4t-kernel-oot-headers", "nvidia-l4t-kernel-oot-modules",
    "nvidia-l4t-kernel-openrm", "nvidia-l4t-display-kernel",
}
NVIDIA_VERSION_PACKAGES = {
    "nvidia-l4t-bootloader", "nvidia-l4t-bootloader-utils",
    "nvidia-l4t-kernel-partitions", "nvidia-l4t-initrd", "nvidia-l4t-extlinux",
    "nvidia-l4t-firmware", "nvidia-l4t-gstreamer",
}
POLICY_CONFIG = "etc/compulab/edge-ai-bsp-policy.json"
POLICY_PREFERENCES = "etc/apt/preferences.d/compulab-edge-ai-bsp"
POLICY_HELPER = "usr/libexec/compulab-edge-ai-bsp-policy"
DROPIN = "etc/systemd/system/nvargus-daemon.service.d/90-edgedes-framos-demo.conf"


def require(condition, message):
    if not condition:
        raise ValueError(message)


def regular(path):
    path = Path(path)
    require(path.is_file() and not path.is_symlink() and
            stat.S_ISREG(path.lstat().st_mode) and path.resolve() == path,
            "Expected canonical regular payload input: " + str(path))
    return path


def digest(path):
    with regular(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def load(path, name):
    specification = importlib.util.spec_from_file_location(name, regular(path))
    module = importlib.util.module_from_spec(specification)
    # Provenance checks must not create __pycache__ in the source tree even
    # when a caller did not start Python with -B.
    exec(compile(Path(path).read_bytes(), str(path), "exec"), module.__dict__)
    return module


def source(config, relative):
    root = Path(config["sources"])
    path = root / relative
    require(path.resolve().is_relative_to(root.resolve()), "Payload source escapes its root")
    return regular(path)


def helper_source(config, name):
    direct = Path(config["sources"]) / name
    if direct.exists() or direct.is_symlink():
        return source(config, name)
    return source(config, "sdk-source/compulab/tools/" + name)


def camera_inputs(config):
    bundle = Path(config["bundle"])
    sources = [regular(bundle / "files" / name) for name in (
        "argus_camera.sh", "gst_camera.sh", "edge-ai-desktop-exec",
        "edge-ai-gst-x11-preview", "edge-ai-argus-framos-demo-check.in",
        "90-edgedes-framos-demo.conf.in", "PROVENANCE.txt",
        "Tegra_Software_License_Agreement-Tegra-Linux.txt")]
    manifest_path = source(config, "runtime-assets.json")
    manifest = json.loads(manifest_path.read_text())
    selected = {}
    for sensor in ("676", "678"):
        flag = config["imx" + sensor + "_extended"]
        require(flag in ("0", "1"), "Extended camera mode flags must be 0 or 1")
        identity = "nito" + sensor + ("ext" if flag == "1" else "")
        records = [row for row in manifest["assets"] if row.get("id") == identity]
        require(len(records) == 1, "Expected one selected NITO source: " + identity)
        record = records[0]
        require(record.get("source") == "local" and record.get("role") == "nito" and
                re.fullmatch(r"[0-9a-f]{64}", record.get("sha256", "")),
                "Invalid selected NITO source metadata")
        path = regular(Path(config["assets"][identity]))
        require(digest(path) == record["sha256"], "Selected NITO checksum mismatch: " + identity)
        selected[sensor] = (identity, path)
    selection = config.get("nito_selection", "auto")
    require(selection in ("auto", "single", "per-camera"), "Invalid NITO selection policy")
    return sources + [manifest_path] + [value[1] for value in selected.values()], selected, selection


def boot_inputs(config):
    sdk = Path(config["sdk"])
    require(sdk.is_absolute() and sdk != Path("/") and sdk.is_dir() and
            sdk.resolve() == sdk, "Canonical NVIDIA SDK reference is required for its vendor menu")
    baseline = regular(sdk / "SDK_BASELINE.json")
    original = json.loads(baseline.read_text())
    backup = Path(original["vendor_backup"])
    require(backup.is_absolute() and backup.resolve() == backup and
            backup.is_relative_to(sdk), "Invalid vendor baseline backup directory")
    key = "rootfs/boot/extlinux/extlinux.conf"
    prefix = regular(backup / key)
    require(digest(prefix) == original["sha256"].get(key),
            "Vendor extlinux baseline checksum mismatch")
    paths = [baseline, prefix, source(config, "edge-ai-uefi-update")]
    for relative in (
            "compulab/boot/rootfs-support/oe4t-set-uefi-OSIndications.sh",
            "compulab/boot/rootfs-support/uefi_common.func",
            "compulab/rootfs/usr/sbin/edge-ai-select-fdt",
            "compulab/rootfs/boot/extlinux/extlinux.conf.imx67x.sample"):
        paths.append(source(config, "sdk-source/" + relative))
    return paths


def policy_inputs(config):
    helper = helper_source(config, "package-bsp-policy.py")
    module = load(helper, "standalone_data_bsp_policy")
    require(set(module.PACKAGES) == KERNEL_VERSION_PACKAGES | NVIDIA_VERSION_PACKAGES,
            "BSP package identity table changed")
    return [helper], module


def capsule_inputs(config):
    directory = Path(config["deploy"]) / "edge-ai-uefi-update-capsules"
    require(directory.is_dir() and directory.resolve() == directory,
            "Fresh deployed capsule bundle is required")
    expected = {machine + "-uefi-" + style + ".cap"
                for machine in MACHINES for style in STYLES}
    legacy = config.get("legacy_guids", ())
    require(isinstance(legacy, (tuple, list)) and
            all(isinstance(value, str) for value in legacy) and
            len(set(legacy)) == len(legacy),
            "Legacy capsule GUIDs must be an explicit unique list")
    for value in legacy:
        require(str(uuid.UUID(value)) == value, "Legacy capsule GUID is not canonical")
        expected.update(machine + "-uefi-" + style + "-from-" + value + ".cap"
                        for machine in MACHINES for style in STYLES)
    capsules = {path.name: regular(path) for path in directory.glob("*.cap")}
    require(set(capsules) == expected, "Require every four-module/three-style capsule exactly once")
    sums = regular(directory / "SHA256SUMS")
    checksums = {}
    for line in sums.read_text().splitlines():
        match = re.fullmatch(r"([0-9a-f]{64}) [ *]([A-Za-z0-9_.+-]+\.cap)", line)
        require(match is not None and match[2] not in checksums,
                "Unsafe or duplicate capsule checksum entry")
        checksums[match[2]] = match[1]
    require(set(checksums) == expected, "Capsule checksum inventory mismatch")
    validator = helper_source(config, "package-rootfs.py")
    module = load(validator, "standalone_data_capsule_validation")
    canonical_guid = None
    for name, path in sorted(capsules.items()):
        require(digest(path) == checksums[name], "Capsule checksum mismatch: " + name)
        current, lowest = module.firmware_version(path)
        require(current == FIRMWARE_VERSION and lowest <= current,
                "Stale/incompatible capsule: " + name)
        data = path.read_bytes()
        require(data[:16] == uuid.UUID("6dcbd5ed-e82d-4c44-bda1-7194199ad92a").bytes_le,
                "Unsupported capsule header GUID: " + name)
        header = struct.unpack_from("<I", data, 16)[0]
        offset = header + struct.unpack_from("<Q", data, header + 8)[0]
        guid = str(uuid.UUID(bytes_le=data[offset + 4:offset + 20]))
        if "-from-" in name:
            require(guid == name.split("-from-", 1)[1][:-4], "Legacy FMP GUID mismatch")
        elif canonical_guid is None:
            canonical_guid = guid
        else:
            require(guid == canonical_guid, "Current capsule FMP GUIDs differ")
    require(canonical_guid not in legacy, "Legacy GUID duplicates current capsule GUID")
    return [sums, validator, source(config, "apply-uefi-capsule"), *capsules.values()], capsules, canonical_guid


def input_provenance(config):
    component = config["component"]
    metadata = {}
    if component == "camera-support":
        paths, selected, selection = camera_inputs(config)
        metadata.update(nito_selection=selection,
                        selected_nitos={sensor: value[0] for sensor, value in selected.items()})
    elif component == "boot-tools":
        paths = boot_inputs(config)
    elif component == "bsp-policy":
        paths, _ = policy_inputs(config)
    elif component == "uefi-capsules":
        paths, capsules, guid = capsule_inputs(config)
        metadata.update(capsule_count=len(capsules), current_fmp_guid=guid)
    else:
        raise ValueError("Unsupported simple component: " + component)
    return dict(component=component, files={str(path): digest(path) for path in paths}, **metadata)


def write(payload, relative, data, mode=0o644):
    path = payload / relative
    require(not path.exists() and not path.is_symlink(), "Payload destination already exists")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data if isinstance(data, bytes) else data.encode())
    path.chmod(mode)


def copy(payload, relative, original, mode=0o644):
    write(payload, relative, regular(original).read_bytes(), mode)


def build_payload(config, run_dir):
    provenance = input_provenance(config)
    run_dir = Path(run_dir)
    require(run_dir.is_absolute() and run_dir.resolve() == run_dir and run_dir.is_dir(),
            "Private canonical run directory required")
    payload = run_dir / "payload"
    require(not payload.exists() and not payload.is_symlink(), "Data payload must be new")
    payload.mkdir()
    component = config["component"]
    metadata = dict(provenance=provenance)
    if component == "camera-support":
        _, selected, selection = camera_inputs(config)
        bundle = Path(config["bundle"]) / "files"
        for name in ("argus_camera.sh", "gst_camera.sh"):
            copy(payload, "opt/compulab/bin/" + name, bundle / name, 0o755)
        for name in ("edge-ai-desktop-exec", "edge-ai-gst-x11-preview"):
            copy(payload, "usr/libexec/" + name, bundle / name, 0o755)
        substitutions = {"@LOCALSTATEDIR@": "/var", "@LIBEXECDIR@": "/usr/libexec",
                         "@NITO_SELECTION@": selection}
        for original, destination, mode in (
                ("edge-ai-argus-framos-demo-check.in", "usr/libexec/edge-ai-argus-framos-demo-check", 0o755),
                ("90-edgedes-framos-demo.conf.in", DROPIN, 0o644)):
            text = (bundle / original).read_text()
            for before, after in substitutions.items():
                text = text.replace(before, after)
            require(not re.search(r"@[A-Z_]+@", text), "Unrendered camera template token")
            write(payload, destination, text, mode)
        for sensor, (_, path) in selected.items():
            copy(payload, "var/nvidia/nvcam/settings/edgedes-imx" + sensor + "-demo.nito", path)
        for name in ("PROVENANCE.txt", "Tegra_Software_License_Agreement-Tegra-Linux.txt"):
            copy(payload, "usr/share/edge-ai-argus-framos-demo/" + name, bundle / name)
        metadata["package_overrides"] = dict(conffiles=["/" + DROPIN])
    elif component == "boot-tools":
        paths = boot_inputs(config)
        prefix = paths[1].read_text()
        sample = paths[-1].read_text()
        marker = "# CompuLab camera entries below"
        require(sample.count(marker) == 1 and
                re.search(r"(?m)^DEFAULT[ \t]+primary[ \t]*$", prefix),
                "Unexpected vendor or current camera extlinux menu")
        text = prefix.rstrip() + "\n\n" + marker + sample.split(marker, 1)[1]
        labels = re.findall(r"(?m)^LABEL[ \t]+([^\s]+)", text)
        require(labels and len(labels) == len(set(labels)), "Duplicate boot menu labels")
        write(payload, "boot/extlinux/extlinux.conf", text)
        copy(payload, "boot/extlinux/extlinux.conf.imx67x.sample", paths[-1])
        copy(payload, "usr/sbin/edge-ai-select-fdt", paths[-2], 0o755)
        copy(payload, "usr/bin/oe4t-set-uefi-OSIndications", paths[3], 0o755)
        copy(payload, "usr/bin/uefi_common.func", paths[4])
        updater = paths[2].read_text().replace("@CAPSULE_DIR@", "/usr/share/compulab/uefi-update-capsules")
        require("@CAPSULE_DIR@" not in updater, "Unrendered capsule updater")
        write(payload, "usr/sbin/edge-ai-uefi-update", updater, 0o755)
        metadata["package_overrides"] = dict(conffiles=["/boot/extlinux/extlinux.conf"])
    elif component == "bsp-policy":
        paths, module = policy_inputs(config)
        policy = dict(schema=1, l4t_version="39.2.1", hold_packages=list(module.PACKAGES))
        write(payload, POLICY_CONFIG, json.dumps(policy, sort_keys=True, indent=2) + "\n")
        copy(payload, POLICY_HELPER, paths[0], 0o755)
        pins = "\n".join("Package: %s\nPin: version %s\nPin-Priority: 1000\n" %
                         (name, KERNEL_VERSION if name in KERNEL_VERSION_PACKAGES else NVIDIA_VERSION)
                         for name in module.PACKAGES)
        write(payload, POLICY_PREFERENCES, pins)
        scripts = {
            "postinst": '#!/bin/sh\nset -eu\nif [ "${1-}" = configure ]; then\n'
                        '    /usr/libexec/compulab-edge-ai-bsp-policy configure\nfi\n',
            "prerm": '#!/bin/sh\nset -eu\nif [ "${1-}" = remove ]; then\n'
                     '    /usr/libexec/compulab-edge-ai-bsp-policy restore-config\nfi\n',
        }
        metadata["package_overrides"] = dict(
            conffiles=["/" + POLICY_CONFIG, "/" + POLICY_PREFERENCES], scripts=scripts)
    elif component == "uefi-capsules":
        _, capsules, guid = capsule_inputs(config)
        destination = "usr/share/compulab/uefi-update-capsules/"
        for name, path in sorted(capsules.items()):
            copy(payload, destination + name, path)
        copy(payload, destination + "apply-uefi-capsule", source(config, "apply-uefi-capsule"), 0o755)
        write(payload, destination + "SHA256SUMS", "".join(
            digest(path) + "  " + name + "\n" for name, path in sorted(capsules.items())))
        write(payload, destination + "README.txt",
              "CompuLab Edge-AI complete boot-firmware capsules\n"
              "Payload L4T release: 39.2.1\nCurrent FMP image-type GUID: " + guid + "\n"
              "Use edge-ai-uefi-update to select the exact module and logo style.\n"
              "Package installation does not stage firmware, flash, or reboot.\n")
    return payload, metadata
