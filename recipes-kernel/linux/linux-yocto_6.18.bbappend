# Published ADI v18, followed by the scoped Linux 6.18 backport.
# Enable with require conf/include/edge-ai-adi-gmsl-v18.inc in local.conf.
FILESEXTRAPATHS:prepend := "${THISDIR}/files:"

LINUX_VERSION_EXTENSION:edge-ai:adi-gmsl-v18 = "-yocto-standard-adi-v18"

SRC_URI:append:edge-ai:adi-gmsl-v18 = " \
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
    file://adi-gmsl-v18/edgedes-adi-v18.cfg \
"
