#!/usr/bin/env python3
"""Provision a newly generated R39.2.1 SDK; default is a read-only plan.

No host apt, SDK Manager, binfmt registration, flashing or service start.
Execution requires root and an already configured ARM64 binfmt interpreter.
"""
import argparse
import contextlib
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import shutil
import subprocess
import tarfile
import tempfile
from urllib.parse import urlparse

HERE = Path(__file__).resolve().parent
BSP_HOLDS = (
    "nvidia-l4t-bootloader", "nvidia-l4t-bootloader-utils",
    "nvidia-l4t-kernel", "nvidia-l4t-kernel-dtbs", "nvidia-l4t-initrd",
    "nvidia-l4t-kernel-partitions", "nvidia-l4t-extlinux", "nvidia-l4t-firmware",
    "nvidia-l4t-kernel-oot-modules", "nvidia-l4t-display-kernel",
    "nvidia-l4t-kernel-nvgpu", "nvidia-l4t-kernel-openrm",
    "nvidia-l4t-kernel-module-configs", "nvidia-l4t-kernel-headers",
    "nvidia-l4t-kernel-oot-headers",
)
BUILD_PACKAGES = (
    "build-essential", "cmake", "pkg-config", "patch", "xxd",
    "libgtk-3-dev", "libx11-dev", "libexpat1-dev", "libegl-dev",
    "libgles-dev", "libjpeg-dev", "libgstreamer1.0-dev",
    "libgstreamer-plugins-base1.0-dev", "libv4l-dev",
)
LAUNCHER_PACKAGES = (
    "gstreamer1.0-tools", "gstreamer1.0-plugins-good",
    "gstreamer1.0-plugins-bad", "gstreamer1.0-plugins-ugly", "libx264-164",
    "libgtk-3-0t64", "libx11-6", "xwayland", "python3", "python3-gi",
    "gir1.2-gtk-3.0", "gir1.2-gstreamer-1.0",
    "gir1.2-gst-plugins-base-1.0", "kmod", "util-linux",
)
PRESERVE = (
    "boot/Image", "boot/initrd",
    "usr/lib/aarch64-linux-gnu/nvidia/libnvscf.so",
    "opt/nvidia/l4t-gpu-libs/nvgpu/libcuda.so.1.1",
    "etc/systemd/nv-load-gpu-libs.sh",
    "etc/systemd/nv-load-display-modules-choose-variant.sh",
)


def digest(path):
    value = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def run(args, *, log=None, stdin=None, env=None):
    result = subprocess.run([str(arg) for arg in args], input=stdin,
                            text=True, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, env=env)
    if log:
        with Path(log).open("a", encoding="utf-8") as stream:
            stream.write("$ " + " ".join(map(str, args)) + "\n")
            stream.write(result.stdout)
    if result.returncode:
        raise RuntimeError(f"command failed ({result.returncode}): {args[0]}; "
                           f"see {log or result.stdout[-2000:]}")
    return result.stdout


def filename(asset):
    return asset.get("file", Path(asset["path"]).name)


def verify_assets(manifest, directory):
    names = set()
    for asset in manifest["assets"]:
        name = filename(asset)
        if name in names or Path(name).name != name:
            raise ValueError("duplicate or unsafe asset filename")
        names.add(name)
        path = directory / name
        if not path.is_file() or path.is_symlink() or digest(path) != asset["sha256"]:
            raise ValueError(f"missing or mismatched pinned asset: {name}")
        if asset["role"] in ("runtime", "build"):
            actual = run(["dpkg-deb", "-f", path, "Package", "Version", "Architecture"])
            fields = dict(line.split(": ", 1) for line in actual.splitlines())
            if (fields.get("Package"), fields.get("Version")) != (
                    asset["package"], asset["version"]):
                raise ValueError(f"package metadata mismatch: {name}")
            if fields.get("Architecture") not in ("arm64", "all"):
                raise ValueError(f"non-Ubuntu-target package: {name}")


def write_manifest(bundle):
    files = sorted(path for path in bundle.rglob("*") if path.is_file()
                   and path.name != "SHA256SUMS"
                   and not any(part in ("scratch", "__pycache__")
                               for part in path.relative_to(bundle).parts))
    (bundle / "SHA256SUMS").write_text("".join(
        f"{digest(path)}  ./{path.relative_to(bundle)}\n" for path in files))


