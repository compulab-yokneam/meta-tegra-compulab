# Build complete UEFI/boot-firmware capsule variants for the selected machine.
BBMULTICONFIG:append = " \
    edge-ai-uefi-nvidia-logo \
    edge-ai-uefi-clab-logo \
    edge-ai-uefi-no-logo \
    edge-ai-uefi-legacy-nvidia-logo \
    edge-ai-uefi-legacy-clab-logo \
    edge-ai-uefi-legacy-no-logo \
"
