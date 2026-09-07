#!/usr/bin/env python3
"""Clear NVIDIA BUP image-entry TNSPEC fields after board-specific build."""

import argparse
import os
import struct
import sys


BUP_MAGIC = b"NVIDIA__BLOB__V3"
HEADER = struct.Struct("=16sIIIIII")
ENTRY = struct.Struct("=40sIIII128s")
TNSPEC_OFFSET = struct.calcsize("=40sIIII")
TNSPEC_SIZE = 128
MAX_ENTRY_COUNT = 4096


def clear_tnspec(path):
    file_size = os.path.getsize(path)
    with open(path, "r+b") as payload:
        header_data = payload.read(HEADER.size)
        if len(header_data) != HEADER.size:
            raise ValueError("file is smaller than the BUP header")

        magic, _version, blob_size, header_size, entry_count, blob_type, _ = \
            HEADER.unpack(header_data)

        if magic != BUP_MAGIC:
            raise ValueError(f"unexpected BUP magic {magic!r}")
        if blob_type != 0:
            raise ValueError(f"unsupported BUP type {blob_type}; expected update type 0")
        if blob_size != file_size:
            raise ValueError(
                f"BUP header size {blob_size} does not match file size {file_size}"
            )
        if header_size < HEADER.size:
            raise ValueError(f"invalid BUP header size {header_size}")
        if entry_count == 0 or entry_count > MAX_ENTRY_COUNT:
            raise ValueError(f"invalid BUP entry count {entry_count}")

        entry_table_end = header_size + entry_count * ENTRY.size
        if entry_table_end > file_size:
            raise ValueError("BUP image-info table extends past end of file")

        populated_tnspec_offsets = []
        for index in range(entry_count):
            entry_offset = header_size + index * ENTRY.size
            payload.seek(entry_offset)
            entry_data = payload.read(ENTRY.size)
            name, image_offset, image_size, _version, update_mode, tnspec = \
                ENTRY.unpack(entry_data)

            image_name = name.split(b"\0", 1)[0]
            if not image_name:
                raise ValueError(f"BUP entry {index} has an empty image name")
            if update_mode not in (0, 1, 2):
                raise ValueError(
                    f"BUP entry {index} ({image_name!r}) has invalid update mode "
                    f"{update_mode}"
                )
            if image_offset + image_size > file_size:
                raise ValueError(
                    f"BUP entry {index} ({image_name!r}) extends past end of file"
                )

            if tnspec.rstrip(b"\0"):
                populated_tnspec_offsets.append(entry_offset + TNSPEC_OFFSET)

        # Validate the complete table before changing the payload, so malformed
        # input cannot be left partially modified.
        for tnspec_offset in populated_tnspec_offsets:
            payload.seek(tnspec_offset)
            payload.write(bytes(TNSPEC_SIZE))

        payload.flush()

    print(
        f"Cleared TNSPEC metadata from {len(populated_tnspec_offsets)} of "
        f"{entry_count} "
        f"BUP image-info entries in {path}"
    )


def main():
    parser = argparse.ArgumentParser(
        description="Clear all image-info TNSPEC fields in an NVIDIA update BUP"
    )
    parser.add_argument("payload", help="path to bl_only_payload")
    args = parser.parse_args()

    try:
        clear_tnspec(args.payload)
    except (OSError, ValueError, struct.error) as error:
        print(f"clear-bup-tnspec: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
