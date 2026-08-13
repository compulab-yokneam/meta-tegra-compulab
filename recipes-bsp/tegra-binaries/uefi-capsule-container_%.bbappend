FILESEXTRAPATHS:prepend:edgeai-orn-nx := "${THISDIR}/${PN}:${THISDIR}/tegra-flashvars:"
FILESEXTRAPATHS:prepend:edgeai-orn-nano := "${THISDIR}/${PN}:${THISDIR}/tegra-flashvars:"

JETSON_BOARD_SPEC:edgeai-orn-nano = "jetson_board_spec_edge_ai_nano.cfg"
JETSON_BOARD_SPEC:edgeai-orn-nx = "jetson_board_spec_edge_ai_nx.cfg"
UEFI_CAPSULE:edgeai-orn-nx = "TEGRA_BL_Orin_NX.Cap.gz"
UEFI_CAPSULE:edgeai-orn-nano = "TEGRA_BL_Orin_Nano.Cap.gz"

EDGE_AI_CAPSULE_DTBS:edgeai-orn-nano = "tegra234-p3768-0000+p3767-0003-nv.dtb tegra234-p3768-0000+p3767-0003-nv-super.dtb tegra234-p3768-0000+p3767-0004-nv.dtb tegra234-p3768-0000+p3767-0004-nv-super.dtb"
EDGE_AI_CAPSULE_DTBS:edgeai-orn-nx = "tegra234-p3768-0000+p3767-0000-nv.dtb tegra234-p3768-0000+p3767-0000-nv-super.dtb tegra234-p3768-0000+p3767-0001-nv.dtb tegra234-p3768-0000+p3767-0001-nv-super.dtb"

EDGE_AI_CAPSULE_DTB_DEPENDS = ""
EDGE_AI_CAPSULE_DTB_DEPENDS:edgeai-orn-nx = "nvidia-kernel-oot-dtb:do_deploy"
EDGE_AI_CAPSULE_DTB_DEPENDS:edgeai-orn-nano = "nvidia-kernel-oot-dtb:do_deploy"
do_compile[depends] += "${EDGE_AI_CAPSULE_DTB_DEPENDS}"

SRC_URI:append:edgeai-orn-nx = " \
    file://tegra234-edgeai-orn-gpio-default.dtsi \
    file://tegra234-edgeai-orn-padvoltage-default.dtsi \
    file://tegra234-edgeai-orn-pinmux.dtsi \
    file://tegra234-edgeai-orn-mb2-bct-misc-p3767-0000.dts \
"

SRC_URI:append:edgeai-orn-nano = " \
    file://tegra234-edgeai-orn-gpio-default.dtsi \
    file://tegra234-edgeai-orn-padvoltage-default.dtsi \
    file://tegra234-edgeai-orn-pinmux.dtsi \
    file://tegra234-edgeai-orn-mb2-bct-misc-p3767-0000.dts \
"

do_compile:prepend:edgeai-orn-nx() {
    install -d ${B}
    install -d ${B}/edgeai-orn-dtbs
    install -m 0644 ${WORKDIR}/tegra234-edgeai-orn-gpio-default.dtsi ${B}/
    install -m 0644 ${WORKDIR}/tegra234-edgeai-orn-padvoltage-default.dtsi ${B}/
    install -m 0644 ${WORKDIR}/tegra234-edgeai-orn-pinmux.dtsi ${B}/
    install -m 0644 ${WORKDIR}/tegra234-edgeai-orn-mb2-bct-misc-p3767-0000.dts ${B}/
    for dtb in ${EDGE_AI_CAPSULE_DTBS}; do
        install -m 0644 ${DEPLOY_DIR_IMAGE}/devicetree/${dtb} ${B}/edgeai-orn-dtbs/
    done
}

do_compile:prepend:edgeai-orn-nano() {
    install -d ${B}
    install -d ${B}/edgeai-orn-dtbs
    install -m 0644 ${WORKDIR}/tegra234-edgeai-orn-gpio-default.dtsi ${B}/
    install -m 0644 ${WORKDIR}/tegra234-edgeai-orn-padvoltage-default.dtsi ${B}/
    install -m 0644 ${WORKDIR}/tegra234-edgeai-orn-pinmux.dtsi ${B}/
    install -m 0644 ${WORKDIR}/tegra234-edgeai-orn-mb2-bct-misc-p3767-0000.dts ${B}/
    for dtb in ${EDGE_AI_CAPSULE_DTBS}; do
        install -m 0644 ${DEPLOY_DIR_IMAGE}/devicetree/${dtb} ${B}/edgeai-orn-dtbs/
    done
}
