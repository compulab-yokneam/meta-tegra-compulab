SUMMARY = "Complete UEFI boot-firmware update capsules for CompuLab Edge-AI"
DESCRIPTION = "Builds NVIDIA-logo, CompuLab-logo, and no-logo full boot-firmware capsules"
LICENSE = "MIT"
LIC_FILES_CHKSUM = "file://${COMMON_LICENSE_DIR}/MIT;md5=0835ade698e0bcf8506ecda2f7b4f302"

PROVIDES += "edge-ai-uefi-logo-capsules"

SRC_URI = " \
    file://apply-uefi-capsule \
    file://edge-ai-uefi-update \
"
S = "${UNPACKDIR}"

inherit deploy l4t_version

INHIBIT_DEFAULT_DEPS = "1"
do_compile[noexec] = "1"

EDGE_AI_UEFI_CAPSULE_MACHINES = "edge-ai-nx-16g edge-ai-nx-8g edge-ai-nano-8g edge-ai-nano-4g"
EDGE_AI_UEFI_CAPSULE_MCS = " \
    edge-ai-uefi-nvidia-logo \
    edge-ai-uefi-clab-logo \
    edge-ai-uefi-no-logo \
    edge-ai-uefi-nx-8g-nvidia-logo \
    edge-ai-uefi-nx-8g-clab-logo \
    edge-ai-uefi-nx-8g-no-logo \
    edge-ai-uefi-nano-8g-nvidia-logo \
    edge-ai-uefi-nano-8g-clab-logo \
    edge-ai-uefi-nano-8g-no-logo \
    edge-ai-uefi-nano-4g-nvidia-logo \
    edge-ai-uefi-nano-4g-clab-logo \
    edge-ai-uefi-nano-4g-no-logo \
"
EDGE_AI_UEFI_LEGACY_FMP_GUIDS ?= ""
EDGE_AI_UEFI_LOWEST_SUPPORTED_VERSION ?= ""
EDGE_AI_UEFI_CAPSULE_FW_VERSION = "${@oe4t.uefi.get_hex_version(d.getVar('L4T_VERSION'))}"
EDGE_AI_UEFI_CAPSULE_LSV = "${@d.getVar('EDGE_AI_UEFI_LOWEST_SUPPORTED_VERSION') or d.getVar('EDGE_AI_UEFI_CAPSULE_FW_VERSION')}"
EDGE_AI_UEFI_CAPSULE_INSTALL_DIR = "${datadir}/compulab/uefi-update-capsules"

do_install[depends] += "coreutils-native:do_populate_sysroot"
do_install[mcdepends] += " \
    mc:${BB_CURRENT_MC}:edge-ai-uefi-nvidia-logo:tegra-uefi-capsules:do_deploy \
    mc:${BB_CURRENT_MC}:edge-ai-uefi-clab-logo:tegra-uefi-capsules:do_deploy \
    mc:${BB_CURRENT_MC}:edge-ai-uefi-no-logo:tegra-uefi-capsules:do_deploy \
    mc:${BB_CURRENT_MC}:edge-ai-uefi-nx-8g-nvidia-logo:tegra-uefi-capsules:do_deploy \
    mc:${BB_CURRENT_MC}:edge-ai-uefi-nx-8g-clab-logo:tegra-uefi-capsules:do_deploy \
    mc:${BB_CURRENT_MC}:edge-ai-uefi-nx-8g-no-logo:tegra-uefi-capsules:do_deploy \
    mc:${BB_CURRENT_MC}:edge-ai-uefi-nano-8g-nvidia-logo:tegra-uefi-capsules:do_deploy \
    mc:${BB_CURRENT_MC}:edge-ai-uefi-nano-8g-clab-logo:tegra-uefi-capsules:do_deploy \
    mc:${BB_CURRENT_MC}:edge-ai-uefi-nano-8g-no-logo:tegra-uefi-capsules:do_deploy \
    mc:${BB_CURRENT_MC}:edge-ai-uefi-nano-4g-nvidia-logo:tegra-uefi-capsules:do_deploy \
    mc:${BB_CURRENT_MC}:edge-ai-uefi-nano-4g-clab-logo:tegra-uefi-capsules:do_deploy \
    mc:${BB_CURRENT_MC}:edge-ai-uefi-nano-4g-no-logo:tegra-uefi-capsules:do_deploy \
"

