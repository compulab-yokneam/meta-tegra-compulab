# Camera-profile DTBs are packaged by edgedes-adi-v18-devicetree.  Keep that
# package in compatible NX16G ADI images without making l4t-launcher-extlinux
# own the same files.  Other universal-bundle machines cannot build this DTB
# recipe and must continue using their module-specific UEFI-selected profile.
RDEPENDS:${PN}:append:edge-ai:adi-gmsl-v18 = " ${@'edgedes-adi-v18-devicetree' if d.getVar('MACHINE') in ('edge-ai-nx-16g', 'edge-ai-nx') else ''}"

# FDT_FILE is intentionally independent of UBOOT_EXTLINUX_FDT.  The latter
# makes l4t-launcher-extlinux copy and package the selected DTB, which would
# conflict with the EDGEDES package.  This hook changes only the boot entry.
python do_create_extlinux_config:append:edge-ai() {
    import os

    fdt_file = (d.getVar("FDT_FILE") or "").strip()
    if not fdt_file:
        return

    if (fdt_file != os.path.basename(fdt_file) or
            not fdt_file.endswith(".dtb") or
            any(char.isspace() for char in fdt_file)):
        bb.fatal("FDT_FILE must be a DTB basename, for example "
                 "edgedes-adi-v18-framos-imx678-port0.dtb")

    config_path = d.getVar("UBOOT_EXTLINUX_CONFIG")
    with open(config_path, "r", encoding="utf-8") as config_file:
        lines = config_file.read().rstrip("\n").splitlines()

    fdt_line = "\tFDT %s/dtb/%s" % (
        d.getVar("L4T_EXTLINUX_BASEDIR"), fdt_file)
    has_fdt = any(line.startswith("\tFDT ") for line in lines)

    output = []
    for line in lines:
        if line.startswith("\tFDT "):
            output.append(fdt_line)
        else:
            output.append(line)
            if not has_fdt and line.startswith("\tLINUX "):
                output.append(fdt_line)

    config = "\n".join(output) + "\n"
    remainder = len(config) % 16
    if remainder:
        config += "\n" * (16 - remainder)

    with open(config_path, "w", encoding="utf-8") as config_file:
        config_file.write(config)
}

do_create_extlinux_config[vardeps] += "FDT_FILE"
