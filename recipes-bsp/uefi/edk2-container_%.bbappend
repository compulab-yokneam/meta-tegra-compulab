FILESEXTRAPATHS:prepend:edgeai-orn := "${THISDIR}/${PN}:"

EDGE_AI_NX_PATCH = "0001-Orin-NX-16GB-Integrate-with-balenaOS-on-L4T-36.5.patch"
DEFAULT_DTB:edgeai-orn-nano = "tegra234-p3768-0000+p3767-0004-nv-super.dtb"
DEFAULT_DTB:edgeai-orn-nx = "tegra234-p3768-0000+p3767-0001-nv-super.dtb"
EDGE_AI_NANO_PATCH = "0001-Orin-Nano-Integrate-with-balenaOS-on-L4T-36.5.patch"

SRC_URI:append:edgeai-orn = " \
    file://0001-Logo-Add-CompuLab-Edge-AI-splash-screens_patch.txt \
    file://0001-build-Apply-Edge-AI-logo-as-a-Git-commit.patch \
"

do_compile:prepend:edgeai-orn-nx() {
    sed -i "/${MACHINE}/d;/declare -A device_specific_patches/a device_specific_patches[\"${MACHINE}\"]=\"${EDGE_AI_NX_PATCH}\"" ${WORKDIR}/build.sh
}

do_compile:prepend:edgeai-orn-nano() {
    sed -i "/${MACHINE}/d;/declare -A device_specific_patches/a device_specific_patches[\"${MACHINE}\"]=\"${EDGE_AI_NANO_PATCH}\"" ${WORKDIR}/build.sh
}
