SUMMARY = "Single-camera and composable multi-port EDGEDES device trees"
LICENSE = "GPL-2.0-only"
LIC_FILES_CHKSUM = "file://${COMMON_LICENSE_DIR}/GPL-2.0-only;md5=801f80980d171dd6425610833a22dbe6"
PR = "r6"

inherit tegra-devicetree

# These are additional test profiles, not a replacement virtual/dtb provider.
PROVIDES = ""
COMPATIBLE_MACHINE = "^$"
# Complete DTBs use the P3767-0000 base; other modules need their own base.
COMPATIBLE_MACHINE:adi-gmsl-v18 = "^(edge-ai-nx-16g|edge-ai-nx)$"
FILESEXTRAPATHS:prepend := "${THISDIR}/nvidia-kernel-oot:"
SRC_URI = " \
    file://tegra234-edge-ai-adi-base.dts \
    file://edgedes-adi-v18-transport-4port.dtso \
    file://edgedes-adi-v18-camera-imx676-port0.dtso \
    file://edgedes-adi-v18-camera-imx676-port1.dtso \
    file://edgedes-adi-v18-camera-imx676-port2.dtso \
    file://edgedes-adi-v18-camera-imx676-port3.dtso \
    file://edgedes-adi-v18-camera-imx678-port0.dtso \
    file://edgedes-adi-v18-camera-imx678-port1.dtso \
    file://edgedes-adi-v18-camera-imx678-port2.dtso \
    file://edgedes-adi-v18-camera-imx678-port3.dtso \
    file://edgedes-adi-v18-tevs-ar0144-port3-deserializer.dtso \
    file://edgedes-adi-v18-tevs-ar0144-port3.dtso \
    file://edgedes-adi-v18-framos-imx678-port0-deserializer.dtso \
    file://edgedes-adi-v18-framos-imx678-port0.dtso \
    file://edgedes-adi-v18-framos-imx678-port1-deserializer.dtso \
    file://edgedes-adi-v18-framos-imx678-port1.dtso \
    file://edgedes-adi-v18-framos-imx678-port2-deserializer.dtso \
    file://edgedes-adi-v18-framos-imx678-port2.dtso \
    file://edgedes-adi-v18-framos-imx678-port3-deserializer.dtso \
    file://edgedes-adi-v18-framos-imx678-port3.dtso \
    file://edgedes-adi-v18-framos-imx678-4port.dtso \
    file://edgedes-adi-v18-framos-imx678-4port-camera-platform.dtsi \
    file://edgedes-adi-v18-framos-imx678-mode.dtsi \
    file://edgedes-adi-v18-framos-imx678-port0.dtsi \
    file://edgedes-adi-v18-framos-imx678-port1.dtsi \
    file://edgedes-adi-v18-framos-imx678-port2.dtsi \
    file://edgedes-adi-v18-framos-imx678-port3.dtsi \
    file://edgedes-adi-v18-framos-4port-deserializer.dtsi \
    file://edgedes-adi-v18-framos-4port-nvcsi.dtsi \
    file://edgedes-adi-v18-framos-4port-vi.dtsi \
    file://edgedes-adi-v18-framos-imx676-port0-deserializer.dtso \
    file://edgedes-adi-v18-framos-imx676-port0.dtso \
    file://edgedes-adi-v18-framos-imx676-port1-deserializer.dtso \
    file://edgedes-adi-v18-framos-imx676-port1.dtso \
    file://edgedes-adi-v18-framos-imx676-port2-deserializer.dtso \
    file://edgedes-adi-v18-framos-imx676-port2.dtso \
    file://edgedes-adi-v18-framos-imx676-port3-deserializer.dtso \
    file://edgedes-adi-v18-framos-imx676-port3.dtso \
    file://edgedes-adi-v18-framos-imx676-4port.dtso \
    file://edgedes-adi-v18-framos-imx676-4port-deserializer.dtsi \
    file://edgedes-adi-v18-framos-imx676-4port-nvcsi.dtsi \
    file://edgedes-adi-v18-framos-imx676-4port-vi.dtsi \
    file://edgedes-adi-v18-framos-imx676-4port-camera-platform.dtsi \
    file://edgedes-adi-v18-framos-imx676-mode.dtsi \
    file://edgedes-adi-v18-framos-imx676-port0.dtsi \
    file://edgedes-adi-v18-framos-imx676-port1.dtsi \
    file://edgedes-adi-v18-framos-imx676-port2.dtsi \
    file://edgedes-adi-v18-framos-imx676-port3.dtsi \
"

