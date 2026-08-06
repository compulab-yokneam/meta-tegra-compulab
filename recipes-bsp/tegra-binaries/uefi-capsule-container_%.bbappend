FILESEXTRAPATHS:prepend:edge-ai-nx-16g := "${THISDIR}/${PN}:${THISDIR}/tegra-flashvars:"
FILESEXTRAPATHS:prepend:edge-ai-nx-8g := "${THISDIR}/${PN}:${THISDIR}/tegra-flashvars:"
FILESEXTRAPATHS:prepend:edge-ai-nano-8g := "${THISDIR}/${PN}:${THISDIR}/tegra-flashvars:"

JETSON_BOARD_SPEC:edge-ai-nx-16g = "jetson_board_spec_edge_ai_nx_16g.cfg"
JETSON_BOARD_SPEC:edge-ai-nx-8g = "jetson_board_spec_edge_ai_nx_8g.cfg"
JETSON_BOARD_SPEC:edge-ai-nano-8g = "jetson_board_spec_edge_ai_nano_8g.cfg"
UEFI_CAPSULE:edge-ai-nx-16g = "TEGRA_BL_Orin_NX.Cap.gz"
UEFI_CAPSULE:edge-ai-nx-8g = "TEGRA_BL_Orin_NX.Cap.gz"
UEFI_CAPSULE:edge-ai-nano-8g = "TEGRA_BL_Orin_Nano.Cap.gz"

SRC_URI:append:edge-ai-nx-16g = " \
    file://tegra234-edge-ai-gpio-default.dtsi \
    file://tegra234-edge-ai-padvoltage-default.dtsi \
    file://tegra234-edge-ai-pinmux.dtsi \
    file://tegra234-edge-ai-mb2-bct-misc-p3767-0000.dts \
"

SRC_URI:append:edge-ai-nx-8g = " \
    file://tegra234-edge-ai-gpio-default.dtsi \
    file://tegra234-edge-ai-padvoltage-default.dtsi \
    file://tegra234-edge-ai-pinmux.dtsi \
    file://tegra234-edge-ai-mb2-bct-misc-p3767-0000.dts \
"

SRC_URI:append:edge-ai-nano-8g = " \
    file://tegra234-edge-ai-gpio-default.dtsi \
    file://tegra234-edge-ai-padvoltage-default.dtsi \
    file://tegra234-edge-ai-pinmux.dtsi \
    file://tegra234-edge-ai-mb2-bct-misc-p3767-0000.dts \
"

do_compile:prepend:edge-ai-nx-16g() {
    install -d ${B}
    install -m 0644 ${WORKDIR}/tegra234-edge-ai-gpio-default.dtsi ${B}/
    install -m 0644 ${WORKDIR}/tegra234-edge-ai-padvoltage-default.dtsi ${B}/
    install -m 0644 ${WORKDIR}/tegra234-edge-ai-pinmux.dtsi ${B}/
    install -m 0644 ${WORKDIR}/tegra234-edge-ai-mb2-bct-misc-p3767-0000.dts ${B}/
}

do_compile:prepend:edge-ai-nx-8g() {
    install -d ${B}
    install -m 0644 ${WORKDIR}/tegra234-edge-ai-gpio-default.dtsi ${B}/
    install -m 0644 ${WORKDIR}/tegra234-edge-ai-padvoltage-default.dtsi ${B}/
    install -m 0644 ${WORKDIR}/tegra234-edge-ai-pinmux.dtsi ${B}/
    install -m 0644 ${WORKDIR}/tegra234-edge-ai-mb2-bct-misc-p3767-0000.dts ${B}/
}

do_compile:prepend:edge-ai-nano-8g() {
    install -d ${B}
    install -m 0644 ${WORKDIR}/tegra234-edge-ai-gpio-default.dtsi ${B}/
    install -m 0644 ${WORKDIR}/tegra234-edge-ai-padvoltage-default.dtsi ${B}/
    install -m 0644 ${WORKDIR}/tegra234-edge-ai-pinmux.dtsi ${B}/
    install -m 0644 ${WORKDIR}/tegra234-edge-ai-mb2-bct-misc-p3767-0000.dts ${B}/
}
