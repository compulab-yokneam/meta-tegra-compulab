SUMMARY = "CompuLab Edge-AI IMX676/IMX678 extlinux configuration example"
DESCRIPTION = "Installs an inactive extlinux example with separate IMX676 and IMX678 camera boot entries. It does not replace the active extlinux.conf or enable camera drivers."
LICENSE = "MIT"
LIC_FILES_CHKSUM = "file://${COMMON_LICENSE_DIR}/MIT;md5=0835ade698e0bcf8506ecda2f7b4f302"

SRC_URI = "file://extlinux.conf.imx67x.sample"
S = "${UNPACKDIR}"

inherit allarch

do_configure[noexec] = "1"
do_compile[noexec] = "1"

do_install() {
    install -d ${D}/boot/extlinux
    install -m 0644 ${S}/extlinux.conf.imx67x.sample \
        ${D}/boot/extlinux/extlinux.conf.imx67x.sample
}

FILES:${PN} = "/boot/extlinux/extlinux.conf.imx67x.sample"
