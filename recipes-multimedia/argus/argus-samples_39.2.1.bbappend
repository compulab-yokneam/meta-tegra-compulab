# The GTK/XWayland compatibility change serves both opt-in FRAMOS profiles.
FILESEXTRAPATHS:prepend := "${THISDIR}/files:"

SRC_URI:append:edge-ai-framos-argus-demo-profile = " file://0001-argus-match-egl-config-to-x11-window.patch"
PR:append:edge-ai-framos-argus-demo-profile = ".edgedesdemo1"