def assemble_bundle(source, destination, assets, manifest):
    """No extracted NVIDIA archives or generated historical receipts in Git."""
    if destination.exists():
        raise ValueError(f"refusing existing runtime destination: {destination}")
    shutil.copytree(source, destination, symlinks=True,
                    ignore=shutil.ignore_patterns("scratch", "__pycache__"))
    (destination / "sources").mkdir()
    (destination / "nito").mkdir()
    public = next(asset for asset in manifest["assets"] if asset["id"] == "publicsources")
    with tarfile.open(assets / filename(public), "r:bz2") as archive:
        for name, expected in manifest["gst_archives"].items():
            member = archive.getmember("Linux_for_Tegra/source/" + name)
            if not member.isfile() or member.size > 64 * 1024 * 1024:
                raise ValueError("unexpected NVIDIA source subarchive")
            path = destination / "sources" / name
            with archive.extractfile(member) as stream, path.open("wb") as output:
                shutil.copyfileobj(stream, output)
            if digest(path) != expected:
                raise ValueError(f"source subarchive hash mismatch: {name}")
    for asset in manifest["assets"]:
        if asset["role"] == "nito":
            shutil.copy2(assets / filename(asset), destination / "nito" / filename(asset))
    write_manifest(destination)


def parse_status(root):
    result = {}
    for record in (root / "var/lib/dpkg/status").read_text().split("\n\n"):
        fields = dict(line.split(": ", 1) for line in record.splitlines()
                      if ": " in line and not line.startswith(" "))
        if fields.get("Status") == "install ok installed":
            result[fields["Package"]] = fields["Version"]
    return result


def check_sdk(sdk):
    root = sdk / "rootfs"
    if sdk == Path("/") or not (sdk / "flash.sh").is_file():
        raise ValueError("--sdk-root must be the generated Linux_for_Tegra directory")
    os_release = (root / "usr/lib/os-release").read_text()
    if "ID=ubuntu\n" not in os_release or 'VERSION_ID="24.04"' not in os_release:
        raise ValueError("Noble Ubuntu 24.04 rootfs required")
    packages = parse_status(root)
    for name in ("nvidia-l4t-core", "nvidia-l4t-camera", "nvidia-l4t-multimedia"):
        if packages.get(name) != "39.2.1-20260806224157":
            raise ValueError(f"wrong or missing SDK package: {name}")
    for path in PRESERVE:
        if not (root / path).is_file() or (root / path).is_symlink():
            raise ValueError(f"missing regular BSP payload: {path}")
    return root, packages


def persistent_binfmt(path):
    if not path.is_file():
        return False
    text = path.read_text()
    lines = text.splitlines()
    return bool(lines) and lines[0] == "enabled" and bool(re.search(r"^flags:.*F", text, re.M))


def check_apt_plan(text):
    """Only the explicitly supplied NVIDIA userspace package may change."""
    for line in text.splitlines():
        match = re.match(r"(Inst|Remv)\s+(\S+)", line)
        if not match:
            continue
        action, package = match.groups()
        package = package.split(":", 1)[0]
        if action == "Remv":
            raise ValueError(f"APT would remove {package}")
        if package.startswith("nvidia-l4t-") and package != "nvidia-l4t-gstreamer":
            raise ValueError(f"APT would replace protected NVIDIA package {package}")


def mounts_below(root):
    return [line for line in run(["findmnt", "-rn", "-o", "TARGET"]).splitlines()
            if line == str(root) or line.startswith(str(root) + "/")]


