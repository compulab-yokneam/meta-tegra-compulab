FILESEXTRAPATHS:prepend := "${THISDIR}/${PN}:"

SRC_URI += "file://0001-compulab-Disable-DecreaseRootfsRetryCount.patch;patchdir=../edk2-nvidia"

def edge_ai_uefi_logo_style(d):
    overrides = (d.getVar("MACHINEOVERRIDES") or "").split(":")
    if "no_logo" in overrides:
        return "none"
    if "clab_logo" in overrides:
        return "clab"
    return "nvidia"

# Capsule multiconfigs set this explicitly so their contents do not depend on
# the logo override selected for the parent image in local.conf.
EDGE_AI_UEFI_LOGO_STYLE ?= "${@edge_ai_uefi_logo_style(d)}"

# The CompuLab boot-logo patch contains binary deltas and must be applied by
# git. Derive the patch tool from the effective style so capsule multiconfigs
# do not also need a matching MACHINEOVERRIDES entry.
PATCHTOOL = "${@'git' if d.getVar('EDGE_AI_UEFI_LOGO_STYLE') == 'clab' else 'quilt'}"
SRC_URI:append = "${@' file://0002-compulab-add-selectable-boot-logo.patch;patchdir=../edk2-nvidia file://clab-logo.cfg' if d.getVar('EDGE_AI_UEFI_LOGO_STYLE') == 'clab' else ' file://no-logo.cfg' if d.getVar('EDGE_AI_UEFI_LOGO_STYLE') == 'none' else ''}"

python make_no_logo_black_screen() {
    import os
    import struct

    if d.getVar("EDGE_AI_UEFI_LOGO_STYLE") != "none":
        return

    # Retain NVIDIA's standard LogoSingleBlack driver so the GOP and boot-info
    # overlay remain active, but replace its artwork in this isolated workdir
    # with a small all-black 16:9 bitmap. no-logo.cfg sets the scaling ratio
    # and center explicitly because the platform defconfig implies its normal
    # 40-percent logo-scaling selector.
    width = 16
    height = 9
    row_size = ((width * 3 + 3) // 4) * 4
    image_size = row_size * height
    file_size = 54 + image_size
    bitmap = bytearray(b"BM")
    bitmap.extend(struct.pack("<IHHI", file_size, 0, 0, 54))
    bitmap.extend(struct.pack("<IiiHHIIiiII", 40, width, height, 1, 24,
                              0, image_size, 2835, 2835, 0, 0))
    bitmap.extend(b"\x00" * image_size)

    logo = os.path.normpath(os.path.join(
        d.getVar("S"), "..", "edk2-nvidia", "Silicon", "NVIDIA", "Drivers",
        "Logo", "nvidiablack-1036x864.bmp"))
    if not os.path.isfile(logo):
        bb.fatal("NVIDIA single-logo bitmap is missing: %s" % logo)
    with open(logo, "wb") as stream:
        stream.write(bitmap)
}

do_configure[prefuncs] += "make_no_logo_black_screen"
