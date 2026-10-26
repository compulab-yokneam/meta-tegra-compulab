# Rebuild the CompuLab NVIDIA Ubuntu SDK

`edge-ai-sdk-manager` prepares JetPack 7.2.1 / L4T R39.2.1 with the installed
SDK Manager CLI, then converts that fresh SDK using this layer's sources and
matched deploy artifacts. It does not copy the manually prepared SDK, inspect
another recipe's `tmp/work`, build a Yocto rootfs, or flash a connected board.
The result remains NVIDIA Ubuntu 24.04, not a Yocto userspace.

## Host requirements and authorization

This is an explicitly privileged, non-hermetic host workflow. Use a dedicated
Ubuntu 24.04 SDK build VM or host, with sufficient free disk space for
SDK downloads, a complete Ubuntu SDK and a separate Ubuntu build sysroot.

Before running it, arrange:

- An installed SDK Manager supporting JetPack 7.2.1 and a valid cached DevZone
  session for the ordinary user who runs BitBake. Initial login is an external
  prerequisite; the recipe does not automate browser/MFA authentication.
- Externally provisioned noninteractive sudo permissions for SDK Manager's
  prerequisites and the conversion helper. A cached `sudo -v` is insufficient:
  SDK Manager invalidates sudo timestamps. The recipe never edits sudoers.
- Host tools including Git, Python 3.12+, rsync, kmod/depmod, initramfs-tools,
  device-tree-compiler, mount/chroot and working QEMU ARM64 binfmt registration
  with the persistent `F` flag. SDK Manager may install additional host tools.
- No other SDK Manager instance. SDK Manager uses a host-global socket.
- NVIDIA licenses accepted by an authorized user and access to the pinned
  NVIDIA downloads and signed Ubuntu Noble package repositories.

Even with `host=false`, SDK Manager's **Jetson Linux Image** action runs host
APT/prerequisite installation and `apply_binaries.sh`. The two enable switches
below explicitly authorize these operations. No host packages are installed
by the Ubuntu-runtime helper: its development APT operations run in a separate
Ubuntu ARM64 build root. It masks devices and blocks service startup.

Do not put passwords/tokens in `local.conf`, recipe variables, `SRC_URI`, or
command-line arguments. No password from `/tmp/2do` is used. SDK Manager's own
password mechanism is unsuitable here because it can expose passwords in
subprocess arguments. Keep NVIDIA authentication in SDK Manager's private
per-user state, outside downloads, deploy and sstate.

## Configuration and command

In the NX16G build's `conf/local.conf`:

```bitbake
MACHINE = "edge-ai-nx-16g"
TEGRA_DEFAULT_KERNEL = "linux-noble-nvidia-tegra"
require conf/include/edge-ai-sdk-manager.inc
EDGE_AI_SDK_ENABLE = "1"
EDGE_AI_SDK_ACCEPT_LICENSE = "1"
LICENSE_FLAGS_ACCEPTED += "nvidia-argus-framos-demo"

# Optional: reuse the existing SDK Manager download cache.
EDGE_AI_SDK_DOWNLOAD_DIR = "/home/val/nvidia/sdkm_downloads"
```

Do not enable `edge-ai-universal-bundle.inc` for this standalone workflow.
The SDK include enables recipe-owned deploy exports and the twelve firmware
multiconfigs and pulls in the ADI kernel/DT configuration. An additional
camera-menu include is not needed for this standalone SDK recipe. Avoid
duplicating the ADI/capsule include lines already pulled in by the SDK include;
existing camera/universal includes may produce harmless duplicate-include
warnings. Nothing adds this host workflow to a normal image build.

```sh
bitbake edge-ai-sdk-manager
```

Output (`MACHINE`, not `MACINED`):

```text
${DEPLOY_DIR_IMAGE}/jetpack-7.2.1-image-build/
  .edge-ai-sdk-ready.json
  JetPack_7.2.1_Linux_JETSON_ORIN_NX_TARGETS/Linux_for_Tegra/
```

Normally `DEPLOY_DIR_IMAGE` is
`${BUILDDIR}/tmp/deploy/images/${MACHINE}`. Override `EDGE_AI_SDK_OUTPUT` for
another **new** destination. If firmware multiconfigs use custom `TMPDIR`s,
override `EDGE_AI_SDK_FIRMWARE_INPUTS` with their machine/style/mc/deploy mapping.

## Sourceable host wrapper

The generated SDK contains `compulab-l4t.env` at its root. Source that file
from a clean Bash shell and run `devshell`, or call its selectors and image/
flash functions directly. It requires no old R36 wrapper and performs no
operation when sourced. Offline creation uses a new owned loop image;
connected operations support QSPI-only or QSPI plus board NVMe, with a
read-only `--dry-run` and explicit confirmation before writes. Full usage:
[wrapper guide](files/sdk-source/compulab/host/WRAPPER.md).

The wrapper also provides `prepare_massflash_boot` (QSPI-only) and
`prepare_massflash_boot_rootfs` (QSPI plus NVMe). They generate native
`mfi_<target>.tar.gz` packages with `--no-flash`, defaulting to five devices;
`--massflash N` selects another limit. Use `--dry-run` first and a homogeneous
module batch. Existing package outputs are never overwritten by the wrapper.

