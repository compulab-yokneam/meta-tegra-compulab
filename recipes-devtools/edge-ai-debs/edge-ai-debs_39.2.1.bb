EDGE_AI_DEB_COMPONENT = "bundle"
require edge-ai-deb.inc
do_create_deb[depends] += "edge-ai-meta-deb:do_create_deb"
