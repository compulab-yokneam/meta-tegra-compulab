#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Read NVIDIA's APP_ext metadata and verify its payload without sourcing it."""
from contextlib import contextmanager
import hashlib
import os
from pathlib import Path
import re
import stat


CHUNK_SIZE = 1024 * 1024
CONFIG_LIMIT = 64 * 1024
ASSIGNMENT = re.compile(
    r"([A-Za-z_][A-Za-z0-9_]*)=(?:([A-Za-z0-9_./:+-]*)|"
    r"'([A-Za-z0-9_./:+-]*)'|\"([A-Za-z0-9_./:+-]*)\")",
    re.ASCII)
BASENAME = re.compile(r"[A-Za-z0-9_.+-]+", re.ASCII)


def require(condition, message):
    if not condition:
        raise ValueError(message)


def regular(path):
    """Read-only checks must not depend on the NFS client's numeric UID."""
    metadata = path.lstat()
    require(stat.S_ISREG(metadata.st_mode) and metadata.st_nlink == 1,
            "Expected a regular, non-linked APP input: " + str(path))
    require(path.resolve(strict=True) == path,
            "Symlink in APP input path: " + str(path))
    require(metadata.st_size > 0, "Empty APP input: " + str(path))
    return metadata


def signature(metadata):
    return (metadata.st_dev, metadata.st_ino, metadata.st_size,
            metadata.st_mtime_ns, metadata.st_ctime_ns,
            metadata.st_mode, metadata.st_nlink)


@contextmanager
def checked_reader(path):
    before = regular(path)
    with path.open("rb") as stream:
        require(signature(os.fstat(stream.fileno())) == signature(before),
                "APP input changed before reading: " + str(path))
        yield stream
        require(signature(os.fstat(stream.fileno())) == signature(before),
                "APP input changed while reading: " + str(path))
    require(signature(regular(path)) == signature(before),
            "APP input path changed while reading: " + str(path))


def small_ascii(path, limit):
    require(regular(path).st_size <= limit,
            "Oversized APP metadata: " + str(path))
    with checked_reader(path) as stream:
        payload = stream.read(limit + 1)
    require(len(payload) <= limit, "Oversized APP metadata: " + str(path))
    try:
        return payload.decode("ascii")
    except UnicodeDecodeError as error:
        raise ValueError("Non-ASCII APP metadata: " + str(path)) from error


def parse_flash_config(path):
    """Accept generated literal assignments, never shell expansions or code."""
    path = Path(path)
    values = {}
    for number, line in enumerate(small_ascii(path, CONFIG_LIMIT).splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        match = ASSIGNMENT.fullmatch(line)
        require(match is not None,
                "Unsafe flash.cfg assignment at line %d: %s" % (number, path))
        name = match[1]
        require(name not in values, "Duplicate flash.cfg key: " + name)
        values[name] = next(value for value in match.groups()[1:]
                            if value is not None)
    return values


def validate_app_payload(directory):
    """Validate the APP_ext payload used by NVIDIA's do_write_APP()."""
    directory = Path(directory)
    require(directory.is_absolute() and directory.is_dir() and
            directory.resolve(strict=True) == directory,
            "APP image directory must be an existing canonical absolute path")
    configuration = parse_flash_config(directory / "flash.cfg")
    filename = configuration.get("APP_ext", "")
    require(BASENAME.fullmatch(filename) is not None and
            filename not in (".", ".."),
            "Missing or unsafe APP_ext payload in flash.cfg")
    payload = directory / filename
    metadata = regular(payload)
    checksum_file = directory / (filename + ".sha1sum")
    expected = small_ascii(checksum_file, 128).strip()
    require(re.fullmatch(r"[0-9a-fA-F]{40}", expected) is not None,
            "Malformed APP SHA1 sidecar: " + str(checksum_file))
    # SHA1 is NVIDIA's transport checksum, not an authentication signature.
    # Stream images instead of loading multi-gigabyte rootfs archives in RAM.
    checksum = hashlib.sha1(usedforsecurity=False)
    with checked_reader(payload) as stream:
        for block in iter(lambda: stream.read(CHUNK_SIZE), b""):
            checksum.update(block)
    actual = checksum.hexdigest()
    require(actual == expected.lower(),
            "APP payload SHA1 mismatch: " + str(payload))
    require(signature(regular(payload)) == signature(metadata),
            "APP payload changed during verification: " + str(payload))
    return {"filename": filename, "sha1": actual,
            "size": metadata.st_size, "configuration": configuration}
