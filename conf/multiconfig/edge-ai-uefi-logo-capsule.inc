# Every multiconfig must set MACHINE explicitly; BitBake does not inherit the
# parent configuration's weak MACHINE assignment.
EDGE_AI_UEFI_CAPSULE_MACHINE ?= "edge-ai-nx-16g"
MACHINE = "${EDGE_AI_UEFI_CAPSULE_MACHINE}"

# Keep each firmware variant in an isolated work/deploy directory.
TMPDIR = "${TOPDIR}/tmp-mc-${BB_CURRENT_MC}"
