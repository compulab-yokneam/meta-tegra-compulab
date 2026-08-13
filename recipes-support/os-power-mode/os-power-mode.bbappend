FILESEXTRAPATHS:prepend := "${THISDIR}/${PN}:"

SRC_URI:append:edge-ai = " \
    file://os-power-mode.patch \
    "
