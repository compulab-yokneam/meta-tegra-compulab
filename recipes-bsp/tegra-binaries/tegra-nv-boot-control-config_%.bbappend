do_compile:edge-ai-nano-4gb() {
        cat > ${B}/nv_boot_control.conf <<EOF
TNSPEC 3767-300-0004-K.2-1-1-jetson-orin-nano-devkit-
COMPATIBLE_SPEC 3767--0005--1--jetson-orin-nano-devkit-
TEGRA_LEGACY_UPDATE true
TEGRA_BOOT_STORAGE nvme0n1
TEGRA_EMMC_ONLY false
TEGRA_CHIPID 0x23
TEGRA_OTA_BOOT_DEVICE /dev/mtdblock0
TEGRA_OTA_GPT_DEVICE /dev/mtdblock0
EOF
}

do_compile:edge-ai-nano-8gb() {
        cat > ${B}/nv_boot_control.conf <<EOF
TNSPEC 3767-300-0003-K.2-1-1-jetson-orin-nano-devkit-
COMPATIBLE_SPEC 3767--0005--1--jetson-orin-nano-devkit-
TEGRA_LEGACY_UPDATE true
TEGRA_BOOT_STORAGE nvme0n1
TEGRA_EMMC_ONLY false
TEGRA_CHIPID 0x23
TEGRA_OTA_BOOT_DEVICE /dev/mtdblock0
TEGRA_OTA_GPT_DEVICE /dev/mtdblock0
EOF

}

do_compile:edge-ai-nx-16g() {
        cat > ${B}/nv_boot_control.conf <<EOF
TNSPEC 3767-300-0000-A.3-1-1-jetson-orin-nx-devkit-
COMPATIBLE_SPEC 3767--0000--1--jetson-orin-nx-devkit-
TEGRA_LEGACY_UPDATE true
TEGRA_BOOT_STORAGE nvme0n1
TEGRA_EMMC_ONLY false
TEGRA_CHIPID 0x23
TEGRA_OTA_BOOT_DEVICE /dev/mtdblock0
TEGRA_OTA_GPT_DEVICE /dev/mtdblock0
EOF

}

do_compile:edge-ai-nx-8g() {
        cat > ${B}/nv_boot_control.conf <<EOF
TNSPEC 3767-300-0001-A.3-1-1-jetson-orin-nx-devkit-
COMPATIBLE_SPEC 3767--0001--1--jetson-orin-nx-devkit-
TEGRA_LEGACY_UPDATE true
TEGRA_BOOT_STORAGE nvme0n1
TEGRA_EMMC_ONLY false
TEGRA_CHIPID 0x23
TEGRA_OTA_BOOT_DEVICE /dev/mtdblock0
TEGRA_OTA_GPT_DEVICE /dev/mtdblock0
EOF
}
