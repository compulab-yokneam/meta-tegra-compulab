# Build the shared Edge-AI runtime and the four module-specific flash profiles.
BBMULTICONFIG = "edge-ai-runtime edge-ai-nx-16g edge-ai-nx-8g edge-ai-nano-8g edge-ai-nano-4g"

# The shared runtime installs the universal UEFI capsule package, so enable
# every module/logo firmware multiconfig needed to assemble that package.
require conf/include/edge-ai-uefi-update-capsules.inc
