FILESEXTRAPATHS:prepend:edgeai-orn := "${THISDIR}/${PN}:"

S:edgeai-orn = "${UNPACKDIR}"

python __anonymous() {
    if "edgeai-orn" in (d.getVar("MACHINEOVERRIDES") or "").split(":"):
        d.delVarFlag("do_patch", "noexec")
        # The upstream recipe inherits allarch, whose RecipePreFinalise handler
        # resets PACKAGE_ARCH before anonymous Python runs.  The installed
        # helper embeds a family-specific capsule filename, so both the output
        # package and its sstate manifests must use the machine architecture.
        # Updating only PACKAGE_ARCH leaves SSTATE_PKGARCH at "allarch" and
        # lets a later Nano/NX build remove the other machine's deployed IPK.
        machine_arch = d.getVar("MACHINE_ARCH")
        d.setVar("PACKAGE_ARCH", machine_arch)
        d.setVar("SSTATE_PKGARCH", machine_arch)
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
