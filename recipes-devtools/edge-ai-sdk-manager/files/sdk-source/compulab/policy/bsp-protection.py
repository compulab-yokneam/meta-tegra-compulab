#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 CompuLab Ltd.
"""Reversible, offline BSP policy; default action only inspects the SDK rootfs."""
import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
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
import uuid

PACKAGES = (
    "nvidia-l4t-bootloader", "nvidia-l4t-bootloader-utils", "nvidia-l4t-kernel",
    "nvidia-l4t-kernel-dtbs", "nvidia-l4t-kernel-partitions", "nvidia-l4t-initrd",
    "nvidia-l4t-extlinux", "nvidia-l4t-firmware", "nvidia-l4t-kernel-oot-modules",
    "nvidia-l4t-display-kernel", "nvidia-l4t-kernel-nvgpu",
    "nvidia-l4t-kernel-openrm", "nvidia-l4t-kernel-module-configs",
    "nvidia-l4t-kernel-headers", "nvidia-l4t-kernel-oot-headers",
)
FLAGS = (
    "ENABLE_SPEC_GENERATION", "ENABLE_UEFI_SPEC_VAR_UPDATE",
    "ENABLE_PARTITION_UPDATE", "ENABLE_ESP_AUTOMOUNT", "ENABLE_AUTO_QSPI_UPDATE",
)
CONFIG = "opt/nvidia/l4t-bootloader-config/nv-l4t-bootloader-config.conf"
SERVICE = "etc/systemd/system/multi-user.target.wants/nv-l4t-bootloader-config.service"
MARKER = "opt/nvidia/l4t-packages/.nv-l4t-disable-boot-fw-update-in-preinstall"
ARTIFACTS = ("kernel/Image", "rootfs/boot/Image", "rootfs/boot/initrd")


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def atomic_write(path, data, mode=0o644, owner=None):
    descriptor, temporary = tempfile.mkstemp(prefix=".bsp-policy.", dir=path.parent)
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


def json_write(path, data):
    atomic_write(path, (json.dumps(data, indent=2, sort_keys=True) + "\n").encode())


def flag_values(data):
    text = data.decode()
    values = {}
    for name in FLAGS:
        matches = re.findall(r'^' + name + r'="([01])"$', text, re.M)
        if len(matches) != 1:
            raise RuntimeError("Expected one vendor flag assignment: " + name)
        values[name] = matches[0]
    return values


