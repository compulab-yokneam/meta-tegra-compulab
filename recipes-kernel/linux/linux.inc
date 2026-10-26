FILESEXTRAPATHS:prepend := "${THISDIR}/files:"

SRC_URI += "file://compulab.cfg"

inherit edge-ai-sdk-export

python edge_ai_sdk_export_kernel_task() {
    edge_ai_sdk_export_kernel(d)
}
do_deploy[postfuncs] += "edge_ai_sdk_export_kernel_task"

do_deploy:append() {
    install -m 0644 ${B}/.config ${DEPLOYDIR}/config-${KERNEL_VERSION}
}
