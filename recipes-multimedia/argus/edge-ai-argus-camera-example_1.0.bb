SUMMARY = "CompuLab Edge-AI Argus camera launcher example"
DESCRIPTION = "Installs a serial-console-safe launcher for the Argus GTK camera sample in the Weston XWayland session."
LICENSE = "MIT"
LIC_FILES_CHKSUM = "file://${COMMON_LICENSE_DIR}/MIT;md5=0835ade698e0bcf8506ecda2f7b4f302"

SRC_URI = "file://argus_camera.sh"
S = "${UNPACKDIR}"

inherit allarch features_check

REQUIRED_DISTRO_FEATURES = "opengl wayland x11"

RDEPENDS:${PN} = " \
    argus-samples \
    kmod \
    shadow-base \
"

do_configure[noexec] = "1"
do_compile[noexec] = "1"

do_install() {
    install -d ${D}/opt/tcompulab/bin
    install -m 0755 ${S}/argus_camera.sh \
        ${D}/opt/tcompulab/bin/argus_camera.sh
}

FILES:${PN} = "/opt/tcompulab/bin/argus_camera.sh"
