LICENSE = "CLOSED"
# LIC_FILES_CHKSUM = "file://README.md;md5=c62d3d893a676f537385ba87ff045a30"

PV = "36.4.4"

inherit l4t_bsp
SS = "${L4T_BSP_SHARED_SOURCE_DIR}"

SRC_URI:append = "\
    file://tegra234-mb1-bct-pinmux-p3767-hdmi-a03.dtsi \
    file://tegra234-mb2-bct-misc-p3767-0000.dts \
    file://README.md \
"

do_install_compulab() {
    cp ${WORKDIR}/tegra234-mb1-bct-pinmux-p3767-hdmi-a03.dtsi ${SS}/bootloader/generic/BCT/
    cp ${WORKDIR}/tegra234-mb2-bct-misc-p3767-0000.dts ${SS}/bootloader/generic/BCT/
}

addtask do_install_compulab
