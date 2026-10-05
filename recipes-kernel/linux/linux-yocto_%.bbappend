FILESEXTRAPATHS:prepend:edgeai-orn := "${THISDIR}/files:"

SRC_URI:append:edgeai-orn = " file://compulab.cfg"
LINUX_VERSION:edgeai-orn = "6.18.48"
SRCREV_machine:edgeai-orn = "5b95344d2d0cfbe5889e3eb5a2ea3939dc3412f0"
SRCREV_meta:edgeai-orn = "185549fc38a492dc3e431b32ac6774620ae6b468"

# Apply the mandatory balenaOS kernel configuration and signing/deployment
# integration to the selected EdgeAI kernel provider.
inherit ${@'kernel-resin deploy' if 'edgeai-orn' in (d.getVar('MACHINEOVERRIDES') or '').split(':') else ''}

# meta-balena-jetson obtains extlinux.conf from its Noble kernel append.  Keep
# the same rootfs boot contract when linux-yocto is selected, without changing
# meta-balena-jetson itself.
DTB_OVERLAYS:edgeai-orn = "/boot/devicetree/tegra234-p3768-0000+p3767-0000-dynamic.dtbo"

KERNEL_ARGS:append:edgeai-orn = "${@bb.utils.contains('DISTRO_FEATURES', 'osdev-image', ' mminit_loglevel=4 console=tty0 console=ttyTCU0,115200', ' console=null quiet splash vt.global_cursor_default=0 consoleblank=0', d)} l4tver=${L4T_VERSION} rootdelay=1 roottimeout=60"
KERNEL_ARGS:remove:edgeai-orn = "nospectre_bhb firmware_class.path=/etc/firmware"

generate_edgeai_extlinux_conf() {
    install -d ${UNPACKDIR}/extlinux
    cat >${UNPACKDIR}/extlinux/extlinux.conf <<EOF
DEFAULT primary
TIMEOUT 10
MENU TITLE Boot Options
LABEL primary
      MENU LABEL primary ${KERNEL_IMAGETYPE}
      FDT default
      OVERLAYS ${DTB_OVERLAYS}
      LINUX /boot/${KERNEL_IMAGETYPE}
      APPEND \${cbootargs} ${KERNEL_ARGS} sdhci_tegra.en_boot_part_access=1 rootwait video=efifb:off
EOF
}

do_install:append:edgeai-orn() {
    generate_edgeai_extlinux_conf
    install -d ${D}/boot/extlinux
    install -m 0644 ${UNPACKDIR}/extlinux/extlinux.conf ${D}/boot/extlinux/
}

PACKAGES:prepend:edgeai-orn = "${PN}-extlinux "
FILES:${PN}-extlinux:edgeai-orn = "/boot/extlinux/extlinux.conf"
RRECOMMENDS:${PN}:append:edgeai-orn = " ${PN}-extlinux"
