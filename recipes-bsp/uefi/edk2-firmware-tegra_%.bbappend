FILESEXTRAPATHS:prepend := "${THISDIR}/${PN}:"

SRC_URI += "file://0001-compulab-Disable-DecreaseRootfsRetryCount.patch;patchdir=../edk2-nvidia"
SRC_URI += "file://0002-Add-clab-splash-logo.patch;patchdir=../edk2-nvidia"
SRC_URI += " \
    file://EdgeAI-ORN480.bmp \
    file://EdgeAI-ORN720.bmp \
    file://EdgeAI-ORN1080.bmp \
"

do_compile:prepend() {
	cp ${WORKDIR}/EdgeAI-ORN480.bmp  ${S}/../edk2-nvidia/Silicon/NVIDIA/Assets/clab/
	cp ${WORKDIR}/EdgeAI-ORN720.bmp  ${S}/../edk2-nvidia/Silicon/NVIDIA/Assets/clab/
	cp ${WORKDIR}/EdgeAI-ORN1080.bmp ${S}/../edk2-nvidia/Silicon/NVIDIA/Assets/clab/
}
