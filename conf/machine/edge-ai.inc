MACHINEOVERRIDES =. "edge-ai:"
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
TEGRA_DEFAULT_KERNEL = "linux-yocto"

CORE_IMAGE_BASE_INSTALL:append = " \
    nvidia-kernel-oot \
    nvidia-kernel-oot-extra \
    nvidia-kernel-oot-base \
    nvidia-kernel-oot-cameras \
    nvidia-kernel-oot-display \
    nvidia-kernel-oot-alsa \
    nvidia-kernel-oot-devicetrees \
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
