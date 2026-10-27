EDGE_AI_DEB_COMPONENT = "device-trees"
require edge-ai-deb.inc
do_create_deb[depends] += "virtual/dtb:do_deploy virtual/dtbo:do_deploy edgedes-adi-v18-devicetree:do_deploy"
