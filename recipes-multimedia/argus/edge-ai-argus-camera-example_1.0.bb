SUMMARY = "CompuLab Edge-AI Argus and GStreamer camera examples"
DESCRIPTION = "Installs a serial-console-safe Argus GTK launcher with physical EDGEDES port selection and simultaneous tiled preview, plus a GStreamer launcher for live preview, MP4 recording and native JPEG capture by Argus sensor index."
LICENSE = "MIT"
LIC_FILES_CHKSUM = "file://${COMMON_LICENSE_DIR}/MIT;md5=0835ade698e0bcf8506ecda2f7b4f302"
PR = "r7"

SRC_URI = " \
    file://argus_camera.sh \
    file://gst_camera.sh \
"
S = "${UNPACKDIR}"

inherit allarch features_check

REQUIRED_DISTRO_FEATURES = "opengl wayland x11"

RDEPENDS:${PN} = " \
    argus-samples \
    gstreamer1.0 \
    gstreamer1.0-plugins-bad-videoparsersbad \
    gstreamer1.0-plugins-bad-waylandsink \
    gstreamer1.0-plugins-good-isomp4 \
    gstreamer1.0-plugins-good-multifile \
    gstreamer1.0-plugins-nvarguscamerasrc \
    gstreamer1.0-plugins-nvjpeg-nvjpeg \
    gstreamer1.0-plugins-nvvidconv \
    gstreamer1.0-plugins-nvvideo4linux2 \
    kmod \
    shadow-base \
    tegra-argus-daemon \
"

do_configure[noexec] = "1"
do_compile[noexec] = "1"

do_install() {
    install -d ${D}/opt/compulab/bin
    install -m 0755 ${S}/argus_camera.sh \
        ${D}/opt/compulab/bin/argus_camera.sh
    install -m 0755 ${S}/gst_camera.sh \
        ${D}/opt/compulab/bin/gst_camera.sh
}

FILES:${PN} = " \
    /opt/compulab/bin/argus_camera.sh \
    /opt/compulab/bin/gst_camera.sh \
"
