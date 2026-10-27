EDGE_AI_DEB_COMPONENT = "uefi-capsules"
require edge-ai-deb.inc
do_create_deb[depends] += "edge-ai-uefi-update-capsules:do_deploy"
