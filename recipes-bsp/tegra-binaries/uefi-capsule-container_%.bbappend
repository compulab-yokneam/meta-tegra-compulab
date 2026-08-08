FILESEXTRAPATHS:prepend:edge-ai-nx := "${THISDIR}/${PN}:${THISDIR}/tegra-flashvars:"
FILESEXTRAPATHS:prepend:edge-ai-nano := "${THISDIR}/${PN}:${THISDIR}/tegra-flashvars:"

JETSON_BOARD_SPEC:edge-ai-nx-16g = "jetson_board_spec_edge_ai_nx_16g.cfg"
JETSON_BOARD_SPEC:edge-ai-nx-8g = "jetson_board_spec_edge_ai_nx_8g.cfg"
JETSON_BOARD_SPEC:edge-ai-nano-8g = "jetson_board_spec_edge_ai_nano_8g.cfg"
JETSON_BOARD_SPEC:edge-ai-nano-4g = "jetson_board_spec_edge_ai_nano_4g.cfg"
UEFI_CAPSULE:edge-ai-nx = "TEGRA_BL_Orin_NX.Cap.gz"
UEFI_CAPSULE:edge-ai-nano = "TEGRA_BL_Orin_Nano.Cap.gz"

EDGE_AI_CAPSULE_DTBS:edge-ai-nx-16g = "tegra234-p3768-0000+p3767-0000-nv.dtb tegra234-p3768-0000+p3767-0000-nv-super.dtb"
EDGE_AI_CAPSULE_DTBS:edge-ai-nx-8g = "tegra234-p3768-0000+p3767-0001-nv.dtb tegra234-p3768-0000+p3767-0001-nv-super.dtb"
EDGE_AI_CAPSULE_DTBS:edge-ai-nano-8g = "tegra234-p3768-0000+p3767-0003-nv.dtb tegra234-p3768-0000+p3767-0003-nv-super.dtb"
EDGE_AI_CAPSULE_DTBS:edge-ai-nano-4g = "tegra234-p3768-0000+p3767-0004-nv.dtb tegra234-p3768-0000+p3767-0004-nv-super.dtb"

EDGE_AI_CAPSULE_DTB_DEPENDS = ""
EDGE_AI_CAPSULE_DTB_DEPENDS:edge-ai-nx = "nvidia-kernel-oot-dtb:do_deploy"
EDGE_AI_CAPSULE_DTB_DEPENDS:edge-ai-nano = "nvidia-kernel-oot-dtb:do_deploy"
do_compile[depends] += "${EDGE_AI_CAPSULE_DTB_DEPENDS}"

SRC_URI:append:edge-ai-nx = " \
    file://tegra234-edge-ai-gpio-default.dtsi \
    file://tegra234-edge-ai-padvoltage-default.dtsi \
    file://tegra234-edge-ai-pinmux.dtsi \
    file://tegra234-edge-ai-mb2-bct-misc-p3767-0000.dts \
"

SRC_URI:append:edge-ai-nano = " \
    file://tegra234-edge-ai-gpio-default.dtsi \
    file://tegra234-edge-ai-padvoltage-default.dtsi \
    file://tegra234-edge-ai-pinmux.dtsi \
    file://tegra234-edge-ai-mb2-bct-misc-p3767-0000.dts \
"

do_compile:prepend:edge-ai-nx() {
    install -d ${B}
    install -d ${B}/edge-ai-dtbs
    install -m 0644 ${WORKDIR}/tegra234-edge-ai-gpio-default.dtsi ${B}/
    install -m 0644 ${WORKDIR}/tegra234-edge-ai-padvoltage-default.dtsi ${B}/
    install -m 0644 ${WORKDIR}/tegra234-edge-ai-pinmux.dtsi ${B}/
    install -m 0644 ${WORKDIR}/tegra234-edge-ai-mb2-bct-misc-p3767-0000.dts ${B}/
    for dtb in ${EDGE_AI_CAPSULE_DTBS}; do
        install -m 0644 ${DEPLOY_DIR_IMAGE}/devicetree/${dtb} ${B}/edge-ai-dtbs/
    done
}

do_compile:prepend:edge-ai-nano() {
    install -d ${B}
    install -d ${B}/edge-ai-dtbs
    install -m 0644 ${WORKDIR}/tegra234-edge-ai-gpio-default.dtsi ${B}/
    install -m 0644 ${WORKDIR}/tegra234-edge-ai-padvoltage-default.dtsi ${B}/
    install -m 0644 ${WORKDIR}/tegra234-edge-ai-pinmux.dtsi ${B}/
    install -m 0644 ${WORKDIR}/tegra234-edge-ai-mb2-bct-misc-p3767-0000.dts ${B}/
    for dtb in ${EDGE_AI_CAPSULE_DTBS}; do
        install -m 0644 ${DEPLOY_DIR_IMAGE}/devicetree/${dtb} ${B}/edge-ai-dtbs/
    done
}