@contextlib.contextmanager
def target_context(root):
    """Mask only this rootfs dev/proc; never bind host devices or sysfs."""
    if mounts_below(root):
        raise ValueError("rootfs already has mounts; another installer may be running")
    policy = root / "usr/sbin/policy-rc.d"
    if policy.is_symlink():
        raise ValueError("refusing symlink policy-rc.d")
    previous = (policy.read_bytes(), policy.stat().st_mode & 0o777) if policy.exists() else None
    mounted = []
    try:
        policy.write_text("#!/bin/sh\nexit 101\n")
        policy.chmod(0o755)
        for relative in ("proc", "dev"):
            path = root / relative
            if path.is_symlink():
                raise ValueError(f"refusing symlink {relative}")
            path.mkdir(exist_ok=True)
        run(["mount", "-t", "proc", "-o", "ro,nosuid,nodev,noexec", "proc", root / "proc"])
        mounted.append(root / "proc")
        run(["mount", "-t", "tmpfs", "-o", "mode=0755,nosuid", "tmpfs", root / "dev"])
        mounted.append(root / "dev")
        for name, major, minor in (("null", 1, 3), ("zero", 1, 5),
                                   ("random", 1, 8), ("urandom", 1, 9)):
            run(["mknod", "-m", "0666", root / "dev" / name, "c", major, minor])
        (root / "dev/pts").mkdir()
        run(["mount", "-t", "devpts", "-o", "newinstance,ptmxmode=0666,mode=0620",
             "devpts", root / "dev/pts"])
        mounted.append(root / "dev/pts")
        for name, link in (("ptmx", "pts/ptmx"), ("fd", "/proc/self/fd"),
                           ("stdin", "/proc/self/fd/0"), ("stdout", "/proc/self/fd/1"),
                           ("stderr", "/proc/self/fd/2")):
            (root / "dev" / name).symlink_to(link)
        yield
    finally:
        cleanup_errors = []
        for mount in reversed(mounted):
            try:
                run(["umount", mount])
            except RuntimeError as error:
                cleanup_errors.append(str(error))
        if previous is None:
            policy.unlink(missing_ok=True)
        else:
            policy.write_bytes(previous[0])
            policy.chmod(previous[1])
        if cleanup_errors:
            raise RuntimeError("owned mount cleanup failed: " + "; ".join(cleanup_errors))


def chroot(root, args, log=None, stdin=None):
    # Never leak BitBake compiler/pkg-config/LD_* settings into native Ubuntu.
    return run(["chroot", root, "/usr/bin/env", "-i", "LC_ALL=C",
                "PATH=/usr/sbin:/usr/bin:/sbin:/bin",
                "DEBIAN_FRONTEND=noninteractive", *args], log=log, stdin=stdin)


def install_runtime(root, assets, manifest, work, mirror):
    installed = parse_status(root)
    requested = []
    for asset in manifest["assets"]:
        if asset["role"] != "runtime":
            continue
        version = installed.get(asset["package"])
        if version and version != asset["version"]:
            raise ValueError(f"refusing unplanned runtime downgrade/change: {asset['package']} {version}")
        if not version:
            requested.append(asset)
    temporary = Path(tempfile.mkdtemp(prefix="compulab-runtime-", dir=root / "tmp"))
    temporary.chmod(0o755)
    try:
        paths = []
        for asset in requested:
            target = temporary / filename(asset)
            shutil.copy2(assets / filename(asset), target)
            paths.append("/" + str(target.relative_to(root)))
        missing_launcher = [name for name in LAUNCHER_PACKAGES if name not in installed]
        for name in ("lists/partial", "archives/partial"):
            (temporary / name).mkdir(parents=True)
        (temporary / "ubuntu.sources").write_text(
            "Types: deb\nURIs: " + mirror + "\n"
            "Suites: noble noble-updates noble-security\n"
            "Components: main restricted universe multiverse\n"
            "Signed-By: /usr/share/keyrings/ubuntu-archive-keyring.gpg\n")
        relative = "/" + str(temporary.relative_to(root))
        apt = ["apt-get", "-o", "Dir::Etc::sourcelist=" + relative + "/ubuntu.sources",
               "-o", "Dir::Etc::sourceparts=-", "-o", "Dir::State::lists=" + relative + "/lists",
               "-o", "Dir::Cache::archives=" + relative + "/archives"]
        with target_context(root):
            if paths or missing_launcher:
                chroot(root, [*apt, "update", "--error-on=any"], work / "runtime-dpkg.log")
                command = [*apt, "--no-install-recommends", "--no-remove", "install",
                           *paths, *missing_launcher]
                plan = chroot(root, [*command[:1], "--simulate", *command[1:]],
                              work / "runtime-dpkg.log")
                check_apt_plan(plan)
                chroot(root, [*command[:1], "-y", *command[1:]], work / "runtime-dpkg.log")
            chroot(root, ["ldconfig"], work / "runtime-dpkg.log")
            if chroot(root, ["dpkg", "--audit"]).strip():
                raise ValueError("SDK dpkg database has unfinished transactions")
            chroot(root, ["dpkg-query", "-W"], work / "runtime-package-versions.log")
        provenance = {str(path.relative_to(temporary)): digest(path)
                      for path in temporary.rglob("*") if path.is_file()}
        (work / "runtime-apt-input-hashes.json").write_text(json.dumps(provenance, indent=2) + "\n")
        for path in (temporary / "lists").glob("*InRelease"):
            shutil.copy2(path, work / ("runtime-" + path.name))
    finally:
        shutil.rmtree(temporary)


