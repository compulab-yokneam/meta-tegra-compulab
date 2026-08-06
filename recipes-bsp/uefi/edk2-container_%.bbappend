# nx
# EDGEI_AI_NX_16G_PATCH = "0001-Orin-NX-16GB-Integrate-with-balenaOS-on-L4T-36.5.patch"
# nano
EDGEI_AI_NX_16G_PATCH = "0001-Orin-Nano-Integrate-with-balenaOS-on-L4T-36.5.patch"
do_compile:prepend () {
    sed -i "/edge-ai-nx-16g/d;/declare -A device_specific_patches/a device_specific_patches[\"edge-ai-nx-16g\"]=\"${EDGEI_AI_NX_16G_PATCH}\"" ${WORKDIR}/build.sh
}
