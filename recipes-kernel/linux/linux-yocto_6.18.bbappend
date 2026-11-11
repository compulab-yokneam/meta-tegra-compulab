# Published ADI v18, followed by the scoped Linux 6.18 backport.
# Enabled for EdgeAI-ORN; device-tree profiles select the fitted sensors.
FILESEXTRAPATHS:prepend := "${THISDIR}/files:"

SRC_URI:append:edgeai-orn = " \
    file://adi-gmsl-v18/0001-media-mc-Add-INTERNAL-pad-flag.patch \
    file://adi-gmsl-v18/0002-dt-bindings-media-i2c-max96717-add-support-for-I2C-A.patch \
    file://adi-gmsl-v18/0003-dt-bindings-media-i2c-max96717-add-support-for-pinct.patch \
    file://adi-gmsl-v18/0004-dt-bindings-media-i2c-max96717-add-support-for-MAX92.patch \
    file://adi-gmsl-v18/0005-dt-bindings-media-i2c-max96717-add-support-for-MAX96.patch \
    file://adi-gmsl-v18/0006-dt-bindings-media-i2c-max96712-use-pattern-propertie.patch \
    file://adi-gmsl-v18/0007-dt-bindings-media-i2c-max96712-add-support-for-I2C-A.patch \
    file://adi-gmsl-v18/0008-dt-bindings-media-i2c-max96712-add-support-for-POC-s.patch \
    file://adi-gmsl-v18/0009-dt-bindings-media-i2c-max96712-add-support-for-MAX96.patch \
    file://adi-gmsl-v18/0010-dt-bindings-media-i2c-max96712-add-control-channel-p.patch \
    file://adi-gmsl-v18/0011-dt-bindings-media-i2c-max96714-add-support-for-MAX96.patch \
    file://adi-gmsl-v18/0012-dt-bindings-media-i2c-add-MAX9296A-MAX96716A-MAX9679.patch \
    file://adi-gmsl-v18/0013-i2c-atr-serialize-attach-detach-against-bus-transfer.patch \
    file://adi-gmsl-v18/0014-media-i2c-add-Maxim-GMSL2-3-serializer-and-deseriali.patch \
    file://adi-gmsl-v18/0015-media-i2c-add-Maxim-GMSL2-3-serializer-framework.patch \
    file://adi-gmsl-v18/0016-media-i2c-add-Maxim-GMSL2-3-deserializer-framework.patch \
    file://adi-gmsl-v18/0017-media-i2c-remove-MAX96717-driver.patch \
    file://adi-gmsl-v18/0018-media-i2c-maxim-serdes-add-MAX96717-driver.patch \
    file://adi-gmsl-v18/0019-arm64-defconfig-disable-deprecated-MAX96712-driver.patch \
    file://adi-gmsl-v18/0020-staging-media-remove-MAX96712-driver.patch \
    file://adi-gmsl-v18/0021-media-i2c-maxim-serdes-add-MAX96724-driver.patch \
    file://adi-gmsl-v18/0022-media-i2c-remove-MAX96714-driver.patch \
    file://adi-gmsl-v18/0023-media-i2c-maxim-serdes-add-MAX9296A-driver.patch \
    file://adi-gmsl-v18/0024-media-maxim-serdes-adapt-ADI-v18-to-Linux-6.18-inter.patch \
    file://adi-gmsl-v18/0025-media-maxim-serdes-preserve-MAX96793-on-GMSL2.patch \
    file://adi-gmsl-v18/0026-media-max96717-qualify-MAX96793-pixel-mode-on-EDGEDE.patch \
    file://adi-gmsl-v18/0027-media-maxim-serdes-add-opt-in-multi-link-default-routes.patch \
    file://adi-gmsl-v18/0028-media-maxim-serdes-discover-optional-camera-links.patch \
    file://adi-gmsl-v18/edgedes-adi-v18.cfg \
"

# Carrier peripherals are available on the default Linux 6.18 kernel.
SRC_URI:append:edgeai-orn = " \
    file://edge-ai-peripherals-6.18/0001-media-Port-RK628-CSI-bridge-to-Linux-6.18.patch \
    file://edge-ai-peripherals-6.18/0002-serial-Port-dedicated-Tegra-RS485-driver-to-6.18.patch \
    file://edge-ai-peripherals-6.18/0003-watchdog-Add-separate-enable-and-ping-GPIO-watchdog.patch \
    file://edge-ai-peripherals-6.18/0004-media-Select-ADV7280-for-the-Edge-AI-PAL-adapter.patch \
    file://edge-ai-peripherals-6.18/peripherals.cfg \
"

# Preserve the forwarding Makefile when shared output is refreshed but the
# make-mod-scripts configure stamp is retained during an incremental rebuild.
do_shared_workdir:append:edgeai-orn() {
    printf 'include %s/Makefile\n' '${STAGING_KERNEL_DIR}' \
        > ${STAGING_KERNEL_BUILDDIR}/Makefile
}
