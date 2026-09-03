FILESEXTRAPATHS:prepend := "${THISDIR}/${PN}:"

SRC_URI += "file://0001-compulab-Disable-DecreaseRootfsRetryCount.patch;patchdir=../edk2-nvidia"

# Enable from conf/local.conf with: MACHINEOVERRIDES =. "clab_logo:"
# The boot-logo patch contains binary deltas and must be applied by git.
PATCHTOOL:clab_logo = "git"
SRC_URI:append:clab_logo = " file://0002-compulab-replace-NVIDIA-boot-logos.patch;patchdir=../edk2-nvidia"

# Enable from conf/local.conf with: MACHINEOVERRIDES =. "no_logo:"
SRC_URI:append:no_logo = " file://no-logo.cfg"

# Disabling the logo takes precedence if both overrides are present.
SRC_URI:remove:no_logo = "file://0002-compulab-replace-NVIDIA-boot-logos.patch;patchdir=../edk2-nvidia"
