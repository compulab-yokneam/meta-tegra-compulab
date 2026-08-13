FILESEXTRAPATHS:prepend := "${THISDIR}/${PN}:"

SRC_URI:append:edgeai-orn = " \
    file://0001-jetson-qspi-helpers-Fix-prepared-capsule-path.patch \
    file://0002-jetson-qspi-helpers-Wait-for-QSPI-device.patch \
"

# Edge-AI BUPs contain the NVIDIA Orin Nano compatibility aliases for both
# normal and Super modes. Use Super to match the UEFI platform configuration
# selected by the Edge-AI EDK2 build.
COMPAT_SPEC_NAME:edgeai-orn-nano = "jetson-orin-nano-devkit-super"
COMPAT_SPEC_NAME:edgeai-orn-nx = "jetson-orin-nano-devkit-super"

EDGE_AI_QSPI_CAPSULE:edgeai-orn-nano = "TEGRA_BL_Orin_Nano.Cap.gz"
EDGE_AI_QSPI_CAPSULE:edgeai-orn-nx = "TEGRA_BL_Orin_NX.Cap.gz"

configure_edge_ai_qspi_manager() {
    # Do not let a second capsule installed by another package be selected by
    # the broad TEGRA_BL*.Cap.gz search in the common helper.
    sed -i \
        's#find / -xdev -type f -name "TEGRA_BL\*.Cap.gz"#find /opt/tegra-binaries -xdev -type f -name "${EDGE_AI_QSPI_CAPSULE}"#' \
        ${D}${libexecdir}/jetson-qspi-helpers
}

do_install:append:edgeai-orn() {
    configure_edge_ai_qspi_manager
}
