#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Rebuild Ubuntu Argus packages in a private copy of a prepared builder.

The default plan is read-only. Execution never installs a package, invokes
SDK Manager/APT, changes the source builder, or accesses a camera or DUT.
"""
import argparse
import contextlib
import fcntl
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
import tarfile
import tempfile


# Even a direct invocation without python -B must leave the plan inputs alone.
sys.dont_write_bytecode = True

GLOBAL_SDK_LOCK = Path("/tmp/edge-ai-sdkmanager.lock")
WORK_MARKER = ".edge-ai-argus-deb-work"
WORK_ID = "CompuLab Argus Debian private work directory, version 1\n"
OUTPUT_MARKER = ".edge-ai-argus-deb-output"
OUTPUT_ID = "CompuLab Argus Debian output directory, version 1\n"
NVIDIA_VERSION = "39.2.1-20260806224157"
CUDA_VERSION = "13.2.86-1"
SOURCE_FILES = ("build-argus-deb.py", "provision-runtime.py", "deb_packages.py",
                "rootfs_package_inventory.py", "runtime-assets.json")
TRANSIENT = {"proc", "sys", "dev", "run", "tmp", "work"}
PATH_FIELDS = ("builder", "work", "output", "sources", "bundle", "source_deb")


def require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def load_module(path, name):
    specification = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


def run(command, log=None, stdin=None, env=None):
    environment = {"PATH": "/usr/sbin:/usr/bin:/sbin:/bin",
                   "LC_ALL": "C", "SOURCE_DATE_EPOCH": "0"}
    if env is not None:
        environment.update(env)
    process = subprocess.Popen([str(value) for value in command], text=True,
                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                               stdin=subprocess.PIPE if stdin is not None else subprocess.DEVNULL,
                               start_new_session=True, env=environment)
    try:
        output, _ = process.communicate(input=stdin)
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
    if log is not None:
        with Path(log).open("a", encoding="utf-8") as stream:
            stream.write("$ " + " ".join(map(str, command)) + "\n")
            stream.write(output)
    if process.returncode:
        raise RuntimeError("Command failed (exit %s): %s%s" % (
            process.returncode, " ".join(map(str, command)),
            " (see " + str(log) + ")" if log else "\n" + output))
    return output


def regular(path):
    path = Path(path)
    require(path.is_file() and not path.is_symlink() and
            stat.S_ISREG(path.stat().st_mode), "Expected regular file: " + str(path))
    return path


def canonical(value, *, directory=None):
    require(isinstance(value, (str, Path)), "Path must be a scalar string")
    path = Path(value)
    require(path.is_absolute() and path != Path("/") and
            path.resolve(strict=False) == path,
            "Expected canonical absolute path: " + str(path))
    if directory is True:
        require(path.is_dir() and not path.is_symlink(),
                "Expected existing directory: " + str(path))
    elif directory is False:
        regular(path)
    return path


def checked_configuration(configuration, require_builder=True):
    expected = set(PATH_FIELDS) | {"uid", "gid", "version", "jobs"}
    require(isinstance(configuration, dict) and
            set(configuration) in (expected, expected | {"format_version"}),
            "Unexpected or missing Argus build configuration fields")
    require(type(configuration.get("format_version", 1)) is int and
            configuration.get("format_version", 1) == 1,
            "Unsupported Argus build configuration version")
    result = dict(configuration)
    for name in ("uid", "gid", "jobs"):
        require(type(result[name]) is int, "Expected integer: " + name)
    require(result["uid"] > 0 and result["gid"] >= 0,
            "An ordinary artifact owner is required")
    require(1 <= result["jobs"] <= 64, "Build jobs must be between 1 and 64")
    require(isinstance(result["version"], str) and
            re.fullmatch(r"39\.2\.1[+~.A-Za-z0-9-]*", result["version"]) and
            not result["version"].endswith("-"),
            "Expected an R39.2.1 Debian package version")
    for name in PATH_FIELDS:
        directory = (True if name in ("sources", "bundle") or
                     (name == "builder" and require_builder) else
                     False if name == "source_deb" else None)
        result[name] = canonical(result[name], directory=directory)
    roots = [result[name] for name in ("builder", "work", "output")]
    for index, left in enumerate(roots):
        for right in roots[index + 1:]:
            require(not left.is_relative_to(right) and not right.is_relative_to(left),
                    "Builder, private work and output paths must not overlap")
    for name in ("sources", "bundle"):
        for root in roots:
            require(not result[name].is_relative_to(root) and
                    not root.is_relative_to(result[name]),
                    "Build sources must not overlap builder/work/output")
    require(not result["source_deb"].is_relative_to(result["builder"]) and
            not result["source_deb"].is_relative_to(result["output"]),
            "Source package must not be inside builder or output")
    if result["source_deb"].is_relative_to(result["work"]):
        require(result["source_deb"].parent == result["work"] / "inputs",
                "Private source packages must be staged directly under inputs")
    return result


def relative_name(value):
    path = PurePosixPath(value)
    require(isinstance(value, str) and value not in ("", ".") and
            not path.is_absolute() and ".." not in path.parts and
            path.as_posix() == value and "\\" not in value,
            "Unsafe relative input path: " + str(value))
    return value


def verify_bundle(bundle):
    bundle = canonical(bundle, directory=True)
    records = {}
    for line in regular(bundle / "SHA256SUMS").read_text().splitlines():
        require(re.fullmatch(r"[0-9a-f]{64}  \./.+", line),
                "Invalid runtime checksum record")
        checksum, name = line.split("  ./", 1)
        relative_name(name)
        require(name not in records and name != "SHA256SUMS",
                "Duplicate runtime checksum record")
        records[name] = checksum
    actual = {}
    for path in sorted(bundle.rglob("*")):
        relative = path.relative_to(bundle)
        if any(part in ("scratch", "__pycache__") for part in relative.parts):
            continue
        require(not path.is_symlink(), "Runtime bundle contains a symlink")
        if path.is_file() and relative.as_posix() != "SHA256SUMS":
            actual[relative.as_posix()] = digest(regular(path))
    require(records and actual == records, "Runtime bundle checksum mismatch")
    return actual


def mmapi_asset(sources):
    manifest = json.loads(regular(Path(sources) / "runtime-assets.json").read_text())
    found = [row for row in manifest["assets"] if row.get("id") == "mmapi"]
    require(len(found) == 1, "Exactly one pinned MMAPI source is required")
    asset = found[0]
    require(asset.get("source") == "nvidia" and asset.get("role") == "source" and
            re.fullmatch(r"[0-9a-f]{64}", asset.get("sha256", "")) and
            Path(asset["path"]).name ==
            "nvidia-l4t-jetson-multimedia-api_" + NVIDIA_VERSION + "_arm64.deb",
            "Unsupported MMAPI source identity")
    return asset


def target_file(root, relative):
    """Resolve target absolute symlinks inside the clone, never on the host."""
    pending = list(PurePosixPath(relative).parts)
    require(not PurePosixPath(relative).is_absolute(), "Relative target path required")
    resolved = []
    links = 0
    while pending:
        part = pending.pop(0)
        if part in ("", "."):
            continue
        if part == "..":
            require(bool(resolved), "Target link escapes its root")
            resolved.pop()
            continue
        candidate = root.joinpath(*resolved, part)
        if candidate.is_symlink():
            links += 1
            require(links <= 40, "Target symlink loop")
            target = candidate.readlink()
            if target.is_absolute():
                resolved = []
                target = target.relative_to("/")
            pending = list(target.parts) + pending
        else:
            resolved.append(part)
    return regular(root.joinpath(*resolved))


def elf_arm64(path):
    with regular(path).open("rb") as stream:
        header = stream.read(20)
    require(len(header) == 20 and header[:6] == b"\x7fELF\x02\x01" and
            int.from_bytes(header[18:20], "little") == 183,
            "Expected an AArch64 ELF payload: " + str(path))


def builder_status(builder):
    builder = canonical(builder, directory=True)
    release = target_file(builder, "etc/os-release").read_text().splitlines()
    values = dict(line.split("=", 1) for line in release
                  if "=" in line and not line.startswith("#"))
    require(values.get("ID", "").strip('"') == "ubuntu" and
            values.get("VERSION_ID", "").strip('"') == "24.04",
            "Prepared Ubuntu 24.04 builder required")
    records = []
    seen = set()
    for paragraph in regular(builder / "var/lib/dpkg/status").read_text().split("\n\n"):
        fields = dict(line.split(": ", 1) for line in paragraph.splitlines()
                      if ": " in line and not line.startswith(" "))
        if fields.get("Status") not in ("install ok installed", "hold ok installed"):
            continue
        package, architecture, version = (fields.get(key, "") for key in
                                          ("Package", "Architecture", "Version"))
        require(re.fullmatch(r"[a-z0-9][a-z0-9+.-]+", package) and
                architecture in ("arm64", "all") and
                re.fullmatch(r"[A-Za-z0-9.+:~_-]+", version),
                "Unsupported builder package identity")
        require((package, architecture) not in seen, "Duplicate builder package")
        seen.add((package, architecture))
        records.append(dict(name=package, architecture=architecture, version=version,
                            selection=fields["Status"].split()[0]))
    installed = {row["name"]: row for row in records}
    required = {name: NVIDIA_VERSION for name in
                ("nvidia-l4t-camera", "nvidia-l4t-multimedia", "nvidia-l4t-gstreamer")}
    required.update({name: CUDA_VERSION for name in
                     ("cuda-nvcc-13-2", "cuda-cudart-13-2")})
    for name, version in required.items():
        require(name in installed and installed[name]["version"] == version and
                installed[name]["architecture"] == "arm64",
                "Missing/mismatched prepared builder package: " + name)
    elf_arm64(target_file(builder, "usr/bin/dpkg"))
    for name in ("cmake", "g++", "pkg-config", "patch", "xxd", "readelf"):
        target_file(builder, "usr/bin/" + name)
    target_file(builder, "usr/local/cuda-13.2/bin/nvcc")
    elf_arm64(target_file(builder, "opt/nvidia/l4t-gpu-libs/nvgpu/libcuda.so.1.1"))
    return sorted(records, key=lambda row: (row["name"], row["architecture"]))


def argus_specification(sources, bundle):
    inventory = load_module(Path(sources) / "rootfs_package_inventory.py",
                            "argus_deb_inventory")
    names = regular(Path(bundle) / "files/argus-full-suite.txt").read_text().splitlines()
    require(len(names) == 23 and len(set(names)) == 23 and
            set(names) == set(inventory.ARGUS_APPS) and
            all(re.fullmatch(r"argus_[A-Za-z0-9]+", name) for name in names),
            "Expected the complete 23-application Argus suite")
    require(inventory.NVIDIA_VERSION == NVIDIA_VERSION, "Argus NVIDIA ABI changed")
    depends = inventory.argus_dependencies()
    return tuple(names), depends


def fingerprint(configuration):
    config = checked_configuration(configuration)
    asset = mmapi_asset(config["sources"])
    require(digest(config["source_deb"]) == asset["sha256"],
            "Pinned MMAPI source checksum mismatch")
    metadata = run(["dpkg-deb", "-f", config["source_deb"],
                    "Package", "Version", "Architecture"])
    fields = dict(line.split(": ", 1) for line in metadata.splitlines() if ": " in line)
    require(fields == {"Package": "nvidia-l4t-jetson-multimedia-api",
                       "Version": NVIDIA_VERSION, "Architecture": "arm64"},
            "Unexpected MMAPI source package metadata")
    names, depends = argus_specification(config["sources"], config["bundle"])
    source_hashes = {name: digest(regular(config["sources"] / name))
                     for name in SOURCE_FILES}
    inputs = dict(schema=1, version=config["version"], source_deb=asset["sha256"],
                  sources=source_hashes, bundle=verify_bundle(config["bundle"]),
                  builder_packages=builder_status(config["builder"]),
                  applications=list(names), depends=list(depends))
    inputs["builder_tools"] = {
        name: digest(target_file(config["builder"], name)) for name in
        ("usr/bin/dpkg", "usr/bin/cmake", "usr/bin/g++",
         "usr/local/cuda-13.2/bin/nvcc",
         "opt/nvidia/l4t-gpu-libs/nvgpu/libcuda.so.1.1")}
    signature = hashlib.sha256(json.dumps(inputs, sort_keys=True,
                                         separators=(",", ":")).encode()).hexdigest()
    return signature, inputs


def mounts_below(path):
    return [line for line in run(["findmnt", "-rn", "-o", "TARGET"]).splitlines()
            if line == str(path) or line.startswith(str(path) + "/")]


def clone_builder(builder, destination):
    require(not destination.exists() and not destination.is_symlink(),
            "Clone destination must be new")
    require(not mounts_below(builder), "Prepared builder has active mounts")
    def ignored(directory, names):
        relative = Path(directory).relative_to(builder)
        if relative == Path("."):
            return set(names) & TRANSIENT
        if relative == Path("var"):
            return set(names) & {"tmp"}
        return set()

    for current, directories, files in os.walk(builder, followlinks=False):
        excluded = ignored(current, directories + files)
        directories[:] = [name for name in directories if name not in excluded]
        for name in directories + files:
            if name in excluded:
                continue
            path = Path(current) / name
            mode = path.lstat().st_mode
            require(stat.S_ISDIR(mode) or stat.S_ISREG(mode) or stat.S_ISLNK(mode),
                    "Special file in prepared builder: " + str(path))
    shutil.copytree(builder, destination, symlinks=True, ignore=ignored)
    for name in TRANSIENT:
        (destination / name).mkdir(mode=0o755, exist_ok=True)
    (destination / "tmp").chmod(0o1777)
    (destination / "var/tmp").mkdir(mode=0o1777, parents=True, exist_ok=True)
    (destination / "var/tmp").chmod(0o1777)


def build_in_clone(config, clone, run_dir):
    provision = load_module(config["sources"] / "provision-runtime.py",
                            "argus_deb_provision")
    provision.run = run
    if os.uname().machine != "aarch64":
        require(provision.persistent_binfmt(Path("/proc/sys/fs/binfmt_misc/qemu-aarch64")),
                "Persistent ARM64 binfmt interpreter is required; no registration attempted")
    shutil.copytree(config["bundle"], clone / "work/runtime",
                    ignore=shutil.ignore_patterns("scratch", "__pycache__"))
    (clone / "work/inputs").mkdir()
    source = clone / "work/inputs" / config["source_deb"].name
    shutil.copyfile(config["source_deb"], source)
    with provision.target_context(clone):
        provision.chroot(clone, ["bash", "/work/runtime/runtime-port.sh", "build",
                                 "--suite", "full", "--source-deb",
                                 "/work/inputs/" + source.name,
                                 "--work-dir", "/work/argus", "--jobs",
                                 str(config["jobs"])], run_dir / "build.log")
    return clone / "work/argus/pkgroot"


def verify_native_payload(config, clone, pkgroot, run_dir):
    provision = load_module(config["sources"] / "provision-runtime.py",
                            "argus_deb_verify_provision")
    provision.run = run
    names, _ = argus_specification(config["sources"], config["bundle"])
    library_path = ("/opt/nvidia/l4t-gpu-libs/nvgpu:/usr/lib/aarch64-linux-gnu/nvidia:"
                    "/usr/local/cuda-13.2/targets/sbsa-linux/lib")
    with provision.target_context(clone):
        for name in names:
            relative = "/" + (pkgroot / "usr/bin" / name).relative_to(clone).as_posix()
            text = provision.chroot(clone, ["env", "LD_LIBRARY_PATH=" + library_path,
                                            "ldd", "-r", relative], run_dir / "loader.log")
            require("not found" not in text and "undefined symbol" not in text,
                    "Unresolved native loader dependencies: " + name)


def owned_file(path, uid, mode=0o600):
    info = regular(path).stat()
    require(info.st_uid == uid and stat.S_IMODE(info.st_mode) == mode,
            "Unexpected file owner/mode: " + str(path))


@contextlib.contextmanager
def lock_file(path, uid, gid, *, create=False, wait=False):
    descriptor = os.open(path, os.O_RDWR | os.O_NOFOLLOW |
                         (os.O_CREAT if create else 0), 0o600)
    try:
        info = os.fstat(descriptor)
        require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and
                stat.S_IMODE(info.st_mode) == 0o600 and info.st_uid in (0, uid),
                "Unsafe Argus build lock: " + str(path))
        if info.st_uid != uid:
            require(create, "SDK lock must belong to the ordinary build user")
            os.fchown(descriptor, uid, gid)
        fcntl.flock(descriptor, fcntl.LOCK_EX | (0 if wait else fcntl.LOCK_NB))
        yield
    finally:
        os.close(descriptor)


def verify_publication(destination, expected_fingerprint, uid):
    canonical(destination, directory=True)
    require(destination.stat().st_uid == uid, "Unexpected publication directory owner")
    manifest_path = destination / "manifest.json"
    owned_file(manifest_path, uid, 0o644)
    manifest = json.loads(manifest_path.read_text())
    require(manifest.get("schema") == 1 and
            manifest.get("fingerprint") == expected_fingerprint,
            "Argus package publication identity mismatch")
    require(hashlib.sha256(json.dumps(manifest.get("inputs"), sort_keys=True,
                                     separators=(",", ":")).encode()).hexdigest()
            == expected_fingerprint, "Published Argus inputs do not match fingerprint")
    package = manifest.get("package", {})
    filename = package.get("filename", "")
    require(re.fullmatch(r"compulab-edge-ai-argus_39\.2\.1[+~.A-Za-z0-9-]*_arm64\.deb",
                         filename), "Invalid published package filename")
    archive = destination / filename
    owned_file(archive, uid, 0o644)
    require(digest(archive) == package.get("sha256"), "Published package checksum mismatch")
    require(package.get("name") == "compulab-edge-ai-argus" and
            package.get("architecture") == "arm64" and
            package.get("version") == manifest["inputs"]["version"] and
            package.get("depends") == manifest["inputs"]["depends"] and
            filename == "compulab-edge-ai-argus_" + package["version"] + "_arm64.deb",
            "Published Argus package metadata changed")
    metadata = run(["dpkg-deb", "-f", archive, "Package", "Version", "Architecture", "Depends"])
    fields = dict(line.split(": ", 1) for line in metadata.splitlines() if ": " in line)
    require(fields == dict(Package=package["name"], Version=package["version"],
                           Architecture="arm64", Depends=", ".join(package["depends"])),
            "Published Debian control metadata does not match manifest")
    verify_archive_payload(archive, package, manifest["inputs"]["applications"])
    owned_file(destination / "SHA256SUMS", uid, 0o644)
    require((destination / "SHA256SUMS").read_text() ==
            package["sha256"] + "  " + filename + "\n" +
            digest(manifest_path) + "  manifest.json\n",
            "Published checksum manifest changed")
    require({path.name for path in destination.iterdir()} ==
            {filename, "manifest.json", "SHA256SUMS"},
            "Unexpected file in Argus package publication")
    return manifest


def verify_archive_payload(archive, package, applications):
    expected = package.get("files", {})
    require(isinstance(expected, dict) and package.get("binary_count") == 23 and
            len(applications) == 23 and len(set(applications)) == 23 and
            set(expected) == {"usr/bin/" + name for name in applications} |
            {"usr/share/doc/compulab-edge-ai-argus/copyright",
             "usr/share/doc/compulab-edge-ai-argus/NVIDIA-LICENSE"},
            "Published Argus payload inventory changed")
    found = {}
    total = 0
    process = subprocess.Popen(["dpkg-deb", "--fsys-tarfile", str(archive)],
                               stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    try:
        with tarfile.open(fileobj=process.stdout, mode="r|") as stream:
            for member in stream:
                if member.isdir():
                    continue
                name = member.name.removeprefix("./")
                total += member.size
                require(member.isfile() and name in expected and name not in found and
                        total <= 256 * 1024 * 1024,
                        "Unexpected Debian package payload")
                with stream.extractfile(member) as payload:
                    found[name] = hashlib.file_digest(payload, "sha256").hexdigest()
        require(process.wait() == 0, "Cannot inspect Debian package payload")
    finally:
        if process.poll() is None:
            process.kill()
        process.wait()
        process.stdout.close()
    require(found == expected, "Debian package payload checksum mismatch")


def prepare_output(config):
    output = config["output"]
    if not output.exists():
        output.mkdir(parents=True, mode=0o755)
        os.chown(output, config["uid"], config["gid"])
    require(output.is_dir() and not output.is_symlink() and
            output.stat().st_uid == config["uid"], "Unexpected output directory owner")
    marker = output / OUTPUT_MARKER
    if not marker.exists():
        require(not any(output.iterdir()), "Refusing an unmarked nonempty output directory")
        descriptor = os.open(marker, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(descriptor, "w") as stream:
            stream.write(OUTPUT_ID)
        os.chown(marker, config["uid"], config["gid"])
    owned_file(marker, config["uid"])
    require(marker.read_text() == OUTPUT_ID, "Invalid Argus output ownership marker")


def publish(config, signature, inputs, pkgroot, run_dir):
    names, depends = argus_specification(config["sources"], config["bundle"])
    expected = {"usr/bin/" + name for name in names}
    files = {path.relative_to(pkgroot).as_posix() for path in pkgroot.rglob("*")
             if path.is_file() or path.is_symlink()}
    require(files == expected, "Unexpected or incomplete Argus package payload inventory")
    hashes = {}
    for name in sorted(expected):
        elf_arm64(pkgroot / name)
        require(stat.S_IMODE((pkgroot / name).stat().st_mode) == 0o755,
                "Argus application must have mode 0755: " + name)
        hashes[name] = digest(pkgroot / name)
    license_dir = pkgroot / "usr/share/doc/compulab-edge-ai-argus"
    license_dir.mkdir(parents=True)
    license_source = pkgroot.parent / "source/argus/LICENSE.TXT"
    regular(license_source)
    shutil.copyfile(license_source, license_dir / "copyright")
    shutil.copyfile(config["bundle"] / "files/Tegra_Software_License_Agreement-Tegra-Linux.txt",
                    license_dir / "NVIDIA-LICENSE")
    for path in license_dir.iterdir():
        path.chmod(0o644)
        hashes[path.relative_to(pkgroot).as_posix()] = digest(path)
    builder = load_module(config["sources"] / "deb_packages.py", "argus_deb_builder")
    prepared = run_dir / "package"
    prepared.mkdir()
    archive = builder.build_package(pkgroot, prepared, "compulab-edge-ai-argus",
                                    config["version"], architecture="arm64", depends=depends)
    manifest = dict(schema=1, fingerprint=signature, inputs=inputs,
                    package=dict(name="compulab-edge-ai-argus", version=config["version"],
                                 architecture="arm64", filename=archive.name,
                                 sha256=digest(archive), depends=list(depends),
                                 binary_count=len(names), files=hashes),
                    validation="Native ELF/loader checks; no hardware validation")
    manifest_path = prepared / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, sort_keys=True, indent=2) + "\n")
    (prepared / "SHA256SUMS").write_text(
        digest(archive) + "  " + archive.name + "\n" +
        digest(manifest_path) + "  manifest.json\n")
    for path in prepared.iterdir():
        regular(path).chmod(0o644)
        os.chown(path, config["uid"], config["gid"])
    prepared.chmod(0o755)
    os.chown(prepared, config["uid"], config["gid"])
    destination = config["output"] / signature
    require(not destination.exists() and not destination.is_symlink(),
            "Argus publication destination appeared during build")
    # Keep rename atomic even when private work and deploy are different filesystems.
    with tempfile.TemporaryDirectory(prefix=".argus-publication-", dir=config["output"]) as temporary:
        staging = Path(temporary) / signature
        shutil.copytree(prepared, staging)
        for path in [staging, *staging.iterdir()]:
            os.chown(path, config["uid"], config["gid"])
        staging.rename(destination)
    return verify_publication(destination, signature, config["uid"])


def record_current(config, manifest):
    """Publish a validated receipt for the coordinated package collector."""
    signature = manifest["fingerprint"]
    destination = config["output"] / signature
    pointer = config["output"] / "current.json"
    require(not pointer.is_symlink(), "Refusing a symlinked Argus receipt")
    value = dict(schema=1, component="argus", fingerprint=signature,
                 publication=str(destination),
                 manifest_sha256=digest(destination / "manifest.json"))
    descriptor, temporary = tempfile.mkstemp(prefix=".current-", dir=config["output"])
    try:
        with os.fdopen(descriptor, "w") as stream:
            json.dump(value, stream, sort_keys=True, indent=2)
            stream.write("\n")
        os.chmod(temporary, 0o644)
        os.chown(temporary, config["uid"], config["gid"])
        os.replace(temporary, pointer)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return manifest


def execute(configuration):
    require(os.geteuid() == 0, "--execute requires explicit root privileges")
    config = checked_configuration(configuration)
    work = canonical(config["work"], directory=True)
    require(work.stat().st_uid == config["uid"] and
            stat.S_IMODE(work.stat().st_mode) == 0o700,
            "Private work must be owned by the ordinary build user with mode 0700")
    owned_file(work / WORK_MARKER, config["uid"])
    require((work / WORK_MARKER).read_text() == WORK_ID, "Invalid private-work ownership marker")
    with lock_file(work / ".build.lock", config["uid"], config["gid"], create=True):
        prepare_output(config)
        with lock_file(config["output"] / ".build.lock", config["uid"], config["gid"], create=True):
            with lock_file(GLOBAL_SDK_LOCK, config["uid"], config["gid"], wait=True):
                require(not mounts_below(config["builder"]), "Prepared builder has active mounts")
                signature, inputs = fingerprint(config)
                destination = config["output"] / signature
                if destination.exists() or destination.is_symlink():
                    return record_current(config, verify_publication(
                        destination, signature, config["uid"]))
                run_dir = Path(tempfile.mkdtemp(prefix="run-", dir=work))
                (run_dir / "inputs.json").write_text(json.dumps(inputs, sort_keys=True, indent=2) + "\n")
                clone = run_dir / "builder"
                print("Cloning prepared Ubuntu ARM64 builder; logs: " + str(run_dir), flush=True)
                clone_builder(config["builder"], clone)
                require(builder_status(clone) == inputs["builder_packages"],
                        "Builder package state changed during snapshot")
            pkgroot = build_in_clone(config, clone, run_dir)
            verify_native_payload(config, clone, pkgroot, run_dir)
            return record_current(config, publish(
                config, signature, inputs, pkgroot, run_dir))


def interrupted(signum, _frame):
    raise InterruptedError("Argus build interrupted by signal " + str(signum))


def main(arguments=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    actions = parser.add_mutually_exclusive_group()
    actions.add_argument("--plan", action="store_true", help="read-only input and prerequisite checks (default)")
    actions.add_argument("--execute", action="store_true")
    args = parser.parse_args(arguments)
    try:
        configuration = json.loads(regular(args.config).read_text())
        if args.execute:
            result = execute(configuration)
            print(json.dumps(result, sort_keys=True, indent=2))
        else:
            signature, inputs = fingerprint(configuration)
            print(json.dumps(dict(action="read-only plan", fingerprint=signature,
                                  destination=str(Path(configuration["output"]) / signature),
                                  inputs=inputs), sort_keys=True, indent=2))
        return 0
    except (OSError, ValueError, KeyError, RuntimeError, subprocess.SubprocessError) as error:
        print("Argus Debian build failed: " + str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    signal.signal(signal.SIGTERM, interrupted)
    signal.signal(signal.SIGINT, interrupted)
    sys.exit(main())