class Policy:
    def __init__(self, sdk):
        self.sdk = Path(sdk).resolve()
        self.root = self.sdk / "rootfs"
        self.db = self.root / "var/lib/dpkg"
        self.config = self.root / CONFIG
        self.directory = self.sdk / "compulab/policy/receipts"
        self.active = self.directory / "active.json"
        if self.sdk == Path("/") or not (self.sdk / "flash.sh").is_file():
            raise RuntimeError("An explicit SDK directory with flash.sh is required.")
        if self.root.is_symlink() or not self.db.is_dir() or not self.config.is_file():
            raise RuntimeError("Expected an SDK rootfs, dpkg database and vendor config.")
        for path in (self.db, self.config):
            if not path.resolve().is_relative_to(self.root.resolve()):
                raise RuntimeError("Refusing a target path outside the SDK rootfs.")
        if self.db.resolve() == Path("/var/lib/dpkg").resolve():
            raise RuntimeError("Refusing the host package database.")
        if not self.directory.resolve().is_relative_to(self.sdk):
            raise RuntimeError("Refusing a policy receipt path outside the SDK.")

    def packages(self):
        found = []
        template = "${binary:Package}\t${Version}\t${Architecture}\t${db:Status-Want}\t${db:Status-Status}\n"
        for name in PACKAGES:
            result = subprocess.run([
                "dpkg-query", "--admindir=" + str(self.db), "-W", "-f=" + template,
                name], capture_output=True, text=True)
            if result.returncode == 1:
                continue
            result.check_returncode()
            parts = result.stdout.strip().split("\t")
            if len(parts) != 5:
                raise RuntimeError("Unexpected package query output for " + name)
            binary, version, architecture, selection, status_ = parts
            if status_ != "installed":
                continue
            if architecture != "arm64" or binary.split(":")[0] != name:
                raise RuntimeError("Unexpected architecture/package: " + binary)
            if selection not in ("install", "hold", "deinstall", "purge"):
                raise RuntimeError("Unexpected original selection: " + selection)
            found.append(dict(name=binary, version=version, selection=selection))
        return found

    def artifacts(self):
        found = {}
        for relative in ARTIFACTS:
            path = self.sdk / relative
            if not path.is_file() or not path.resolve().is_relative_to(self.sdk):
                raise RuntimeError("Missing or external canonical artifact: " + relative)
            found[relative] = digest(path)
        return found

    def service(self):
        path = self.root / SERVICE
        if not path.is_symlink():
            raise RuntimeError("The NVIDIA bootloader metadata service must remain enabled.")
        return os.readlink(path)

    def receipt(self):
        if not self.active.is_file():
            return None, None
        pointer = json.loads(self.active.read_text())
        name = pointer["receipt"]
        if Path(name).name != name or not re.fullmatch(r"[0-9TZ_-]+[a-f0-9]+\.json", name):
            raise RuntimeError("Invalid policy receipt pointer.")
        path = self.directory / name
        record = json.loads(path.read_text())
        if record["sdk"] != str(self.sdk):
            raise RuntimeError("Policy receipt belongs to a different SDK path.")
        return path, record

    @contextmanager
    def locked(self):
        # Coordinate with apt/chroot on THIS rootfs, never the host frontend.
        with (self.db / "lock-frontend").open("r+b") as lock:
            try:
                fcntl.lockf(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as error:
                raise RuntimeError("Target package preparation is busy; retry later.") from error
            yield

    def selections(self, packages, hold):
        text = "".join(p["name"] + "\t" + ("hold" if hold else p["selection"]) + "\n"
                       for p in packages)
        environment = dict(os.environ, DPKG_FRONTEND_LOCKED="true")
        subprocess.run(["dpkg", "--admindir=" + str(self.db), "--set-selections"],
                       input=text, text=True, env=environment, check=True)

    def install_config(self, data, record):
        atomic_write(self.config, data, record["config_mode"],
                     (record["config_uid"], record["config_gid"]))

    def check(self):
        packages = self.packages()
        flags = flag_values(self.config.read_bytes())
        _, record = self.receipt()
        protected = bool(packages) and all(p["selection"] == "hold" for p in packages)
        protected = protected and flags["ENABLE_AUTO_QSPI_UPDATE"] == "0"
        protected = protected and not (self.root / MARKER).exists()
        service = self.service()
        if record and record["state"] == "active":
            protected = protected and digest(self.config) == record["applied_config_sha256"]
            try:
                self.verify(record, active=True)
            except RuntimeError:
                protected = False
        else:
            protected = False
        return dict(protected=protected, receipt_state=record["state"] if record else "none",
                    sdk=str(self.sdk), packages=packages, flags=flags,
                    service=service, artifacts=self.artifacts())

    def apply(self):
        with self.locked():
            path, old = self.receipt()
            if old and old["state"] == "active":
                if not self.check()["protected"]:
                    raise RuntimeError("Existing active policy drifted; inspect before changing it.")
                return self.check()
            if old and old["state"] not in ("restored", "rolled_back"):
                raise RuntimeError("Incomplete previous policy; restore it before retrying.")
            if (self.root / MARKER).exists():
                raise RuntimeError("Temporary NVIDIA preinstall marker remains; finish preparation first.")
            packages = self.packages()
            if not packages:
                raise RuntimeError("No installed packages from the targeted BSP set were found.")
            original = self.config.read_bytes()
            flags = flag_values(original)
            updated = re.sub(rb'^ENABLE_AUTO_QSPI_UPDATE="1"$',
                             b'ENABLE_AUTO_QSPI_UPDATE="0"', original, flags=re.M)
            before = self.artifacts()
            info = self.config.stat()
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            identifier = stamp + "_" + uuid.uuid4().hex
            self.directory.mkdir(parents=True, exist_ok=True)
            path = self.directory / (identifier + ".json")
            backup = self.directory / (identifier + ".original.conf")
            with backup.open("xb") as stream:
                stream.write(original)
            record = dict(schema=1, sdk=str(self.sdk), state="prepared", packages=packages,
                          original_config=backup.name, original_config_sha256=digest(backup),
                          applied_config_sha256=hashlib.sha256(updated).hexdigest(),
                          config_mode=stat.S_IMODE(info.st_mode), config_uid=info.st_uid,
                          config_gid=info.st_gid, original_flags=flags,
                          service=self.service(), artifacts_before=before)
            json_write(path, record)
            json_write(self.active, {"receipt": path.name})
            try:
                self.selections(packages, hold=True)
                self.install_config(updated, record)
                self.verify(record, active=True)
                if self.artifacts() != before:
                    raise RuntimeError("Canonical kernel/initrd changed concurrently.")
                record.update(state="active", artifacts_after=self.artifacts())
                json_write(path, record)
            except Exception:
                try:
                    self.install_config(original, record)
                    self.selections(packages, hold=False)
                    record["state"] = "rolled_back"
                except Exception:
                    record["state"] = "incomplete"
                json_write(path, record)
                raise
            return self.check()

    def verify(self, record, active):
        current = {p["name"]: p for p in self.packages()}
        if set(current) != {p["name"] for p in record["packages"]}:
            raise RuntimeError("Installed targeted package set changed; manual review required.")
        for package in record["packages"]:
            found = current[package["name"]]
            allowed = {"hold"} if active else {"hold", package["selection"]}
            if found["version"] != package["version"] or found["selection"] not in allowed:
                raise RuntimeError("Package selection/version drift: " + package["name"])
        if self.service() != record["service"]:
            raise RuntimeError("Bootloader metadata service enablement changed.")

    def restore(self):
        with self.locked():
            path, record = self.receipt()
            if record is None:
                raise RuntimeError("No owned receipt exists; refusing to guess original holds.")
            if record["state"] in ("restored", "rolled_back"):
                return self.check()
            self.verify(record, active=record["state"] == "active")
            hashes = {record["applied_config_sha256"], record["original_config_sha256"]}
            if digest(self.config) not in hashes:
                raise RuntimeError("Vendor configuration changed; refusing to overwrite it.")
            backup = self.directory / record["original_config"]
            if backup.parent != self.directory or digest(backup) != record["original_config_sha256"]:
                raise RuntimeError("Original configuration receipt is invalid.")
            before = self.artifacts()
            self.install_config(backup.read_bytes(), record)
            self.selections(record["packages"], hold=False)
            current = self.packages()
            if current != record["packages"]:
                raise RuntimeError("Original package selections were not restored exactly.")
            if digest(self.config) != record["original_config_sha256"]:
                raise RuntimeError("Original vendor configuration was not restored exactly.")
            if self.artifacts() != before:
                raise RuntimeError("Canonical kernel/initrd changed concurrently during restore.")
            record.update(state="restored", artifacts_after_restore=self.artifacts())
            json_write(path, record)
            return self.check()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", nargs="?", choices=("check", "apply", "restore"), default="check")
    parser.add_argument("--sdk", type=Path, default=Path(__file__).resolve().parents[2])
    args = parser.parse_args()
    try:
        policy = Policy(args.sdk)
        result = getattr(policy, args.action)()
        print(json.dumps(result, indent=2, sort_keys=True))
        return int(args.action == "check" and not result["protected"])
    except (OSError, RuntimeError, subprocess.CalledProcessError, ValueError, KeyError) as error:
        print("CompuLab BSP policy: " + str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
