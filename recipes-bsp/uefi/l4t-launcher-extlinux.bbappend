# Camera-profile DTBs are packaged by edgedes-adi-v18-devicetree.  Keep that
# package in compatible NX16G ADI images without making l4t-launcher-extlinux
# own the same files.  Other universal-bundle machines cannot build this DTB
# recipe and must continue using their module-specific UEFI-selected profile.
RDEPENDS:${PN}:append:edge-ai:adi-gmsl-v18 = " ${@'edgedes-adi-v18-devicetree' if d.getVar('MACHINE') in ('edge-ai-nx-16g', 'edge-ai-nx') else ''}"

# FDT_FILE is intentionally independent of UBOOT_EXTLINUX_FDT.  The latter
# makes l4t-launcher-extlinux copy and package the selected DTB, which would
# conflict with the EDGEDES package.  This hook changes only the boot entry.
# FDT_OVERLAYS likewise references separately packaged /boot/devicetree files.
# Opt in to label-specific FDT_FILE/FDT_OVERLAYS overrides with FDT_PER_ENTRY.
# In that mode an empty label-specific FDT_FILE deliberately selects UEFI.
FDT_PER_ENTRY ?= "0"

# Catch conflicting ownership before the base class rejects an empty FDT.
python do_create_extlinux_config:prepend:edge-ai() {
    if d.getVar("FDT_PER_ENTRY") == "1":
        labels = (d.getVar("UBOOT_EXTLINUX_LABELS") or "").split()
        localdata = bb.data.createCopy(d)
        keep_overrides = [value for value in
                          (d.getVar("OVERRIDES") or "").split(":")
                          if value not in labels]
        for label in labels:
            localdata.setVar("OVERRIDES", ":".join(keep_overrides + [label]))
            if ((localdata.getVar("FDT_OVERLAYS") or "").split() and
                    (localdata.getVar("UBOOT_EXTLINUX_FDTOVERLAYS") or "").split()):
                bb.fatal("Use either FDT_OVERLAYS or "
                         "UBOOT_EXTLINUX_FDTOVERLAYS, not both; "
                         "they use different file ownership and paths "
                         "(boot entry %s)" % label)
        return
    if ((d.getVar("FDT_OVERLAYS") or "").split() and
            (d.getVar("UBOOT_EXTLINUX_FDTOVERLAYS") or "").split()):
        bb.fatal("Use either FDT_OVERLAYS or UBOOT_EXTLINUX_FDTOVERLAYS, "
                 "not both; they use different file ownership and paths")
}

