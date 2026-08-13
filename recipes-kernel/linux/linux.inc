FILESEXTRAPATHS:prepend := "${THISDIR}/files:"

SRC_URI:append:edgeai-orn = " file://compulab.cfg"

COMPATIBLE_MACHINE := "^(edgeai-orn|${COMPATIBLE_MACHINE})"