assemble_capsule_bundle() {
    bundle_dir="$1"
    rm -rf "$bundle_dir"
    install -d "$bundle_dir"
    install -m 0755 ${S}/apply-uefi-capsule "$bundle_dir/"

    reference_guid=
    for mc in ${EDGE_AI_UEFI_CAPSULE_MCS}; do
        case "$mc" in
            edge-ai-uefi-nvidia-logo|edge-ai-uefi-clab-logo|edge-ai-uefi-no-logo)
                machine=edge-ai-nx-16g
                ;;
            edge-ai-uefi-nx-8g-*) machine=edge-ai-nx-8g ;;
            edge-ai-uefi-nano-8g-*) machine=edge-ai-nano-8g ;;
            edge-ai-uefi-nano-4g-*) machine=edge-ai-nano-4g ;;
            *) bbfatal "Unknown UEFI capsule multiconfig: $mc" ;;
        esac
        case "$mc" in
            *-nvidia-logo) variant=nvidia-logo ;;
            *-clab-logo) variant=clab-logo ;;
            *-no-logo) variant=no-logo ;;
            *) bbfatal "Unknown UEFI capsule logo variant: $mc" ;;
        esac

        mc_deploy=${TOPDIR}/tmp-mc-$mc/deploy/images/$machine
        capsule=$mc_deploy/$machine-tegra-bl.cap
        guid_file=$mc_deploy/${TEGRA_FLASHVAR_UEFI_IMAGE}.fmp-image-type-id

        [ -s "$capsule" ] || bbfatal "Missing $variant capsule: $capsule"
        [ -s "$guid_file" ] || bbfatal "Missing $variant FMP image-type GUID: $guid_file"

        guid=$(cat "$guid_file")
        if [ -z "$reference_guid" ]; then
            reference_guid=$guid
        elif [ "$guid" != "$reference_guid" ]; then
            bbfatal "FMP image-type GUID mismatch: $variant uses $guid, expected $reference_guid"
        fi

        install -m 0644 "$capsule" "$bundle_dir/$machine-uefi-$variant.cap"

        for legacy_guid in ${EDGE_AI_UEFI_LEGACY_FMP_GUIDS}; do
            if [ "$legacy_guid" = "$reference_guid" ]; then
                bbfatal "Legacy FMP GUID duplicates the current GUID: $legacy_guid"
            fi

            legacy_capsule=$mc_deploy/$machine-tegra-bl-$legacy_guid.cap
            [ -s "$legacy_capsule" ] || bbfatal "Missing $variant capsule for legacy GUID $legacy_guid: $legacy_capsule"
            install -m 0644 "$legacy_capsule" \
                "$bundle_dir/$machine-uefi-$variant-from-$legacy_guid.cap"
        done
    done

    printf '%s\n' \
        'CompuLab Edge-AI complete UEFI boot-firmware update capsules' \
        'Machines: ${EDGE_AI_UEFI_CAPSULE_MACHINES}' \
        'Payload L4T release: ${L4T_VERSION}' \
        'Firmware version: ${EDGE_AI_UEFI_CAPSULE_FW_VERSION}' \
        'Lowest supported version after update: ${EDGE_AI_UEFI_CAPSULE_LSV}' \
        'Current FMP image-type GUID: '"$reference_guid" \
        'Additional legacy FMP GUIDs: ${EDGE_AI_UEFI_LEGACY_FMP_GUIDS}' \
        'Accepted source TNSPEC: any (empty BUP image-entry TNSPEC)' \
        '' \
        'The updater selects a machine-specific capsule from the module board ID and SKU.' \
        'Every BUP is built for one exact module before its TNSPEC metadata is cleared.' \
        'Always use edge-ai-uefi-update so module board ID and SKU are checked before staging.' \
        'A -from-<GUID> capsule targets a device built with that custom legacy GUID.' \
        'Copy exactly one matching capsule and apply-uefi-capsule to the target.' \
        'The helper requires efibootmgr and setup-nv-boot-control.' \
        'Run: sudo ./apply-uefi-capsule <capsule-file>' \
        > "$bundle_dir/README.txt"

    (cd "$bundle_dir" && sha256sum -- *.cap > SHA256SUMS)
}

do_install() {
    assemble_capsule_bundle "${D}${EDGE_AI_UEFI_CAPSULE_INSTALL_DIR}"

    install -d ${D}${sbindir}
    sed -e 's,@CAPSULE_DIR@,${EDGE_AI_UEFI_CAPSULE_INSTALL_DIR},g' \
        ${S}/edge-ai-uefi-update > ${D}${sbindir}/edge-ai-uefi-update
    chmod 0755 ${D}${sbindir}/edge-ai-uefi-update
}

do_deploy() {
    bundle_dir=${DEPLOYDIR}/edge-ai-uefi-update-capsules
    rm -rf "$bundle_dir"
    install -d "$bundle_dir"
    cp -a ${D}${EDGE_AI_UEFI_CAPSULE_INSTALL_DIR}/. "$bundle_dir/"
    install -m 0755 ${D}${sbindir}/edge-ai-uefi-update "$bundle_dir/"
}

FILES:${PN} = " \
    ${EDGE_AI_UEFI_CAPSULE_INSTALL_DIR} \
    ${sbindir}/edge-ai-uefi-update \
"
RDEPENDS:${PN} = "busybox efibootmgr setup-nv-boot-control-service"
PACKAGE_ARCH = "${MACHINE_ARCH}"

# EDK2 records source/build paths in the firmware payload.  The capsule must
# remain byte-for-byte intact after it is generated, so it cannot be sanitized
# by the packaging task.
INSANE_SKIP:${PN} += "buildpaths"

addtask deploy after do_install before do_build
