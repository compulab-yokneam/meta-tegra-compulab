FILESEXTRAPATHS:prepend := "${THISDIR}/files:"

SRC_URI += "file://compulab.cfg"

COMPATIBLE_MACHINE := "^(edge-ai-nx-16g|${COMPATIBLE_MACHINE})"
