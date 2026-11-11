# Keep fixed USB-role variants selectable through edge-ai-select-fdt as well
# as FDT_FILE. Normal tegra-devicetree packaging owns /boot/devicetree.
EDGE_AI_USB_ROLE_DTBS = " \
    ${@' '.join('tegra234-p3768-0000+p3767-%s-nv-super-%s.dtb' % (sku, role) for sku in ('0000', '0001', '0003', '0004', '0005') for role in ('host', 'device'))} \
"

do_sign_dtbs:append:edge-ai() {
    for dtb in ${EDGE_AI_USB_ROLE_DTBS}; do
        tegra_uefi_split_sign "${B}/$dtb"
    done
}

do_install:append:edge-ai() {
    install -d ${D}/boot/dtb
    for dtb in ${EDGE_AI_USB_ROLE_DTBS}; do
        install -m 0644 ${B}/$dtb ${D}/boot/dtb/
        if ${TEGRA_UEFI_USE_SIGNED_FILES}; then
            install -m 0644 ${B}/$dtb.sig ${D}/boot/dtb/
        fi
    done
}

FILES:${PN}:append:edge-ai = " /boot/dtb/*.dtb /boot/dtb/*.dtb.sig"
