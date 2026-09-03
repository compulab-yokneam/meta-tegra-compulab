SUMMARY = "Minimal removable-media image for updating CompuLab Edge-AI UEFI"
DESCRIPTION = "Bootable WIC image containing complete UEFI capsules and only their runtime requirements"
LICENSE = "MIT"

# Keep this assignment independent of CORE_IMAGE_BASE_INSTALL and
# CORE_IMAGE_EXTRA_INSTALL, which intentionally contain the full product stack
# for the normal Edge-AI images.
IMAGE_INSTALL = " \
    base-files \
    base-passwd \
    busybox \
    netbase \
    shadow-base \
    systemd \
    update-alternatives-opkg \
    edge-ai-uefi-update-capsules \
"
IMAGE_FEATURES = "empty-root-password serial-autologin-root"
IMAGE_LINGUAS = ""
NO_RECOMMENDATIONS = "1"

IMAGE_FSTYPES = "wic.zst wic.bmap"
WKS_FILE = "edge-ai-uefi-update.wks.in"
WKS_FILE_DEPENDS_BOOTLOADERS = "grub-efi"
WKS_BOOT_SIZE ?= "128M"

IMAGE_EFI_BOOT_FILES = " \
    grub-efi-bootaa64.efi;EFI/BOOT/bootaa64.efi \
    Image;Image \
"
INITRAMFS_WKS_FSTYPE = "cpio.gz"

# Override the product image's large rootfs floor.  The normal 1.3 overhead
# factor plus this reserve leaves writable room for journals and diagnostics.
IMAGE_ROOTFS_SIZE = "98304"
IMAGE_ROOTFS_EXTRA_SPACE = "16384"

EDGE_AI_UEFI_CAPSULE_MACHINE ??= ""

python validate_uefi_update_image_machine() {
    image_machine = d.getVar("MACHINE")
    capsule_machine = d.getVar("EDGE_AI_UEFI_CAPSULE_MACHINE")

    if not capsule_machine:
        bb.fatal("edge-ai-uefi-update-image requires "
                 "EDGE_AI_UEFI_CAPSULE_MACHINE to be set explicitly")
    if capsule_machine != image_machine:
        bb.fatal("Refusing to put %s capsules in an image for %s" %
                 (capsule_machine, image_machine))
}
do_rootfs[prefuncs] += "validate_uefi_update_image_machine"

COMPATIBLE_MACHINE = "(edge-ai.*)"

inherit core-image
