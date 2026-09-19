# The JP7 flasher can boot while QSPI still contains L4T r36 firmware.  Avoid
# pulling in every kernel module: tegra-dce from the r39 module set aborts when
# paired with the old display firmware and resets the board before flashing.
# Required EdgeAI storage and network modules are installed explicitly by the
# image recipe.
RDEPENDS:${PN}:remove:edgeai-orn = "kernel-modules"