def prepare_builder(root, builder, assets, manifest, bundle, work, mirror):
    def ignore(directory, names):
        relative = Path(directory).relative_to(root)
        if relative == Path("."):
            return set(names) & {"proc", "sys", "dev", "run", "tmp", "work"}
        if relative == Path("usr"):
            return set(names) & {"src"}
        if relative == Path("usr/lib"):
            return set(names) & {"modules"}
        return set()
    shutil.copytree(root, builder, symlinks=True, ignore=ignore)
    for relative in ("proc", "sys", "dev", "run", "tmp", "work", "work/inputs"):
        (builder / relative).mkdir(parents=True, exist_ok=True)
    (builder / "tmp").chmod(0o1777)
    shutil.copytree(bundle, builder / "work/runtime")
    for asset in manifest["assets"]:
        if asset["role"] == "build" or asset["id"] == "mmapi":
            shutil.copy2(assets / filename(asset), builder / "work/inputs" / filename(asset))
    resolver = builder / "etc/resolv.conf"
    resolver.unlink(missing_ok=True)
    shutil.copyfile("/etc/resolv.conf", resolver)
    # Only signed Noble feeds are enabled in the disposable builder. All
    # NVIDIA build tools arrive as the exact fetcher-verified local .debs.
    (builder / "etc/apt/sources.list").write_text("")
    parts = builder / "etc/apt/sources.list.d"
    for path in parts.iterdir():
        if path.is_file() or path.is_symlink():
            path.unlink()
    (parts / "ubuntu.sources").write_text(
        "Types: deb\nURIs: " + mirror + "\n"
        "Suites: noble noble-updates noble-security\n"
        "Components: main restricted universe multiverse\n"
        "Signed-By: /usr/share/keyrings/ubuntu-archive-keyring.gpg\n")
    local_debs = ["/work/inputs/" + filename(asset) for asset in manifest["assets"]
                  if asset["role"] == "build"]
    with target_context(builder):
        chroot(builder, ["apt-get", "update"], work / "builder-apt.log")
        command = ["apt-get", "--no-install-recommends", "install", *BUILD_PACKAGES, *local_debs]
        plan = chroot(builder, [command[0], "--simulate", *command[1:]], work / "builder-apt.log")
        check_apt_plan(plan)
        chroot(builder, [command[0], "-y", *command[1:]], work / "builder-apt.log")
        chroot(builder, ["dpkg-query", "-W"], work / "builder-package-versions.log")


