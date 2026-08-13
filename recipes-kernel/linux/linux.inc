FILESEXTRAPATHS:prepend := "${THISDIR}/files:"

SRC_URI:append:edge-ai = " file://compulab.cfg"

COMPATIBLE_MACHINE := "^(edge-ai|${COMPATIBLE_MACHINE})"
