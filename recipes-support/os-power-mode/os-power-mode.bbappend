FILESEXTRAPATHS:prepend:edgeai-orn := "${THISDIR}/${PN}:"
S:edgeai-orn = "${UNPACKDIR}"
python __anonymous() {
    if "edgeai-orn" in (d.getVar("MACHINEOVERRIDES") or "").split(":"):
        d.delVarFlag("do_patch", "noexec")
        # This machine-specific patch makes the inherited allarch package vary
        # by machine.  Keep its package and sstate architectures aligned so a
        # Nano build cannot replace or remove the NX output, or vice versa.
        machine_arch = d.getVar("MACHINE_ARCH")
        d.setVar("PACKAGE_ARCH", machine_arch)
        d.setVar("SSTATE_PKGARCH", machine_arch)
}
SRC_URI:append:edgeai-orn = " file://os-power-mode.patch"
