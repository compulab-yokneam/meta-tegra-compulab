FILESEXTRAPATHS:prepend := "${THISDIR}/${PN}:"

# The boot-logo patch contains binary deltas and must be applied by git.
PATCHTOOL = "git"

SRC_URI += " \
    file://0001-compulab-Disable-DecreaseRootfsRetryCount.patch;patchdir=../edk2-nvidia \
    file://0002-compulab-replace-NVIDIA-boot-logos.patch;patchdir=../edk2-nvidia \
"
