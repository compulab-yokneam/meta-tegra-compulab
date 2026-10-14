EDGEDES FRAMOS Argus demo for Yocto / NVIDIA R39.2.1
=================================================

See README.md for current build, installation, GStreamer and Argus commands.
See ARGUS-DEMO-VALIDATION.txt and IMX676-VALIDATION.txt for measured results.

This is an explicit internal, uncalibrated demo option, not a production
camera profile. NVIDIA license terms and notices remain unchanged.
The normal layer configuration is unchanged.

Build opt-in:
    require conf/include/edge-ai-argus-framos-demo.inc

For a complete NX16G image with selectable all-port camera boot entries,
replace that include (do not require both) with:
    require conf/include/edge-ai-argus-framos-camera-menu.inc
Default camera-imx676 and alternative camera-imx678 accept any connected
subset on ports 0-3. camera-mixed uses explicitly assigned per-port models;
camera-uefi retains the UEFI tree with no explicit FDT/overlays.
Set EDGE_AI_CAMERA_BOOT_DEFAULT and EDGE_AI_CAMERA_MIXED_OVERLAYS as described
in README.md. Camera DTBs remain NX16G-only; use camera-uefi as the default
when the universal rootfs is used on other modules. The complete-DTB selector
rewrites every entry, so use the boot menu to preserve independent profiles.

The old edge-ai-argus-imx678-demo.inc remains a compatibility include.
It now selects the shared edge-ai-argus-framos-demo package.

Select exactly one profile matching the attached camera and coax port:
    IMX676: edgedes-adi-v18-framos-imx676-port{0,1,2,3}.dtb
           3552x3556 RAW12, 10 FPS
    IMX678: edgedes-adi-v18-framos-imx678-port{0,1,2,3}.dtb
           3856x2180 RAW12, 10 FPS
For any subset of homogeneous assemblies on ports 0-3, select the reusable
edgedes-adi-v18-framos-imx676-4port.dtb or
edgedes-adi-v18-framos-imx678-4port.dtb for the attached model.
Composable mixed setups use tegra234-edge-ai-adi-base.dtb, one
edgedes-adi-v18-transport-4port.dtbo and one
edgedes-adi-v18-camera-imx{676,678}-portN.dtbo per configured physical port.
Set FDT_FILE plus ordered FDT_OVERLAYS as described in README.md. These are
new leaf overlays; the original single-port pairs must not be stacked.
Boot-time link discovery skips empty inputs. Requires ADI patch 0028 and
NVIDIA OOT patches 0103/0104/0105 in the matching
max-serdes.ko and tegra-camera.ko; a DTB-only upgrade is insufficient.
Keep the existing single-port entry as a fallback when testing the new profile.
This is not arbitrary sensor-model detection or runtime hot-plug support.
Video device numbers/Argus indexes compact; output VC remains the physical port.

One argus_camera / argus_oneshot / nvarguscamerasrc supports both sensors.
The launcher /opt/compulab/bin/argus_camera.sh accepts -d PORT / --port PORT
for physical EDGEDES ports 0..3, and --device INDEX for compact Argus indexes.
No arguments retain the first-camera preview. A lone camera on physical
port 1 is selected by -d 1 or --device 0. The old -d index alias is replaced.
Port selection verifies native module identities against live DT badges;
it does not guess from module order or video-node suffixes. Empty ports and
ambiguous identities are rejected. The matching patched argus-samples is
required. Run --list to inspect port/index mappings and sensor modes without
preview; --device remains usable when physical identity is unavailable.
Use --all (or -a) to preview all connected physical ports simultaneously,
or --ports 0,1 to select a comma-separated physical port set. Each requested
port must be connected; missing ports reject the whole selection. One tiled
window contains concurrent Argus sessions, each with its own mode 0 and
native output resolution at 10 FPS. Esc or Ctrl+C stops all sessions. Tiles
follow native index order, not the requested physical-port order. Capture
is not hardware synchronized. The updated argus-samples is required for the
per-session mode fix. Matching DT/ISP configuration remains necessary;
this option does not resolve mixed-sensor NITO qualification limits.
No second Argus application or fork of NVIDIA core libraries is introduced.
The source-built samples retain the same demo-only GTK/Xwayland EGL fix.

The shared package installs separate mode data, not separate applications:
    /var/nvidia/nvcam/settings/edgedes-imx676-demo.nito
    /var/nvidia/nvcam/settings/edgedes-imx678-demo.nito
Its device-tree package dependency installs the complete boot profiles:
    /boot/dtb/edgedes-adi-v18-tevs-ar0144-port3.dtb
    /boot/dtb/edgedes-adi-v18-framos-imx678-port{0,1,2,3}.dtb
    /boot/dtb/edgedes-adi-v18-framos-imx678-4port.dtb
    /boot/dtb/edgedes-adi-v18-framos-imx676-port{0,1,2,3}.dtb
    /boot/dtb/edgedes-adi-v18-framos-imx676-4port.dtb
    /boot/dtb/tegra234-edge-ai-adi-base.dtb
    /boot/devicetree/edgedes-adi-v18-transport-4port.dtbo
    /boot/devicetree/edgedes-adi-v18-camera-imx{676,678}-port{0,1,2,3}.dtbo
The shell launcher selects the NITO from the live DT badge and execs the
unchanged vendor daemon. IMX678's previous NITO remains byte-identical.
See README.md and files/PROVENANCE.txt for both hashes and conversion inputs.

This is not sensor/lens-specific FRAMOS tuning. Provenance and the unchanged
NVIDIA agreement are installed in /usr/share/edge-ai-argus-framos-demo/.
The guard accepts one to four IMX678 or one to four IMX676 cameras with
distinct port badges. Port-1/2/3 and four-stream routing still need hardware
validation for both models. It does not auto-detect sensor silicon.
EDGE_AI_ARGUS_NITO_SELECTION defaults to "auto": homogeneous connected subsets
use their model-specific forced file, including mixed-capable modular entries
with only one model connected. Mixed active models require the modular marker
and use experimental default-directory NITO lookup. Explicit "single" rejects
mixed models; explicit "per-camera" uses lookup on marked profiles even with
one camera, while legacy homogeneous entries keep their forced-file fallback.
The condition/start guard logs its effective policy and checks the selected
forced file is regular/readable. Existing NITO embedded identities must be
verified or regenerated before mixed ISP capture can be qualified. See README.md,
MIXED-CAMERA-OVERLAYS.txt and IMX678-MULTIPORT-VALIDATION.txt.

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
