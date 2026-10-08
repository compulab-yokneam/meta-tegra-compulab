MACHINEOVERRIDES =. "edge-ai:"

# Relax /dev/mem access, allow PCI resource reassignment, and disable PCIe
# Active State Power Management for the Edge-AI PCIe topology.
KERNEL_ARGS:append = " iomem=relaxed pci=realloc pcie_aspm=off"

# Use the framebuffer exposed by the UEFI Graphics Output Protocol for tty1
# until the NVIDIA DRM driver takes over.  This is opt-in because NVIDIA's
# default Orin command line explicitly disables efifb.
KERNEL_ARGS:remove:early_tty1 = "video=efifb:off console=tty0"
KERNEL_ARGS:append:early_tty1 = " console=tty1 fbcon=nodefer"

# The removable WIC images use GRUB command lines rather than KERNEL_ARGS.
EDGE_AI_WIC_TTY1_ARGS ?= ""
EDGE_AI_WIC_TTY1_ARGS:early_tty1 = "console=tty1 fbcon=nodefer"

TEGRA_FLASHVAR_MB2BCT_CFG = "tegra234-edge-ai-mb2-bct-misc-p3767-0000.dts"
TEGRA_FLASHVAR_PINMUX_CONFIG = "tegra234-edge-ai-pinmux.dtsi"
TEGRA_FLASHVAR_PMC_CONFIG = "tegra234-edge-ai-padvoltage-default.dtsi"
ODMDATA = "gbe-uphy-config-9,hsstp-lane-map-3,hsio-uphy-config-0"

TNSPEC_BOOTDEV = "nvme0n1p1"
PARTITION_LAYOUT_TEMPLATE_DEFAULT = "flash_t234_qspi.xml"
PARTITION_LAYOUT_EXTERNAL_DEFAULT = "flash_l4t_t234_nvme.xml"
TEGRAFLASH_NO_INTERNAL_STORAGE = "0"

KERNEL_DEVICETREE:edge-ai:append = " \
    tegra234-p3768-0000+p3767-0000-nv-super.dtb \
    tegra234-p3768-0000+p3767-0001-nv-super.dtb \
    tegra234-p3768-0000+p3767-0003-nv-super.dtb \
    tegra234-p3768-0000+p3767-0004-nv-super.dtb \
    tegra234-p3768-0000+p3767-0005-nv-super.dtb \
"

PREFERRED_PROVIDER_virtual/kernel = "linux-yocto"
# An empty FDT_FILE preserves the normal UEFI-selected device tree.  Set it to
# a DTB basename to emit an explicit "FDT /boot/dtb/<name>" in extlinux.conf.
FDT_FILE ?= ""

# Keep the NX16G NVIDIA profile available as a known-good fallback even when
# UEFI supplies the active DTB and extlinux.conf has no explicit FDT line.
EDGE_AI_FALLBACK_FDT_FILE = "tegra234-p3768-0000+p3767-0000-nv-super.dtb"
L4T_UBOOT_EXTLINUX_EXTRA_FDTS:append = "${@'' if d.getVar('EDGE_AI_FALLBACK_FDT_FILE') in (d.getVar('UBOOT_EXTLINUX_FDT') or '').split() else ' ' + d.getVar('EDGE_AI_FALLBACK_FDT_FILE')}"

TEGRA_DEFAULT_KERNEL = "linux-yocto"

CORE_IMAGE_BASE_INSTALL:append = " \
    edge-ai-fdt-selector \
    nvidia-kernel-oot \
    nvidia-kernel-oot-extra \
    nvidia-kernel-oot-base \
    nvidia-kernel-oot-cameras \
    nvidia-kernel-oot-display \
    nvidia-kernel-oot-alsa \
    nvidia-kernel-oot-dtb \
    kernel-modules \
    linux-firmware-iwlwifi-misc	\
    linux-firmware-ibt-misc \
"

CORE_IMAGE_EXTRA_INSTALL:append = " \
    bluez5 \
    can-utils \
    nfs-utils \
    usbutils \
    net-tools \
    i2c-tools \
    libgpiod-tools \
    memtester \
    minicom \
    tmux \
    iotop \
    htop \
    iperf3 \
    firefox \
"

CORE_IMAGE_EXTRA_INSTALL:append:conflict = " \
    networkmanager \
    modemmanager \
"
