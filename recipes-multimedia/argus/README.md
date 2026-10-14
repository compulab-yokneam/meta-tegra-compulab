# FRAMOS IMX676 / IMX678 Argus demo

Internal, uncalibrated demo for Edge-AI Orin NX16G: one to four IMX676 or IMX678
sensors on EDGEDES ports 0-3, with homogeneous presets and experimental mixed
modular profiles; ADI v18, NVIDIA R39.2.1 and Linux
`6.18.48-yocto-standard-adi-v18`.
IMX678 uses **3856×2180** and IMX676 uses **3552×3556**, both RGGB RAW12
at 10 FPS. Argus provides ISP-processed **NV12**, not RAW12, to GStreamer.
One `argus_camera`, `argus_oneshot`, and `nvarguscamerasrc` serve both sensors.
Only the kernel sensor module, DT profile, NITO mode data and native frame size differ.

IMX678 reuses the exact previous successful NITO. IMX676 uses separately
exported mode data with the same generic NVIDIA template and converter.
Neither is FRAMOS factory IQ tuning.
It does not qualify other modes, mixed cameras or cold-power startup,
and the demo option does not grant new NVIDIA redistribution rights.

## Build and enable

Add this explicit opt-in to the build configuration:

```bitbake
require conf/include/edge-ai-argus-framos-demo.inc
```

Requires `opengl systemd wayland x11` distro features. The image installs all
eleven complete ADI v18 camera profiles plus the neutral overlay base under
`/boot/dtb`. Select the profile
matching the attached sensor and coax port: both IMX676 and IMX678 have
port-0, port-1, port-2 and port-3 profiles. For example,
`edgedes-adi-v18-framos-imx676-port2.dtb` selects an IMX676 on coax port 2.
`edgedes-adi-v18-framos-imx676-4port.dtb` and
`edgedes-adi-v18-framos-imx678-4port.dtb` discover the connected assemblies of
the selected sensor model on any subset of the four ports at boot.
The include does not select
the boot DTB, flash or reboot the target.

For an ordinary single-machine image, set the default profile by basename in
`conf/local.conf`:

```bitbake
FDT_FILE = "edgedes-adi-v18-framos-imx678-port0.dtb"
```

For the universal bundle, scope the same setting to its shared runtime so that
the four module-specific flash profiles continue using their UEFI DTBs:

```bitbake
FDT_FILE:edge-ai-shared-runtime = "edgedes-adi-v18-framos-imx678-port0.dtb"
```

Use the matching `edgedes-adi-v18-framos-imx676-portN.dtb` for IMX676 or
`edgedes-adi-v18-framos-imx678-portN.dtb` for IMX678, where
`N` is the EDGEDES coax port (0-3). Leave `FDT_FILE`
unset or empty to keep the module-specific DTB supplied by UEFI. The generated
extlinux entry uses `FDT /boot/dtb/<basename>`; paths are not accepted as the
option value. The NVIDIA NX16G fallback
`tegra234-p3768-0000+p3767-0000-nv-super.dtb` is always retained in
`/boot/dtb`, independently of the selected default.

For one reusable IMX676 DTB covering any combination of EDGEDES inputs,
select the complete multi-port profile:

```bitbake
FDT_FILE = "edgedes-adi-v18-framos-imx676-4port.dtb"
```

For the same optional-port support with IMX678 instead, select:

```bitbake
FDT_FILE = "edgedes-adi-v18-framos-imx678-4port.dtb"
```

For a universal bundle, set the chosen basename using
`FDT_FILE:edge-ai-shared-runtime` instead. Choose one model-specific DTB;
the image contains both families, but it does not identify or mix sensor
silicon automatically. The existing IMX678 port-0 profile is unchanged.

Each matching `edgedes-adi-v18-framos-imx67{6,8}-4port.dtbo` is a standalone
overlay for the same NX16G base. The top-level `.dtso` includes the common
`edgedes-adi-v18-framos-4port-{deserializer,nvcsi,vi}.dtsi` transport fragments
plus per-model serializer/sensor and camera-module fragments. Each model's
`edgedes-adi-v18-framos-imx67{6,8}-mode.dtsi` holds its qualified sensor mode.
The original IMX676 transport helper names remain compatibility includes.
Build the top-level source to produce one overlay; `.dtsi` files are source
components, not independently loadable overlays.

