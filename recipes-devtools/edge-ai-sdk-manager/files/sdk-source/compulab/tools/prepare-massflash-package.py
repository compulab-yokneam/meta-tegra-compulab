#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Finalize a freshly generated T234 massflash package without host profiles."""
import argparse
import csv
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shlex
import stat
import sys
import tarfile
import tempfile


TARGETS = ("edge-ai-nx-16g", "edge-ai-nx-8g", "edge-ai-nano-8g",
           "edge-ai-nano-4g")
SCOPES = ("bootloader", "full")
LOGOS = ("clab-logo", "nvidia-logo", "no-logo")
RECEIPT = "compulab-massflash.json"
GUIDE = "README.compulab-massflash.md"
SCRIPTS = ("l4t_initrd_flash.sh", "l4t_initrd_flash_internal.sh",
           "l4t_initrd_flash.func", "l4t_network_flash.func",
           "l4t_kernel_flash_vars.func")


def require(condition, message):
    if not condition:
        raise ValueError(message)


def allowed_owners():
    owners = {0, os.getuid()}
    # sudo-generated package files are root-owned, but the SDK and profiles
    # usually belong to the ordinary invoking user.
    invoking = os.environ.get("SUDO_UID", "")
    if os.getuid() == 0 and invoking.isdecimal():
        owners.add(int(invoking))
    return owners


def regular(path, *, single_link=False, check_owner=True):
    info = path.lstat()
    require(stat.S_ISREG(info.st_mode) and info.st_size > 0,
            "Missing/nonregular native package input: " + str(path))
    require(path.resolve(strict=True) == path,
            "Symlink in native package input: " + str(path))
    if check_owner:
        require(info.st_uid in allowed_owners(),
                "Unexpected native package input owner: " + str(path))
    require(not single_link or info.st_nlink == 1,
            "Hard-linked package output is not supported: " + str(path))
    return info


def check_tree(package):
    """Preserve native internal symlinks, never archive external/special files."""
    for folder, directories, files in os.walk(package, followlinks=False):
        for name in directories + files:
            path = Path(folder) / name
            mode = path.lstat().st_mode
            require(stat.S_ISREG(mode) or stat.S_ISDIR(mode) or
                    stat.S_ISLNK(mode),
                    "Special file in native package: " + str(path))
            if stat.S_ISLNK(mode):
                require(not os.path.isabs(os.readlink(path)) and
                        path.resolve(strict=True).is_relative_to(package),
                        "Escaping/absolute package symlink: " + str(path))


def app_payload(directory):
    helper = Path(__file__).with_name("flash_app_metadata.py")
    regular(helper, check_owner=False)
    specification = importlib.util.spec_from_file_location(
        "compulab_flash_app_metadata", helper)
    require(specification and specification.loader,
            "APP metadata validator is unavailable")
    module = importlib.util.module_from_spec(specification)
    sys.modules[specification.name] = module
    specification.loader.exec_module(module)
    return module.validate_app_payload(directory)


def check_index(directory, device, *, need_app=False, external_device=None):
    index = directory / "flash.idx"
    regular(index, check_owner=False)
    regular(directory / "flash.cfg", check_owner=False)
    rows = list(csv.reader(index.read_text().splitlines(),
                           skipinitialspace=True))
    require(rows, "Empty native flash index: " + str(index))
    app_names = []
    for row in rows:
        require(len(row) >= 8, "Malformed native flash index: " + str(index))
        location = row[1].strip().split(":")
        require(len(location) == 3 and location[:2] == [str(device), "0"],
                "Unexpected storage device in " + str(index))
        name = row[4].strip()
        if name:
            require(re.fullmatch(r"[A-Za-z0-9_.+-]+", name) and
                    name not in (".", ".."),
                    "Unsafe flash-image filename: " + name)
            regular(directory / name, check_owner=False)
        if location[2] == "APP":
            app_names.append(name)
    if need_app:
        require(len(app_names) == 1,
                "Full massflash package must contain one APP partition")
        app = app_payload(directory)
        require(not app_names[0] or app_names[0] == app["filename"],
                "APP index filename conflicts with flash.cfg APP_ext")
        if external_device is not None:
            require(app["configuration"].get("external_device") == external_device,
                    "APP configuration does not match the selected NVMe device")


