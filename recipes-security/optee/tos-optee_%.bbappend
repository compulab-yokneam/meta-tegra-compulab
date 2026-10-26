# SPDX-License-Identifier: MIT
# Copyright (c) 2026 CompuLab Ltd.
EDGE_AI_SDK_FIRMWARE_ROLE = "tos"
require recipes-bsp/uefi/edge-ai-sdk-firmware-export.inc

# Make the exact MM input visible in this recipe's sysroot for match checks.
# Without the explicit opt-in, the original TOS dependency graph is unchanged.
DEPENDS:append:tegra234 = "${@' edk2-nvidia-standalone-mm' if d.getVar('EDGE_AI_SDK_EXPORTS') == '1' else ''}"