All four inputs share MAX96724 PHY2 and the four-lane CSI-C output. Each
sensor emits native VC0. The ADI framework maps these to output VCs 0-3,
matching the four NVCSI/VI channels and the port-specific `mode0.vc_id`.
The overlay enables `compulab,default-multi-link-routes` and
`compulab,allow-missing-links`. ADI patches `0027`/`0028` detect link locks
before creating the downstream I2C adapters and camera notifiers. Empty inputs
are excluded; the physical port remains the output VC and stream ID, so a
camera alone on port 3 still uses output VC3. Serializer aliases are pinned to
their physical ports; sensor/expander aliases are unique across all four paths.
The kernel temporarily detaches only the absent cameras' module metadata from
the live device tree, preventing Argus from enumerating nonexistent cameras.
The DTB on disk is not rewritten. NVIDIA OOT patch `0103` leaves absent VI
channels unregistered instead of blocking the connected cameras.

Install both matching updated `max-serdes.ko` and `tegra-camera.ko` with this
DTB; replacing the DTB alone is insufficient. Keep a single-port boot entry for
rollback. The single-port profiles do not enable automatic discovery and keep
their existing behavior.

Connect complete, powered camera/serializer assemblies of the selected model
before booting. IMX678 retains its native 3856x2180 RAW12, 10-FPS mode,
37.125-MHz clock and 594-MHz input link frequency (1.188 Gb/s/lane); IMX676
retains its separate 3552x3556 mode and 360-MHz input link frequency.
Zero connected cameras should boot normally with no camera video devices and
the demo Argus service skipped. Discovery is performed at boot, not during
live cable hot-plugging; power down before changing the cabling. It detects
reachable GMSL links, not sensor silicon: IMX678 and IMX676 require their own
DTB and NITO, while TEVS and other models need their matching profiles.
The default automatic policy selects one sensor-specific NITO for homogeneous
connected subsets. Mixed IMX676/IMX678 active modules require the modular
overlays below and matching per-camera NITO identities; mixed legacy presets
remain rejected. A connected serializer with a failed sensor is not treated
as an empty port.

Video device numbers and Argus camera indexes are compact and are not physical
port numbers. A lone camera on any port can therefore be `/dev/video0` and
Argus device 0 while retaining its physical-port output VC. No frame
synchronization is configured. Sparse-port, four-camera capture, output
bandwidth and cold-power reliability still require hardware validation.

On the target, an administrator can browse the installed profiles and update
all entries in `/boot/extlinux/extlinux.conf` interactively:

```bash
edge-ai-select-fdt
```

The command accepts a DTB basename for non-interactive use, `--show`, `--list`,
and `--uefi` to remove explicit FDT statements. Selecting a complete DTB or
UEFI also clears `OVERLAYS`, preventing a previous stack from being applied
onto the fallback DTB. The selector does not author modular overlay lists.
It saves the original
configuration as `/boot/extlinux/extlinux.conf.bak`. Reboot after changing the
selection. If signed-extlinux enforcement is enabled, the modified file must be
re-signed before reboot; the selector warns when it finds an existing signature.

## Complete image with an all-port camera boot menu

For an NX16G image containing both sensor drivers, applications and all boot
profiles, replace the demo include in `conf/local.conf` with:

```bitbake
require conf/include/edge-ai-argus-framos-camera-menu.inc
EDGE_AI_CAMERA_BOOT_DEFAULT = "camera-imx676"
```

The generated boot menu has four independent entries:

- `camera-imx676`: IMX676 on any subset of ports 0-3; default.
- `camera-imx678`: IMX678 on any subset of ports 0-3.
- `camera-mixed`: the explicit modular sensor layout described below.
- `camera-uefi`: the original UEFI-provided tree, without FDT or overlays.

Empty inputs are optional. Sensor models are not auto-detected: select the
profile matching the connected hardware, and power down before changing it.
The homogeneous entries use the matching packaged NITO through default `auto`.
The mixed entry defaults to IMX676 port 0 plus IMX678 port 1; unconfigured ports
2/3 remain empty. To assign all four mixed ports explicitly, for example:

```bitbake
EDGE_AI_CAMERA_MIXED_OVERLAYS = " \
    edgedes-adi-v18-transport-4port.dtbo \
    edgedes-adi-v18-camera-imx676-port0.dtbo \
    edgedes-adi-v18-camera-imx678-port1.dtbo \
    edgedes-adi-v18-camera-imx676-port2.dtbo \
    edgedes-adi-v18-camera-imx678-port3.dtbo \
"
EDGE_AI_CAMERA_BOOT_DEFAULT = "camera-mixed"
```

