compulab_extlinux() {
    if [ -f ${IMAGE_ROOTFS}/boot/extlinux/extlinux.conf ]; then
        sed -i "s/\(APPEND\)/\1 root=PARTUUID=${PARTUUID} rootwait ro/g" ${IMAGE_ROOTFS}/boot/extlinux/extlinux.conf
    fi
}

compulab_firmware() {
   if [ -d ${IMAGE_ROOTFS}/lib/firmware ]; then
        tar -C ${IMAGE_ROOTFS} -cjvf ${DEPLOY_DIR_IMAGE}/image-firmware.tar.bz2 lib/firmware
    fi
}
