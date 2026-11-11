# Without Secure Boot, tegra_uefi_attach_sign creates byte-for-byte copies.
# Keep these deployment artifacts for capsule generation, but do not install
# redundant copies in the rootfs and HUP boot volume. Signed builds retain them.
do_install:append:edgeai-orn() {
    if ! ${TEGRA_UEFI_USE_SIGNED_FILES}; then
        rm -f ${D}/boot/devicetree/*.dtb.signed ${D}/boot/devicetree/*.dtbo.signed
    fi
}