Deploy commands flash by default; `deploy_bootloader --no-flash` and
`deploy_bootloader_rootfs --no-flash` explicitly select image generation only.
Unlike `--dry-run`, this still invokes native tools and writes generated files.
The massflash preparation functions always use `--no-flash`.

Full device deployment explicitly generates images in phase 1, validates fresh
target/NVMe/logo inputs, and invokes `--flash-only` in phase 2. Its native logs
are retained in a private host temporary directory printed by the wrapper;
an inner RCM `--no-flash` message alone does not mean deployment was disabled.

SDK conversion also applies a version/hash-checked R39.2.1 native initrd fix.
Each device slot gets a fresh extraction directory, preventing the second
slot's `mkdir: ... File exists` failure and stale per-slot configuration.
The original script is backed up, and preflight checks the exact reviewed
patched script; existing baseline manifests are not refreshed to hide drift.

## Included functionality

- NX16G, NX8G, Nano8G and Nano4G board profiles, correct per-module memory/BPMP
  defaults, carrier BCTs, watchdog, Ethernet/PCIe/USB/TPM device-tree changes,
  additional boot arguments and optional early HDMI tty1.
- The complete matched Noble kernel and packaged base/OOT modules, including
  the ADI v18 camera port; kernel config and effective symbol-CRC checks;
  module-specific DTBs, composable camera overlays and source-only matching
  development-header archives. Ubuntu initrds are rebuilt with NVIDIA's tool;
  stock kernel/modules/DTB/initrd fallbacks remain available.
- Twelve independently built UEFI/general, minimal RCM, launcher and matched
  TOS/StandaloneMM sets (four modules times three logo styles), build configs,
  license notices, hashes and provenance. Normal boot uses a private immutable
  L4TConfiguration template, separate from RCM boot-image locking.
- All twelve update capsules and Ubuntu-compatible capsule helpers. No EFI
  variable or boot partition is written while preparing the SDK.
- All 23 Argus applications and the three functionally patched GStreamer
  plugins, built against Ubuntu in an isolated native-QEMU build root, not
  copied from Yocto. Includes matching NITOs, launchers, live/record/capture,
  fullscreen and Nano software-H.264 fallback. CUDA build inputs are pinned.
- Ubuntu-native runtime dependencies, reversible BSP/GStreamer package holds,
  preservation of NVIDIA's first-boot GPU selection, FDT selector/sample menu,
  safe legacy-wrapper adapter, Git vendor baseline and integration manifests.

`EDGE_AI_IMX676_EXTENDED_MODES` defaults to `1`; IMX678 defaults to `0`. The
same values select the DT modes and runtime NITOs. Explicit camera-menu DTBs
are still NX16G profiles: adding the other three boot targets does not qualify
their camera hardware. Mixed-camera/NITO and real-time CPU encoding behavior
still require hardware validation. No secure-boot production signing keys are
introduced; existing development signing policy is retained.

## Repeat runs, failures and verification

SDK Manager deletes an existing `Linux_for_Tegra` during preparation. Therefore
this recipe never reruns it over an existing output. A successful output is
reused only after input fingerprints and installed artifacts verify unchanged.
Changed inputs require a new `EDGE_AI_SDK_OUTPUT` and a new
`EDGE_AI_SDK_HOST_WORK`. Failed/partial directories are retained for diagnosis,
are marked incomplete, and are never treated as valid SDKs. Inspect/recover
them manually; there is no automatic recursive deletion or resume guesswork.
Preparing a new path also updates SDK Manager's shared component inventory and
global image-directory setting. It does not uninstall the old manually
prepared SDK, but other SDK Manager operations will see the new inventory.

Private host work and logs default to `${TOPDIR}/sdk-manager-work/${MACHINE}`
(directory mode 0700, SDK Manager logs mode 0600). SDK Manager output is not
streamed into BitBake logs or exported into deploy/sstate. Review its own
per-user logs according to your authentication-data policy. The root-owned
SDK/build roots are deliberately outside `WORKDIR`: `clean`/`cleansstate`
neither remove them nor revoke SDK Manager authentication.

Read-only checks include input/archive hashes, all firmware-set identities,
109 requested kernel settings, effective module CRCs, Ubuntu initrd contents,
native runtime ELF loading/plugin registration and BSP policy. Publication of
`.edge-ai-sdk-ready.json` is the final step; an output without it is incomplete.
These checks do not establish hardware boot/camera qualification.

Offline fixture tests (no SDK Manager, sudo, network or devices):

```sh
python3 -B -m unittest discover -s recipes-devtools/edge-ai-sdk-manager/tests
python3 -B -m unittest discover -s recipes-devtools/edge-ai-sdk-manager/files/runtime/tests
python3 -B -m unittest discover -s recipes-kernel/linux/tests
python3 -B -m unittest discover -s recipes-bsp/uefi/tests
```

The fully privileged SDK Manager/native-QEMU workflow must additionally be
tested on the intended SDK build host; passing fixtures is not an end-to-end
SDK preparation result.
