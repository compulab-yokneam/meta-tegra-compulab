# Opt-in NX16G FRAMOS camera boot menu for a complete image rebuild.
# Includes the camera drivers, applications, tuning files and installed DTBs.
require conf/include/edge-ai-argus-framos-demo.inc

# Homogeneous profiles cover all four physical ports; unplugged inputs are
# optional. Select the profile matching the sensor model before changing it.
EDGE_AI_CAMERA_BOOT_DEFAULT ?= "camera-imx676"

# Mixed sensor identities are explicit, never automatically detected.
# Keep the existing port-0/port-1 layout by default; add port-2/port-3 leaves
# only when their sensor models are known. A configured empty input is valid.
# Mixed active models still require qualified embedded per-camera NITO data.
EDGE_AI_CAMERA_MIXED_OVERLAYS ?= " \
    edgedes-adi-v18-transport-4port.dtbo \
    edgedes-adi-v18-camera-imx676-port0.dtbo \
    edgedes-adi-v18-camera-imx678-port1.dtbo \
"

python __anonymous() {
    overrides = (d.getVar("OVERRIDES") or "").split(":")
    if (d.getVar("MACHINE") not in ("edge-ai-nx-16g", "edge-ai-nx") or
            "edge-ai-profile-build" in overrides):
        return

    # The universal runtime is built for NX16G, but its explicit camera DTBs
    # are not portable to the other modules. Keep module-specific flash-profile
    # builds unchanged, including the NX16G flash-profile multiconfig.
    labels = ["camera-imx676", "camera-imx678", "camera-mixed", "camera-uefi"]
    default = d.getVar("EDGE_AI_CAMERA_BOOT_DEFAULT")
    if default not in labels:
        bb.fatal("EDGE_AI_CAMERA_BOOT_DEFAULT must be one of: %s" % " ".join(labels))
    if (d.getVar("UBOOT_EXTLINUX_FDTOVERLAYS") or "").split():
        bb.fatal("The FRAMOS camera menu uses FDT_OVERLAYS, not "
                 "UBOOT_EXTLINUX_FDTOVERLAYS")
    mixed_overlays = (d.getVar("EDGE_AI_CAMERA_MIXED_OVERLAYS") or "").split()
    if (not mixed_overlays or
            mixed_overlays[0] != "edgedes-adi-v18-transport-4port.dtbo"):
        bb.fatal("EDGE_AI_CAMERA_MIXED_OVERLAYS must begin with "
                 "edgedes-adi-v18-transport-4port.dtbo")

    d.setVar("FDT_PER_ENTRY", "1")
    d.setVar("UBOOT_EXTLINUX_LABELS", " ".join(labels))
    d.setVar("UBOOT_EXTLINUX_DEFAULT_LABEL", default)
    if not d.getVar("UBOOT_EXTLINUX_TIMEOUT"):
        d.setVar("UBOOT_EXTLINUX_TIMEOUT", "50")
    # Camera DTBs belong to edgedes-adi-v18-devicetree, not this boot package.
    d.setVar("UBOOT_EXTLINUX_FDT", "")

    profiles = {
        "camera-imx676": (
            "IMX676 all ports (empty inputs allowed)",
            "edgedes-adi-v18-framos-imx676-4port.dtb", ""),
        "camera-imx678": (
            "IMX678 all ports (empty inputs allowed)",
            "edgedes-adi-v18-framos-imx678-4port.dtb", ""),
        "camera-mixed": (
            "Explicit mixed IMX676/IMX678 ports (experimental)",
            "tegra234-edge-ai-adi-base.dtb",
            " ".join(mixed_overlays)),
        "camera-uefi": (
            "UEFI-provided device tree (camera-profile fallback)", "", ""),
    }
    for label, (description, fdt, overlays) in profiles.items():
        d.setVar("UBOOT_EXTLINUX_MENU_DESCRIPTION:%s" % label, description)
        d.setVar("FDT_FILE:%s" % label, fdt)
        d.setVar("FDT_OVERLAYS:%s" % label, overlays)
}
