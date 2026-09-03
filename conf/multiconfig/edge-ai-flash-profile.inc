# Flash profiles build their own boot firmware, DTBs, BCTs and flash
# configuration. The bundle recipe replaces their empty rootfs placeholder
# with the filesystem produced by edge-ai-runtime.
TMPDIR = "${TOPDIR}/tmp-mc-${BB_CURRENT_MC}"
MACHINEOVERRIDES =. "edge-ai-profile-build:"

EDGE_AI_UNIVERSAL_IMAGE ?= "demo-image-weston"
EDGE_AI_FLASH_PROFILE_IMAGE ?= "edge-ai-flash-profile"
EDGE_AI_UNIVERSAL_RUNTIME_MC ?= "edge-ai-runtime"
EDGE_AI_UNIVERSAL_RUNTIME_MACHINE ?= "edge-ai-nx-16g"
EDGE_AI_UNIVERSAL_RUNTIME_DEPLOY_DIR = "${TOPDIR}/tmp-mc-${EDGE_AI_UNIVERSAL_RUNTIME_MC}/deploy/images/${EDGE_AI_UNIVERSAL_RUNTIME_MACHINE}"
EDGE_AI_UNIVERSAL_ROOTFS = "${EDGE_AI_UNIVERSAL_RUNTIME_DEPLOY_DIR}/${EDGE_AI_UNIVERSAL_IMAGE}-${EDGE_AI_UNIVERSAL_RUNTIME_MACHINE}.rootfs.ext4"
EDGE_AI_ROOTFS_PLACEHOLDER = "${WORKDIR}/edge-ai-rootfs-placeholder.ext4"

IMAGE_TEGRAFLASH_ROOTFS:edge-ai-profile-build = "${EDGE_AI_ROOTFS_PLACEHOLDER}"
IMAGE_TYPEDEP:tegraflash-tar:edge-ai-profile-build = ""
do_image_tegraflash_tar[mcdepends] += "mc::${EDGE_AI_UNIVERSAL_RUNTIME_MC}:${EDGE_AI_UNIVERSAL_IMAGE}:do_image_ext4"

edge_ai_create_rootfs_placeholder() {
    rm -f ${EDGE_AI_ROOTFS_PLACEHOLDER}
    touch ${EDGE_AI_ROOTFS_PLACEHOLDER}
}
do_image_tegraflash_tar[prefuncs] += "edge_ai_create_rootfs_placeholder"
