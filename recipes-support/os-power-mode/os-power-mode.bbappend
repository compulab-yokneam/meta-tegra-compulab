FILESEXTRAPATHS:prepend := "${THISDIR}/${PN}:"

SRC_URI:append:edgeai-orn = " \
    file://os-power-mode.patch \
    "
