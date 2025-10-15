FILESEXTRAPATHS:prepend := "${THISDIR}/files:"

SRC_URI += "file://compulab.cfg"

do_deploy:append() {
	install -m 0644 ${B}/.config $deployDir/config-${KERNEL_VERSION}
	install -m 0644 ${B}/System.map $deployDir/System.map-${KERNEL_VERSION}
}
