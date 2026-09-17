FILESEXTRAPATHS:prepend:edgeai-orn := "${THISDIR}/${PN}:"

S:edgeai-orn = "${UNPACKDIR}"
python __anonymous() {
    if "edgeai-orn" in (d.getVar("MACHINEOVERRIDES") or "").split(":"):
        d.delVarFlag("do_patch", "noexec")
        # Current allarch finalization resets PACKAGE_ARCH before anonymous code.
        d.setVar("PACKAGE_ARCH", d.getVar("MACHINE_ARCH"))
}
SRC_URI:append:edgeai-orn = " file://0001-jetson-qspi-helpers-Fix-prepared-capsule-path.patch"

# Match the normal/Super aliases contained in the combined family BUP.
COMPAT_SPEC_NAME:edgeai-orn = "jetson-orin-nano-devkit-super"
EDGE_AI_QSPI_CAPSULE:edgeai-orn-nano = "TEGRA_BL_Orin_Nano.Cap.gz"
EDGE_AI_QSPI_CAPSULE:edgeai-orn-nx = "TEGRA_BL_Orin_NX.Cap.gz"

do_install:append:edgeai-orn() {
    # Keep the target's /tmp migration search and rootfs fallback, selecting
    # only this family's capsule if another package supplies a second capsule.
    sed -i 's/"TEGRA_BL\*.Cap.gz"/"${EDGE_AI_QSPI_CAPSULE}"/g' \
        ${D}${libexecdir}/jetson-qspi-helpers
}
