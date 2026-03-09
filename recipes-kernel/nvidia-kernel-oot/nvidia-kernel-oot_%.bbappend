FILESEXTRAPATHS:prepend := "${THISDIR}/${PN}:"

SRC_URI += " \
	file://0001-compulab-dts-Enable-pcie-140c0000-pcie-140e0000.patch;patchdir=hardware/nvidia/t23x/nv-public \
	file://0002-compulab-dts-Update-usb-ports-configuration.patch;patchdir=hardware/nvidia/t23x/nv-public \
	file://0003-compulab-dts-Enable-serial-3110000.patch;patchdir=hardware/nvidia/t23x/nv-public \
	file://0004-compulab-dts-Change-the-display-13800000-hotplug-pol.patch;patchdir=hardware/nvidia/t23x/nv-public \
	file://0005-compulab-dts-Remove-unused-padctl-3520000-fusb301-25.patch;patchdir=hardware/nvidia/t23x/nv-public \
	file://0006-compulab-dts-Define-tpm-on-spi-3210000.patch;patchdir=hardware/nvidia/t23x/nv-public \
	"
