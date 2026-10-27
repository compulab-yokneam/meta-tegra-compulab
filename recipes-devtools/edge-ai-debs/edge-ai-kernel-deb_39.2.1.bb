EDGE_AI_DEB_COMPONENT = "kernel"
require edge-ai-deb.inc
do_create_deb[depends] += "virtual/kernel:do_deploy nvidia-kernel-oot:do_deploy virtual/dtb:do_deploy virtual/dtbo:do_deploy edgedes-adi-v18-devicetree:do_deploy"
