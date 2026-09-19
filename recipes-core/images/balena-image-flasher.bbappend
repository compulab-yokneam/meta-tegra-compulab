# QSPI on fielded EdgeAI systems can still contain the L4T r36 display
# firmware while the JP7 flasher boots an r39 kernel.  Loading tegra-dce in
# that mixed state aborts DCE firmware and resets the board before flashing or
# capsule preparation starts.  The flasher does not need display acceleration;
# keep it on the EFI framebuffer until the matching r39 capsule is installed.
IMAGE_INSTALL:remove:edgeai-orn = " \
    kernel-modules \
    nvidia-kernel-oot \
    nvidia-kernel-oot-display \
    nvidia-drm-loadconf \
"
