# SPDX-License-Identifier: MIT
# Copyright (c) 2026 CompuLab Ltd.
# Optional, deploy/sstate-managed inputs for the SDK conversion recipe.
EDGE_AI_SDK_EXPORTS ?= "0"

def edge_ai_sdk_firmware_export(d):
    import hashlib
    import json
    import os
    from pathlib import Path
    import shutil
    from urllib.parse import unquote
    import zlib

    if d.getVar("EDGE_AI_SDK_EXPORTS") != "1":
        return

    role = d.getVar("EDGE_AI_SDK_FIRMWARE_ROLE")
    if role not in ("general", "rcm", "standalone-mm", "tos"):
        bb.fatal("Unknown Edge-AI SDK firmware export role: %s" % role)
    if d.getVar("SOC_FAMILY") != "tegra234":
        bb.fatal("Edge-AI SDK firmware exports currently require Tegra234")
    if d.getVar("L4T_VERSION") != "39.2.1":
        bb.fatal("Edge-AI SDK firmware exports currently require L4T 39.2.1")

    build = Path(d.getVar("B"))
    source = Path(d.getVar("S"))
    output = Path(d.getVar("DEPLOYDIR")) / "edge-ai-sdk/firmware" / d.getVar("PN")
    platform = d.getVar("EDK2_PLATFORM") or ""
    entries = []
    inputs = []

    def require_file(path):
        if not path.is_file() or path.stat().st_size == 0:
            bb.fatal("Required Edge-AI SDK firmware input is missing/empty: %s" % path)
        return path

    def sha256(path):
        with path.open("rb") as stream:
            result = hashlib.sha256()
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                result.update(block)
        return result.hexdigest()

    def add(path, name, origin):
        inputs.append((require_file(path), name, origin))

    metadata = {
        "schema": 1,
        "role": role,
        "recipe": d.getVar("PN"),
        "version": d.getVar("PV"),
        "revision": d.getVar("PR"),
        "machine": d.getVar("MACHINE"),
        "multiconfig": d.getVar("BB_CURRENT_MC") or "",
        "l4t_version": d.getVar("L4T_VERSION"),
        "license": d.getVar("LICENSE"),
        "source_date_epoch": d.getVar("SOURCE_DATE_EPOCH"),
        "source_revisions": {
            key: d.getVar(key) for key in sorted(d.keys())
            if key == "SRCREV" or key.startswith("SRCREV_")
        },
    }

    if role in ("general", "rcm", "standalone-mm"):
        metadata["edk2"] = {
            "platform": platform,
            "build_mode": d.getVar("EDK2_BUILD_MODE"),
            "compiler": d.getVar("EDK_COMPILER"),
        }
        binary = build / "images" / d.getVar("EDK2_BIN_NAME")
        if role == "general":
            style = d.getVar("EDGE_AI_UEFI_LOGO_STYLE")
            styles = {"clab": "clab-logo", "none": "no-logo", "nvidia": "nvidia-logo"}
            if style not in styles:
                bb.fatal("Unknown Edge-AI SDK UEFI logo style: %s" % style)
            metadata["logo_style"] = styles[style]
            metadata["lowest_supported_version"] = d.getVar("TEGRA_UEFI_LOWEST_SUPPORTED_VERSION")
            add(binary, "uefi.bin", "build/images/${EDK2_BIN_NAME}")
            # do_deploy follows do_install and therefore do_sign_efi_launcher.
            # Copy the signed build output, never an unrelated ESP/sysroot file.
            add(build / "images/BOOTAA64.efi", "BOOTAA64.efi", "build/images/BOOTAA64.efi")
            config = build / "nvidia-config/Tegra" / platform
            add(config / ".config", "general.cfg", "build/nvidia-config/Tegra/${EDK2_PLATFORM}/.config")
            add(config / "fmp-image-type-id.txt", "fmp-image-type-id.txt", "build/nvidia-config/Tegra/${EDK2_PLATFORM}/fmp-image-type-id.txt")
            for name in ("L4TConfiguration.dtbo", "L4TConfiguration-rcmboot.dtbo"):
                require_file(build / "images" / name)
            for path in sorted((build / "images").glob("*.dtbo")):
                add(path, path.name, "build/images/" + path.name)
        elif role == "rcm":
            add(binary, "uefi-rcm.bin", "build/images/${EDK2_BIN_NAME}")
            add(build / "nvidia-config/Tegra" / platform / ".config", "minimal.cfg", "build/nvidia-config/Tegra/${EDK2_PLATFORM}/.config")
        else:
            add(binary, "standalone_mm_optee.bin", "build/images/${EDK2_BIN_NAME}")
            dsc = d.getVar("EDK2_PLATFORM_DSC")
            add(Path(d.getVar("S_EDK2_NVIDIA")) / dsc, "StandaloneMmOptee.dsc", "edk2-nvidia/" + dsc)
            # This recipe builds a DSC directly and generates no Kconfig.
            metadata["edk2"]["configuration_kind"] = "DSC, not generated Kconfig"
            metadata["edk2"]["debug_print_error_level"] = d.getVar("TEGRA_UEFI_STMM_DEBUG_PRINT_ERROR_LEVEL")
    else:
        tos = require_file(source / d.getVar("TOSIMG"))
        staging = Path(d.getVar("STAGING_DATADIR"))
        tee = require_file(staging / "trusted-os/tee-raw.bin")
        monitor = require_file(staging / "trusted-os/bl31.bin")
        mm = require_file(staging / "edk2-nvidia/standalone_mm_optee.bin")
        tos_data, tee_data, mm_data = tos.read_bytes(), tee.read_bytes(), mm.read_bytes()
        tee_offset = tos_data.find(tee_data)
        if tee_offset < 0:
            bb.fatal("TOS does not contain this recipe's staged OP-TEE image")
        mm_offset = None
        # OP-TEE embeds its Standalone MM as a compressed secure partition.
        # Locate and compare exact bytes; do not assume the prior build's offsets.
        for offset in range(len(tee_data) - 1):
            if tee_data[offset] != 0x78 or tee_data[offset + 1] not in (1, 0x5e, 0x9c, 0xda):
                continue
            try:
                stream = zlib.decompressobj()
                expanded = stream.decompress(tee_data[offset:], len(mm_data) + 1)
            except zlib.error:
                continue
            if stream.eof and expanded == mm_data:
                mm_offset = offset
                break
        if mm_offset is None:
            bb.fatal("OP-TEE does not embed this recipe's staged Standalone MM")
        metadata["matched_trusted_os"] = {
            "tee_raw_sha256": sha256(tee),
            "standalone_mm_sha256": sha256(mm),
            "bl31_sha256": sha256(monitor),
            "tos_tee_offset": tee_offset,
            "tee_stmm_zlib_offset": mm_offset,
        }
        add(tos, "tos.img", "source/${TOSIMG}")
        add(source / (d.getVar("SOC_FAMILY") + "-optee.dtb"), "tegra234-optee.dtb", "source/${SOC_FAMILY}-optee.dtb")

    # Retain complete original notices, even if LIC_FILES_CHKSUM selects lines.
    for index, specification in enumerate((d.getVar("LIC_FILES_CHKSUM") or "").split()):
        uri = specification.split(";", 1)[0]
        if not uri.startswith("file://"):
            bb.fatal("Unsupported firmware license URI: %s" % uri)
        path = Path(unquote(uri[len("file://"):]))
        if not path.is_absolute():
            path = source / path
        add(path, "licenses/%02d-%s" % (index, path.name), "LIC_FILES_CHKSUM entry %d" % index)
    if not any(name.startswith("licenses/") for _, name, _ in inputs):
        bb.fatal("Edge-AI SDK firmware export requires original license notices")

    # All writes remain in DEPLOYDIR, so deploy.bbclass owns sstate and cleanup.
    for path, name, origin in inputs:
        target = output / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)
        os.chmod(target, 0o644)
        entries.append({"path": name, "origin": origin, "sha256": sha256(target), "size": target.stat().st_size})
    metadata["files"] = entries
    manifest = output / "manifest.json"
    manifest.write_text(json.dumps(metadata, indent=2, sort_keys=True) + "\n")
    os.chmod(manifest, 0o644)
    checksums = [(entry["sha256"], entry["path"]) for entry in entries]
    checksums.append((sha256(manifest), "manifest.json"))
    sums = output / "SHA256SUMS"
    sums.write_text("".join("%s  %s\n" % pair for pair in sorted(checksums, key=lambda pair: pair[1])))
    os.chmod(sums, 0o644)

python edge_ai_sdk_export_firmware() {
    edge_ai_sdk_firmware_export(d)
}

do_deploy[postfuncs] += "edge_ai_sdk_export_firmware"
do_deploy[vardeps] += "EDGE_AI_SDK_EXPORTS EDGE_AI_SDK_FIRMWARE_ROLE"
