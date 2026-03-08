# Hack: The fetch task is disabled on this recipe, so the following is just for the task signature.
FILESEXTRAPATHS:prepend := "${THISDIR}/tegra-flashvars:"
SRC_URI:append:edge-ai = "\
    file://tegra234-edge-ai-gpio-default.dtsi \
    file://tegra234-edge-ai-padvoltage-default.dtsi \
    file://tegra234-edge-ai-pinmux.dtsi \
    file://tegra234-edge-ai-mb2-bct-misc-p3767-0000.dts \
"

# Hack: As the fetch task is disabled for this recipe, we have to directly access the files."
CUSTOM_DTSI_DIR := "${THISDIR}/tegra-flashvars"
do_install:append:edge-ai() {
    install -m 0644 ${CUSTOM_DTSI_DIR}/tegra234-edge-ai-gpio-default.dtsi ${D}${datadir}/tegraflash/
    install -m 0644 ${CUSTOM_DTSI_DIR}/tegra234-edge-ai-padvoltage-default.dtsi ${D}${datadir}/tegraflash/
    install -m 0644 ${CUSTOM_DTSI_DIR}/tegra234-edge-ai-pinmux.dtsi ${D}${datadir}/tegraflash/
    install -m 0644 ${CUSTOM_DTSI_DIR}/tegra234-edge-ai-mb2-bct-misc-p3767-0000.dts ${D}${datadir}/tegraflash/
    sed -i 's/\(enable_wdt =\).*;/\1 <1>;/g' ${D}${datadir}/tegraflash/tegra234-mb1-bct-misc-common.dtsi
}
