# FDT_OVERLAYS uses detached signatures next to /boot/devicetree/*.dtbo.
do_sign_dtbs:append:edge-ai() {
    for overlay in ${B}/*.dtbo; do
        [ -f "$overlay" ] || continue
        tegra_uefi_split_sign "$overlay"
    done
}

do_install:append:edge-ai() {
    if ${TEGRA_UEFI_USE_SIGNED_FILES}; then
        for signature in ${B}/*.dtbo.sig; do
            [ -f "$signature" ] || continue
            install -m 0644 "$signature" ${D}/boot/devicetree/
        done
    fi
}

do_deploy:append:edge-ai() {
    if ${TEGRA_UEFI_USE_SIGNED_FILES}; then
        for signature in ${B}/*.dtbo.sig; do
            [ -f "$signature" ] || continue
            install -m 0644 "$signature" ${DEPLOYDIR}/devicetree/
        done
    fi
}

FILES:${PN}:append:edge-ai = " /boot/devicetree/*.dtbo.sig"
