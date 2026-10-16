SUMMARY = "Demo-only uncalibrated FRAMOS IMX676/IMX678 NITO and Argus runtime"
DESCRIPTION = "Opt-in ISP migration baseline for one to four IMX676 or IMX678 cameras on Edge-AI NX16G, ADI v18 and NVIDIA R39.2.1. Automatic NITO selection uses a model-specific file for homogeneous connected cameras and experimental per-camera lookup for marked mixed profiles, which needs matching embedded identities. Not FRAMOS factory IQ tuning or a production camera profile."
HOMEPAGE = "https://developer.nvidia.com/embedded/jetpack/downloads/archive-7.2.1"

# The generated NITO contains parameters from NVIDIA's generic template.
# Do not relicense it as MIT/BSD or infer redistribution rights from demo use.
LICENSE = "LicenseRef-Proprietary"
LIC_FILES_CHKSUM = "file://Tegra_Software_License_Agreement-Tegra-Linux.txt;md5=376d20bd5275442226fcdf54e4844ddf"
LICENSE_FLAGS = "nvidia-argus-framos-demo"

inherit features_check l4t_version

# The full demo includes GTK/X11 samples as well as native Wayland GStreamer.
REQUIRED_DISTRO_FEATURES = "opengl systemd wayland x11"
COMPATIBLE_MACHINE = "^$"
COMPATIBLE_MACHINE:edge-ai-framos-argus-demo-profile = "^(edge-ai-nx-16g|edge-ai-nx)$"
PACKAGE_ARCH = "${MACHINE_ARCH}"
PR = "r10"

# Match the device-tree defaults independently for each sensor. IMX676 uses its
# tested extended profile by default; 0 retains the original native-mode NITO.
EDGE_AI_IMX676_EXTENDED_MODES ?= "1"
EDGE_AI_IMX678_EXTENDED_MODES ?= "0"

# Auto chooses from the models remaining after optional-link discovery. It
# keeps homogeneous cameras on their validated model-specific file, even in
# modular profiles, and permits mixed lookup only for marked modular DTs.
# Explicit single/per-camera values retain their previous policy semantics.
EDGE_AI_ARGUS_NITO_SELECTION ?= "auto"

SRC_URI = " \
    file://edgedes-imx676-demo.nito \
    file://edgedes-imx678-demo.nito \
    file://90-edgedes-framos-demo.conf.in \
    file://edge-ai-argus-framos-demo-check \
    file://PROVENANCE.txt \
    file://Tegra_Software_License_Agreement-Tegra-Linux.txt \
"
SRC_URI:append = " \
    ${@'file://edgedes-imx676-extended-demo.nito' if d.getVar('EDGE_AI_IMX676_EXTENDED_MODES') == '1' else ''} \
    ${@'file://edgedes-imx678-extended-demo.nito' if d.getVar('EDGE_AI_IMX678_EXTENDED_MODES') == '1' else ''} \
"
S = "${UNPACKDIR}"

RCONFLICTS:${PN} = "edge-ai-argus-imx678-demo"
RREPLACES:${PN} = "edge-ai-argus-imx678-demo"

RDEPENDS:${PN} = " \
    edgedes-adi-v18-devicetree \
    tegra-libraries-camera \
    tegra-argus-daemon \
    argus-samples \
    gstreamer1.0-plugins-nvarguscamerasrc \
    gstreamer1.0-plugins-nvvidconv \
    gstreamer1.0-plugins-bad-waylandsink \
    kmod \
    ${VIRTUAL-RUNTIME_base-utils} \
"

python __anonymous() {
    if d.getVar("EDGE_AI_IMX676_EXTENDED_MODES") not in ("0", "1"):
        bb.fatal("EDGE_AI_IMX676_EXTENDED_MODES must be 0 or 1")
    if d.getVar("EDGE_AI_IMX678_EXTENDED_MODES") not in ("0", "1"):
        bb.fatal("EDGE_AI_IMX678_EXTENDED_MODES must be 0 or 1")
    selection = d.getVar("EDGE_AI_ARGUS_NITO_SELECTION")
    if selection not in ("auto", "single", "per-camera"):
        bb.fatal("EDGE_AI_ARGUS_NITO_SELECTION must be 'auto', 'single' or 'per-camera'")
    if "edge-ai-framos-argus-demo-profile" not in (d.getVar("OVERRIDES") or "").split(":"):
        return
    if "adi-gmsl-v18" not in (d.getVar("OVERRIDES") or "").split(":"):
        raise bb.parse.SkipRecipe("FRAMOS Argus demo requires the ADI v18 profile")
    if d.getVar("L4T_VERSION") != "39.2.1":
        raise bb.parse.SkipRecipe("FRAMOS Argus demo is scoped to NVIDIA R39.2.1")
}

