# Carrier peripheral support for EdgeAI-ORN on Linux 6.18.
FILESEXTRAPATHS:prepend := "${THISDIR}/files:"

# Carrier peripherals are available on the default Linux 6.18 kernel.
SRC_URI:append:edgeai-orn = " \
    file://edge-ai-peripherals-6.18/0002-serial-Port-dedicated-Tegra-RS485-driver-to-6.18.patch \
    file://edge-ai-peripherals-6.18/0003-watchdog-Add-separate-enable-and-ping-GPIO-watchdog.patch \
    file://edge-ai-peripherals-6.18/peripherals.cfg \
"

# Preserve the forwarding Makefile when shared output is refreshed but the
# make-mod-scripts configure stamp is retained during an incremental rebuild.
do_shared_workdir:append:edgeai-orn() {
    printf 'include %s/Makefile\n' '${STAGING_KERNEL_DIR}' \
        > ${STAGING_KERNEL_BUILDDIR}/Makefile
}