S = "${UNPACKDIR}"
DT_FILES_PATH = "${UNPACKDIR}"
DT_FILES = " \
    tegra234-edge-ai-adi-base.dts \
    edgedes-adi-v18-transport-4port.dtso \
    edgedes-adi-v18-camera-imx676-port0.dtso \
    edgedes-adi-v18-camera-imx676-port1.dtso \
    edgedes-adi-v18-camera-imx676-port2.dtso \
    edgedes-adi-v18-camera-imx676-port3.dtso \
    edgedes-adi-v18-camera-imx678-port0.dtso \
    edgedes-adi-v18-camera-imx678-port1.dtso \
    edgedes-adi-v18-camera-imx678-port2.dtso \
    edgedes-adi-v18-camera-imx678-port3.dtso \
    edgedes-adi-v18-tevs-ar0144-port3-deserializer.dtso \
    edgedes-adi-v18-tevs-ar0144-port3.dtso \
    edgedes-adi-v18-framos-imx678-port0-deserializer.dtso \
    edgedes-adi-v18-framos-imx678-port0.dtso \
    edgedes-adi-v18-framos-imx678-port1-deserializer.dtso \
    edgedes-adi-v18-framos-imx678-port1.dtso \
    edgedes-adi-v18-framos-imx678-port2-deserializer.dtso \
    edgedes-adi-v18-framos-imx678-port2.dtso \
    edgedes-adi-v18-framos-imx678-port3-deserializer.dtso \
    edgedes-adi-v18-framos-imx678-port3.dtso \
    edgedes-adi-v18-framos-imx678-4port.dtso \
    edgedes-adi-v18-framos-imx676-port0-deserializer.dtso \
    edgedes-adi-v18-framos-imx676-port0.dtso \
    edgedes-adi-v18-framos-imx676-port1-deserializer.dtso \
    edgedes-adi-v18-framos-imx676-port1.dtso \
    edgedes-adi-v18-framos-imx676-port2-deserializer.dtso \
    edgedes-adi-v18-framos-imx676-port2.dtso \
    edgedes-adi-v18-framos-imx676-port3-deserializer.dtso \
    edgedes-adi-v18-framos-imx676-port3.dtso \
    edgedes-adi-v18-framos-imx676-4port.dtso \
"

EDGE_AI_ADI_V18_COMPLETE_DTBS = " \
    edgedes-adi-v18-tevs-ar0144-port3.dtb \
    edgedes-adi-v18-framos-imx678-port0.dtb \
    edgedes-adi-v18-framos-imx678-port1.dtb \
    edgedes-adi-v18-framos-imx678-port2.dtb \
    edgedes-adi-v18-framos-imx678-port3.dtb \
    edgedes-adi-v18-framos-imx678-4port.dtb \
    edgedes-adi-v18-framos-imx676-port0.dtb \
    edgedes-adi-v18-framos-imx676-port1.dtb \
    edgedes-adi-v18-framos-imx676-port2.dtb \
    edgedes-adi-v18-framos-imx676-port3.dtb \
    edgedes-adi-v18-framos-imx676-4port.dtb \
"