do_configure[noexec] = "1"
do_compile[noexec] = "1"

do_install() {
    # Pin the exact previous successful uncalibrated baseline, not factory tuning.
    # Each sensor needs its native mode metadata, not a different application.
    profile_sha256=$(sha256sum ${S}/edgedes-imx678-demo.nito)
    profile_sha256=${profile_sha256%% *}
    test "$profile_sha256" = "fbbe09af35b1fe561b2f0c0995cdd2b916915284bf770ce8500456fb186e5f2f" || \
        bbfatal "FRAMOS demo NITO does not match the previous validated baseline"
    profile_sha256=$(sha256sum ${S}/edgedes-imx676-demo.nito)
    profile_sha256=${profile_sha256%% *}
    test "$profile_sha256" = "61ddaf20d9a6d639fa34d3e368d0c7d86fc469b1602fa2c4f86d591d736d41e3" || \
        bbfatal "IMX676 demo NITO does not match its generated native mode profile"

    # Keep the original source/hash for rollback. Extended modes select their
    # own cumulative per-mode NITO, not a replacement daemon or global policy.
    imx676_profile=edgedes-imx676-demo.nito
    if [ "${EDGE_AI_IMX676_EXTENDED_MODES}" = "1" ]; then
        imx676_profile=edgedes-imx676-extended-demo.nito
        profile_sha256=$(sha256sum ${S}/$imx676_profile)
        profile_sha256=${profile_sha256%% *}
        test "$profile_sha256" = "6205cd7ef74335f26c81c4182a51d05994a8f93fc6d6a935d310c7514a97d16e" || \
            bbfatal "IMX676 extended demo NITO does not match its generated mode profile"
    fi

    imx678_profile=edgedes-imx678-demo.nito
    if [ "${EDGE_AI_IMX678_EXTENDED_MODES}" = "1" ]; then
        imx678_profile=edgedes-imx678-extended-demo.nito
        profile_sha256=$(sha256sum ${S}/$imx678_profile)
        profile_sha256=${profile_sha256%% *}
        test "$profile_sha256" = "b029ea2b6f15f0b323fe83b9e6aa31969141d520820ebbd9d8b6be7480bad7c3" || \
            bbfatal "IMX678 extended demo NITO does not match its generated mode profile"
    fi

    # Keep any legacy/vendor NITO intact; own only this separate demo filename.
    install -d ${D}${localstatedir}/nvidia/nvcam/settings
    install -m 0644 ${S}/$imx676_profile \
        ${D}${localstatedir}/nvidia/nvcam/settings/edgedes-imx676-demo.nito
    install -m 0644 ${S}/$imx678_profile \
        ${D}${localstatedir}/nvidia/nvcam/settings/edgedes-imx678-demo.nito

    install -d ${D}${libexecdir}
    sed -e 's|@LOCALSTATEDIR@|${localstatedir}|g' \
        -e 's|@NITO_SELECTION@|${EDGE_AI_ARGUS_NITO_SELECTION}|g' \
        ${S}/edge-ai-argus-framos-demo-check > ${D}${libexecdir}/edge-ai-argus-framos-demo-check
    chmod 0755 ${D}${libexecdir}/edge-ai-argus-framos-demo-check

    install -d ${D}${sysconfdir}/systemd/system/nvargus-daemon.service.d
    sed -e 's|@LIBEXECDIR@|${libexecdir}|g' \
        -e 's|@LOCALSTATEDIR@|${localstatedir}|g' \
        -e 's|@NITO_SELECTION@|${EDGE_AI_ARGUS_NITO_SELECTION}|g' \
        ${S}/90-edgedes-framos-demo.conf.in > \
        ${D}${sysconfdir}/systemd/system/nvargus-daemon.service.d/90-edgedes-framos-demo.conf

    # Ship the unchanged vendor agreement together with provenance in the main
    # package, rather than relying on an optional image-wide documentation flag.
    install -d ${D}${datadir}/${BPN}
    install -m 0644 ${S}/PROVENANCE.txt \
        ${S}/Tegra_Software_License_Agreement-Tegra-Linux.txt ${D}${datadir}/${BPN}/
}

FILES:${PN} = " \
    ${localstatedir}/nvidia/nvcam/settings/edgedes-imx676-demo.nito \
    ${localstatedir}/nvidia/nvcam/settings/edgedes-imx678-demo.nito \
    ${libexecdir}/edge-ai-argus-framos-demo-check \
    ${sysconfdir}/systemd/system/nvargus-daemon.service.d/90-edgedes-framos-demo.conf \
    ${datadir}/${BPN} \
"
CONFFILES:${PN} = "${sysconfdir}/systemd/system/nvargus-daemon.service.d/90-edgedes-framos-demo.conf"
