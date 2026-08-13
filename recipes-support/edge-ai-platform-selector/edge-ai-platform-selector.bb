SUMMARY = "Select the Edge-AI module-specific device tree"
LICENSE = "Apache-2.0"
LIC_FILES_CHKSUM = "file://${BALENA_COREBASE}/COPYING.Apache-2.0;md5=89aea4e17d99a7cacdbeed46a0096b10"

SRC_URI = " \
    file://edge-ai-platform-selector \
    file://edge-ai-platform-selector.service \
"

S = "${WORKDIR}"

inherit allarch systemd

RDEPENDS:${PN} = "bash"
SYSTEMD_SERVICE:${PN} = "edge-ai-platform-selector.service"

EDGE_AI_PLATFORM_SKUS:edge-ai-nano = "0003 0004"
EDGE_AI_PLATFORM_SKUS:edge-ai-nx = "0000 0001"

do_compile[noexec] = "1"

do_install() {
    install -d ${D}${sbindir}
    install -m 0755 ${WORKDIR}/edge-ai-platform-selector ${D}${sbindir}/
    sed -i 's/@SUPPORTED_SKUS@/${EDGE_AI_PLATFORM_SKUS}/' \
        ${D}${sbindir}/edge-ai-platform-selector

    install -d ${D}${systemd_system_unitdir}
    install -m 0644 ${WORKDIR}/edge-ai-platform-selector.service \
        ${D}${systemd_system_unitdir}/
}
