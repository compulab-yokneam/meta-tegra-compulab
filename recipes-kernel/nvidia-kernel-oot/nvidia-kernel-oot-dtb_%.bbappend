# Fixed USB-role variants use the same split signing as the default DTBs.
do_sign_dtbs:append:edgeai-orn() {
    for dtb in ${EDGE_AI_USB_ROLE_DTBS}; do
        tegra_uefi_split_sign "${B}/$dtb"
    done
}

do_install:append:edgeai-orn() {
    install -d ${D}/boot/dtb
    for dtb in ${EDGE_AI_USB_ROLE_DTBS}; do
        install -m 0644 ${B}/$dtb ${D}/boot/dtb/
        if ${TEGRA_UEFI_USE_SIGNED_FILES}; then
            install -m 0644 ${B}/$dtb.sig ${D}/boot/dtb/
        fi
    done
}

FILES:${PN}:append:edgeai-orn = " /boot/dtb/*.dtb /boot/dtb/*.dtb.sig"
