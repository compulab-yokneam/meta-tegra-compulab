DEVICE_SPECIFIC_SPACE:edgeai-orn-nx = "598016"
BALENA_BOOT_SIZE:edgeai-orn-nx = "121440"
IMAGE_ROOTFS_SIZE:edgeai-orn-nx = "733184"
PART_SPEC_FILE:edgeai-orn-nx = "partition_specification234_orin_nano.txt"
BALENA_STATE_SIZE:edgeai-orn-nx = "20480"

DEVICE_SPECIFIC_SPACE:edgeai-orn-nano = "598016"
BALENA_BOOT_SIZE:edgeai-orn-nano = "121440"
IMAGE_ROOTFS_SIZE:edgeai-orn-nano = "733184"
PART_SPEC_FILE:edgeai-orn-nano = "partition_specification234_orin_nano.txt"
BALENA_STATE_SIZE:edgeai-orn-nano = "20480"

# JetPack 7 ships both the Orin and Thor display stacks.  Use NVIDIA's
# platform-aware loader so the Orin modules are selected in dependency order;
# the generic balena loader attempts to load nvidia-drm directly.
IMAGE_INSTALL:append:edgeai-orn = " tegra-configs-display-driver"
IMAGE_INSTALL:remove:edgeai-orn = "nvidia-drm-loadconf"
