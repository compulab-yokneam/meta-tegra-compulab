MACHINEOVERRIDES =. "edge-ai:"
TEGRA_FLASHVAR_MB2BCT_CFG = "tegra234-edge-ai-mb2-bct-misc-p3767-0000.dts"
TEGRA_FLASHVAR_PINMUX_CONFIG = "tegra234-edge-ai-pinmux.dtsi"
TEGRA_FLASHVAR_PMC_CONFIG = "tegra234-edge-ai-padvoltage-default.dtsi"

TNSPEC_BOOTDEV = "nvme0n1p1"
PARTITION_LAYOUT_TEMPLATE_DEFAULT = "flash_t234_qspi.xml"
PARTITION_LAYOUT_EXTERNAL_DEFAULT = "flash_l4t_t234_nvme.xml"
TEGRAFLASH_NO_INTERNAL_STORAGE = "0"

KERNEL_DEVICETREE:edge-ai:append = " \
    tegra234-p3768-0000+p3767-0000-nv-super.dtb \
    tegra234-p3768-0000+p3767-0000-nv-super-device.dtb \
    tegra234-p3768-0000+p3767-0000-nv-super-host.dtb \
    tegra234-p3768-0000+p3767-0001-nv-super.dtb \
    tegra234-p3768-0000+p3767-0001-nv-super-device.dtb \
    tegra234-p3768-0000+p3767-0001-nv-super-host.dtb \
    tegra234-p3768-0000+p3767-0003-nv-super.dtb \
    tegra234-p3768-0000+p3767-0003-nv-super-device.dtb \
    tegra234-p3768-0000+p3767-0003-nv-super-host.dtb \
    tegra234-p3768-0000+p3767-0004-nv-super.dtb \
    tegra234-p3768-0000+p3767-0004-nv-super-device.dtb \
    tegra234-p3768-0000+p3767-0004-nv-super-host.dtb \
    tegra234-p3768-0000+p3767-0005-nv-super.dtb \
    tegra234-p3768-0000+p3767-0005-nv-super-device.dtb \
    tegra234-p3768-0000+p3767-0005-nv-super-host.dtb \
"