def verify_target(root, suite, work):
    library_path = "/opt/nvidia/l4t-gpu-libs/nvgpu:/usr/lib/aarch64-linux-gnu/nvidia:/usr/local/cuda-13.2/targets/sbsa-linux/lib"
    plugins = ["libgstnvarguscamerasrc.so", "libgstnvvidconv.so",
               "libgstnvvideo4linux2.so", "libgstx264.so", "libgstnvjpeg.so"]
    with target_context(root):
        for relative in ["usr/bin/" + name for name in suite] + [
                "usr/lib/aarch64-linux-gnu/gstreamer-1.0/" + name for name in plugins]:
            output = chroot(root, ["env", "LD_LIBRARY_PATH=" + library_path,
                                  "ldd", "-r", "/" + relative], work / "target-loader.log")
            if "not found" in output or "undefined symbol" in output:
                raise ValueError(f"target loader failure: {relative}")
        for plugin in plugins:
            chroot(root, ["env", "LD_LIBRARY_PATH=" + library_path,
                          "GST_PLUGIN_SYSTEM_PATH_1_0=", "GST_PLUGIN_PATH_1_0=",
                          "GST_REGISTRY_FORK=no", "GST_REGISTRY=/dev/null",
                          "gst-inspect-1.0", "--plugin",
                          "/usr/lib/aarch64-linux-gnu/gstreamer-1.0/" + plugin],
                   work / "target-plugin-registration.log")
        chroot(root, ["/opt/compulab/bin/gst_camera.sh", "record", "--sensor", "imx678",
                      "--encoder", "software", "--dry-run"], work / "target-launcher.log")
        chroot(root, ["python3", "-c", "import gi; gi.require_version('Gtk','3.0'); gi.require_version('Gst','1.0'); gi.require_version('GstVideo','1.0'); from gi.repository import Gtk,Gst,GstVideo"], work / "target-launcher.log")


def execute(args, manifest, root):
    if os.geteuid() != 0:
        raise ValueError("--execute requires explicit root privileges; no sudo/password is hidden here")
    binfmt = Path("/proc/sys/fs/binfmt_misc/qemu-aarch64")
    if not persistent_binfmt(binfmt):
        raise ValueError("preconfigured ARM64 binfmt with persistent F interpreter required; host state is not changed")
    if run(["git", "-c", f"safe.directory={args.sdk_root}", "-C", args.sdk_root,
            "rev-parse", "--show-toplevel"]).strip() != str(args.sdk_root):
        raise ValueError("SDK must have its own Git baseline before provisioning")
    run(["git", "-c", f"safe.directory={args.sdk_root}", "-C", args.sdk_root,
         "rev-parse", "--verify", "HEAD"])
    if args.work_dir.exists():
        raise ValueError("--work-dir must be new; do not silently reuse a partial provision")
    args.work_dir.mkdir(parents=True)
    before = {path: digest(root / path) for path in PRESERVE if (root / path).is_file()}
    holds_before = chroot(root, ["apt-mark", "showhold"]).splitlines()
    # Record and protect the existing BSP before any disposable-builder APT.
    available_holds = [name for name in BSP_HOLDS if name in parse_status(root)]
    chroot(root, ["apt-mark", "hold", *available_holds], args.work_dir / "package-policy.log")
    bundle = args.sdk_root / "compulab/runtime"
    assemble_bundle(args.bundle_source, bundle, args.assets_dir, manifest)
    install_runtime(root, args.assets_dir, manifest, args.work_dir, args.ubuntu_mirror)
    if before != {path: digest(root / path) for path in before}:
        raise ValueError("runtime package install changed protected BSP/vendor payloads")
    builder = args.work_dir / "builder"
    prepare_builder(root, builder, args.assets_dir, manifest, bundle,
                    args.work_dir, args.ubuntu_mirror)
    mmapi = next(asset for asset in manifest["assets"] if asset["id"] == "mmapi")
    with target_context(builder):
        chroot(builder, ["bash", "/work/runtime/runtime-port.sh", "build", "--suite", "full",
                        "--source-deb", "/work/inputs/" + filename(mmapi),
                        "--work-dir", "/work/argus", "--jobs", str(args.jobs)],
               args.work_dir / "argus-build.log")
        chroot(builder, ["bash", "/work/runtime/gst-port.sh", "build",
                        "--work-dir", "/work/gst", "--mmapi-source", "/work/argus/source",
                        "--cuda-path", "/usr/local/cuda-13.2", "--jobs", str(args.jobs)],
               args.work_dir / "gst-build.log")
    run(["bash", bundle / "runtime-port.sh", "stage", "--rootfs", root,
         "--work-dir", builder / "work/argus", "--gst-work-dir", builder / "work/gst",
         "--imx676-extended", args.imx676_extended, "--imx678-extended", args.imx678_extended],
        log=args.work_dir / "runtime-stage.log")
    chroot(root, ["apt-mark", "hold", "nvidia-l4t-gstreamer"], args.work_dir / "package-policy.log")
    suite = (bundle / "files/argus-full-suite.txt").read_text().splitlines()
    verify_target(root, suite, args.work_dir)
    after = {path: digest(root / path) for path in before}
    if before != after:
        raise ValueError("runtime provisioning changed a protected BSP/vendor payload")
    holds_after = chroot(root, ["apt-mark", "showhold"]).splitlines()
    if not set(holds_before).issubset(holds_after):
        raise ValueError("an existing package hold was lost")
    receipt = args.sdk_root / "compulab/receipts/runtime-provision"
    receipt.mkdir(parents=True)
    for path in args.work_dir.iterdir():
        if path.is_file() and (path.suffix in (".log", ".json") or path.name.endswith("InRelease")):
            shutil.copy2(path, receipt / path.name)
    shutil.copytree(builder / "work/argus/stage-backup", receipt / "pre-stage-backup")
    files = ["usr/bin/" + name for name in suite] + [
        "usr/lib/aarch64-linux-gnu/gstreamer-1.0/" + name for name in
        ("libgstnvarguscamerasrc.so", "libgstnvvidconv.so", "libgstnvvideo4linux2.so")]
    (receipt / "receipt.json").write_text(json.dumps({
        "schema": 1, "method": "isolated Ubuntu Noble aarch64 native build under QEMU",
        "bundle_sha256": digest(bundle / "SHA256SUMS"),
        "assets": manifest, "preserved_payloads": after,
        "holds_before": holds_before, "holds_after": holds_after,
        "new_holds": sorted(set(holds_after) - set(holds_before)),
        "installed_elf_sha256": {path: digest(root / path) for path in files},
        "hardware_tested": False, "services_started": False,
        "nito_modes": {"imx676_extended": args.imx676_extended,
                       "imx678_extended": args.imx678_extended},
    }, indent=2) + "\n")


