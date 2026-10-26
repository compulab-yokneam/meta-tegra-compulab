# SPDX-License-Identifier: MIT
# Export source data separately: never install Yocto development executables
# or dependencies into the NVIDIA Ubuntu rootfs.
inherit edge-ai-sdk-export

do_deploy() {
    :
}
python edge_ai_sdk_export_devsrc_task() {
    edge_ai_sdk_export_devsrc(d)
}
do_deploy[postfuncs] += "edge_ai_sdk_export_devsrc_task"
addtask deploy after do_install before do_build