Mixed Argus capture still requires matched embedded NITO identities; installing
both baseline NITOs does not qualify that configuration. The full image build
for the existing universal-runtime setup is:

```bash
bitbake -k mc:edge-ai-runtime:demo-image-weston
```

The menu opt-in leaves module-specific flash-profile builds unchanged. These
explicit camera DTBs remain **NX16G-only**, even in a universal rootfs. Use
`EDGE_AI_CAMERA_BOOT_DEFAULT = "camera-uefi"` when sharing that rootfs with
other modules; camera defaults must not force the NX16G tree on another module.
The existing `edge-ai-select-fdt` replaces FDT settings in every entry and
clears overlays. To keep the camera menu and its fallbacks, select a boot-menu
entry or change only `DEFAULT` instead of using that complete-DTB replacement.
Manual Secure Boot configuration edits require re-signing.

## Composable mixed-sensor overlays

The image installs one shared transport overlay and eight independent camera
overlays under `/boot/devicetree`. Load the transport first, then exactly one
IMX676 or IMX678 overlay per configured physical port. Do not stack the old
single-port pairs or homogeneous four-port overlays: they overwrite shared
CSI/VI configuration rather than composing independent ports.

For example, add to `conf/local.conf` after the demo include:

```bitbake
FDT_FILE = "tegra234-edge-ai-adi-base.dtb"
FDT_OVERLAYS = " \
    edgedes-adi-v18-transport-4port.dtbo \
    edgedes-adi-v18-camera-imx676-port0.dtbo \
    edgedes-adi-v18-camera-imx678-port1.dtbo \
    edgedes-adi-v18-camera-imx676-port2.dtbo \
    edgedes-adi-v18-camera-imx678-port3.dtbo \
"
# Homogeneous connected subsets use their model-specific demo NITO.
# Truly mixed subsets require qualified per-camera NITO identities.
EDGE_AI_ARGUS_NITO_SELECTION = "auto"
```

Omit a leaf for an unconfigured port. A configured but physically empty port
is handled by existing optional-link discovery. A transport-only stack is
valid and has no cameras. This selects models explicitly, not by chip-ID
detection, and does not support cable hotplug.

For a universal bundle, scope all three assignments with
`:edge-ai-shared-runtime` so module-specific flash profiles remain unchanged.
This does not make the explicit camera base portable to other modules: these
EDGEDES camera entries remain NX16G-only, including in a universal rootfs.
Do not also set `UBOOT_EXTLINUX_FDTOVERLAYS`: it uses different ownership/paths
and requires its own base setting.

The generator emits an explicit `FDT /boot/dtb/tegra234-edge-ai-adi-base.dtb`
plus a comma-separated `OVERLAYS` line with ordered absolute
`/boot/devicetree/...` paths. The neutral base and overlays retain symbols for
later fixups. Common transport owns the deserializer, four ATR adapters,
fixed CSI-C/VC0-3 output graph and model-free module placeholders. Each leaf
owns only its serializer/sensor, port connection and camera metadata. Leaves
do not depend on other leaves. Invalid ordering, duplicate port models,
wrong base and unsafe names are rejected. The DT compile task validates
all 81 empty/IMX676/IMX678 port combinations using ordered libfdt composition.

No UEFI patch or capsule update is needed. With `TEGRA_UEFI_DB_KEY` and
`TEGRA_UEFI_DB_CERT` configured, the DT recipe installs detached `.sig` files
for rootfs base/overlays; the extlinux recipe signs its configuration through
the existing task. Manual edits need re-signing. Attached `.signed` artifacts
do not replace the detached signatures expected for these rootfs paths.

`EDGE_AI_ARGUS_NITO_SELECTION` defaults to `auto`. After optional-link pruning,
one to four active cameras of the same model use that model's packaged NITO
through explicit `NVCAMERA_NITO_PATH`, even in a modular mixed-capable entry.
For example, IMX676 port 0 plus a configured but empty IMX678 port 1 still
selects `edgedes-imx676-demo.nito`; it does not rely on automatic badge matching.
Truly mixed active models use per-camera lookup only with the modular
`compulab,per-camera-nito` marker. Unmarked mixed profiles remain rejected.

