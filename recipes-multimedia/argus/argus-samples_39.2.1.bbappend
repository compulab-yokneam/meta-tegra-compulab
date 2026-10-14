# The GTK/XWayland compatibility change serves both opt-in FRAMOS profiles.
FILESEXTRAPATHS:prepend := "${THISDIR}/files:"

SRC_URI += " \
    file://0002-argus-camera-report-module-identity.patch \
    file://0003-argus-camera-use-per-session-sensor-modes.patch \
"
PR:append = ".clabinfo2"

SRC_URI:append:edge-ai-framos-argus-demo-profile = " file://0001-argus-match-egl-config-to-x11-window.patch"
PR:append:edge-ai-framos-argus-demo-profile = ".edgedesdemo1"
