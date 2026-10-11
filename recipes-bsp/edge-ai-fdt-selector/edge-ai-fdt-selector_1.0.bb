SUMMARY = "Interactive extlinux device-tree selector for Edge-AI"
LICENSE = "MIT"
LIC_FILES_CHKSUM = "file://${COMMON_LICENSE_DIR}/MIT;md5=0835ade698e0bcf8506ecda2f7b4f302"

SRC_URI = "file://edge-ai-select-fdt"
S = "${UNPACKDIR}"

inherit allarch

RDEPENDS:${PN} = "${VIRTUAL-RUNTIME_base-utils}"

do_configure[noexec] = "1"
do_compile[noexec] = "1"

do_install() {
    install -d ${D}${sbindir}
    install -m 0755 ${S}/edge-ai-select-fdt ${D}${sbindir}/edge-ai-select-fdt
}