Explicit `single` always requires homogeneous active models. Explicit
`per-camera` retains directory lookup for marked profiles even with just one
camera, allowing identity-matching tests; unmarked legacy profiles retain
their forced-file fallback. The guard logs the requested/effective policy,
active camera count and selected file. It requires a regular readable forced
NITO at both service condition and start, and replaces inherited overrides.

For per-camera lookup, the guard allows mixed distinct ports, clears inherited
`NVCAMERA_NITO_PATH` and starts the unchanged daemon using its default
`/var/nvidia/nvcam/settings` lookup. It requires a readable `.nito`, but file
presence does not validate embedded identity or mode data. Correct selection
uses camera metadata inside NITO, not merely filenames. The supplied baseline
files were validated through forced-file selection; their automatic matches
are **not qualified**. Verify or regenerate embedded identities with official
NVIDIA tools before claiming mixed ISP support. Renaming files or removing
the mixed guard alone is insufficient; this code does not modify NITO binaries.

First validate raw V4L2 capture and homogeneous modular profiles with `auto`.
Then test each model with explicit `per-camera` and confirm the daemon-selected
NITO identity in logs. Only then test two mixed cameras independently and
concurrently, reversed/sparse ports and four cameras.
Keep a complete homogeneous boot entry without `OVERLAYS` as fallback. See
`MIXED-CAMERA-OVERLAYS.txt` for scope and limits.

In the prepared Blacksail build environment, build the existing applications,
GStreamer plugin and demo profile recipes:

```bash
bitbake mc:edge-ai-runtime:argus-samples \
        mc:edge-ai-runtime:gstreamer1.0-plugins-nvarguscamerasrc \
        mc:edge-ai-runtime:edge-ai-argus-framos-demo
```

To build the kernel-module package and standalone device-tree deploy artifacts
without rebuilding the rootfs:

```bash
bitbake -c package_write_deb mc:edge-ai-runtime:nvidia-kernel-oot
bitbake -c deploy mc:edge-ai-runtime:edgedes-adi-v18-devicetree
```

The module is `fr_imx676.ko`; IMX678 keeps its existing `fr_imx678.ko`.
Use packages matching the running kernel. The Argus demo package pulls the
device-tree package into a generated image, but it does not select a boot DTB.
A development target using a manually installed ADI bootset still needs the
matching camera driver modules and explicit boot-profile selection.

When using `devtool`, an active `nvidia-kernel-oot` external-source override
bypasses the recipe's `SRC_URI` camera patches. Apply the layer's `0100` through
`0103` patches to that development source, or save its changes and reset the
override before a normal image build. A successful build of an unpatched
external tree does not supply the optional-camera driver. The prepared
optional-camera bootset uses a separately patched build of `tegra-camera.ko`
and does not modify the active NVIDIA development source.

To force application/plugin recompilation, run this first, then the build
above to refresh packages:

```bash
bitbake -f -c compile mc:edge-ai-runtime:argus-samples \
        mc:edge-ai-runtime:gstreamer1.0-plugins-nvarguscamerasrc
```

These are package builds, not a regenerated rootfs. Build the selected image
separately when an updated image is needed, for example:

```bash
bitbake mc:edge-ai-runtime:demo-image-weston
```

For an existing target, install matching Yocto packages and dependencies; do
not substitute Ubuntu packages or manually replace NVIDIA core libraries.
Applications/plugin are source-built; proprietary Argus core libraries and
the daemon remain NVIDIA prebuilt binaries supplied by their existing recipes.

## Check the target

Run one capture client at a time. As an administrator, with all capture clients
stopped, reload/restart the daemon after installing the profile:

```bash
systemctl daemon-reload
systemctl restart nvargus-daemon
systemctl is-active nvargus-daemon
systemctl cat nvargus-daemon
```

