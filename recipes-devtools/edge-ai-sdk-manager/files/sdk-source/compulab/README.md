# CompuLab Edge-AI / NVIDIA Ubuntu SDK

This SDK was generated from JetPack 7.2.1 / L4T R39.2.1 and the matching
CompuLab Yocto layer exports. It supports these boot/flash target names:

| Target | P3767 module SKU |
| --- | --- |
| `edge-ai-nx-16g` | 0000 |
| `edge-ai-nx-8g` | 0001 |
| `edge-ai-nano-8g` | 0003 |
| `edge-ai-nano-4g` | 0004 |

Use the target matching the physical module; never force another SKU. Online
flashing preserves NVIDIA EEPROM/fuse discovery. These profiles augment the
stock NVIDIA flashing scripts instead of replacing them. No device was
flashed, rebooted or hardware-qualified during SDK generation.

`EDGE_AI_UEFI_LOGO_STYLE=clab-logo|nvidia-logo|no-logo` selects matching general
UEFI, minimal RCM, launcher and TOS/StandaloneMM assets. The default is
`clab-logo`. `no-logo` retains firmware version/menu text on a black background.
`EDGE_AI_EARLY_TTY1=1` enables the optional early HDMI console boot arguments.
Development signing policy is retained; production secure-boot key management
is an independent deployment responsibility.

## Boot/runtime files

The installed kernel, complete effective module set and DTs share one ABI.
The runtime and recovery initrds were regenerated from NVIDIA Ubuntu. Do not
replace individual modules with stock NVIDIA/Yocto binaries. Matching
source-only header archives and compiler requirements are under `kernel/`.

The Ubuntu boot menu keeps `DEFAULT primary` and native `${cbootargs}`. Camera
DT entries are explicitly NX16G-only. Other modules use their module-specific
UEFI DTB. Stock kernel/initrd/DTB entries are diagnostic fallbacks, not a
promise of CompuLab peripheral support. The target helper
`edge-ai-select-fdt` safely selects FDT files; consult its `--help` and the
installed `/boot/extlinux/extlinux.conf.imx67x.sample`.

All 23 Argus applications and the three modified GStreamer plugins are built
against Ubuntu libraries. Camera helpers live in `/opt/compulab/bin`:

```sh
/opt/compulab/bin/argus_camera.sh --help
/opt/compulab/bin/gst_camera.sh --help
```

Configured sensor models/ports and NITO calibration must match the connected
hardware. IMX676 extended modes are enabled by default; IMX678 extended modes
remain optional. Mixed active sensors need qualified per-camera calibration.
Nano recording uses software x264 by default because Nano has no NVENC; CPU
throughput at large sensor modes requires validation.

`edge-ai-uefi-update {clab-logo|nvidia-logo|no-logo}` on the target stages a
module-specific full firmware capsule. Read its output and the capsule guide
before rebooting; firmware updates are real persistent device operations.
Generating this SDK does not issue them.

## Protection and verification

First-boot GPU selection remains unchanged. A version/hash-checked patch to
the native initrd generator isolates each massflash device's temporary tree;
the original script is preserved under `patches/`. Other vendor flashing
tools are unchanged, and preflight rejects unreviewed changes.
Coordinated BSP packages and rebuilt GStreamer are held so an ordinary APT
upgrade cannot silently replace the matched custom kernel/firmware/plugins.
`policy/bsp-protection.py` defaults to read-only inspection; explicit `apply`
and `restore` use receipts to preserve previous selections. Restore only as
part of a planned coordinated BSP replacement, not an ordinary update.

`SDK_BASELINE.json`, `kernel-manifest.json`, `export-provenance.json`, firmware
provenance, runtime receipts and `integration-files.json` record actual inputs
and installed hashes. The outer `.edge-ai-sdk-ready.json` is published only
after verification; without it, the SDK is incomplete. Do not rerun SDK Manager
over this SDK: its pre-install step deletes `Linux_for_Tegra`.

From `Linux_for_Tegra`, rerun the self-contained, read-only verifier with:

```sh
python3 -B compulab/tools/verify-sdk.py --verify --sdk-root "$PWD"
```

The SDK has its own Git vendor-baseline commit. Binary/rootfs payloads are
not represented by that source commit; preserve manifests and backups too.

## Existing raw-image wrapper

See `host/README.md`. Source the existing wrapper first, then source
`host/legacy-wrapper-compat.sh`; do not run legacy bulk support downloads over
this SDK. The adapter preserves the wrapper API, validates owned loop images
before writes, and rejects stale conflicting module metadata. For Nano, clear
old NX fallback exports (`FAB`, `BOARDREV`, `CHIPREV`, chip-SKU/RAM-code fields)
before selecting the correct target. Raw-image creation/flashing is a separate
explicit operation and has not been run by SDK generation.
