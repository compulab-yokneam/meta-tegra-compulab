FILESEXTRAPATHS:prepend := "${THISDIR}/files:"

SRC_URI:append:edge-ai = " file://compulab.cfg"

COMPATIBLE_MACHINE := "^(edge-ai-nx-16g|edge-ai-nx-8g|${COMPATIBLE_MACHINE})"
