FILESEXTRAPATHS:prepend:edgeai-orn := "${THISDIR}/${PN}:"

SRC_URI:append:edgeai-orn = " \
    file://0001-compulab-Use-multiple-gray-boot-logos.patch;patchdir=../edk2-nvidia \
"
SRC_URI:append:edgeai-orn = " \
    file://EdgeAI-ORN480.bmp \
    file://EdgeAI-ORN720.bmp \
    file://EdgeAI-ORN1080.bmp \
"

do_deploy_clab_logo() {
    cp ${UNPACKDIR}/EdgeAI-ORN480.bmp  ${S_EDK2_NVIDIA}/Silicon/NVIDIA/Drivers/Logo/nvidiagray480.bmp
    cp ${UNPACKDIR}/EdgeAI-ORN720.bmp  ${S_EDK2_NVIDIA}/Silicon/NVIDIA/Drivers/Logo/nvidiagray720.bmp
    cp ${UNPACKDIR}/EdgeAI-ORN1080.bmp ${S_EDK2_NVIDIA}/Silicon/NVIDIA/Drivers/Logo/nvidiagray1080.bmp
}

do_compile:prepend:edgeai-orn() {
    do_deploy_clab_logo
}

# Both family images use the Orin Nano NVMe partition layout (rootA/rootB
# at 15/16), including NX modules. The Xavier NX patch uses 7/8.
DEFAULT_DTB:edgeai-orn-nano = "tegra234-p3768-0000+p3767-0004-nv-super.dtb"
DEFAULT_DTB:edgeai-orn-nx = "tegra234-p3768-0000+p3767-0001-nv-super.dtb"
SRC_URI:append:edgeai-orn = " file://0001-Orin-Nano-Integrate-with-balenaOS-on-L4T-39.2.0.patch;patchdir=../edk2-nvidia"