Expect `active` and the shared `edge-ai-argus-framos-demo-check --start` launcher.
For homogeneous active cameras, default `auto` selects `edgedes-imx676-demo.nito` or
`edgedes-imx678-demo.nito` under `/var/nvidia/nvcam/settings`, then execs the
unchanged vendor daemon. Marked modular profiles with both models active instead
use directory lookup and require matching embedded identities, as described
above. Explicit `per-camera` also selects lookup for marked homogeneous profiles.
The guard accepts one to four supported modules with distinct port badges;
unsupported modules, empty sets and mixed unmarked profiles skip the service.
Mixed capture remains subject to matching NITO data and hardware validation.
DT selection is explicit, not chip-ID detection. The IMX676
and IMX678 port-1/2/3 and auto-detected multi-port profiles reuse each model's
qualified sensor mode and CSI-C routing, but need hardware validation on those
physical links and in the four-stream aggregate configuration. See
`IMX678-MULTIPORT-VALIDATION.txt` for the IMX678 implementation/test scope.
When migrating from the old IMX678-only package, purge it first to remove its
retained service drop-in, then install `edge-ai-argus-framos-demo`.

```bash
sha256sum /var/nvidia/nvcam/settings/edgedes-imx67*-demo.nito
gst-inspect-1.0 nvarguscamerasrc
gst-inspect-1.0 nvvidconv
gst-inspect-1.0 waylandsink
```

Expected NITO SHA256 (IMX676, then IMX678):

```text
61ddaf20d9a6d639fa34d3e368d0c7d86fc469b1602fa2c4f86d591d736d41e3
fbbe09af35b1fe561b2f0c0995cdd2b916915284bf770ce8500456fb186e5f2f
```

## GStreamer pipelines

Choose the native size matching the booted profile:

```bash
# IMX676
width=3552; height=3556; preview_width=720; preview_height=720
# IMX678: width=3856; height=2180; preview_width=1280; preview_height=724
```

Run preview from the active Weston user's desktop terminal. This keeps native
sensor/ISP resolution and scales only the display, converting NVMM NV12 to
ordinary system-memory BGRx for `waylandsink`. Stop with Ctrl+C.

```bash
gst-launch-1.0 -e nvarguscamerasrc sensor-id=0 sensor-mode=0 ! \
  "video/x-raw(memory:NVMM),format=NV12,width=$width,height=$height,framerate=10/1" ! \
  nvvidconv ! "video/x-raw,format=BGRx,width=$preview_width,height=$preview_height" ! \
  waylandsink sync=false
```

Headless 100-frame test; check actual buffer messages, not EOS alone:

```bash
gst-launch-1.0 -e -v nvarguscamerasrc sensor-id=0 sensor-mode=0 num-buffers=100 ! \
  "video/x-raw(memory:NVMM),format=NV12,width=$width,height=$height,framerate=10/1" ! \
  identity silent=false ! fakesink sync=false
```

SSH preview requires the active desktop's environment and socket access. On
the current tested desktop these were `XDG_RUNTIME_DIR=/run/user/1000` and
`WAYLAND_DISPLAY=wayland-1`; discover the actual values for your session rather
than assuming those values are portable. An X11 `DISPLAY` does not configure
native Wayland output.

NVIDIA's JPEG library uses `lsmod` to detect the GPU platform. The demo package
requires `kmod`; `/usr/sbin` must also be in the application's PATH. Missing
`lsmod` caused a JPEG crash in the tested minimal desktop environment. The
Argus commands below set PATH for that process without changing system files.

## Argus applications

Edge-AI `demo-image-weston` images also install the supplied camera boot
example as `/boot/extlinux/extlinux.conf.imx67x.sample`. It contains separate
all-port IMX676 and IMX678 entries and is inactive: the generated
`/boot/extlinux/extlinux.conf` remains unchanged. The sample is for the NX16G
camera profile and assumes its matching DTBs, overlays and initrd are
installed. Review its boot arguments and model selection before adapting it
to the active configuration; it relies on `${cbootargs}` for root-device
settings. This package does not enable camera drivers.

The packaged launcher selects any connected Argus camera and also works from
a root serial/SSH shell by switching to the Weston desktop user:

```bash
/opt/compulab/bin/argus_camera.sh --list
/opt/compulab/bin/argus_camera.sh -d 1
/opt/compulab/bin/argus_camera.sh --port=3
/opt/compulab/bin/argus_camera.sh --device 0
/opt/compulab/bin/argus_camera.sh --device=1
```

Without arguments it retains the existing device-0, sensor-mode-0, 10-FPS
preview. `-d PORT` (or `--port PORT`) now selects physical EDGEDES port 0–3.
It matches the native Argus module identity against enabled live DT badges;
it never guesses from module order or a `/dev/videoN` suffix. Empty ports and
ambiguous identities are rejected. The matching patched `argus-samples`
package is required for physical-port selection.

