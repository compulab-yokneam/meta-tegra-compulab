compulab_extlinux() {
    if [ -f ${IMAGE_ROOTFS}/boot/extlinux/extlinux.conf ]; then
        sed -i "s/\(APPEND\)/\1 root=PARTUUID=${PARTUUID} rootwait ro/g" ${IMAGE_ROOTFS}/boot/extlinux/extlinux.conf
    fi
}
