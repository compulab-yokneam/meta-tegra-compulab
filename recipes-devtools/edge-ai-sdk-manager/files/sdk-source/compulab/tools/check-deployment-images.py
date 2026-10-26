#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Read-only freshness and scope checks between generation and device flashing."""
import argparse
import csv
import importlib.util
import json
from pathlib import Path
import re
import shlex
import stat
import sys


TARGETS = ("edge-ai-nx-16g", "edge-ai-nx-8g", "edge-ai-nano-8g",
           "edge-ai-nano-4g")
LOGOS = ("clab-logo", "nvidia-logo", "no-logo")
PARAMETERS = "tools/kernel_flash/initrdflashparam.txt"
MAPPING = "tools/kernel_flash/initrdflashimgmap.txt"
INTERNAL = "tools/kernel_flash/images/internal/flash.idx"
EXTERNAL = "tools/kernel_flash/images/external/flash.idx"
SNAPSHOT_FILES = (PARAMETERS, MAPPING, "bootloader/boot0.img", INTERNAL, EXTERNAL)
LAYOUT = "tools/kernel_flash/flash_l4t_t234_nvme.xml"


def require(condition, message):
    if not condition:
        raise ValueError(message)


def regular(path, *, nonempty=True):
    """Inspect read-only inputs without assuming matching NFS client UIDs."""
    info = path.lstat()
    require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1,
            "Expected a regular, non-linked deployment input: " + str(path))
    require(path.resolve(strict=True) == path,
            "Symlink in deployment input: " + str(path))
    require(not nonempty or info.st_size > 0,
            "Empty deployment input: " + str(path))
    return info


def sdk_directory(value):
    sdk = Path(value)
    require(sdk.is_absolute() and sdk != Path("/") and sdk.is_dir() and
            sdk.resolve(strict=True) == sdk,
            "SDK root must be an existing canonical absolute directory")
    regular(sdk / "flash.sh")
    return sdk


def local_path(sdk, relative):
    path = sdk / relative
    require(path.resolve(strict=False) == path,
            "Symlink in deployment input: " + str(path))
    return path


def signature(path):
    try:
        info = regular(path, nonempty=False)
    except FileNotFoundError:
        return None
    return [info.st_dev, info.st_ino, info.st_size,
            info.st_mtime_ns, info.st_ctime_ns]


def snapshot(sdk_root):
    sdk = sdk_directory(sdk_root)
    # Check the shared validator before a potentially long generation phase.
    regular(Path(__file__).with_name("flash_app_metadata.py"))
    return {"format_version": 1, "sdk_root": str(sdk), "files": {
        relative: signature(local_path(sdk, relative))
        for relative in SNAPSHOT_FILES}}


def check_before(before, sdk):
    require(isinstance(before, dict) and
            set(before) == {"format_version", "sdk_root", "files"} and
            type(before["format_version"]) is int and
            before["format_version"] == 1 and before["sdk_root"] == str(sdk),
            "Generation snapshot does not match this SDK")
    records = before["files"]
    require(isinstance(records, dict) and set(records) == set(SNAPSHOT_FILES),
            "Generation snapshot has unexpected deployment inputs")
    for value in records.values():
        require(value is None or (isinstance(value, list) and len(value) == 5 and
                all(type(item) is int and item >= 0 for item in value)),
                "Malformed deployment-input file signature")


def parameters(sdk, target, external_device):
    path = local_path(sdk, PARAMETERS)
    regular(path)
    tokens = shlex.split(path.read_text())
    require(all(re.fullmatch(r"[A-Za-z0-9_./:+-]+", token) for token in tokens),
            "Unsafe shell characters in saved flash parameters")
    require(tokens[-2:] == [target, "external"],
            "Saved flash parameters do not match selected target/root device")
    values, flags = {}, set()
    position = 0
    arguments = tokens[:-2]
    while position < len(arguments):
        name = arguments[position]
        require(name not in values and name not in flags,
                "Duplicate saved flash option: " + name)
        if name in ("--external-device", "-c", "-S", "--network"):
            require(position + 1 < len(arguments),
                    "Missing saved flash option value: " + name)
            values[name] = arguments[position + 1]
            position += 2
        elif name in ("--read-ramcode", "--ekb-pair"):
            flags.add(name)
            position += 1
        else:
            raise ValueError("Unsupported saved flash option: " + name)
    require(values.get("--external-device") == external_device,
            "Saved NVMe device does not match selected board device")
    require(values.get("--network") == "usb0",
            "Saved flashing network must be usb0")
    layout = values.get("-c", "")
    require(layout in (LAYOUT, str(sdk / LAYOUT)),
            "Saved NVMe partition layout does not match this workflow")
    regular(local_path(sdk, LAYOUT))
    if "-S" in values:
        require(re.fullmatch(r"[1-9][0-9]*(?:KiB|MiB|GiB)?", values["-S"]),
                "Unsupported saved APP size")
    return tokens


