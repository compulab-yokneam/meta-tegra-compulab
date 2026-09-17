FILESEXTRAPATHS:prepend:edgeai-orn := "${THISDIR}/${PN}:"
S:edgeai-orn = "${UNPACKDIR}"
python __anonymous() {
    if "edgeai-orn" in (d.getVar("MACHINEOVERRIDES") or "").split(":"):
        d.delVarFlag("do_patch", "noexec")
        # Current allarch finalization resets PACKAGE_ARCH before anonymous code.
        d.setVar("PACKAGE_ARCH", d.getVar("MACHINE_ARCH"))
}
SRC_URI:append:edgeai-orn = " file://os-power-mode.patch"
