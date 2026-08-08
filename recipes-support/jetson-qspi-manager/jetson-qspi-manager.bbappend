# Edge-AI BUPs contain the NVIDIA Orin Nano compatibility aliases for both
# normal and Super modes. Use Super to match the UEFI platform configuration
# selected by the Edge-AI EDK2 build.
COMPAT_SPEC_NAME:edge-ai-nx-16g = "jetson-orin-nano-devkit-super"
COMPAT_SPEC_NAME:edge-ai-nx-8g = "jetson-orin-nano-devkit-super"
COMPAT_SPEC_NAME:edge-ai-nano-8g = "jetson-orin-nano-devkit-super"
COMPAT_SPEC_NAME:edge-ai-nano-4g = "jetson-orin-nano-devkit-super"

EDGE_AI_QSPI_CAPSULE:edge-ai-nx-16g = "TEGRA_BL_Orin_NX.Cap.gz"
EDGE_AI_QSPI_CAPSULE:edge-ai-nx-8g = "TEGRA_BL_Orin_NX.Cap.gz"
EDGE_AI_QSPI_CAPSULE:edge-ai-nano-8g = "TEGRA_BL_Orin_Nano.Cap.gz"
EDGE_AI_QSPI_CAPSULE:edge-ai-nano-4g = "TEGRA_BL_Orin_Nano.Cap.gz"

configure_edge_ai_qspi_manager() {
    # Do not let a second capsule installed by another package be selected by
    # the broad TEGRA_BL*.Cap.gz search in the common helper.
    sed -i \
        's#find / -xdev -type f -name "TEGRA_BL\*.Cap.gz"#find /opt/tegra-binaries -xdev -type f -name "${EDGE_AI_QSPI_CAPSULE}"#' \
        ${D}${libexecdir}/jetson-qspi-helpers
}

do_install:append:edge-ai-nx-16g() {
    configure_edge_ai_qspi_manager
}

do_install:append:edge-ai-nx-8g() {
    configure_edge_ai_qspi_manager
}

do_install:append:edge-ai-nano-8g() {
    configure_edge_ai_qspi_manager
}

do_install:append:edge-ai-nano-4g() {
    configure_edge_ai_qspi_manager
}
