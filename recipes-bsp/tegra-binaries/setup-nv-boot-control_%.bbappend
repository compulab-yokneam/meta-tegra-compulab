do_install:append:edge-ai-shared-runtime() {
    sed -i 's,^TARGET=.*,TARGET=$(/usr/libexec/edge-ai-machine-name) || exit 1,' \
        ${D}${bindir}/setup-nv-boot-control
}

RDEPENDS:${PN}:append:edge-ai-shared-runtime = " edge-ai-universal-runtime"
