# FRAMOS IMX676 / IMX678 Argus demo

Internal, uncalibrated demo for Edge-AI Orin NX16G: one to four IMX676 sensors on
EDGEDES ports 0-3, or one IMX678 on port 0; ADI v18, NVIDIA R39.2.1 and Linux
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
seven complete ADI v18 camera profiles under `/boot/dtb`. Select the profile
matching the attached sensor and coax port: IMX678 has a port-0 profile, while
IMX676 has port-0, port-1, port-2 and port-3 profiles. For example,
`edgedes-adi-v18-framos-imx676-port2.dtb` selects an IMX676 on coax port 2.
`edgedes-adi-v18-framos-imx676-4port.dtb` discovers the connected IMX676
assemblies on any subset of the four ports at boot.
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

Use the matching `edgedes-adi-v18-framos-imx676-portN.dtb` for IMX676, where
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

The matching `edgedes-adi-v18-framos-imx676-4port.dtbo` is a standalone overlay
for the same NX16G base. Its `.dtso` includes source fragments for the
MAX96724, each serializer/sensor path, NVCSI, VI and camera modules. The
`edgedes-adi-v18-framos-imx676-mode.dtsi` fragment holds the shared sensor
mode. Build this top-level source to produce one overlay; `.dtsi` files are
included source components.

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

Connect complete, powered IMX676 camera/serializer assemblies before booting.
Zero connected cameras should boot normally with no camera video devices and
the demo Argus service skipped. Discovery is performed at boot, not during
live cable hot-plugging; power down before changing the cabling. It detects
reachable GMSL links, not arbitrary sensor silicon: IMX678, TEVS, other models,
and mixed sensor types still need their matching profiles. A connected
serializer with a failed sensor is not treated as an empty port.

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
and `--uefi` to remove explicit FDT statements. It saves the original
configuration as `/boot/extlinux/extlinux.conf.bak`. Reboot after changing the
selection. If signed-extlinux enforcement is enabled, the modified file must be
re-signed before reboot; the selector warns when it finds an existing signature.

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
It selects `edgedes-imx676-demo.nito` or `edgedes-imx678-demo.nito` under
`/var/nvidia/nvcam/settings`, then execs the unchanged vendor daemon.
The service guard accepts one IMX678 module or one to four IMX676 modules with
distinct port badges; mixed sensor types and unsupported camera modules skip
the demo service. DT selection is explicit, not chip-ID detection. The IMX676
port-1/2/3 and auto-detected multi-port profiles reuse the qualified sensor mode
and CSI-C routing, but need hardware validation on those physical links and
in the four-stream aggregate configuration.
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

The packaged launcher selects any connected Argus camera and also works from
a root serial/SSH shell by switching to the Weston desktop user:

```bash
/opt/compulab/bin/argus_camera.sh --list
/opt/compulab/bin/argus_camera.sh --device 0
/opt/compulab/bin/argus_camera.sh --device=1
```

Without arguments it retains the existing device-0, sensor-mode-0, 10-FPS
preview. `--list` prints the native sample's device and sensor-mode information,
then exits without starting preview. `--device` (or `-d`) selects the compact
Argus device index shown by `--list`, not the physical coax port or a
`/dev/videoN` suffix. A camera alone on any EDGEDES port is device 0; with two
connected cameras, select device 0 or 1. Use `--help` for the launcher options.

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