def validate(sdk_root, target, scope, massflash, logo, early_tty1):
    require(target in TARGETS, "Unsupported massflash target")
    require(scope in SCOPES, "Unsupported massflash scope")
    require(type(massflash) is int and 1 <= massflash <= 64,
            "Massflash count must be between 1 and 64")
    require(logo in LOGOS, "Unsupported massflash logo")
    require(str(early_tty1) in ("0", "1"), "Early tty1 must be 0 or 1")
    sdk = Path(sdk_root)
    require(sdk.is_absolute() and sdk.resolve(strict=True) == sdk,
            "SDK root must be an existing canonical absolute directory")
    require(sdk.is_dir(), "SDK root is not a directory")
    # These inputs are only read. NFS and native cp -a may retain the SDK
    # server's numeric UID; output ownership checks remain strict below.
    regular(sdk / "flash.sh", check_owner=False)
    regular(sdk / (target + ".conf"), check_owner=False)
    package = sdk / ("mfi_" + target)
    info = package.lstat()
    require(stat.S_ISDIR(info.st_mode) and
            package.resolve(strict=True).parent == sdk,
            "Native massflash package must be a real SDK child directory")
    require(info.st_uid in allowed_owners(),
            "Unexpected native massflash directory owner")
    archive = sdk / (package.name + ".tar.gz")
    regular(archive, single_link=True)
    require(tarfile.is_tarfile(archive), "Native massflash archive is invalid")
    profile = package / (target + ".conf")
    regular(profile, single_link=True)
    require(profile.read_bytes() == (sdk / (target + ".conf")).read_bytes(),
            "Native package profile does not match the selected SDK profile")
    for name in (GUIDE, RECEIPT):
        require(not os.path.lexists(package / name),
                "Massflash package was already finalized: " + str(package))
    check_tree(package)
    kernel_flash = package / "tools/kernel_flash"
    for name in SCRIPTS:
        regular(kernel_flash / name, check_owner=False)
    regular(package / "bootloader/flashcmd.txt", check_owner=False)
    regular(kernel_flash / "images/l4t_flash_from_kernel.sh", check_owner=False)
    parameters = kernel_flash / "initrdflashparam.txt"
    regular(parameters, check_owner=False)
    tokens = shlex.split(parameters.read_text())
    require(all(re.fullmatch(r"[A-Za-z0-9_./:+-]+", token) for token in tokens),
            "Unsafe shell characters in saved flash parameters")
    require(tokens[-2:] == [target, "external"],
            "Saved flash parameters do not match target/root device")
    require(not {"--direct", "--external-only", "--boot-rootfs"} & set(tokens),
            "Unsupported direct/external-only/boot-rootfs flash parameters")
    if scope == "full":
        require(tokens.count("--external-device") == 1,
                "Full package is missing its external NVMe device")
        position = tokens.index("--external-device")
        require(position + 1 < len(tokens) and
                re.fullmatch(r"nvme[0-9]+n[0-9]+p1", tokens[position + 1]),
                "Full package must target a board NVMe APP partition")
        external_device = tokens[position + 1]
    else:
        require("--external-device" not in tokens,
                "Bootloader-only package must not target external storage")
    mapping = kernel_flash / "initrdflashimgmap.txt"
    regular(mapping, check_owner=False)
    images = {}
    for line in mapping.read_text().splitlines():
        match = re.fullmatch(r"flashimg([0-9]+)=([A-Za-z0-9_.+-]+)", line)
        require(match is not None, "Malformed native flash-initrd mapping")
        number, name = int(match[1]), match[2]
        require(number not in images and name not in (".", ".."),
                "Duplicate/invalid native flash-initrd mapping")
        regular(package / "bootloader" / name, check_owner=False)
        images[number] = name
    require(set(images) == set(range(massflash)),
            "Native flash-initrd count does not match massflash count")
    check_index(kernel_flash / "images/internal", 3)
    external = kernel_flash / "images/external"
    if scope == "full":
        check_index(external, 9, need_app=True, external_device=external_device)
    else:
        require(not os.path.lexists(external / "flash.idx"),
                "Bootloader-only package contains an external flash index")
    return sdk, package, archive, profile, tokens