def app_payload(directory):
    helper = Path(__file__).with_name("flash_app_metadata.py")
    regular(helper)
    specification = importlib.util.spec_from_file_location(
        "compulab_flash_app_metadata", helper)
    require(specification and specification.loader,
            "APP metadata validator is unavailable")
    module = importlib.util.module_from_spec(specification)
    sys.modules[specification.name] = module
    specification.loader.exec_module(module)
    return module.validate_app_payload(directory)


def check_index(sdk, relative, device, *, need_app=False, external_device=None):
    path = local_path(sdk, relative)
    regular(path)
    regular(local_path(sdk, str(Path(relative).with_name("flash.cfg"))))
    rows = list(csv.reader(path.read_text().splitlines(), skipinitialspace=True))
    require(rows, "Empty generated flash index: " + str(path))
    app_names = []
    for row in rows:
        require(len(row) >= 8, "Malformed generated flash index: " + str(path))
        location = row[1].strip().split(":")
        require(len(location) == 3 and location[:2] == [str(device), "0"],
                "Unexpected storage device in generated flash index")
        name = row[4].strip()
        if name:
            require(re.fullmatch(r"[A-Za-z0-9_.+-]+", name) and
                    name not in (".", ".."),
                    "Unsafe generated flash-image filename")
            regular(local_path(sdk, str(Path(relative).parent / name)))
        if location[2] == "APP":
            app_names.append(name)
    if need_app:
        require(len(app_names) == 1,
                "Generated NVMe flash index must contain one APP partition")
        # NVIDIA deliberately leaves APP's index filename empty and resolves
        # the rootfs payload through APP_ext in flash.cfg at flashing time.
        app = app_payload(path.parent)
        require(not app_names[0] or app_names[0] == app["filename"],
                "APP index filename conflicts with flash.cfg APP_ext")
        if external_device is not None:
            require(app["configuration"].get("external_device") == external_device,
                    "APP configuration does not match the selected NVMe device")
    return len(rows)


def check_rcm_command(sdk, target, logo):
    path = local_path(sdk, "bootloader/flashcmd.txt")
    regular(path)
    tokens = shlex.split(path.read_text())
    require(tokens.count("--bl") == 1 and tokens.count("--cmd") == 1,
            "Unexpected generated RCM command")
    for option in ("--bl", "--cmd"):
        require(tokens.index(option) + 1 < len(tokens),
                "Missing generated RCM argument: " + option)
    require(tokens[tokens.index("--cmd") + 1] == "rcmboot",
            "Generated command is not an RCM boot command")
    name = Path(tokens[tokens.index("--bl") + 1]).name
    prefix = "compulab-%s-%s-rcm" % (target, logo)
    require(re.fullmatch(re.escape(prefix) + r"[_.][A-Za-z0-9_.+-]+", name),
            "Generated RCM bootloader does not match selected target/logo")


def validate_images(sdk_root, target, external_device, logo, before):
    require(target in TARGETS, "Unsupported deployment target")
    require(logo in LOGOS, "Unsupported deployment logo")
    require(re.fullmatch(r"nvme[0-9]+n[0-9]+p1", external_device),
            "Expected a board NVMe APP partition")
    sdk = sdk_directory(sdk_root)
    check_before(before, sdk)
    after = snapshot(sdk)
    for relative in (PARAMETERS, MAPPING):
        regular(local_path(sdk, relative))
        require(after["files"][relative] != before["files"][relative],
                "Generation did not refresh deployment input: " + relative)
    parameters(sdk, target, external_device)
    mapping = local_path(sdk, MAPPING).read_text().splitlines()
    require(len(mapping) == 1, "Deployment requires exactly one generated flash initrd")
    match = re.fullmatch(r"flashimg0=([A-Za-z0-9_.+-]+)", mapping[0])
    require(match is not None and match[1] not in (".", ".."),
            "Generated flash initrd mapping is invalid")
    initrd = "bootloader/" + match[1]
    regular(local_path(sdk, initrd))
    check_rcm_command(sdk, target, logo)
    internal = check_index(sdk, INTERNAL, 3)
    external = check_index(sdk, EXTERNAL, 9, need_app=True,
                           external_device=external_device)
    return {"status": "verified", "target": target, "logo": logo,
            "external_device": external_device, "flash_initrd": initrd,
            "internal_partitions": internal, "external_partitions": external,
            "fresh_inputs": [PARAMETERS, MAPPING],
            "hardware_validation": "Not performed"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sdk-root", type=Path, required=True)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--snapshot", action="store_true")
    action.add_argument("--before-json")
    parser.add_argument("--target", choices=TARGETS)
    parser.add_argument("--external-device")
    parser.add_argument("--logo", choices=LOGOS)
    arguments = parser.parse_args()
    try:
        if arguments.snapshot:
            require(not any((arguments.target, arguments.external_device,
                             arguments.logo)),
                    "Snapshot mode does not accept deployment selections")
            result = snapshot(arguments.sdk_root)
        else:
            require(all((arguments.target, arguments.external_device,
                         arguments.logo)),
                    "Validation requires target, external device and logo")
            result = validate_images(arguments.sdk_root, arguments.target,
                                     arguments.external_device, arguments.logo,
                                     json.loads(arguments.before_json))
    except (OSError, ValueError) as error:
        parser.exit(1, "Deployment image verification failed: %s\n" % error)
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
