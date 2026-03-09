FILESEXTRAPATHS:prepend := "${THISDIR}/${PN}:"

SRC_URI += "file://0001-compulab-Disable-DecreaseRootfsRetryCount.patch;patchdir=../edk2-nvidia"
SRC_URI += " \
    file://EdgeAI-ORN480.bmp \
    file://EdgeAI-ORN720.bmp \
    file://EdgeAI-ORN1080.bmp \
"

do_deploy_clab_logo() {
    cp ${WORKDIR}/sources/EdgeAI-ORN480.bmp  ${S}/../edk2-nvidia/Silicon/NVIDIA/Drivers/Logo/nvidiagray480.bmp
    cp ${WORKDIR}/sources/EdgeAI-ORN720.bmp  ${S}/../edk2-nvidia/Silicon/NVIDIA/Drivers/Logo/nvidiagray720.bmp
    cp ${WORKDIR}/sources/EdgeAI-ORN1080.bmp ${S}/../edk2-nvidia/Silicon/NVIDIA/Drivers/Logo/nvidiagray1080.bmp
}

do_compile:prepend() {
    do_deploy_clab_logo
}
