FILESEXTRAPATHS:prepend := "${THISDIR}/files:"

SRC_URI += "file://compulab.cfg"

do_deploy:append() {
    install -m 0644 ${B}/.config ${DEPLOYDIR}/config-${KERNEL_VERSION}
}
