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

EDGE_AI_UEFI_CAPSULE_MCS = "edge-ai-uefi-nvidia-logo edge-ai-uefi-clab-logo edge-ai-uefi-no-logo"
EDGE_AI_UEFI_LEGACY_CAPSULE_MCS = "edge-ai-uefi-legacy-nvidia-logo edge-ai-uefi-legacy-clab-logo edge-ai-uefi-legacy-no-logo"
EDGE_AI_UEFI_CAPSULE_MACHINE ?= "edge-ai-nx-16g"
EDGE_AI_UEFI_LEGACY_TNSPEC ?= "edge-ai"
EDGE_AI_UEFI_LEGACY_FMP_GUIDS ?= ""
EDGE_AI_UEFI_LOWEST_SUPPORTED_VERSION ?= ""
EDGE_AI_UEFI_CAPSULE_FW_VERSION = "${@oe4t.uefi.get_hex_version(d.getVar('L4T_VERSION'))}"
EDGE_AI_UEFI_CAPSULE_LSV = "${@d.getVar('EDGE_AI_UEFI_LOWEST_SUPPORTED_VERSION') or d.getVar('EDGE_AI_UEFI_CAPSULE_FW_VERSION')}"
EDGE_AI_UEFI_CAPSULE_DEPLOY_BASENAME = "${EDGE_AI_UEFI_CAPSULE_MACHINE}-tegra-bl.cap"
EDGE_AI_UEFI_LEGACY_CAPSULE_DEPLOY_BASENAME = "${EDGE_AI_UEFI_LEGACY_TNSPEC}-tegra-bl.cap"
EDGE_AI_UEFI_CAPSULE_INSTALL_DIR = "${datadir}/compulab/uefi-update-capsules"

do_install[depends] += "coreutils-native:do_populate_sysroot"
do_install[mcdepends] += " \
    mc::edge-ai-uefi-nvidia-logo:tegra-uefi-capsules:do_deploy \
    mc::edge-ai-uefi-clab-logo:tegra-uefi-capsules:do_deploy \
    mc::edge-ai-uefi-no-logo:tegra-uefi-capsules:do_deploy \
    mc::edge-ai-uefi-legacy-nvidia-logo:tegra-uefi-capsules:do_deploy \
    mc::edge-ai-uefi-legacy-clab-logo:tegra-uefi-capsules:do_deploy \
    mc::edge-ai-uefi-legacy-no-logo:tegra-uefi-capsules:do_deploy \
"

assemble_capsule_bundle() {
    bundle_dir="$1"
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

        for legacy_guid in ${EDGE_AI_UEFI_LEGACY_FMP_GUIDS}; do
            if [ "$legacy_guid" = "$reference_guid" ]; then
                bbfatal "Legacy FMP GUID duplicates the current GUID: $legacy_guid"
            fi

            legacy_capsule=$mc_deploy/${EDGE_AI_UEFI_CAPSULE_MACHINE}-tegra-bl-$legacy_guid.cap
            [ -s "$legacy_capsule" ] || bbfatal "Missing $variant capsule for legacy GUID $legacy_guid: $legacy_capsule"
            install -m 0644 "$legacy_capsule" \
                "$bundle_dir/${EDGE_AI_UEFI_CAPSULE_MACHINE}-uefi-$variant-from-$legacy_guid.cap"
        done
    done

    for mc in ${EDGE_AI_UEFI_LEGACY_CAPSULE_MCS}; do
        case "$mc" in
            edge-ai-uefi-legacy-nvidia-logo) variant=nvidia-logo ;;
            edge-ai-uefi-legacy-clab-logo) variant=clab-logo ;;
            edge-ai-uefi-legacy-no-logo) variant=no-logo ;;
            *) bbfatal "Unknown legacy UEFI capsule multiconfig: $mc" ;;
        esac

        mc_deploy=${TOPDIR}/tmp-mc-$mc/deploy/images/${EDGE_AI_UEFI_CAPSULE_MACHINE}
        capsule=$mc_deploy/${EDGE_AI_UEFI_LEGACY_CAPSULE_DEPLOY_BASENAME}
        guid_file=$mc_deploy/${TEGRA_FLASHVAR_UEFI_IMAGE}.fmp-image-type-id

        [ -s "$capsule" ] || bbfatal "Missing legacy-TNSPEC $variant capsule: $capsule"
        [ -s "$guid_file" ] || bbfatal "Missing legacy-TNSPEC $variant FMP image-type GUID: $guid_file"

        guid=$(cat "$guid_file")
        if [ "$guid" != "$reference_guid" ]; then
            bbfatal "FMP image-type GUID mismatch: legacy-TNSPEC $variant uses $guid, expected $reference_guid"
        fi

        install -m 0644 "$capsule" \
            "$bundle_dir/${EDGE_AI_UEFI_CAPSULE_MACHINE}-uefi-$variant-from-tnspec-${EDGE_AI_UEFI_LEGACY_TNSPEC}.cap"

        for legacy_guid in ${EDGE_AI_UEFI_LEGACY_FMP_GUIDS}; do
            legacy_capsule=$mc_deploy/${EDGE_AI_UEFI_LEGACY_TNSPEC}-tegra-bl-$legacy_guid.cap
            [ -s "$legacy_capsule" ] || bbfatal "Missing legacy-TNSPEC $variant capsule for legacy GUID $legacy_guid: $legacy_capsule"
            install -m 0644 "$legacy_capsule" \
                "$bundle_dir/${EDGE_AI_UEFI_CAPSULE_MACHINE}-uefi-$variant-from-tnspec-${EDGE_AI_UEFI_LEGACY_TNSPEC}-guid-$legacy_guid.cap"
        done
    done

    printf '%s\n' \
        'CompuLab Edge-AI complete UEFI boot-firmware update capsules' \
        'Machine: ${EDGE_AI_UEFI_CAPSULE_MACHINE}' \
        'Payload L4T release: ${L4T_VERSION}' \
        'Firmware version: ${EDGE_AI_UEFI_CAPSULE_FW_VERSION}' \
        'Lowest supported version after update: ${EDGE_AI_UEFI_CAPSULE_LSV}' \
        'Current FMP image-type GUID: '"$reference_guid" \
        'Additional legacy FMP GUIDs: ${EDGE_AI_UEFI_LEGACY_FMP_GUIDS}' \
        'Legacy platform TNSPEC target: ${EDGE_AI_UEFI_LEGACY_TNSPEC}' \
        '' \
        'Capsules without a -from- suffix target the current machine TNSPEC and standard Orin GUID.' \
        'A -from-tnspec-${EDGE_AI_UEFI_LEGACY_TNSPEC} capsule targets older firmware whose platform target is ${EDGE_AI_UEFI_LEGACY_TNSPEC}.' \
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
        -e 's,@MACHINE@,${EDGE_AI_UEFI_CAPSULE_MACHINE},g' \
        -e 's,@LEGACY_TNSPEC@,${EDGE_AI_UEFI_LEGACY_TNSPEC},g' \
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
