#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Build three Ubuntu-native GStreamer plugins in a private builder clone.

This module supplies input_provenance() and build_payload() to the shared
standalone Debian publisher. It does not publish/install packages itself.
No APT, SDK Manager, host package installation, camera or DUT is accessed.
"""
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import sys
import tarfile


sys.dont_write_bytecode = True
PLUGINS = (
    "libgstnvarguscamerasrc.so", "libgstnvvidconv.so",
    "libgstnvvideo4linux2.so",
)
ARCHIVES = (
    "gst-nvarguscamera_src.tbz2", "gst-nvvidconv_src.tbz2",
    "gst-nvvideo4linux2_src.tbz2", "libgstnvcustomhelper_src.tbz2",
)
LIBRARY_PATH = (
    "/opt/nvidia/l4t-gpu-libs/nvgpu:/usr/lib/aarch64-linux-gnu/nvidia:"
    "/usr/local/cuda-13.2/targets/sbsa-linux/lib"
)
SOURCE_NAMES = ("build-gstreamer-deb.py", "build-argus-deb.py",
                "provision-runtime.py", "runtime-assets.json",
                "rootfs_package_inventory.py")


def require(condition, message):
    if not condition:
        raise ValueError(message)


def load_module(path, name):
    specification = importlib.util.spec_from_file_location(name, path)
    require(specification and specification.loader, "Missing native build helper")
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


def support_module(config):
    sources = Path(config["sources"])
    return load_module(sources / "build-argus-deb.py", "gst_native_support")


def checked_inputs(config, support):
    sources = support.canonical(config["sources"], directory=True)
    bundle = support.canonical(config["bundle"], directory=True)
    builder = support.canonical(config["builder"], directory=True)
    require(isinstance(config.get("assets"), dict) and
            {"mmapi", "publicsources"}.issubset(config["assets"]),
            "GStreamer needs pinned MMAPI and public-source assets")
    assets = {name: support.canonical(config["assets"][name], directory=False)
              for name in ("mmapi", "publicsources")}
    require(not any(path.is_relative_to(builder) for path in assets.values()),
            "Pinned assets must be staged outside the read-only builder")
    manifest = json.loads(support.regular(sources / "runtime-assets.json")
                          .read_text())
    records = {}
    for name in assets:
        found = [row for row in manifest["assets"] if row.get("id") == name]
        require(len(found) == 1, "Duplicate/missing pinned source: " + name)
        record = found[0]
        require(record.get("role") == "source" and
                re.fullmatch(r"[0-9a-f]{64}", record.get("sha256", "")),
                "Invalid pinned source record: " + name)
        require(support.digest(assets[name]) == record["sha256"],
                "Pinned source checksum mismatch: " + name)
        records[name] = record
    require(records["mmapi"] == support.mmapi_asset(sources),
            "Unsupported MMAPI source identity")
    require(records["publicsources"].get("source") == "sources" and
            records["publicsources"].get("path") == "public_sources.tbz2",
            "Unsupported NVIDIA public-source identity")
    checksums = manifest.get("gst_archives", {})
    require(set(checksums) == set(ARCHIVES) and all(
        re.fullmatch(r"[0-9a-f]{64}", value) for value in checksums.values()),
        "Expected the complete pinned GStreamer source archive set")
    metadata = support.run(["dpkg-deb", "-f", assets["mmapi"],
                            "Package", "Version", "Architecture"])
    fields = dict(line.split(": ", 1) for line in metadata.splitlines()
                  if ": " in line)
    require(fields == {"Package": "nvidia-l4t-jetson-multimedia-api",
                       "Version": support.NVIDIA_VERSION,
                       "Architecture": "arm64"},
            "Unexpected MMAPI source package metadata")
    return sources, bundle, builder, assets, records, checksums


def input_provenance(config):
    """Read and validate relevant sources/environment without any mutation."""
    support = support_module(config)
    sources, bundle, builder, _assets, records, checksums = checked_inputs(
        config, support)
    result = dict(
        schema=1, source_assets={name: record["sha256"]
                                 for name, record in records.items()},
        source_archives=checksums,
        sources={name: support.digest(support.regular(sources / name))
                 for name in SOURCE_NAMES},
        runtime=support.verify_bundle(bundle),
        builder_packages=support.builder_status(builder),
        plugins=list(PLUGINS))
    result["builder_tools"] = {
        name: support.digest(support.target_file(builder, name)) for name in
        ("usr/bin/dpkg", "usr/bin/cmake", "usr/bin/g++", "usr/bin/make",
         "usr/bin/pkg-config", "usr/bin/patch",
         "usr/local/cuda-13.2/bin/nvcc",
         "opt/nvidia/l4t-gpu-libs/nvgpu/libcuda.so.1.1")}
    return result


def stage_archives(public_sources, destination, checksums, support):
    """Copy only pinned regular subarchives; never extract an outer path."""
    require(not destination.exists() and not destination.is_symlink(),
            "GStreamer subarchive directory must be new")
    destination.mkdir()
    with tarfile.open(public_sources, "r:bz2") as archive:
        members = archive.getmembers()
        for name in ARCHIVES:
            source_name = "Linux_for_Tegra/source/" + name
            matches = [member for member in members if member.name == source_name]
            require(len(matches) == 1, "Missing/duplicate NVIDIA subarchive: " + name)
            member = matches[0]
            require(member.isfile() and 0 < member.size <= 64 * 1024 * 1024,
                    "Unsupported NVIDIA subarchive: " + name)
            target = destination / name
            with archive.extractfile(member) as stream, target.open("xb") as output:
                shutil.copyfileobj(stream, output)
            target.chmod(0o644)
            require(support.digest(target) == checksums[name],
                    "NVIDIA subarchive checksum mismatch: " + name)


def prepare_mmapi(assets, clone, bundle, support, log):
    package = clone / "work/mmapi-package"
    require(not package.exists() and not package.is_symlink(),
            "MMAPI staging directory must be new")
    support.run(["dpkg-deb", "-x", assets["mmapi"], package], log)
    source = package / "usr/src/jetson_multimedia_api"
    support.canonical(source, directory=True)
    support.regular(source / "argus/include/Argus/Argus.h")
    # Header consumers use the same reviewed source adaptation queue. This
    # only applies patches; no Argus sample or application is compiled.
    for patch in sorted((bundle / "patches/argus").glob("*.patch")):
        support.regular(patch)
        support.run(["patch", "--batch", "--forward", "--fuzz=0", "-p1",
                     "-d", source, "-i", patch], log)
    return source


def collect_payload(clone, destination, support):
    require(not destination.exists() and not destination.is_symlink(),
            "GStreamer payload directory must be new")
    source = clone / "work/gst/plugins"
    support.canonical(source, directory=True)
    require({path.name for path in source.iterdir()} == set(PLUGINS),
            "Unexpected or incomplete native GStreamer plugin inventory")
    target = destination / "usr/lib/aarch64-linux-gnu/gstreamer-1.0"
    target.mkdir(parents=True)
    hashes = {}
    for name in PLUGINS:
        plugin = support.regular(source / name)
        support.elf_arm64(plugin)
        output = target / name
        shutil.copyfile(plugin, output)
        output.chmod(0o644)
        hashes[output.relative_to(destination).as_posix()] = support.digest(output)
    licenses = destination / "usr/share/doc/compulab-edge-ai-gstreamer"
    licenses.mkdir(parents=True)
    agreement = clone / "work/runtime/files/Tegra_Software_License_Agreement-Tegra-Linux.txt"
    shutil.copyfile(support.regular(agreement), licenses / "NVIDIA-LICENSE")
    for component in ("gst-nvarguscamera", "gst-nvvidconv", "gst-v4l2"):
        directory = clone / "work/gst/source" / component
        if not directory.is_dir():
            continue
        for source in sorted(directory.iterdir()):
            if source.name.upper().startswith(("COPYING", "LICENSE")):
                shutil.copyfile(support.regular(source),
                                licenses / (component + "-" + source.name))
    for path in licenses.iterdir():
        path.chmod(0o644)
        hashes[path.relative_to(destination).as_posix()] = support.digest(path)
    return hashes


def build_payload(config, run_dir):
    """Return a fresh native plugin payload and build provenance.

    The generic publisher holds the per-work/output locks. Only snapshot
    acquisition takes the shared SDK lock, allowing unrelated SDK use once
    the independent builder clone has been created.
    """
    support = support_module(config)
    sources, bundle, builder, assets, _records, checksums = checked_inputs(
        config, support)
    run_dir = support.canonical(run_dir, directory=True)
    for source in (sources, bundle, builder):
        require(not run_dir.is_relative_to(source) and
                not source.is_relative_to(run_dir),
                "Private GStreamer run must not overlap its source inputs")
    require(not any(path.is_relative_to(run_dir) for path in assets.values()),
            "Pinned assets must be staged outside the new private run")
    for name in ("uid", "gid", "jobs"):
        require(type(config.get(name)) is int, "Expected integer: " + name)
    require(config["uid"] > 0 and config["gid"] >= 0 and
            1 <= config["jobs"] <= 64, "Invalid artifact owner or build parallelism")
    provision = support.load_module(sources / "provision-runtime.py",
                                    "gstreamer_native_provision")
    provision.run = support.run
    if os.uname().machine != "aarch64":
        require(provision.persistent_binfmt(Path("/proc/sys/fs/binfmt_misc/qemu-aarch64")),
                "Persistent ARM64 binfmt interpreter required")
    clone = run_dir / "builder"
    with support.lock_file(support.GLOBAL_SDK_LOCK, config["uid"], config["gid"], wait=True):
        require(not support.mounts_below(builder), "Prepared builder has active mounts")
        before = input_provenance(config)
        support.clone_builder(builder, clone)
        require(support.builder_status(clone) == before["builder_packages"],
                "Prepared builder package state changed during snapshot")
    runtime = clone / "work/runtime"
    shutil.copytree(bundle, runtime,
                    ignore=shutil.ignore_patterns("scratch", "__pycache__"))
    stage_archives(assets["publicsources"], runtime / "sources", checksums, support)
    # The added licensed subarchives are covered by the private bundle's
    # checksum manifest; the maintained source bundle is never rewritten.
    provision.write_manifest(runtime)
    mmapi = prepare_mmapi(assets, clone, runtime, support, run_dir / "prepare.log")
    native_mmapi = "/" + mmapi.relative_to(clone).as_posix()
    with provision.target_context(clone):
        provision.chroot(clone, ["bash", "/work/runtime/gst-port.sh", "build",
                                 "--work-dir", "/work/gst", "--mmapi-source",
                                 native_mmapi, "--cuda-path", "/usr/local/cuda-13.2",
                                 "--jobs", str(config["jobs"])], run_dir / "build.log")
        for name in PLUGINS:
            text = provision.chroot(clone, ["env", "LD_LIBRARY_PATH=" + LIBRARY_PATH,
                                            "ldd", "-r", "/work/gst/plugins/" + name],
                                    run_dir / "loader.log")
            require("not found" not in text and "undefined symbol" not in text,
                    "Unresolved native plugin dependencies: " + name)
    payload = run_dir / "payload"
    hashes = collect_payload(clone, payload, support)
    return payload, dict(inputs=before, files=hashes, plugin_count=len(PLUGINS),
                         native_build=True, hardware_validated=False,
                         services_started=False, apt_invoked=False,
                         sdk_manager_invoked=False)
