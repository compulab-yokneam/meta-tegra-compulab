#!/usr/bin/python3
# SPDX-License-Identifier: MIT
"""Manage the package-owned Ubuntu BSP policy, never firmware or services."""

import argparse
import base64
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import tempfile


PACKAGES = (
    "nvidia-l4t-bootloader", "nvidia-l4t-bootloader-utils",
    "nvidia-l4t-kernel", "nvidia-l4t-kernel-dtbs",
    "nvidia-l4t-kernel-partitions", "nvidia-l4t-initrd",
    "nvidia-l4t-extlinux", "nvidia-l4t-firmware",
    "nvidia-l4t-kernel-oot-modules", "nvidia-l4t-display-kernel",
    "nvidia-l4t-kernel-nvgpu", "nvidia-l4t-kernel-openrm",
    "nvidia-l4t-kernel-module-configs", "nvidia-l4t-kernel-headers",
    "nvidia-l4t-kernel-oot-headers", "nvidia-l4t-gstreamer",
)
FLAGS = (
    "ENABLE_SPEC_GENERATION", "ENABLE_UEFI_SPEC_VAR_UPDATE",
    "ENABLE_PARTITION_UPDATE", "ENABLE_ESP_AUTOMOUNT",
    "ENABLE_AUTO_QSPI_UPDATE",
)
CONFIG = "opt/nvidia/l4t-bootloader-config/nv-l4t-bootloader-config.conf"
DESIRED = "etc/compulab/edge-ai-bsp-policy.json"
STATE = "var/lib/compulab-edge-ai-bsp-policy/state.json"
APT_PIN = "etc/apt/preferences.d/compulab-edge-ai-bsp"


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def flags(data):
    text = data.decode("utf-8")
    result = {}
    for name in FLAGS:
        values = re.findall(r'^' + name + r'="([01])"$', text, re.M)
        require(len(values) == 1,
                "Expected one literal vendor flag assignment: " + name)
        result[name] = values[0]
    return result


def protected_config(data):
    flags(data)
    return re.sub(rb'^ENABLE_AUTO_QSPI_UPDATE="1"$',
                  b'ENABLE_AUTO_QSPI_UPDATE="0"', data, flags=re.M)


