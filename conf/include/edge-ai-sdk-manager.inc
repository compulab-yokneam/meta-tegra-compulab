# Standalone, explicitly privileged NVIDIA Ubuntu SDK generation.
# This is a host-side workflow, not a package for IMAGE_INSTALL.
EDGE_AI_SDK_EXPORTS = "1"
require conf/include/edge-ai-adi-gmsl-v18.inc
require conf/include/edge-ai-uefi-update-capsules.inc

# This include exports inputs but does not authorize host changes.
# Set both switches in local.conf only on a dedicated SDK build host.
EDGE_AI_SDK_ENABLE ?= "0"
EDGE_AI_SDK_ACCEPT_LICENSE ?= "0"
