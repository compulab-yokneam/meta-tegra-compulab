FILESEXTRAPATHS:prepend := "${THISDIR}/files:"

SRC_URI += "file://compulab.cfg"

do_deploy:append() {
    cp ${B}/.config ${DEPLOY_DIR_IMAGE}/config-${KERNEL_VERSION}
}