def atomic_bytes(path, content, mode=0o644):
    descriptor, temporary = tempfile.mkstemp(
        prefix=".compulab-massflash-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
            os.fchmod(stream.fileno(), mode)
        os.replace(temporary, path)
    finally:
        if os.path.lexists(temporary):
            os.unlink(temporary)


def prepare_package(sdk_root, target, scope, massflash, logo, early_tty1):
    sdk, package, archive, profile, tokens = validate(
        sdk_root, target, scope, massflash, logo, early_tty1)
    previous = profile.read_bytes()
    previous_mode = stat.S_IMODE(profile.stat().st_mode)
    archive_mode = stat.S_IMODE(archive.stat().st_mode)
    config = ("# Prebuilt T234 massflash runtime; not an SDK build profile.\n"
              "# Images and firmware are already selected and signed.\n"
              "CHIPID=0x23\n"
              "MAX_MASSFLASH=%d\n"
              "_UNIFIED_FLASH=\nUNIFIED_FLASH=\n" % massflash)
    receipt = {
        "format_version": 1, "target": target, "scope": scope,
        "massflash": massflash, "logo": logo,
        "early_tty1": int(early_tty1), "prebuilt_only": True,
        "sdk_profile_sha256": hashlib.sha256(previous).hexdigest(),
        "native_flash_parameters": tokens,
    }
    effect = ("QSPI firmware only; internal/NVMe root filesystems are not written"
              if scope == "bootloader" else
              "QSPI firmware and the board NVMe, including its APP filesystem")
    guide = ("# CompuLab prebuilt massflash package\n\n"
             "Target: `%s`; logo: `%s`; early tty1: `%s`.\n\n"
             "WARNING: the following command flashes connected Jetsons and "
             "overwrites %s.\n\n"
             "Use only identical module SKUs and qualified hardware revisions "
             "matching the package's board/FAB/BOARDREV/RAMCODE configuration. "
             "This is not a universal cross-platform package.\n\n"
             "Extract this archive on a writable Linux filesystem, enter "
             "`%s`, and connect at most %d matching boards in recovery mode. "
             "Review the selected devices before explicitly running:\n\n"
             "```sh\nsudo ./tools/kernel_flash/l4t_initrd_flash.sh \\\n"
             "    --flash-only --massflash %d --network usb0 --keep \\\n"
             "    %s external\n```\n\n"
             "This directory contains prebuilt images, not a full SDK. "
             "Use `--flash-only`; do not regenerate images here. The minimal "
             "board configuration intentionally has no dependencies on the "
             "original SDK's CompuLab profiles or rootfs. Preparation did not "
             "flash the boards. Hardware boot qualification is still required.\n"
             ) % (target, logo, early_tty1, effect, package.name, massflash,
                  massflash, target)
    descriptor, temporary = tempfile.mkstemp(
        prefix=".compulab-massflash-", suffix=".tar.gz", dir=sdk)
    os.close(descriptor)
    try:
        atomic_bytes(profile, config.encode(), previous_mode)
        atomic_bytes(package / RECEIPT,
                     (json.dumps(receipt, indent=2, sort_keys=True) + "\n").encode())
        atomic_bytes(package / GUIDE, guide.encode())
        with tarfile.open(temporary, "w:gz", dereference=False) as stream:
            stream.add(package, arcname=package.name)
        with open(temporary, "rb") as stream:
            os.fsync(stream.fileno())
        os.chmod(temporary, archive_mode)
        os.replace(temporary, archive)
    except BaseException:
        atomic_bytes(profile, previous, previous_mode)
        for name in (RECEIPT, GUIDE):
            (package / name).unlink(missing_ok=True)
        raise
    finally:
        if os.path.lexists(temporary):
            os.unlink(temporary)
    return {"package": str(package), "archive": str(archive), **receipt}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sdk-root", type=Path, required=True)
    parser.add_argument("--target", choices=TARGETS, required=True)
    parser.add_argument("--scope", choices=SCOPES, required=True)
    parser.add_argument("--massflash", type=int, required=True)
    parser.add_argument("--logo", choices=LOGOS, required=True)
    parser.add_argument("--early-tty1", choices=("0", "1"), required=True)
    arguments = parser.parse_args()
    try:
        result = prepare_package(arguments.sdk_root, arguments.target,
                                 arguments.scope, arguments.massflash,
                                 arguments.logo, arguments.early_tty1)
    except (OSError, ValueError, tarfile.TarError) as error:
        parser.exit(1, "Massflash finalization stopped: %s\n" % error)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
