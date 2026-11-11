SUMMARY = "Single-camera and composable multi-port EDGEDES device trees"
LICENSE = "GPL-2.0-only"
LIC_FILES_CHKSUM = "file://${COMMON_LICENSE_DIR}/GPL-2.0-only;md5=801f80980d171dd6425610833a22dbe6"
PR = "r10"

inherit tegra-devicetree

# Keep each sensor's advertised modes and per-mode NITO selection synchronized.
# IMX676 enables the tested extended set; set it to 0 for the native baseline.
# IMX678 remains opt-in and needs its own matching extended NITO profile.
EDGE_AI_IMX676_EXTENDED_MODES ?= "1"
EDGE_AI_IMX678_EXTENDED_MODES ?= "0"
DTC_PPFLAGS:append = " \
    ${@'-DEDGE_AI_IMX676_EXTENDED_MODES=1' if d.getVar('EDGE_AI_IMX676_EXTENDED_MODES') == '1' else ''} \
    ${@'-DEDGE_AI_IMX678_EXTENDED_MODES=1' if d.getVar('EDGE_AI_IMX678_EXTENDED_MODES') == '1' else ''} \
"

python __anonymous() {
    for sensor in ("IMX676", "IMX678"):
        variable = "EDGE_AI_%s_EXTENDED_MODES" % sensor
        if d.getVar(variable) not in ("0", "1"):
            bb.fatal("%s must be 0 or 1" % variable)
}

# These are additional test profiles, not a replacement virtual/dtb provider.
PROVIDES = ""
COMPATIBLE_MACHINE = "^$"
# Complete DTBs use the selected module base. Default to the family fallback.
EDGEAI_ORN_CAMERA_BASE_DTB ?= "${EDGE_AI_DEFAULT_DTB}"
COMPATIBLE_MACHINE:edgeai-orn = "^(edgeai-orn-nano|edgeai-orn-nx)$"
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
    file://edgedes-adi-v18-framos-imx678-mode-common.dtsi \
    file://edgedes-adi-v18-framos-imx678-modes.dtsi \
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
    file://edgedes-adi-v18-framos-imx676-mode-common.dtsi \
    file://edgedes-adi-v18-framos-imx676-modes.dtsi \
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

# Generate the neutral camera base for this family/module before preprocessing.
do_configure:append:edgeai-orn() {
    printf '// SPDX-License-Identifier: GPL-2.0-only\n#include "%s"\n' \
        '${@d.getVar("EDGEAI_ORN_CAMERA_BASE_DTB").removesuffix(".dtb")}.dts' \
        > ${UNPACKDIR}/tegra234-edge-ai-adi-base.dts
}

# Build module-specific camera profiles for both SKUs in each Balena family.
DT_FILES:append:edgeai-orn = " ${@' '.join('tegra234-edge-ai-adi-base-p3767-%s.dts' % sku for sku in d.getVar('EDGEAI_ORN_CAMERA_SKUS').split())}"
EDGE_AI_ADI_V18_COMPLETE_DTBS:append:edgeai-orn = " ${@' '.join('tegra234-edge-ai-adi-base-p3767-%s.dtb' % sku for sku in d.getVar('EDGEAI_ORN_CAMERA_SKUS').split())} ${@' '.join('edgedes-adi-v18-%s-p3767-%s.dtb' % (profile, sku) for sku in d.getVar('EDGEAI_ORN_CAMERA_SKUS').split() for profile in ['tevs-ar0144-port3'] + ['framos-%s-port%d' % (sensor, port) for sensor in ('imx676', 'imx678') for port in range(4)] + ['framos-%s-4port' % sensor for sensor in ('imx676', 'imx678')])}"

python edgeai_generate_camera_bases() {
    from pathlib import Path
    for sku in d.getVar('EDGEAI_ORN_CAMERA_SKUS').split():
        (Path(d.getVar('UNPACKDIR')) / ('tegra234-edge-ai-adi-base-p3767-%s.dts' % sku)).write_text(
            '// SPDX-License-Identifier: GPL-2.0-only\n#include "tegra234-p3768-0000+p3767-%s-nv-super.dts"\n' % sku)
}

python do_compile:append:edgeai-orn() {
    import itertools
    import subprocess
    import tempfile
    from pathlib import Path
    build = Path(d.getVar('B'))
    profiles = ['tevs-ar0144-port3'] + ['framos-%s-port%d' % (sensor, port)
                for sensor in ('imx676', 'imx678') for port in range(4)]
    for sku in d.getVar('EDGEAI_ORN_CAMERA_SKUS').split():
        base = build / ('tegra234-edge-ai-adi-base-p3767-%s.dtb' % sku)
        for profile in profiles:
            name = 'edgedes-adi-v18-' + profile
            subprocess.run(['fdtoverlay', '-i', str(base), '-o',
                            str(build / ('%s-p3767-%s.dtb' % (name, sku))),
                            str(build / (name + '-deserializer.dtbo')),
                            str(build / (name + '.dtbo'))], check=True)
        for sensor in ('imx676', 'imx678'):
            name = 'edgedes-adi-v18-framos-%s-4port' % sensor
            subprocess.run(['fdtoverlay', '-i', str(base), '-o',
                            str(build / ('%s-p3767-%s.dtb' % (name, sku))),
                            str(build / (name + '.dtbo'))], check=True)
        with tempfile.TemporaryDirectory(prefix='camera-%s-' % sku, dir=build) as check_dir:
            for sensors in itertools.product((None, 'imx676', 'imx678'), repeat=4):
                overlays = [build / 'edgedes-adi-v18-transport-4port.dtbo']
                overlays.extend(build / ('edgedes-adi-v18-camera-%s-port%d.dtbo' % (sensor, port))
                                for port, sensor in enumerate(sensors) if sensor)
                subprocess.run(['fdtoverlay', '-i', str(base), '-o',
                                str(Path(check_dir) / 'composed.dtb'),
                                *map(str, overlays)], check=True)
    bb.note('Validated all 81 modular camera configurations for each family SKU')
}

do_configure[prefuncs] += "edgeai_generate_camera_bases"
