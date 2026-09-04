SUMMARY = "One release bundle for all supported CompuLab Edge-AI P3767 modules"
LICENSE = "MIT"
LIC_FILES_CHKSUM = "file://${COMMON_LICENSE_DIR}/MIT;md5=0835ade698e0bcf8506ecda2f7b4f302"

SRC_URI = "file://flash-edge-ai.sh"
S = "${UNPACKDIR}"

inherit deploy

INHIBIT_DEFAULT_DEPS = "1"
do_compile[noexec] = "1"
do_install[noexec] = "1"

EDGE_AI_UNIVERSAL_IMAGE ?= "demo-image-weston"
EDGE_AI_FLASH_PROFILE_IMAGE ?= "edge-ai-flash-profile"
EDGE_AI_UNIVERSAL_MACHINES = "edge-ai-nx-16g edge-ai-nx-8g edge-ai-nano-8g edge-ai-nano-4g"
EDGE_AI_UNIVERSAL_RUNTIME_MC = "edge-ai-runtime"
EDGE_AI_UNIVERSAL_RUNTIME_MACHINE = "edge-ai-nx-16g"
EDGE_AI_UNIVERSAL_RUNTIME_DEPLOY_DIR = "${TOPDIR}/tmp-mc-${EDGE_AI_UNIVERSAL_RUNTIME_MC}/deploy/images/${EDGE_AI_UNIVERSAL_RUNTIME_MACHINE}"
EDGE_AI_UNIVERSAL_ROOTFS = "${EDGE_AI_UNIVERSAL_RUNTIME_DEPLOY_DIR}/${EDGE_AI_UNIVERSAL_IMAGE}-${EDGE_AI_UNIVERSAL_RUNTIME_MACHINE}.rootfs.ext4"
EDGE_AI_UNIVERSAL_BUNDLE_NAME = "${EDGE_AI_UNIVERSAL_IMAGE}-edge-ai-universal-${DISTRO_VERSION}"

do_deploy[depends] += "zstd-native:do_populate_sysroot"
do_deploy[mcdepends] += " \
    mc::edge-ai-runtime:${EDGE_AI_UNIVERSAL_IMAGE}:do_image_complete \
    mc::edge-ai-nx-16g:${EDGE_AI_FLASH_PROFILE_IMAGE}:do_image_complete \
    mc::edge-ai-nx-8g:${EDGE_AI_FLASH_PROFILE_IMAGE}:do_image_complete \
    mc::edge-ai-nano-8g:${EDGE_AI_FLASH_PROFILE_IMAGE}:do_image_complete \
    mc::edge-ai-nano-4g:${EDGE_AI_FLASH_PROFILE_IMAGE}:do_image_complete \
"

do_deploy() {
    bundle_dir=${B}/${EDGE_AI_UNIVERSAL_BUNDLE_NAME}
    rm -rf "$bundle_dir"
    install -d "$bundle_dir/runtime" "$bundle_dir/profiles"

    cp --reflink=auto --sparse=always "${EDGE_AI_UNIVERSAL_ROOTFS}" \
        "$bundle_dir/runtime/${EDGE_AI_UNIVERSAL_IMAGE}.ext4"
    install -m 0755 ${S}/flash-edge-ai.sh "$bundle_dir/flash-edge-ai.sh"

    for machine in ${EDGE_AI_UNIVERSAL_MACHINES}; do
        case "$machine" in
            edge-ai-nx-16g) expected_sku=0000 ;;
            edge-ai-nx-8g) expected_sku=0001 ;;
            edge-ai-nano-8g) expected_sku=0003 ;;
            edge-ai-nano-4g) expected_sku=0004 ;;
            *) bbfatal "Unknown Edge-AI profile: $machine" ;;
        esac
        profile_dir="$bundle_dir/profiles/$machine"
        archive="${TOPDIR}/tmp-mc-$machine/deploy/images/$machine/${EDGE_AI_FLASH_PROFILE_IMAGE}-$machine.rootfs.tegraflash-tar.zst"
        install -d "$profile_dir"
        tar --zstd -xf "$archive" -C "$profile_dir" \
            --exclude="${EDGE_AI_FLASH_PROFILE_IMAGE}.ext4"
        ln -s "../../runtime/${EDGE_AI_UNIVERSAL_IMAGE}.ext4" \
            "$profile_dir/${EDGE_AI_FLASH_PROFILE_IMAGE}.ext4"

        profile_sku=$(sed -n 's/^CHECK_BOARDSKU="\([0-9][0-9]*\)"/\1/p' \
            "$profile_dir/flashvars")
        [ "$profile_sku" = "$expected_sku" ] || \
            bbfatal "$machine has unexpected board SKU: $profile_sku"
        sed -i "s/^CHECK_BOARDSKU=.*/CHECK_BOARDSKU=\"\${CHECK_BOARDSKU-$expected_sku}\"/" \
            "$profile_dir/flashvars"
    done

    printf '%s\n' \
        'CompuLab Edge-AI universal release bundle' \
        'Shared runtime: ${EDGE_AI_UNIVERSAL_IMAGE}.ext4' \
        'Supported modules: P3767-0000, P3767-0001, P3767-0003, P3767-0004' \
        '' \
        'BOARD-INSTALLED NVME (default)' \
        '1. Power off the board and securely install a compatible NVMe.' \
        '2. Put the board in USB recovery mode and connect it to this Linux host.' \
        '3. Verify detection without writing anything:' \
        '     sudo ./flash-edge-ai.sh --detect-only' \
        '4. Erase and install the NVMe, and update matching QSPI boot firmware:' \
        '     sudo ./flash-edge-ai.sh' \
        '5. On success, power off, leave recovery mode, and boot from NVMe.' \
        '' \
        'The default uses initrd flashing to access nvme0n1 inside the board.' \
        'Do not pass a host /dev/nvme path. Do not interrupt power or USB.' \
        'To preserve compatible QSPI firmware and update only the board NVMe:' \
        '     sudo ./flash-edge-ai.sh -- --external-only' \
        'Failure logs are saved under profiles/<selected-machine>/log.initrd-flash.*' \
        '' \
        'HOST-CONNECTED MEDIA (explicit, destructive)' \
        '     sudo ./flash-edge-ai.sh --host-device /dev/sdX' \
        'Verify /dev/sdX carefully. Never select the host system disk.' \
        > "$bundle_dir/README.txt"

    install -d ${DEPLOYDIR}
    tar --sort=name --mtime="@${SOURCE_DATE_EPOCH}" --owner=0 --group=0 \
        --numeric-owner --sparse --zstd -C ${B} \
        -cf ${DEPLOYDIR}/${EDGE_AI_UNIVERSAL_BUNDLE_NAME}.tar.zst \
        ${EDGE_AI_UNIVERSAL_BUNDLE_NAME}
    (cd ${DEPLOYDIR} && \
        sha256sum ${EDGE_AI_UNIVERSAL_BUNDLE_NAME}.tar.zst \
        > ${EDGE_AI_UNIVERSAL_BUNDLE_NAME}.tar.zst.sha256)
}

addtask deploy after do_unpack before do_build
