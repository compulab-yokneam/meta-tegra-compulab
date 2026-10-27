# The GTK/XWayland compatibility change serves both opt-in FRAMOS profiles.
FILESEXTRAPATHS:prepend := "${THISDIR}/files:"

SRC_URI += " \
    file://0002-argus-camera-report-module-identity.patch \
    file://0003-argus-camera-use-per-session-sensor-modes.patch \
    file://0005-argus-preview-allow-depthless-egl-config.patch \
    file://0006-argus-camera-clean-up-partial-capture-start.patch \
"
PR:append = ".clabinfo3"

SRC_URI:append:edge-ai-framos-argus-demo-profile = " file://0001-argus-match-egl-config-to-x11-window.patch"
PR:append:edge-ai-framos-argus-demo-profile = ".edgedesdemo1"
