# Family images do not know the installed module SKU at build time. Restore
# the runtime template used by setup-nv-boot-control so tegra-boardspec can
# populate the exact P3767 SKU after the first boot.
do_compile:edgeai-orn-family() {
        cat > ${B}/nv_boot_control.template <<EOF
TNSPEC @TNSPEC@
COMPATIBLE_SPEC @COMPATIBLE_SPEC@
TEGRA_LEGACY_UPDATE true
TEGRA_BOOT_STORAGE @BOOT_STORAGE@
TEGRA_EMMC_ONLY false
TEGRA_CHIPID 0x23
TEGRA_OTA_BOOT_DEVICE /dev/mtdblock0
TEGRA_OTA_GPT_DEVICE /dev/mtdblock0
EOF
}

do_install:edgeai-orn-family() {
        install -d ${D}${sysconfdir}
        install -m 0644 ${B}/nv_boot_control.template ${D}${sysconfdir}/
        ln -sf /run/nv_boot_control/nv_boot_control.conf \
                ${D}${sysconfdir}/nv_boot_control.conf
}
