#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Build fresh kernel/DT payloads without changing the source Ubuntu SDK.

The generic Debian publisher owns privileges, locks, versions and output.
Only the kernel builder regenerates an initrd, inside a private SDK clone.
The device-tree builder never stages a kernel, native runtime or firmware.
"""
import hashlib
import importlib.util
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import signal
import stat
import subprocess
import sys


sys.dont_write_bytecode = True
RELEASE = "6.8.12-l4t-r39.2.1-1021.21-clab-adi-v18"
NVIDIA_VERSION = "39.2.1-20260806224157"
SKUS = {"edge-ai-nx-16g": "0000", "edge-ai-nx-8g": "0001",
        "edge-ai-nano-8g": "0003", "edge-ai-nano-4g": "0004"}
DT_SUFFIXES = (".dtb", ".dtbo", ".dtb.sig", ".dtbo.sig",
               ".dtb.signed", ".dtbo.signed")
TRANSIENT = {"proc", "sys", "dev", "run", "tmp", "work"}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def regular(path):
    path = Path(path)
    require(path.is_file() and not path.is_symlink() and
            stat.S_ISREG(path.stat().st_mode), "Expected regular boot input: " + str(path))
    return path


def canonical(path):
    path = Path(path)
    require(path.is_absolute() and path != Path("/") and path.is_dir() and
            path.resolve() == path, "Expected canonical boot staging directory: " + str(path))
    return path


def relative_name(value):
    require(isinstance(value, str), "Boot input path must be a string")
    path = PurePosixPath(value)
    require(value not in ("", ".") and not path.is_absolute() and
            ".." not in path.parts and path.as_posix() == value and "\\" not in value,
            "Unsafe relative boot input: " + value)
    return value


def load_module(path, name):
    specification = importlib.util.spec_from_file_location(name, regular(path))
    module = importlib.util.module_from_spec(specification)
    sys.modules[name] = module
    specification.loader.exec_module(module)
    return module


def source_file(config, name):
    sources = canonical(config["sources"])
    direct = sources / name
    if direct.is_file():
        return regular(direct)
    return regular(sources / "sdk-source/compulab/tools" / name)


def run(*command, cwd=None):
    process = subprocess.Popen([str(value) for value in command], cwd=cwd,
                               stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                               stderr=subprocess.STDOUT, text=True, start_new_session=True,
                               env={"PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
                                    "LC_ALL": "C", "SOURCE_DATE_EPOCH": "0"})
    try:
        output, _ = process.communicate()
    except BaseException:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            process.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.communicate()
        raise
    if process.returncode:
        raise RuntimeError("Boot payload command failed: " + " ".join(map(str, command)) +
                           "\n" + output)
    return output


def checked_baseline(sdk):
    sdk = canonical(sdk)
    baseline = json.loads(regular(sdk / "SDK_BASELINE.json").read_text())
    require(baseline.get("format_version") == 1 and
            baseline.get("l4t_version") == "39.2.1" and
            isinstance(baseline.get("sha256"), dict),
            "A verified R39.2.1 vendor baseline is required")
    # The saved absolute path may describe the SDK's original host/NFS mount.
    # Resolve the known backup beneath this explicitly selected SDK instead.
    backup = canonical(sdk / "compulab/vendor-backup")
    for name, checksum in baseline["sha256"].items():
        relative_name(name)
        require(isinstance(checksum, str) and re.fullmatch(r"[0-9a-f]{64}", checksum),
                "Invalid vendor baseline checksum")
    return baseline, backup


def stock_file(sdk, name):
    baseline, backup = checked_baseline(sdk)
    relative_name(name)
    require(name in baseline["sha256"], "Stock input is not recorded in vendor baseline: " + name)
    path = regular(backup / name)
    require(path.resolve() == path and digest(path) == baseline["sha256"][name],
            "Stock vendor baseline checksum mismatch: " + name)
    return path


def dtb_name(sku):
    return "tegra234-p3768-0000+p3767-" + sku + "-nv-super.dtb"


def validate_ubuntu_sdk(sdk):
    rootfs = canonical(Path(sdk) / "rootfs")
    release = regular(rootfs / "usr/lib/os-release").read_text()
    require(re.search(r'(?m)^ID="?ubuntu"?$', release) and
            re.search(r'(?m)^VERSION_ID="?24[.]04"?$', release),
            "NVIDIA Ubuntu 24.04 is required for initrd generation")
    require(re.search(r"# R39 .*REVISION: 2[.]1,",
                      regular(rootfs / "etc/nv_tegra_release").read_text()),
            "Only L4T R39.2.1 Ubuntu initrds are supported")
    installed = {}
    for paragraph in regular(rootfs / "var/lib/dpkg/status").read_text().split("\n\n"):
        fields = dict(line.split(": ", 1) for line in paragraph.splitlines()
                      if ": " in line and not line.startswith(" "))
        if fields.get("Status") in ("install ok installed", "hold ok installed"):
            installed[fields.get("Package")] = fields
    for package, expected in (("nvidia-l4t-initrd", NVIDIA_VERSION),
                              ("nvidia-l4t-kernel", "6.8.12-tegra-" + NVIDIA_VERSION)):
        row = installed.get(package, {})
        require(row.get("Version") == expected and row.get("Architecture") == "arm64",
                "Missing/mismatched Ubuntu initrd environment: " + package)
    with regular(rootfs / "usr/bin/dpkg").open("rb") as stream:
        header = stream.read(20)
    require(header[:6] == b"\x7fELF\x02\x01" and len(header) == 20 and
            int.from_bytes(header[18:20], "little") == 183,
            "The Ubuntu initrd environment must be AArch64")


def fresh_dt_inputs(deploy):
    deploy = canonical(deploy)
    directory = canonical(deploy / "devicetree")
    files = {}
    for path in sorted(directory.iterdir()):
        if path.name.endswith(DT_SUFFIXES):
            regular(path)
            if path.suffix in (".sig", ".signed"):
                regular(path.with_suffix(""))
            files["devicetree/" + path.name] = path
    for sku in SKUS.values():
        name = dtb_name(sku)
        candidates = [path for path in (deploy / name, directory / name) if path.exists()]
        require(candidates and len({digest(regular(path)) for path in candidates}) == 1,
                "Missing or conflicting fresh module DTB: " + name)
        for path in candidates:
            files[path.relative_to(deploy).as_posix()] = path
        for extension in (".sig", ".signed"):
            companions = [path.with_name(name + extension) for path in candidates
                          if path.with_name(name + extension).exists()]
            require(len({digest(regular(path)) for path in companions}) <= 1,
                    "Conflicting fresh module DTB signatures: " + name + extension)
            for path in companions:
                files[path.relative_to(deploy).as_posix()] = path
    required = {"edgedes-adi-v18-transport-4port.dtbo",
                "edgedes-adi-v18-framos-imx676-4port.dtb",
                "edgedes-adi-v18-framos-imx678-4port.dtb",
                "tegra234-edge-ai-adi-base.dtb"}
    required.update("edgedes-adi-v18-camera-%s-port%d.dtbo" % (sensor, port)
                    for sensor in ("imx676", "imx678") for port in range(4))
    require(required.issubset({path.name for path in files.values()}),
            "Fresh camera DTB/overlay set is incomplete")
    return files


def input_provenance(config, component):
    require(component in ("kernel", "device-trees"), "Unsupported boot package component")
    sdk = canonical(config["sdk"])
    deploy = canonical(config["deploy"])
    records = {"sdk/SDK_BASELINE.json": digest(regular(sdk / "SDK_BASELINE.json"))}
    for name, path in fresh_dt_inputs(deploy).items():
        records["deploy/" + name] = digest(path)
    baseline, backup = checked_baseline(sdk)
    selected = {"kernel/dtb/" + dtb_name(sku) for sku in SKUS.values()}
    selected.update(name + extension for name in list(selected)
                    for extension in (".sig", ".signed")
                    if name + extension in baseline["sha256"])
    if component == "kernel":
        validate_ubuntu_sdk(sdk)
        selected.update(("kernel/Image", "rootfs/boot/Image", "rootfs/boot/initrd"))
        for name in ("kernel", "nvidia-kernel-oot"):
            for extension in (".json", ".tar.xz"):
                path = regular(deploy / "edge-ai-sdk" / (name + extension))
                records["deploy/edge-ai-sdk/" + path.name] = digest(path)
        for name in ("tools/l4t_update_initrd.sh", "rootfs/var/lib/dpkg/status",
                     "rootfs/etc/nv_tegra_release", "rootfs/usr/sbin/nv-update-initrd",
                     "rootfs/usr/lib/os-release", "rootfs/usr/bin/dpkg"):
            records["sdk/" + name] = digest(regular(sdk / name))
        lists = canonical(sdk / "rootfs/etc/nv-update-initrd/list.d")
        for path in sorted(lists.iterdir()):
            if path.is_file():
                records["sdk/rootfs/etc/nv-update-initrd/list.d/" + path.name] = digest(regular(path))
        for name in ("assemble-sdk.py", "install-kernel.py", "check-module-abi.py",
                     "provision-runtime.py"):
            records["sources/" + name] = digest(source_file(config, name))
    for name in sorted(selected):
        records["stock/" + name] = digest(stock_file(sdk, name))
    return records


def copy_file(source, destination, mode=0o644):
    source = regular(source)
    require(not destination.exists() and not destination.is_symlink(),
            "Refusing existing boot payload destination: " + str(destination))
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, destination)
    destination.chmod(mode)


def stage_device_trees(config, destination):
    sdk = canonical(config["sdk"])
    deploy = canonical(config["deploy"])
    require(not destination.exists(), "Device-tree staging must be new")
    inputs = fresh_dt_inputs(deploy)
    destination.mkdir()
    dtb = destination / "boot/dtb"
    overlays = destination / "boot/devicetree"
    dtb.mkdir(parents=True)
    overlays.mkdir(parents=True)
    for name, path in inputs.items():
        if not name.startswith("devicetree/"):
            continue
        copy_file(path, overlays / path.name)
        if path.name.endswith((".dtb", ".dtb.sig", ".dtb.signed")):
            copy_file(path, dtb / path.name)
    baseline, _ = checked_baseline(sdk)
    for machine, sku in SKUS.items():
        name = dtb_name(sku)
        originals = [path for path in (deploy / name, deploy / "devicetree" / name)
                     if path.is_file()]
        source = originals[0]
        if not (dtb / name).exists():
            copy_file(source, dtb / name)
        alias = "tegra234-" + machine + "-nv-super.dtb"
        copy_file(source, dtb / alias)
        stock = "kernel/dtb/" + name
        copy_file(stock_file(sdk, stock), dtb / ("nvidia-stock-" + name))
        for extension in (".sig", ".signed"):
            companions = [path.with_name(name + extension) for path in originals
                          if path.with_name(name + extension).is_file()]
            if companions:
                if not (dtb / (name + extension)).exists():
                    copy_file(companions[0], dtb / (name + extension))
                copy_file(companions[0], dtb / (alias + extension))
            if stock + extension in baseline["sha256"]:
                copy_file(stock_file(sdk, stock + extension),
                          dtb / ("nvidia-stock-" + name + extension))
    return destination


def build_device_trees(config, run_dir):
    run_dir = canonical(run_dir)
    provenance = input_provenance(config, "device-trees")
    payload = stage_device_trees(config, run_dir / "payload")
    paths = [path for path in payload.rglob("*") if path.is_file()]
    return payload, dict(kernel_release=RELEASE, fresh_inputs=provenance,
                         dtb_count=sum(path.name.endswith(".dtb") for path in paths),
                         overlay_count=sum(path.name.endswith(".dtbo") for path in paths),
                         aliases={machine: "tegra234-" + machine + "-nv-super.dtb"
                                  for machine in SKUS}, hardware_validation="Not performed")


def clone_sdk_rootfs(config, run_dir):
    sdk = canonical(config["sdk"])
    original = canonical(sdk / "rootfs")
    run_dir = canonical(run_dir)
    require(not run_dir.is_relative_to(sdk) and not sdk.is_relative_to(run_dir),
            "Private kernel work must not overlap the source SDK")
    mounts = run("findmnt", "-rn", "-o", "TARGET").splitlines()
    require(not any(path == str(original) or path.startswith(str(original) + "/")
                    for path in mounts), "Source SDK rootfs has active mounts")
    clone = run_dir / "Linux_for_Tegra"
    require(not clone.exists() and not clone.is_symlink(), "Private kernel SDK clone must be new")
    clone.mkdir()

    def ignore(directory, names):
        relative = Path(directory).relative_to(original)
        if relative == Path("."):
            return set(names) & TRANSIENT
        if relative == Path("var"):
            return set(names) & {"tmp"}
        return set()

    shutil.copytree(original, clone / "rootfs", symlinks=True, ignore=ignore)
    for name in (*TRANSIENT, "var/tmp"):
        (clone / "rootfs" / name).mkdir(parents=True, exist_ok=True)
    for name in ("tmp", "var/tmp"):
        (clone / "rootfs" / name).chmod(0o1777)
    baseline, _ = checked_baseline(sdk)
    backup = clone / "compulab/vendor-backup"
    for name in baseline["sha256"]:
        copy_file(stock_file(sdk, name), backup / name)
    baseline = dict(baseline, vendor_backup=str(backup))
    (clone / "SDK_BASELINE.json").write_text(json.dumps(baseline, sort_keys=True, indent=2) + "\n")
    git = canonical(sdk / ".git")
    shutil.copytree(git, clone / ".git", symlinks=True)
    copy_file(regular(sdk / "tools/l4t_update_initrd.sh"), clone / "tools/l4t_update_initrd.sh", 0o755)
    fallback_qemu = sdk / "nv_tegra/qemu-aarch64-static"
    if fallback_qemu.is_file():
        copy_file(fallback_qemu, clone / "nv_tegra/qemu-aarch64-static", 0o755)
    for name in ("install-kernel.py", "check-module-abi.py"):
        copy_file(source_file(config, name), clone / "compulab/tools" / name, 0o755)
    # Do not reuse a previously customized initrd as the vendor seed.
    copy_file(stock_file(sdk, "kernel/Image"), clone / "kernel/Image")
    copy_file(stock_file(sdk, "rootfs/boot/initrd"), clone / "bootloader/l4t_initrd.img")
    (clone / "kernel/dtb").mkdir()

    # Preserve removed clone contents for diagnosis; never remove SDK inputs.
    for relative in ("usr/lib/modules/" + RELEASE, "boot/Image.nvidia-stock",
                     "boot/initrd.nvidia-stock"):
        path = clone / "rootfs" / relative
        if path.exists() or path.is_symlink():
            require(not path.is_symlink() and path.resolve() == path,
                    "Unexpected symlink in cloned kernel replacement")
            destination = run_dir / "clone-backup/rootfs" / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            path.rename(destination)
    return clone


def install_private_kernel(config, artifacts, clone):
    installer = load_module(source_file(config, "install-kernel.py"), "boot_payload_installer")
    provision = load_module(source_file(config, "provision-runtime.py"), "boot_payload_provision")

    def installer_run(*command, cwd=None):
        if str(command[0]) == str(clone / "tools/l4t_update_initrd.sh"):
            with provision.target_context(clone / "rootfs"):
                return run(*command, cwd=cwd)
        return run(*command, cwd=cwd)

    installer.run = installer_run
    rootfs, modules, backup = installer.inspect_sources(artifacts, clone)
    installer.install(artifacts, clone, rootfs, modules, backup)
    return json.loads(regular(clone / "compulab/kernel-manifest.json").read_text())


def build_kernel(config, run_dir):
    require(os.geteuid() == 0, "Kernel initrd preparation requires explicit root authorization")
    run_dir = canonical(run_dir)
    provenance = input_provenance(config, "kernel")
    assembler = load_module(source_file(config, "assemble-sdk.py"), "boot_payload_assembler")
    assembler.run = run
    artifacts, manifests = assembler.prepare_artifacts(
        dict(deploy=str(canonical(config["deploy"])), work=str(run_dir)))
    count = assembler.validate_kernel_config(artifacts, manifests["kernel"])
    clone = clone_sdk_rootfs(config, run_dir)
    installed = install_private_kernel(config, artifacts, clone)
    payload = run_dir / "payload"
    require(not payload.exists(), "Kernel payload destination must be new")
    payload.mkdir()
    for name in ("boot/Image", "boot/initrd", "boot/config-" + RELEASE,
                 "boot/Image.nvidia-stock", "boot/initrd.nvidia-stock",
                 "etc/nv-update-initrd/list.d/modules.override"):
        copy_file(clone / "rootfs" / name, payload / name)
    modules = clone / "rootfs/usr/lib/modules" / RELEASE
    require(len(list(modules.rglob("*.ko"))) > 100, "Incomplete installed module payload")
    shutil.copytree(modules, payload / "usr/lib/modules" / RELEASE, symlinks=True,
                    ignore=shutil.ignore_patterns("build", "source"))
    licenses = artifacts / "metadata/licenses"
    if licenses.is_dir():
        shutil.copytree(licenses, payload / "usr/share/doc/compulab-edge-ai-kernel/licenses")
    return payload, dict(kernel_release=RELEASE, config_request_count=count,
                         module_count=installed["module_count"],
                         initrd_sha256=installed["initrd_sha256"],
                         fresh_inputs=provenance,
                         conffiles=["/etc/nv-update-initrd/list.d/modules.override"],
                         diversions=[["/boot/Image", "/boot/Image.compulab-distrib"],
                                     ["/boot/initrd", "/boot/initrd.compulab-distrib"]],
                         hardware_validation="Not performed")