`--list` shows physical-port-to-Argus-index mappings and the native sample's
sensor-mode information, then exits without starting preview. `--device INDEX`
retains explicit compact Argus-index selection. A camera alone on port 1 is
Argus device 0: use `-d 1` or `--device 0`. Unlike earlier launcher versions,
`-d` no longer aliases `--device`. Use `--help` for the launcher options.

To preview multiple connected cameras simultaneously in one tiled window:

```bash
# All connected physical ports, skipping empty ports
/opt/compulab/bin/argus_camera.sh --all

# Only physical ports 0 and 1 (both must be connected)
/opt/compulab/bin/argus_camera.sh --ports 0,1
```

`--ports=0,1,2,3` is also supported. These options cannot be combined with
`-d`, `--device` or `--list`. Port identities are queried once and the entire
selection is checked before starting capture; a missing requested port
rejects the whole selection. Each camera gets a separate Argus capture
session, its own sensor mode and native output resolution. Preview uses
mode 0 at 10 FPS for each camera. Tiles follow native Argus index order,
not the order of the physical port list. Esc or Ctrl+C stops all sessions.
This is concurrent preview, not hardware-synchronized frame capture.

Install the matching updated `argus-samples` together with the launcher:
the original sample reuses another device's sensor-mode object in its
multi-session path. Sensor models still require matching device-tree
configuration and ISP tuning. The launcher does not detect sensor models
or resolve the mixed-sensor NITO qualification limits documented above.

Headless native JPEG, in a fresh writable directory:

```bash
capture_dir=$(mktemp -d /tmp/framos-oneshot.XXXXXX)
cd "$capture_dir"
PATH=/usr/sbin:/usr/bin:/sbin:/bin:$PATH argus_oneshot
```

Output: `argus_oneShot.jpg`, native size of the selected sensor. Copy wanted images out of `/tmp`
before rebooting.

The GTK viewer uses X11/XWayland, not a native Wayland backend. Run it from the
Weston user's desktop terminal with valid X11 access:

```bash
PATH=/usr/sbin:/usr/bin:/sbin:/bin:$PATH GDK_BACKEND=x11 DISPLAY=:0 argus_camera \
  --device=0 --sensormode=0 --framerate=10 --kpi=1
```

GTK JPEG example; keep `--still=1 --exit` last because CLI actions run in order:

```bash
capture_dir=$(mktemp -d /tmp/framos-gtk-still.XXXXXX)
cd "$capture_dir"
PATH=/usr/sbin:/usr/bin:/sbin:/bin:$PATH GDK_BACKEND=x11 DISPLAY=:0 argus_camera \
  --device=0 --sensormode=0 --framerate=10 --still=1 --exit
```

Output: `image0000.jpg`. Reusing a directory can overwrite that filename.
Root SSH credentials are not the desktop user's X11 credentials.

Both sensors use the same demo-patched `argus-samples` revision `r0.edgedesdemo1`.
IMX676 native JPEG, 100-buffer headless/Wayland pipelines, and GTK live preview
passed at 10 FPS, including a warm-reboot capture check. AWB converged; AE
reported timeout in the ceiling/light scene, so AE/IQ is not fully qualified.
Previous IMX678 post-install native JPEG and metadata tests passed: 100/100 frames at
10.000217 FPS, final-20 AE/AWB convergence 20/20 each, and zero invalid
automatic-control metadata, timestamp errors or skipped frames. GTK still
capture saved a native JPEG; live GTK display measured 9.98-10.02 FPS without
reported frame drops after the process-local PATH fix.

## Rollback

As an administrator, with no capture client running:

```bash
dpkg --purge edge-ai-argus-framos-demo
systemctl daemon-reload
systemctl restart nvargus-daemon
```

Purge removes the configuration drop-in; plain package removal may retain it.
Remove any manually created temporary `/run/systemd/system/nvargus-daemon.service.d/90-edgedes-imx678-demo.conf`
before restarting as well. To undo the demo-only GTK EGL patch, reinstall the
saved ordinary `argus-samples` package without the `.edgedesdemo1` revision.
Existing vendor/legacy NITOs, kernel, DTB and firmware are unchanged.

See [detailed integration notes](README.txt),
[previous IMX678 validation](ARGUS-DEMO-VALIDATION.txt),
[IMX676 validation](IMX676-VALIDATION.txt), and
[NITO provenance and license notes](files/PROVENANCE.txt).
