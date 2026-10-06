SUMMARY = "Single-camera EDGEDES device trees for ADI v18 on Edge-AI"
LICENSE = "GPL-2.0-only"
LIC_FILES_CHKSUM = "file://${COMMON_LICENSE_DIR}/GPL-2.0-only;md5=801f80980d171dd6425610833a22dbe6"

inherit tegra-devicetree

# These are additional test profiles, not a replacement virtual/dtb provider.
PROVIDES = ""
COMPATIBLE_MACHINE = "^$"
# Complete DTBs use the P3767-0000 base; other modules need their own base.
COMPATIBLE_MACHINE:adi-gmsl-v18 = "^(edge-ai-nx-16g|edge-ai-nx)$"
FILESEXTRAPATHS:prepend := "${THISDIR}/nvidia-kernel-oot:"
SRC_URI = " \
    file://tegra234-edge-ai-adi-base.dts \
    file://edgedes-adi-v18-tevs-ar0144-port3.dtso \
    file://edgedes-adi-v18-framos-imx678-port0.dtso \
    file://edgedes-adi-v18-framos-imx676-port0.dtso \
"

S = "${UNPACKDIR}"
DT_FILES_PATH = "${UNPACKDIR}"
DT_FILES = " \
    tegra234-edge-ai-adi-base.dts \
    edgedes-adi-v18-tevs-ar0144-port3.dtso \
    edgedes-adi-v18-framos-imx678-port0.dtso \
    edgedes-adi-v18-framos-imx676-port0.dtso \
"

# Produce complete FDTs for extlinux as well as reusable DT overlays.
# The base comes from the same patched NVIDIA sources as the OOT modules.
python do_compile:append() {
    import os
    import subprocess
    build = d.getVar("B")
    for profile in ("tevs-ar0144-port3", "framos-imx678-port0", "framos-imx676-port0"):
        name = "edgedes-adi-v18-" + profile
        subprocess.run([
            "fdtoverlay", "-i", os.path.join(build, "tegra234-edge-ai-adi-base.dtb"),
            "-o", os.path.join(build, name + ".dtb"),
            os.path.join(build, name + ".dtbo"),
        ], check=True)
}
