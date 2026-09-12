# Do not install systemd's interactive shell integration.  Remove the backing
# scripts together with the profile links and tmpfiles rules that create them.
PACKAGECONFIG:remove = "osc-context"

do_install:append() {
    rm -f \
        ${D}${nonarch_libdir}/systemd/profile.d/70-systemd-shell-extra.sh \
        ${D}${nonarch_libdir}/systemd/profile.d/80-systemd-osc-context.sh \
        ${D}${sysconfdir}/profile.d/70-systemd-shell-extra.sh \
        ${D}${sysconfdir}/profile.d/80-systemd-osc-context.sh \
        ${D}${nonarch_libdir}/tmpfiles.d/20-systemd-shell-extra.conf \
        ${D}${nonarch_libdir}/tmpfiles.d/20-systemd-osc-context.conf
}
