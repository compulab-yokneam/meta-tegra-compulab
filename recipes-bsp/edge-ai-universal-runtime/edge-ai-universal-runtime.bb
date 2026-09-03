SUMMARY = "Runtime module detection for the CompuLab Edge-AI universal image"
LICENSE = "MIT"
LIC_FILES_CHKSUM = "file://${COMMON_LICENSE_DIR}/MIT;md5=0835ade698e0bcf8506ecda2f7b4f302"

SRC_URI = " \
    file://edge-ai-board-sku \
    file://edge-ai-machine-name \
    file://edge-ai-select-nvpmodel \
    file://10-edge-ai-universal.conf \
"

S = "${UNPACKDIR}"

COMPATIBLE_MACHINE = "(edge-ai)"
PACKAGE_ARCH = "${MACHINE_ARCH}"

do_install() {
    install -d ${D}${libexecdir}
    install -m 0755 ${S}/edge-ai-board-sku ${D}${libexecdir}/
    install -m 0755 ${S}/edge-ai-machine-name ${D}${libexecdir}/
    install -m 0755 ${S}/edge-ai-select-nvpmodel ${D}${libexecdir}/

    install -d ${D}${systemd_system_unitdir}/nvpmodel.service.d
    install -m 0644 ${S}/10-edge-ai-universal.conf \
        ${D}${systemd_system_unitdir}/nvpmodel.service.d/
}

FILES:${PN} = "${libexecdir} ${systemd_system_unitdir}/nvpmodel.service.d"
