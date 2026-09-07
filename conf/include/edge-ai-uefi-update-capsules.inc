# Build complete UEFI/boot-firmware capsule variants for every supported
# CompuLab Edge-AI module.  The resulting package selects the correct payload
# at runtime from the module board ID and SKU.
BBMULTICONFIG:append = " \
    edge-ai-uefi-nvidia-logo \
    edge-ai-uefi-clab-logo \
    edge-ai-uefi-no-logo \
    edge-ai-uefi-nx-8g-nvidia-logo \
    edge-ai-uefi-nx-8g-clab-logo \
    edge-ai-uefi-nx-8g-no-logo \
    edge-ai-uefi-nano-8g-nvidia-logo \
    edge-ai-uefi-nano-8g-clab-logo \
    edge-ai-uefi-nano-8g-no-logo \
    edge-ai-uefi-nano-4g-nvidia-logo \
    edge-ai-uefi-nano-4g-clab-logo \
    edge-ai-uefi-nano-4g-no-logo \
"
