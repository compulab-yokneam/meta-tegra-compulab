EDGEDES FRAMOS Argus demo for Yocto / NVIDIA R39.2.1
=================================================

See README.md for current build, installation, GStreamer and Argus commands.
See ARGUS-DEMO-VALIDATION.txt and IMX676-VALIDATION.txt for measured results.

This is an explicit internal, uncalibrated demo option, not a production
camera profile. NVIDIA license terms and notices remain unchanged.
The normal layer configuration is unchanged.

Build opt-in:
    require conf/include/edge-ai-argus-framos-demo.inc

The old edge-ai-argus-imx678-demo.inc remains a compatibility include.
It now selects the shared edge-ai-argus-framos-demo package.

Select exactly one port-0 profile matching the attached camera:
    IMX676: edgedes-adi-v18-framos-imx676-port0.dtb, 3552x3556 RAW12, 10 FPS
    IMX678: edgedes-adi-v18-framos-imx678-port0.dtb, 3856x2180 RAW12, 10 FPS

One argus_camera / argus_oneshot / nvarguscamerasrc supports both sensors.
No second Argus application or fork of NVIDIA core libraries is introduced.
The source-built samples retain the same demo-only GTK/Xwayland EGL fix.

The shared package installs separate mode data, not separate applications:
    /var/nvidia/nvcam/settings/edgedes-imx676-demo.nito
    /var/nvidia/nvcam/settings/edgedes-imx678-demo.nito
The shell launcher selects the NITO from the live DT badge and execs the
unchanged vendor daemon. IMX678's previous NITO remains byte-identical.
See README.md and files/PROVENANCE.txt for both hashes and conversion inputs.

This is not sensor/lens-specific FRAMOS tuning. Provenance and the unchanged
NVIDIA agreement are installed in /usr/share/edge-ai-argus-framos-demo/.
The guard accepts only module0 with one of the two supported port-0 badges.
It does not auto-detect sensor silicon or qualify mixed cameras.

Upgrade from the old IMX678-only package:
    stop all capture clients
    systemctl stop nvargus-daemon
    dpkg --purge edge-ai-argus-imx678-demo
    install the matching shared Yocto package
    systemctl daemon-reload
    systemctl restart nvargus-daemon

Purge removes the old retained service configuration; otherwise two drop-ins
could select different profiles. Back up package-owned settings before purge.
The shared package also declares a conflict/replacement for the old package.

Rollback the demo with no capture clients running:
    dpkg --purge edge-ai-argus-framos-demo
    systemctl daemon-reload
    systemctl restart nvargus-daemon

To undo the sample EGL fix, reinstall the saved ordinary argus-samples package.
The demo package does not change boot entries, driver modules, firmware,
vendor NITOs or NVIDIA core libraries. DTB selection remains explicit.
No HDR, additional modes, mixed sensors, production IQ or cold-power startup
qualification is implied.
