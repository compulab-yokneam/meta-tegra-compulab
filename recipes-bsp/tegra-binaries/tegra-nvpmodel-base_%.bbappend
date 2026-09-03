do_install:append:edge-ai-shared-runtime() {
    install -d ${D}${sysconfdir}/nvpmodel
    for sku in 0000 0001 0003 0004; do
        install -m 0644 \
            ${B}${sysconfdir}/nvpmodel/nvpmodel_p3767_${sku}_super.conf \
            ${D}${sysconfdir}/nvpmodel/
    done
}
