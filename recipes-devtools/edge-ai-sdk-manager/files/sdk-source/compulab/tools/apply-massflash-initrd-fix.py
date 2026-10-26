#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Apply or verify the reviewed, version-pinned R39.2.1 massflash initrd fix."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import stat
import sys
import tempfile


VENDOR_FILE = "tools/kernel_flash/l4t_initrd_flash_internal.sh"
PATCH_FILE = ("compulab/patches/"
              "0001-kernel-flash-Isolate-massflash-initrd-working-trees.patch")
BACKUP_FILE = "compulab/patches/l4t_initrd_flash_internal.sh.vendor-original"
BEFORE_SHA256 = "505b7b61b3cb864bdc3a1f7c474ab4f22106b1da4976980d86709f1755ec76f2"
AFTER_SHA256 = "9c2c8cc62b305c127efe569dc103d1476da692eb9c5f6c9f54f856bd6fdedc11"
PATCH_SHA256 = "0b80bc62bfb441dbf6218e3ae87c810b2de35b82638616d0a7fe9f6dcac9e029"


def require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(payload):
    return hashlib.sha256(payload).hexdigest()


def owners():
    allowed = {0, os.getuid()}
    invoking = os.environ.get("SUDO_UID", "")
    if os.getuid() == 0 and invoking.isdecimal():
        allowed.add(int(invoking))
    return allowed


def regular(path, *, check_owner=True):
    metadata = path.lstat()
    require(stat.S_ISREG(metadata.st_mode) and metadata.st_nlink == 1,
            "Expected a non-symlink, non-hardlinked regular file: " + str(path))
    require(path.resolve(strict=True) == path,
            "Symlink in SDK patch path: " + str(path))
    if check_owner:
        require(metadata.st_uid in owners(),
                "Unexpected owner of SDK patch input: " + str(path))
    return metadata


def checked_inputs(sdk_root, *, check_owner=True):
    sdk = Path(sdk_root)
    require(sdk.is_absolute() and sdk != Path("/") and
            sdk.resolve(strict=True) == sdk and sdk.is_dir(),
            "SDK root must be a canonical absolute directory")
    target = sdk / VENDOR_FILE
    patch = sdk / PATCH_FILE
    regular(target, check_owner=check_owner)
    regular(patch, check_owner=check_owner)
    payload = patch.read_bytes()
    require(digest(payload) == PATCH_SHA256,
            "Reviewed massflash patch checksum mismatch")
    return sdk, target, payload


def patched_payload(original, patch):
    """Consume only the one pinned unified-diff hunk, without invoking a shell."""
    require(digest(patch) == PATCH_SHA256,
            "Reviewed massflash patch checksum mismatch")
    header = b"@@ -466,6 +466,13 @@\n"
    require(patch.count(header) == 1 and patch.count(b"\n@@ ") == 1,
            "Unexpected reviewed patch layout")
    lines = patch.split(header, 1)[1].splitlines(keepends=True)
    require(all(line[:1] in (b" ", b"+", b"-") for line in lines),
            "Unexpected reviewed patch hunk")
    before = b"".join(line[1:] for line in lines
                      if line[:1] in (b" ", b"-"))
    after = b"".join(line[1:] for line in lines
                     if line[:1] in (b" ", b"+"))
    require(len(before.splitlines()) == 6 and len(after.splitlines()) == 13 and
            original.count(before) == 1,
            "Massflash initrd source does not contain the reviewed context")
    return original.replace(before, after, 1)


def atomic_write(path, payload, mode, metadata, *, new=False):
    descriptor, temporary = tempfile.mkstemp(
        prefix=".compulab-massflash-initrd-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            if os.getuid() == 0:
                os.fchown(stream.fileno(), metadata.st_uid, metadata.st_gid)
            os.fchmod(stream.fileno(), mode)
            os.fsync(stream.fileno())
        if new:
            # Never replace an unexpected pre-existing backup, even in a race.
            os.link(temporary, path)
        else:
            os.replace(temporary, path)
    finally:
        if os.path.lexists(temporary):
            os.unlink(temporary)


def checked_backup(sdk, *, check_owner=True):
    backup = sdk / BACKUP_FILE
    regular(backup, check_owner=check_owner)
    require(digest(backup.read_bytes()) == BEFORE_SHA256,
            "Massflash vendor backup checksum mismatch")
    return backup


def verify_fix(sdk_root):
    # NFS clients can see valid SDK files owned by another numeric UID.
    # Read-only verification trusts exact reviewed hashes, not UID equality.
    # Applying the fix still uses the strict ownership checks above.
    sdk, target, _ = checked_inputs(sdk_root, check_owner=False)
    require(digest(target.read_bytes()) == AFTER_SHA256,
            "Reviewed massflash initrd isolation fix is missing or changed")
    checked_backup(sdk, check_owner=False)
    return {"status": "verified", "file": VENDOR_FILE,
            "before_sha256": BEFORE_SHA256, "after_sha256": AFTER_SHA256,
            "patch_sha256": PATCH_SHA256, "backup": BACKUP_FILE}


def apply_fix(sdk_root):
    sdk, target, patch = checked_inputs(sdk_root)
    original = target.read_bytes()
    if digest(original) == AFTER_SHA256:
        checked_backup(sdk)
        return verify_fix(sdk)
    require(digest(original) == BEFORE_SHA256,
            "Unrecognized NVIDIA initrd-flash script; refusing to patch")
    updated = patched_payload(original, patch)
    require(digest(updated) == AFTER_SHA256,
            "Reviewed massflash patch produced an unexpected checksum")
    backup = sdk / BACKUP_FILE
    metadata = regular(target)
    if os.path.lexists(backup):
        checked_backup(sdk)
    else:
        atomic_write(backup, original, 0o444, metadata, new=True)
    require(target.read_bytes() == original,
            "NVIDIA initrd-flash script changed while preparing its patch")
    regular(target)
    atomic_write(target, updated, stat.S_IMODE(metadata.st_mode), metadata)
    result = verify_fix(sdk)
    result["status"] = "applied"
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sdk-root", type=Path, required=True)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--apply", action="store_true")
    action.add_argument("--verify", action="store_true")
    arguments = parser.parse_args()
    try:
        operation = apply_fix if arguments.apply else verify_fix
        result = operation(arguments.sdk_root)
    except (OSError, ValueError) as error:
        parser.exit(1, "Massflash initrd fix stopped: %s\n" % error)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
