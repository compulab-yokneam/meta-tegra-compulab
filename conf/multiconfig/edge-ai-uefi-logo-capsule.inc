# Every multiconfig must set MACHINE explicitly; BitBake does not inherit the
# parent configuration's weak MACHINE assignment.
EDGE_AI_UEFI_CAPSULE_MACHINE ?= "edge-ai-nx-16g"
MACHINE = "${EDGE_AI_UEFI_CAPSULE_MACHINE}"

# Standard R35/R36 Orin full-UEFI builds use the same image-type GUID as the
# R39 general configuration. Add only product-specific GUIDs used by older
# deployed firmware here; the capsule recipe emits one copy for each GUID.
EDGE_AI_UEFI_LEGACY_FMP_GUIDS ?= ""
TEGRA_UEFI_CAPSULE_ALT_IMAGE_TYPE_GUIDS = "${EDGE_AI_UEFI_LEGACY_FMP_GUIDS}"

# The default makes a major-version upgrade one-way. A lower value may be set
# explicitly when the product security policy must retain downgrade support.
EDGE_AI_UEFI_LOWEST_SUPPORTED_VERSION ?= ""
TEGRA_UEFI_LOWEST_SUPPORTED_VERSION = "${@d.getVar('EDGE_AI_UEFI_LOWEST_SUPPORTED_VERSION') or oe4t.uefi.get_hex_version(d.getVar('L4T_VERSION'))}"

# Keep each firmware variant in an isolated work/deploy directory.
TMPDIR = "${TOPDIR}/tmp-mc-${BB_CURRENT_MC}"
