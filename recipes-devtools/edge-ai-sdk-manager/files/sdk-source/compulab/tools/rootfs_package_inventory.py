#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Inventory converted Ubuntu rootfs payloads for CompuLab Debian packages.

This module only reads explicitly selected staging trees. It neither changes
the rootfs nor runs a package manager, target executable or host SDK tool.
Package paths and conffile paths are relative to the selected rootfs.
"""

import os
from pathlib import Path
import re
import stat


RELEASE = "6.8.12-l4t-r39.2.1-1021.21-clab-adi-v18"
NVIDIA_VERSION = "39.2.1-20260806224157"
NVIDIA_KERNEL_VERSION = "6.8.12-tegra-" + NVIDIA_VERSION
MACHINES = ("edge-ai-nx-16g", "edge-ai-nx-8g", "edge-ai-nano-8g",
            "edge-ai-nano-4g")
STYLES = ("nvidia-logo", "clab-logo", "no-logo")
SKUS = ("0000", "0001", "0003", "0004")
ARGUS_APPS = (
    "argus_bayeraveragemap", "argus_camera", "argus_cudabayerdemosaic",
    "argus_cudahistogram", "argus_demosaicOutput", "argus_denoise",
    "argus_eglimage", "argus_gstvideoencode", "argus_histogram",
    "argus_multisensor", "argus_multistream", "argus_oneshot",
    "argus_openglbox", "argus_rawBayerOutput", "argus_sensorPrivateMetadata",
    "argus_syncStereoRawReprocess", "argus_syncsensor", "argus_syncstereo",
    "argus_userAlternatingAutoExposure", "argus_userautoexposure",
    "argus_userautowhitebalance", "argus_yuvOneShot", "argus_yuvjpeg",
)
PLUGINS = ("libgstnvarguscamerasrc.so", "libgstnvvidconv.so",
           "libgstnvvideo4linux2.so")
DT_SUFFIXES = (".dtb", ".dtbo", ".dtb.sig", ".dtbo.sig",
               ".dtb.signed", ".dtbo.signed")


def require(condition, message):
    if not condition:
        raise ValueError(message)


def canonical_directory(value):
    path = Path(value)
    require(path.is_absolute() and path != Path("/") and path.is_dir() and
            path.resolve(strict=True) == path,
            "Expected a canonical staging directory: " + str(path))
    return path


def relative_name(value):
    name = str(value)
    path = Path(name)
    require(name not in ("", ".", "..") and not path.is_absolute() and
            all(part not in ("", ".", "..") for part in path.parts) and
            path.as_posix() == name and
            re.fullmatch(r"[A-Za-z0-9_+.,/@=-]+", name),
            "Unsafe package payload path: " + name)
    return name


def regular(root, relative, *, nonempty=False):
    relative = relative_name(relative)
    path = root / relative
    try:
        info = path.lstat()
    except FileNotFoundError as error:
        raise ValueError("Required package payload is missing: " + relative) \
            from error
    require(stat.S_ISREG(info.st_mode) and path.resolve(strict=True) == path,
            "Nonregular or symlinked package payload: " + relative)
    require(not nonempty or info.st_size > 0,
            "Empty required package payload: " + relative)
    return relative


def tree_files(root, relative):
    relative = relative_name(relative)
    directory = canonical_directory(root / relative)
    found = []
    for current, directories, files in os.walk(directory, followlinks=False):
        for name in sorted(directories):
            path = Path(current) / name
            canonical_directory(path)
            relative_name(path.relative_to(root).as_posix())
        for name in sorted(files):
            path = Path(current) / name
            found.append(regular(root, path.relative_to(root).as_posix()))
    require(found, "Package payload tree is empty: " + relative)
    return tuple(sorted(found))


def nvidia(package):
    return package + " (= " + NVIDIA_VERSION + ")"


def own(package, version):
    return "compulab-edge-ai-" + package + " (= " + version + ")"


def device_tree_paths(root, artifacts):
    paths = set()
    for folder in ("dtb", "devicetree"):
        directory = canonical_directory(artifacts / "boot" / folder)
        for source in sorted(directory.iterdir()):
            if not source.name.endswith(DT_SUFFIXES):
                continue
            relative = source.relative_to(artifacts).as_posix()
            regular(artifacts, relative, nonempty=True)
            if source.suffix in (".sig", ".signed"):
                regular(artifacts,
                        source.with_suffix("").relative_to(artifacts)
                        .as_posix(), nonempty=True)
            paths.add(regular(root, relative, nonempty=True))
    require(paths, "Artifact-derived device-tree inventory is empty")
    for machine, sku in zip(MACHINES, SKUS):
        alias = "tegra234-" + machine + "-nv-super.dtb"
        stock = "nvidia-stock-tegra234-p3768-0000+p3767-" + sku + \
                "-nv-super.dtb"
        for name in (alias, stock):
            relative = "boot/dtb/" + name
            paths.add(regular(root, relative, nonempty=True))
            for suffix in (".sig", ".signed"):
                companion = root / (relative + suffix)
                if companion.exists() or companion.is_symlink():
                    paths.add(regular(root, relative + suffix, nonempty=True))
    return tuple(sorted(paths))


def collect_packages(sdk: Path, artifacts: Path, version: str) -> list:
    """Return complete, nonoverlapping package inventories without writes."""
    require(isinstance(version, str) and len(version) <= 128 and
            re.fullmatch(r"[0-9][A-Za-z0-9.+:~\-]*", version),
            "Invalid Debian addon package version")
    sdk = canonical_directory(sdk)
    artifacts = canonical_directory(artifacts)
    root = canonical_directory(sdk / "rootfs")
    packages = []

    def add(name, architecture, paths, depends=(), conffiles=()):
        payload = tuple(sorted({regular(root, path) for path in paths}))
        configuration = tuple(sorted(relative_name(path) for path in conffiles))
        require(set(configuration).issubset(payload),
                "Conffile is absent from package payload: " + name)
        require(payload, "Empty package inventory: " + name)
        packages.append(dict(name="compulab-edge-ai-" + name,
                             architecture=architecture, depends=tuple(depends),
                             conffiles=configuration, paths=payload))

    module_paths = tree_files(root, "usr/lib/modules/" + RELEASE)
    require(any(path.endswith(".ko") for path in module_paths),
            "Kernel module package contains no loadable modules")
    kernel = (
        "boot/Image", "boot/initrd", "boot/config-" + RELEASE,
        "boot/Image.nvidia-stock", "boot/initrd.nvidia-stock",
        "etc/nv-update-initrd/list.d/modules.override",
    ) + module_paths
    add("kernel", "arm64", kernel,
        depends=(nvidia("nvidia-l4t-core"),
                 "nvidia-l4t-kernel (= " + NVIDIA_KERNEL_VERSION + ")",
                 nvidia("nvidia-l4t-initrd"), "kmod"),
        conffiles=("etc/nv-update-initrd/list.d/modules.override",))

    add("device-trees", "all", device_tree_paths(root, artifacts),
        depends=(own("kernel", version),))

    capsule_directory = "usr/share/compulab/uefi-update-capsules"
    capsules = tree_files(root, capsule_directory)
    for machine in MACHINES:
        for style in STYLES:
            regular(root, capsule_directory + "/" + machine + "-uefi-" +
                    style + ".cap", nonempty=True)
    for name in ("SHA256SUMS", "README.txt", "apply-uefi-capsule"):
        regular(root, capsule_directory + "/" + name, nonempty=True)
    add("uefi-capsules", "all", capsules)

    add("boot-tools", "all", (
        "usr/sbin/edge-ai-uefi-update", "usr/sbin/edge-ai-select-fdt",
        "usr/bin/oe4t-set-uefi-OSIndications", "usr/bin/uefi_common.func",
        "boot/extlinux/extlinux.conf.imx67x.sample",
        "boot/extlinux/extlinux.conf",
    ), depends=(own("kernel", version), own("device-trees", version),
                "compulab-edge-ai-uefi-capsules", "efibootmgr", "efivar",
                "util-linux", "coreutils"),
        conffiles=("boot/extlinux/extlinux.conf",))

    manifest = sdk / "compulab/runtime/files/argus-full-suite.txt"
    regular(sdk, manifest.relative_to(sdk).as_posix(), nonempty=True)
    applications = manifest.read_text().splitlines()
    require(len(applications) == len(ARGUS_APPS) and
            len(set(applications)) == len(applications) and
            set(applications) == set(ARGUS_APPS),
            "Expected the complete 23-application Argus suite")
    add("argus", "arm64", ("usr/bin/" + app for app in applications),
        depends=(nvidia("nvidia-l4t-camera"),
                 nvidia("nvidia-l4t-multimedia"), "libgtk-3-0t64",
                 "libx11-6", "libexpat1", "libegl1", "libgles2",
                 "cuda-cudart-13-2 (= 13.2.86-1)"))

    add("gstreamer", "arm64", (
        "usr/lib/aarch64-linux-gnu/gstreamer-1.0/" + name
        for name in PLUGINS),
        depends=(nvidia("nvidia-l4t-gstreamer"),
                 nvidia("nvidia-l4t-camera"),
                 nvidia("nvidia-l4t-multimedia"), "libgstreamer1.0-0",
                 "libgstreamer-plugins-base1.0-0",
                 "cuda-cudart-13-2 (= 13.2.86-1)"))

    dropin = "etc/systemd/system/nvargus-daemon.service.d/" + \
             "90-edgedes-framos-demo.conf"
    add("camera-support", "all", (
        "opt/compulab/bin/argus_camera.sh", "opt/compulab/bin/gst_camera.sh",
        "usr/libexec/edge-ai-desktop-exec",
        "usr/libexec/edge-ai-gst-x11-preview",
        "usr/libexec/edge-ai-argus-framos-demo-check", dropin,
        "var/nvidia/nvcam/settings/edgedes-imx676-demo.nito",
        "var/nvidia/nvcam/settings/edgedes-imx678-demo.nito",
        "usr/share/edge-ai-argus-framos-demo/PROVENANCE.txt",
        "usr/share/edge-ai-argus-framos-demo/" +
        "Tegra_Software_License_Agreement-Tegra-Linux.txt",
    ), depends=(own("argus", version), own("gstreamer", version),
                "python3", "python3-gi", "gir1.2-gtk-3.0",
                "gir1.2-gstreamer-1.0", "gir1.2-gst-plugins-base-1.0",
                "gstreamer1.0-tools", "gstreamer1.0-plugins-base",
                "gstreamer1.0-plugins-good", "gstreamer1.0-plugins-bad",
                "gstreamer1.0-plugins-ugly", "gstreamer1.0-x",
                "libx264-164", "xwayland"), conffiles=(dropin,))

    seen = set()
    for package in packages:
        require(not seen.intersection(package["paths"]),
                "Overlapping CompuLab package payloads")
        seen.update(package["paths"])
    return packages
