# Standalone Ubuntu packages with matched recipe-owned deploy inputs.
# This does not include edge-ai-sdk-manager or authorize SDK creation.
EDGE_AI_SDK_EXPORTS = "1"
require conf/include/edge-ai-adi-gmsl-v18.inc
require conf/include/edge-ai-uefi-update-capsules.inc
EDGE_AI_DEB_ENABLE ?= "0"