def atomic_write(path, data, mode, owner=None):
    descriptor, temporary = tempfile.mkstemp(
        prefix=".compulab-bsp-policy-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
            os.fchmod(stream.fileno(), mode)
            if owner is not None:
                os.fchown(stream.fileno(), *owner)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


class Policy:
    def __init__(self, root):
        self.root = Path(root)
        require(self.root.is_absolute() and self.root.is_dir() and
                self.root.resolve() == self.root,
                "The target root must be an existing canonical directory")
        self.db = self.safe("var/lib/dpkg", directory=True)
        self.config = self.safe(CONFIG)
        self.desired = self.safe(DESIRED)
        self.state = self.safe(STATE, optional=True)
        release = self.root / "usr/lib/os-release"
        if not release.is_file():
            release = self.root / "etc/os-release"
        require(release.is_file() and
                release.resolve().is_relative_to(self.root),
                "The target root has no confined operating-system metadata")
        text = release.read_text()
        require(re.search(r'(?m)^ID=ubuntu$', text) and
                re.search(r'(?m)^VERSION_ID="24[.]04"$', text),
                "The policy requires Ubuntu 24.04")
        specification = json.loads(self.desired.read_text())
        require(isinstance(specification, dict) and
                specification.get("schema") == 1 and
                specification.get("l4t_version") == "39.2.1",
                "Unsupported BSP policy specification")
        names = specification.get("hold_packages")
        require(isinstance(names, list) and names and
                all(isinstance(name, str) and name in PACKAGES
                    for name in names) and len(names) == len(set(names)),
                "Invalid or duplicate policy package names")
        self.names = tuple(names)
        self.frontend_locked = False

    def safe(self, relative, *, optional=False, directory=False):
        path = self.root / relative
        require(path.resolve(strict=False) == path,
                "Symlink in BSP policy path: " + str(path))
        if not path.exists():
            require(optional, "Missing BSP policy path: " + str(path))
            return path
        info = path.lstat()
        if directory:
            require(stat.S_ISDIR(info.st_mode),
                    "Not a policy directory: " + str(path))
        else:
            require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1,
                    "Not a regular, singly linked policy file: " + str(path))
        return path

    def packages(self):
        result = []
        # binary:Package adds a foreign-architecture suffix on the build
        # host but may omit it in the native ARM64 maintainer script.
        template = ("${Package}\t${Version}\t${Architecture}\t"
                    "${db:Status-Want}\t${db:Status-Status}\n")
        for name in self.names:
            query = subprocess.run(
                ["dpkg-query", "--admindir=" + str(self.db), "-W",
                 "-f=" + template, name],
                capture_output=True, text=True, check=False)
            if query.returncode == 1:
                continue
            query.check_returncode()
            fields = query.stdout.strip().split("\t")
            require(len(fields) == 5, "Malformed package status: " + name)
            binary, version, architecture, selection, status_ = fields
            if status_ != "installed":
                continue
            require(architecture == "arm64" and binary == name and
                    selection in ("install", "hold") and
                    re.fullmatch(r"[A-Za-z0-9.+:~_-]+", version),
                    "Unsupported package architecture/status: " + name)
            result.append(dict(name=binary + ":" + architecture, version=version,
                               selection=selection))
        require(result, "No installed NVIDIA packages selected by the policy")
        return result

    def read_state(self):
        path = self.safe(STATE, optional=True)
        if not path.exists():
            return None
        require(stat.S_IMODE(path.stat().st_mode) & 0o077 == 0,
                "Policy state must not be accessible to other users")
        value = json.loads(path.read_text())
        require(isinstance(value, dict) and value.get("schema") == 1,
                "Invalid policy state schema")
        original = base64.b64decode(value.get("original_config", ""),
                                    validate=True)
        require(original and value.get("original_config_sha256") ==
                sha256(original), "Original policy configuration is corrupt")
        require(value.get("applied_config_sha256") ==
                sha256(protected_config(original)),
                "Applied policy configuration hash is invalid")
        mode = value.get("config_mode")
        require(type(mode) is int and 0 <= mode <= 0o777,
                "Invalid original configuration mode")
        packages = value.get("packages")
        require(isinstance(packages, list) and packages,
                "Missing original package selections")
        seen = set()
        for item in packages:
            require(isinstance(item, dict) and set(item) ==
                    {"name", "version", "selection"},
                    "Malformed original package selection")
            name = item["name"]
            require(isinstance(name, str), "Invalid original package name")
            base = name.removesuffix(":arm64")
            require(base in self.names and base not in seen and
                    name in (base, base + ":arm64") and
                    item["selection"] in ("install", "hold") and
                    isinstance(item["version"], str) and
                    re.fullmatch(r"[A-Za-z0-9.+:~_-]+", item["version"]),
                    "Invalid original package selection: " + name)
            seen.add(base)
            # Accept existing native/bare state without confusing the same
            # package with its host-query spelling. Keep versions/selections.
            item["name"] = base + ":arm64"
        return value

    def check_current(self, state, current):
        expected = {item["name"]: item for item in state["packages"]}
        found = {item["name"]: item for item in current}
        require(set(expected) == set(found),
                "The installed protected package set changed")
        for name, item in found.items():
            require(item["version"] == expected[name]["version"],
                    "Protected package version changed: " + name)
            require(item["selection"] in
                    {"hold", expected[name]["selection"]},
                    "Protected package selection changed: " + name)
        require(sha256(self.config.read_bytes()) in
                {state["original_config_sha256"],
                 state["applied_config_sha256"]},
                "Vendor configuration changed; refusing to overwrite it")

    def write_state(self, value):
        data = (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()
        atomic_write(self.state, data, 0o600)

    @contextmanager
    def frontend_lock(self):
        # dpkg already owns this lock while running a maintainer script.
        if os.environ.get("DPKG_MAINTSCRIPT_PACKAGE"):
            yield
            return
        lock = self.safe("var/lib/dpkg/lock-frontend", optional=True)
        descriptor = os.open(lock, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW,
                             0o600)
        with os.fdopen(descriptor, "r+b") as stream:
            try:
                fcntl.lockf(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as error:
                raise RuntimeError(
                    "Target package preparation is busy") from error
            self.frontend_locked = True
            try:
                yield
            finally:
                self.frontend_locked = False

    @contextmanager
    def locked(self):
        require(os.geteuid() == 0, "Changing BSP policy requires root")
        self.safe(STATE, optional=True)
        self.state.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.state.parent.chmod(0o700)
        lock = self.safe(str(self.state.parent.relative_to(self.root) /
                             "lock"), optional=True)
        descriptor = os.open(lock, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW,
                             0o600)
        with os.fdopen(descriptor, "r+b") as stream:
            try:
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as error:
                raise RuntimeError(
                    "Another BSP policy action is active") from error
            with self.frontend_lock():
                yield

    def set_selections(self, packages, *, hold):
        require(not os.environ.get("DPKG_MAINTSCRIPT_PACKAGE"),
                "Selection changes must run outside dpkg/apt; use configure "
                "or restore-config from maintainer scripts")
        data = "".join(item["name"] + "\t" +
                       ("hold" if hold else item["selection"]) + "\n"
                       for item in packages)
        environment = dict(os.environ)
        if environment.get("DPKG_MAINTSCRIPT_PACKAGE") or self.frontend_locked:
            environment["DPKG_FRONTEND_LOCKED"] = "true"
        subprocess.run(["dpkg", "--admindir=" + str(self.db),
                        "--set-selections"], input=data, text=True,
                       env=environment, check=True)

    def install_config(self, data, mode):
        info = self.safe(CONFIG).stat()
        atomic_write(self.config, data, mode, (info.st_uid, info.st_gid))

    def pinned_versions(self):
        """Read this package's exact-version APT pin as literal data."""
        path = self.safe(APT_PIN, optional=True)
        if not path.exists():
            return {}
        lines = [line for line in path.read_text().splitlines()
                 if not line.lstrip().startswith("#")]
        pins = {}
        for paragraph in re.split(r"\n\s*\n", "\n".join(lines).strip()):
            require(paragraph, "Empty BSP APT pin specification")
            fields = {}
            for line in paragraph.splitlines():
                require(line and not line[0].isspace() and ":" in line,
                        "Unsupported BSP APT pin line")
                key, value = line.split(":", 1)
                require(key in ("Package", "Pin", "Pin-Priority") and
                        key not in fields,
                        "Duplicate/unknown BSP APT pin field")
                fields[key] = value.strip()
            require(set(fields) == {"Package", "Pin", "Pin-Priority"} and
                    fields["Pin-Priority"] == "1000",
                    "BSP APT pin must have exact priority 1000")
            version = re.fullmatch(r"version ([A-Za-z0-9.+:~_-]+)",
                                   fields["Pin"])
            require(version is not None, "BSP APT pin needs a literal version")
            names = fields["Package"].split()
            require(names, "BSP APT pin has no package names")
            for name in names:
                base = name.removesuffix(":arm64")
                require(base in self.names and
                        name in (base, base + ":arm64") and base not in pins,
                        "Unknown/duplicate BSP APT pin package: " + name)
                pins[base] = version[1]
        return pins

    def package_protection(self, current):
        pins = self.pinned_versions()
        if all(item["selection"] == "hold" for item in current):
            return "holds"
        if all(pins.get(item["name"].removesuffix(":arm64")) ==
               item["version"] for item in current):
            return "apt-pins"
        return "none"

    def check(self):
        current = self.packages()
        state = self.read_state()
        result = dict(protected=False, root=str(self.root),
                      packages=current, flags=flags(self.config.read_bytes()),
                      state="absent" if state is None else
                      state.get("state", "seeded"))
        if state is None:
            return result
        try:
            self.check_current(state, current)
            result["package_protection"] = self.package_protection(current)
        except RuntimeError as error:
            result["reason"] = str(error)
            return result
        result["protected"] = (
            result["package_protection"] != "none" and
            sha256(self.config.read_bytes()) == state["applied_config_sha256"])
        return result

    def apply(self):
        require(not os.environ.get("DPKG_MAINTSCRIPT_PACKAGE"),
                "Run apply outside dpkg/apt; maintainer scripts use configure")
        return self.activate(selections=True)

    def configure(self):
        return self.activate(selections=False)

    def activate(self, *, selections):
        with self.locked():
            current = self.packages()
            state = self.read_state()
            old_config = self.config.read_bytes()
            info = self.config.stat()
            if state is None:
                state = dict(
                    schema=1, state="prepared",
                    original_config=base64.b64encode(old_config).decode(),
                    original_config_sha256=sha256(old_config),
                    applied_config_sha256=sha256(protected_config(old_config)),
                    config_mode=stat.S_IMODE(info.st_mode), packages=current)
                self.write_state(state)
            self.check_current(state, current)
            updated = protected_config(base64.b64decode(
                state["original_config"], validate=True))
            try:
                if selections:
                    self.set_selections(state["packages"], hold=True)
                else:
                    require(self.package_protection(current) != "none",
                            "Package protection requires verified holds or "
                            "exact installed-version APT pins")
                self.install_config(updated, state["config_mode"])
                require(self.check()["protected"], "Policy activation failed")
                state["state"] = "active"
                self.write_state(state)
            except Exception:
                self.install_config(old_config, stat.S_IMODE(info.st_mode))
                if selections:
                    self.set_selections(current, hold=False)
                raise
        return self.check()

    def restore(self):
        require(not os.environ.get("DPKG_MAINTSCRIPT_PACKAGE"),
                "Run restore outside dpkg/apt; maintainer scripts use "
                "restore-config")
        return self.restore_state(selections=True)

    def restore_config(self):
        return self.restore_state(selections=False)

    def restore_state(self, *, selections):
        with self.locked():
            state = self.read_state()
            require(state is not None,
                    "No owned policy state; original selections are unknown")
            self.check_current(state, self.packages())
            if selections:
                self.set_selections(state["packages"], hold=False)
            self.install_config(base64.b64decode(state["original_config"],
                                                validate=True),
                                state["config_mode"])
            if selections:
                restored = {item["name"]: item for item in self.packages()}
                expected = {item["name"]: item for item in state["packages"]}
                require(restored == expected,
                        "Original package selections were not restored")
            state["state"] = ("restored" if selections else "config-restored")
            self.write_state(state)
        return self.check()


def main(arguments=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("check", "apply", "restore",
                                           "configure", "restore-config"),
                        nargs="?", default="check")
    parser.add_argument("--root", type=Path, default=Path("/"))
    args = parser.parse_args(arguments)
    try:
        result = getattr(Policy(args.root), args.action.replace("-", "_"))()
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    except (OSError, ValueError, RuntimeError,
            subprocess.CalledProcessError) as error:
        print("BSP policy: " + str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