# Produce complete FDTs for extlinux as well as reusable DT overlays.
# The base comes from the same patched NVIDIA sources as the OOT modules.
python do_compile:append() {
    import itertools
    import os
    import subprocess
    import tempfile
    build = d.getVar("B")
    profiles = ["tevs-ar0144-port3"]
    for sensor in ("imx676", "imx678"):
        profiles.extend("framos-%s-port%d" % (sensor, port) for port in range(4))
    for profile in profiles:
        name = "edgedes-adi-v18-" + profile
        subprocess.run([
            "fdtoverlay", "-i", os.path.join(build, "tegra234-edge-ai-adi-base.dtb"),
            "-o", os.path.join(build, name + ".dtb"),
            os.path.join(build, name + "-deserializer.dtbo"),
            os.path.join(build, name + ".dtbo"),
        ], check=True)
    for sensor in ("imx676", "imx678"):
        multi = "edgedes-adi-v18-framos-%s-4port" % sensor
        subprocess.run([
            "fdtoverlay", "-i", os.path.join(build, "tegra234-edge-ai-adi-base.dtb"),
            "-o", os.path.join(build, multi + ".dtb"),
            os.path.join(build, multi + ".dtbo"),
        ], check=True)

    # Validate every empty/IMX676/IMX678 port combination with the same ordered
    # libfdt application used at boot. Do not install 81 redundant merged DTBs.
    with tempfile.TemporaryDirectory(prefix="modular-check-", dir=build) as check_dir:
        for sensors in itertools.product((None, "imx676", "imx678"), repeat=4):
            overlays = [os.path.join(build, "edgedes-adi-v18-transport-4port.dtbo")]
            overlays.extend(os.path.join(build, "edgedes-adi-v18-camera-%s-port%d.dtbo" %
                                         (sensor, port))
                            for port, sensor in enumerate(sensors) if sensor)
            subprocess.run([
                "fdtoverlay", "-i", os.path.join(build, "tegra234-edge-ai-adi-base.dtb"),
                "-o", os.path.join(check_dir, "composed.dtb"),
                *overlays,
            ], check=True)
    bb.note("Validated all 81 modular EDGEDES camera configurations")
}

# Keep the normal /boot/devicetree output from tegra-devicetree, and also put
# the complete, directly bootable EDGEDES profiles in the requested rootfs
# location. The neutral, symbol-enabled base is now selectable for OVERLAYS;
# reusable overlays remain separately owned here under /boot/devicetree.
do_sign_dtbs:append() {
    for dtbf in ${B}/*.dtb ${B}/*.dtbo; do
        [ -f "$dtbf" ] || continue
        tegra_uefi_split_sign "$dtbf"
    done
}

do_install:append() {
    install -d ${D}/boot/dtb
    for dtb in tegra234-edge-ai-adi-base.dtb ${EDGE_AI_ADI_V18_COMPLETE_DTBS}; do
        install -m 0644 ${B}/$dtb ${D}/boot/dtb/
        if ${TEGRA_UEFI_USE_SIGNED_FILES}; then
            install -m 0644 ${B}/$dtb.sig ${D}/boot/dtb/
        fi
    done
    # Detached signatures are what L4TLauncher expects for rootfs artifacts.
    # Do not accidentally package stale signatures from an unsigned build.
    if ${TEGRA_UEFI_USE_SIGNED_FILES}; then
        for signature in ${B}/*.dtb.sig ${B}/*.dtbo.sig; do
            [ -f "$signature" ] || continue
            install -m 0644 "$signature" ${D}/boot/devicetree/
        done
    fi
}

do_deploy:append() {
    if ${TEGRA_UEFI_USE_SIGNED_FILES}; then
        for signature in ${B}/*.dtb.sig ${B}/*.dtbo.sig; do
            [ -f "$signature" ] || continue
            install -m 0644 "$signature" ${DEPLOYDIR}/devicetree/
        done
    fi
}

FILES:${PN}:append = " /boot/dtb/*.dtb /boot/dtb/*.dtb.sig /boot/devicetree/*.dtb.sig /boot/devicetree/*.dtbo.sig"