def main(argv=None):
    def interrupted(signum, frame):
        # Raise through target_context so owned mounts/policy files unwind.
        raise SystemExit("Runtime provisioning interrupted; incomplete work retained")
    signal.signal(signal.SIGTERM, interrupted)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sdk-root", type=Path, required=True)
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--assets-dir", type=Path, required=True)
    parser.add_argument("--bundle-source", type=Path, default=HERE / "runtime")
    parser.add_argument("--asset-manifest", type=Path, default=HERE / "runtime-assets.json")
    parser.add_argument("--ubuntu-mirror", default="https://ports.ubuntu.com/ubuntu-ports")
    parser.add_argument("--jobs", type=int, default=4)
    parser.add_argument("--imx676-extended", choices=("0", "1"), default="1")
    parser.add_argument("--imx678-extended", choices=("0", "1"), default="0")
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args(argv)
    for name in ("sdk_root", "work_dir", "assets_dir", "bundle_source"):
        setattr(args, name, getattr(args, name).resolve())
    if args.jobs < 1:
        parser.error("--jobs must be positive")
    mirror = urlparse(args.ubuntu_mirror)
    if mirror.scheme != "https" or not mirror.hostname or mirror.username or mirror.password:
        parser.error("use an HTTPS Ubuntu mirror without embedded credentials")
    if args.sdk_root == args.work_dir or args.sdk_root in args.work_dir.parents or args.work_dir in args.sdk_root.parents:
        parser.error("SDK and isolated work directories must not contain each other")
    manifest = json.loads(args.asset_manifest.read_text())
    verify_assets(manifest, args.assets_dir)
    root, _ = check_sdk(args.sdk_root)
    run(["bash", args.bundle_source / "runtime-port.sh", "check"])
    if not args.execute:
        print(json.dumps({"action": "read-only plan", "sdk_root": str(args.sdk_root),
                          "builder": str(args.work_dir / "builder"),
                          "runtime_debs": [filename(asset) for asset in manifest["assets"]
                                           if asset["role"] == "runtime"],
                          "argus_apps": 23, "rebuilt_gst_plugins": 3,
                          "requires_root_and_existing_binfmt": True,
                          "host_apt": False, "device_access": False}, indent=2))
        return 0
    execute(args, manifest, root)
    print("PASS: Ubuntu runtime provisioned; hardware remains unqualified.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ValueError, RuntimeError, OSError, KeyError) as error:
        raise SystemExit(f"ERROR: {error}")
