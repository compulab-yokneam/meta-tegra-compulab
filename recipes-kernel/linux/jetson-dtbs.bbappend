install_edge_ai_dtbs() {
	install -m 0644 "${DEPLOY_DIR_IMAGE}/devicetree/tegra234-p3768-0000+p3767-0005-nv.dtb" "${D}/boot/tegra234-p3768-0000+p3767-0005-nv.dtb"
	install -m 0644 "${DEPLOY_DIR_IMAGE}/devicetree/tegra234-p3768-0000+p3767-0005-nv-super.dtb" "${D}/boot/tegra234-p3768-0000+p3767-0005-nv-super.dtb"
	install -m 0644 "${DEPLOY_DIR_IMAGE}/devicetree/tegra234-p3768-0000+p3767-0004-nv.dtb" "${D}/boot/tegra234-p3768-0000+p3767-0004-nv.dtb"
	install -m 0644 "${DEPLOY_DIR_IMAGE}/devicetree/tegra234-p3768-0000+p3767-0004-nv-super.dtb" "${D}/boot/tegra234-p3768-0000+p3767-0004-nv-super.dtb"
	install -m 0644 "${DEPLOY_DIR_IMAGE}/devicetree/tegra234-p3768-0000+p3767-0003-nv.dtb" "${D}/boot/tegra234-p3768-0000+p3767-0003-nv.dtb"
	install -m 0644 "${DEPLOY_DIR_IMAGE}/devicetree/tegra234-p3768-0000+p3767-0003-nv-super.dtb" "${D}/boot/tegra234-p3768-0000+p3767-0003-nv-super.dtb"
	install -m 0644 "${DEPLOY_DIR_IMAGE}/devicetree/tegra234-p3768-0000+p3767-0001-nv.dtb" "${D}/boot/tegra234-p3768-0000+p3767-0001-nv.dtb"
	install -m 0644 "${DEPLOY_DIR_IMAGE}/devicetree/tegra234-p3768-0000+p3767-0001-nv-super.dtb" "${D}/boot/tegra234-p3768-0000+p3767-0001-nv-super.dtb"
	install -m 0644 "${DEPLOY_DIR_IMAGE}/devicetree/tegra234-p3768-0000+p3767-0000-nv.dtb" "${D}/boot/tegra234-p3768-0000+p3767-0000-nv.dtb"
	install -m 0644 "${DEPLOY_DIR_IMAGE}/devicetree/tegra234-p3768-0000+p3767-0000-nv-super.dtb" "${D}/boot/tegra234-p3768-0000+p3767-0000-nv-super.dtb"
}

do_install:append:edge-ai-nx() {
	install_edge_ai_dtbs
}

do_install:append:edge-ai-nano() {
	install_edge_ai_dtbs
}

EDGE_AI_DTB_FILES = " \
	/boot/tegra234-p3768-0000+p3767-0005-nv.dtb \
	/boot/tegra234-p3768-0000+p3767-0005-nv-super.dtb \
        /boot/tegra234-p3768-0000+p3767-0004-nv.dtb \
        /boot/tegra234-p3768-0000+p3767-0004-nv-super.dtb \
	/boot/tegra234-p3768-0000+p3767-0003-nv.dtb \
	/boot/tegra234-p3768-0000+p3767-0003-nv-super.dtb \
	/boot/tegra234-p3768-0000+p3767-0001-nv.dtb \
	/boot/tegra234-p3768-0000+p3767-0001-nv-super.dtb \
	/boot/tegra234-p3768-0000+p3767-0000-nv.dtb \
	/boot/tegra234-p3768-0000+p3767-0000-nv-super.dtb \
"

FILES:${PN}:edge-ai-nx += "${EDGE_AI_DTB_FILES}"
FILES:${PN}:edge-ai-nano += "${EDGE_AI_DTB_FILES}"