python do_create_extlinux_config:append:edge-ai() {
    import os
    import re

    if d.getVar("FDT_PER_ENTRY") == "1":
        labels = (d.getVar("UBOOT_EXTLINUX_LABELS") or "").split()
        if not labels or len(labels) != len(set(labels)):
            bb.fatal("FDT_PER_ENTRY requires unique UBOOT_EXTLINUX_LABELS")
        for label in labels:
            if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.+-]*", label):
                bb.fatal("FDT_PER_ENTRY requires safe boot labels: %s" % label)

        localdata = bb.data.createCopy(d)
        keep_overrides = [value for value in
                          (d.getVar("OVERRIDES") or "").split(":")
                          if value not in labels]
        profiles = {}
        for label in labels:
            localdata.setVar("OVERRIDES", ":".join(keep_overrides + [label]))
            fdt_file = (localdata.getVar("FDT_FILE") or "").strip()
            overlays = (localdata.getVar("FDT_OVERLAYS") or "").split()
            if not fdt_file and overlays:
                bb.fatal("FDT_OVERLAYS requires an explicit FDT_FILE base DTB "
                         "(boot entry %s)" % label)
            if fdt_file and (fdt_file != os.path.basename(fdt_file) or
                             not re.fullmatch(
                                 r"[A-Za-z0-9][A-Za-z0-9_.+-]*\.dtb", fdt_file)):
                bb.fatal("FDT_FILE must be a safe DTB basename "
                         "(boot entry %s)" % label)
            if (localdata.getVar("UBOOT_EXTLINUX_FDTOVERLAYS") or "").split():
                bb.fatal("FDT_PER_ENTRY uses package-owned FDT_FILE and "
                         "FDT_OVERLAYS, not UBOOT_EXTLINUX_FDTOVERLAYS "
                         "(boot entry %s)" % label)
            for overlay in overlays:
                if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.+-]*\.dtbo", overlay):
                    bb.fatal("FDT_OVERLAYS accepts safe DTBO basenames only; "
                             "invalid name: %s (boot entry %s)" % (overlay, label))
            if len(overlays) != len(set(overlays)):
                bb.fatal("FDT_OVERLAYS must not contain duplicate DTBO names "
                         "(boot entry %s)" % label)

            transport = "edgedes-adi-v18-transport-4port.dtbo"
            modular = any(name.startswith(("edgedes-adi-v18-camera-",
                                           "edgedes-adi-v18-transport-"))
                          for name in overlays)
            if modular:
                if d.getVar("MACHINE") not in ("edge-ai-nx-16g", "edge-ai-nx"):
                    bb.fatal("EDGEDES modular overlays require an Edge-AI "
                             "NX16G MACHINE: edge-ai-nx-16g or edge-ai-nx")
                if "adi-gmsl-v18" not in keep_overrides:
                    bb.fatal("EDGEDES modular overlays require adi-gmsl-v18 "
                             "in OVERRIDES")
                if overlays[0] != transport:
                    bb.fatal("EDGEDES camera overlays require %s first" % transport)
                if fdt_file != "tegra234-edge-ai-adi-base.dtb":
                    bb.fatal("EDGEDES modular overlays require "
                             "FDT_FILE = tegra234-edge-ai-adi-base.dtb")
                ports = set()
                for overlay in overlays[1:]:
                    match = re.fullmatch(
                        r"edgedes-adi-v18-camera-imx(676|678)-port([0-3])\.dtbo",
                        overlay)
                    if not match:
                        bb.fatal("EDGEDES transport supports only canonical "
                                 "IMX676/IMX678 port overlays, not %s" % overlay)
                    port = match.group(2)
                    if port in ports:
                        bb.fatal("Select only one camera model for EDGEDES "
                                 "physical port %s" % port)
                    ports.add(port)
            profiles[label] = (fdt_file, overlays)

        config_path = d.getVar("UBOOT_EXTLINUX_CONFIG")
        with open(config_path, "r", encoding="utf-8") as config_file:
            lines = config_file.read().rstrip("\n").splitlines()
        output = []
        seen = set()
        current = None
        kernels = {}
        for line in lines:
            words = line.lstrip().split(None, 1)
            directive = words[0] if words else ""
            if directive == "LABEL":
                current = words[1] if len(words) == 2 else ""
                if current not in profiles or current in seen:
                    bb.fatal("FDT_PER_ENTRY encountered an unexpected or "
                             "duplicate LABEL: %s" % current)
                seen.add(current)
                kernels[current] = 0
            if directive in ("FDT", "OVERLAYS"):
                if current is None:
                    bb.fatal("FDT_PER_ENTRY encountered FDT/OVERLAYS "
                             "outside a boot entry")
                continue
            output.append(line)
            if directive == "LINUX":
                if current is None:
                    bb.fatal("FDT_PER_ENTRY encountered LINUX outside a boot entry")
                kernels[current] += 1
                fdt_file, overlays = profiles[current]
                if fdt_file:
                    output.append("\tFDT %s/dtb/%s" % (
                        d.getVar("L4T_EXTLINUX_BASEDIR"), fdt_file))
                if overlays:
                    output.append("\tOVERLAYS " + ",".join(
                        "%s/devicetree/%s" % (d.getVar("L4T_EXTLINUX_BASEDIR"), name)
                        for name in overlays))
        if seen != set(labels) or any(count != 1 for count in kernels.values()):
            bb.fatal("FDT_PER_ENTRY requires one LABEL and one LINUX line "
                     "for every configured boot entry")
        config = "\n".join(output) + "\n"
        remainder = len(config) % 16
        if remainder:
            config += "\n" * (16 - remainder)
        with open(config_path, "w", encoding="utf-8") as config_file:
            config_file.write(config)
        return

    fdt_file = (d.getVar("FDT_FILE") or "").strip()
    overlays = (d.getVar("FDT_OVERLAYS") or "").split()
    if not fdt_file:
        if overlays:
            bb.fatal("FDT_OVERLAYS requires an explicit FDT_FILE base DTB")
        return

    if (fdt_file != os.path.basename(fdt_file) or
            not fdt_file.endswith(".dtb") or
            any(char.isspace() for char in fdt_file)):
        bb.fatal("FDT_FILE must be a DTB basename, for example "
                 "edgedes-adi-v18-framos-imx678-port0.dtb")

    if overlays:
        if (d.getVar("UBOOT_EXTLINUX_FDTOVERLAYS") or "").split():
            bb.fatal("Use either FDT_OVERLAYS or "
                     "UBOOT_EXTLINUX_FDTOVERLAYS, not both")
        for overlay in overlays:
            if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.+-]*\.dtbo", overlay):
                bb.fatal("FDT_OVERLAYS accepts safe DTBO basenames only; "
                         "invalid name: %s" % overlay)
        if len(overlays) != len(set(overlays)):
            bb.fatal("FDT_OVERLAYS must not contain duplicate DTBO names")

        transport = "edgedes-adi-v18-transport-4port.dtbo"
        camera_prefix = "edgedes-adi-v18-camera-"
        transport_prefix = "edgedes-adi-v18-transport-"
        modular = any(name.startswith((camera_prefix, transport_prefix))
                      for name in overlays)
        if modular:
            if d.getVar("MACHINE") not in ("edge-ai-nx-16g", "edge-ai-nx"):
                bb.fatal("EDGEDES modular overlays require an Edge-AI NX16G "
                         "MACHINE: edge-ai-nx-16g or edge-ai-nx")
            if "adi-gmsl-v18" not in (d.getVar("OVERRIDES") or "").split(":"):
                bb.fatal("EDGEDES modular overlays require adi-gmsl-v18 "
                         "in OVERRIDES")
            if overlays[0] != transport:
                bb.fatal("EDGEDES camera overlays require %s first" % transport)
            if fdt_file != "tegra234-edge-ai-adi-base.dtb":
                bb.fatal("EDGEDES modular overlays require "
                         "FDT_FILE = tegra234-edge-ai-adi-base.dtb")
            ports = set()
            for overlay in overlays[1:]:
                match = re.fullmatch(
                    r"edgedes-adi-v18-camera-imx(676|678)-port([0-3])\.dtbo",
                    overlay)
                if not match:
                    bb.fatal("EDGEDES transport supports only canonical "
                             "IMX676/IMX678 port overlays, not %s" % overlay)
                port = match.group(2)
                if port in ports:
                    bb.fatal("Select only one camera model for EDGEDES "
                             "physical port %s" % port)
                ports.add(port)

    config_path = d.getVar("UBOOT_EXTLINUX_CONFIG")
    with open(config_path, "r", encoding="utf-8") as config_file:
        lines = config_file.read().rstrip("\n").splitlines()

    fdt_line = "\tFDT %s/dtb/%s" % (
        d.getVar("L4T_EXTLINUX_BASEDIR"), fdt_file)
    if overlays:
        overlay_line = "\tOVERLAYS " + ",".join(
            "%s/devicetree/%s" % (d.getVar("L4T_EXTLINUX_BASEDIR"), name)
            for name in overlays)
        output = []
        entries = 0
        kernels = 0
        for line in lines:
            words = line.lstrip().split(None, 1)
            directive = words[0] if words else ""
            if directive == "LABEL":
                entries += 1
            if directive in ("FDT", "OVERLAYS"):
                continue
            output.append(line)
            if directive == "LINUX":
                kernels += 1
                output.extend((fdt_line, overlay_line))
        if not entries or entries != kernels:
            bb.fatal("FDT_OVERLAYS requires one LINUX line per boot entry")
    else:
        # Preserve existing FDT_FILE-only generation byte for byte.
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

do_create_extlinux_config[vardeps] += " \
    FDT_FILE FDT_OVERLAYS FDT_PER_ENTRY \
    UBOOT_EXTLINUX_LABELS UBOOT_EXTLINUX_DEFAULT_LABEL \
    UBOOT_EXTLINUX_FDTOVERLAYS L4T_EXTLINUX_BASEDIR \
    MACHINE OVERRIDES \
    ${@' '.join('%s:%s' % (variable, label) for label in (d.getVar('UBOOT_EXTLINUX_LABELS') or '').split() for variable in ('FDT_FILE', 'FDT_OVERLAYS', 'UBOOT_EXTLINUX_FDTOVERLAYS'))} \
"
