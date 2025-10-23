INHERIT += "compulab-tools"
ROOTFS_POSTPROCESS_COMMAND:append = " compulab_extlinux"
ROOTFS_POSTPROCESS_COMMAND:append = " compulab_firmware"

IMAGE_FSTYPES = "wic.bmap wic.zst tar.zst"

CORE_IMAGE_EXTRA_INSTALL:append = "\
    kernel-modules \
    packagegroup-core-boot \
    packagegroup-core-full-cmdline \
"

# Build settings
IMAGE_INSTALL:append = " grub-efi "
IMAGE_INSTALL:append = " grub-bootconf "
IMAGE_INSTALL:append = " gptfdisk "

WKS_FILE = "efi-boot-bootpart.wks.in"
WKS_FILE_DEPENDS_BOOTLOADERS = "grub-efi"

WKS_BOOT_SIZE ?= "128M"

IMAGE_EFI_BOOT_FILES:append = " \
    grub-efi-bootaa64.efi;EFI/BOOT/bootaa64.efi \
    Image;Image \
"

INITRAMFS_WKS_FSTYPE = "cpio.gz"
