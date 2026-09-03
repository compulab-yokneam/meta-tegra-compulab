SUMMARY = "Tegra flash-profile carrier for the CompuLab Edge-AI universal bundle"
LICENSE = "MIT"
LIC_FILES_CHKSUM = "file://${COMMON_LICENSE_DIR}/MIT;md5=0835ade698e0bcf8506ecda2f7b4f302"

# The tegraflash task packages an empty rootfs placeholder. The bundle recipe
# replaces it with a link to the edge-ai-runtime image, avoiding four copies of
# a large Weston filesystem in the intermediate profile archives.
IMAGE_INSTALL = ""
IMAGE_LINGUAS = ""
IMAGE_FEATURES = ""
IMAGE_FSTYPES = "tegraflash-tar.zst"

inherit image
