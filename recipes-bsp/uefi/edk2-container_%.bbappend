DEFAULT_DTB:edge-ai-nx-16g = "tegra234-p3768-0000+p3767-0000-nv-super.dtb"
DEFAULT_DTB:edge-ai-nx-8g = "tegra234-p3768-0000+p3767-0001-nv-super.dtb"
EDGE_AI_NX_PATCH = "0001-Orin-NX-16GB-Integrate-with-balenaOS-on-L4T-36.5.patch"
DEFAULT_DTB:edge-ai-nano-8g = "tegra234-p3768-0000+p3767-0003-nv-super.dtb"
DEFAULT_DTB:edge-ai-nano-4g = "tegra234-p3768-0000+p3767-0004-nv-super.dtb"
EDGE_AI_NANO_PATCH = "0001-Orin-Nano-Integrate-with-balenaOS-on-L4T-36.5.patch"

do_compile:prepend:edge-ai-nx() {
    sed -i "/${MACHINE}/d;/declare -A device_specific_patches/a device_specific_patches[\"${MACHINE}\"]=\"${EDGE_AI_NX_PATCH}\"" ${WORKDIR}/build.sh
}

do_compile:prepend:edge-ai-nano() {
    sed -i "/${MACHINE}/d;/declare -A device_specific_patches/a device_specific_patches[\"${MACHINE}\"]=\"${EDGE_AI_NANO_PATCH}\"" ${WORKDIR}/build.sh
}
