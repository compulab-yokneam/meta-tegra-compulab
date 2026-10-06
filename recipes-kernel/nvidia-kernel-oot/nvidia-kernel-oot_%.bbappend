FILESEXTRAPATHS:prepend := "${THISDIR}/${PN}:"

SRC_URI:append:edge-ai = " \
	file://0001-compulab-dts-Enable-pcie-140c0000-pcie-140e0000.patch \
	file://0002-compulab-dts-Update-usb-ports-configuration.patch \
	file://0003-compulab-dts-Enable-serial-3110000.patch \
	file://0004-compulab-dts-Change-the-display-13800000-hotplug-pol.patch \
	file://0005-compulab-dts-Remove-unused-padctl-3520000-fusb301-25.patch \
	file://0006-compulab-dts-Define-tpm-on-spi-3210000.patch \
	file://0007-compulab-dts-Set-Edge-AI-platform-identity.patch \
	"

# Keep the legacy NVIDIA-only build unchanged unless the ADI profile is enabled.
SRC_URI:append:edge-ai:adi-gmsl-v18 = " \
    file://0100-media-tegra-support-adi-streams-graph.patch;patchdir=nvidia-oot \
    file://0101-media-edgedes-add-tevs-and-framos-imx678.patch;patchdir=nvidia-oot \
"

TEGRA_OOT_EXTRA_CAMERA_DRIVERS:append:edge-ai:adi-gmsl-v18 = " \
    nv-kernel-module-tevs nv-kernel-module-fr-imx678 \
"
