EDGE_AI_DEB_COMPONENT = "meta"
require edge-ai-deb.inc
do_create_deb[depends] += "edge-ai-argus-deb:do_create_argus_deb edge-ai-gstreamer-deb:do_create_deb edge-ai-kernel-deb:do_create_deb edge-ai-device-trees-deb:do_create_deb edge-ai-uefi-capsules-deb:do_create_deb edge-ai-boot-tools-deb:do_create_deb edge-ai-camera-support-deb:do_create_deb edge-ai-bsp-policy-deb:do_create_deb"
