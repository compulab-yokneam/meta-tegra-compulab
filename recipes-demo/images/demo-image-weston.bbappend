# Match meta-tegrademo's demo-image-docker-minimal.inc.
REQUIRED_DISTRO_FEATURES:append = " virtualization"
IMAGE_FEATURES += "container-registry"
CORE_IMAGE_BASE_INSTALL += "docker nvidia-container-toolkit docker-registry-config"

# Install the Argus launcher and an inactive camera boot example on Edge-AI.
IMAGE_INSTALL:append:edge-ai = " \
    edge-ai-argus-camera-example \
    edge-ai-extlinux-samples \
"
