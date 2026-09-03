SUMMARY = "UEFI boot-logo update capsules for CompuLab Edge-AI"
DESCRIPTION = "Builds NVIDIA-logo, CompuLab-logo, and no-logo UEFI capsule variants"
LICENSE = "MIT"
LIC_FILES_CHKSUM = "file://${COMMON_LICENSE_DIR}/MIT;md5=0835ade698e0bcf8506ecda2f7b4f302"

SRC_URI = "file://apply-uefi-capsule"
S = "${UNPACKDIR}"

inherit deploy l4t_version

INHIBIT_DEFAULT_DEPS = "1"
do_compile[noexec] = "1"
do_install[noexec] = "1"

EDGE_AI_UEFI_CAPSULE_MCS = "edge-ai-uefi-nvidia-logo edge-ai-uefi-clab-logo edge-ai-uefi-no-logo"
EDGE_AI_UEFI_CAPSULE_MACHINE ?= "edge-ai-nx-16g"
EDGE_AI_UEFI_CAPSULE_FW_VERSION = "${@oe4t.uefi.get_hex_version(d.getVar('L4T_VERSION')) if d.getVar('L4T_VERSION') else 'unknown'}"
EDGE_AI_UEFI_CAPSULE_DEPLOY_BASENAME = "${EDGE_AI_UEFI_CAPSULE_MACHINE}-tegra-bl.cap"

do_deploy[depends] += "coreutils-native:do_populate_sysroot"
do_deploy[mcdepends] += " \
    mc::edge-ai-uefi-nvidia-logo:tegra-uefi-capsules:do_deploy \
    mc::edge-ai-uefi-clab-logo:tegra-uefi-capsules:do_deploy \
    mc::edge-ai-uefi-no-logo:tegra-uefi-capsules:do_deploy \
"

do_deploy() {
    bundle_dir=${DEPLOYDIR}/edge-ai-uefi-logo-capsules
    rm -rf "$bundle_dir"
    install -d "$bundle_dir"
    install -m 0755 ${S}/apply-uefi-capsule "$bundle_dir/"

    reference_guid=
    for mc in ${EDGE_AI_UEFI_CAPSULE_MCS}; do
        case "$mc" in
            edge-ai-uefi-nvidia-logo) variant=nvidia-logo ;;
            edge-ai-uefi-clab-logo) variant=clab-logo ;;
            edge-ai-uefi-no-logo) variant=no-logo ;;
            *) bbfatal "Unknown UEFI capsule multiconfig: $mc" ;;
        esac

        mc_deploy=${TOPDIR}/tmp-mc-$mc/deploy/images/${EDGE_AI_UEFI_CAPSULE_MACHINE}
        capsule=$mc_deploy/${EDGE_AI_UEFI_CAPSULE_DEPLOY_BASENAME}
        guid_file=$mc_deploy/${TEGRA_FLASHVAR_UEFI_IMAGE}.fmp-image-type-id

        [ -s "$capsule" ] || bbfatal "Missing $variant capsule: $capsule"
        [ -s "$guid_file" ] || bbfatal "Missing $variant FMP image-type GUID: $guid_file"

        guid=$(cat "$guid_file")
        if [ -z "$reference_guid" ]; then
            reference_guid=$guid
        elif [ "$guid" != "$reference_guid" ]; then
            bbfatal "FMP image-type GUID mismatch: $variant uses $guid, expected $reference_guid"
        fi

        install -m 0644 "$capsule" "$bundle_dir/${EDGE_AI_UEFI_CAPSULE_MACHINE}-uefi-$variant.cap"
    done

    printf '%s\n' \
        'CompuLab Edge-AI UEFI boot-logo update capsules' \
        'Machine: ${EDGE_AI_UEFI_CAPSULE_MACHINE}' \
        'FMP image-type GUID: '"$reference_guid" \
        'Firmware version: ${EDGE_AI_UEFI_CAPSULE_FW_VERSION}' \
        '' \
        'Copy exactly one matching capsule and apply-uefi-capsule to the target.' \
        'Run: sudo ./apply-uefi-capsule <capsule-file>' \
        > "$bundle_dir/README.txt"

    (cd "$bundle_dir" && sha256sum -- *.cap > SHA256SUMS)
}

addtask deploy after do_unpack before do_build
