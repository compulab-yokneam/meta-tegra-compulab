# Standalone NVIDIA Ubuntu Debian packages

Each target regenerates one CompuLab Ubuntu package from current layer
sources or matched recipe deploy exports. No target depends on
`edge-ai-sdk-manager:do_create_sdk`; SDK Manager and APT are never invoked.
These are Ubuntu archives, not packages for a Yocto `IMAGE_INSTALL`.

| Target | Output package | Required work |
| --- | --- | --- |
| `edge-ai-argus-deb` | `compulab-edge-ai-argus` | Build all 23 applications in a private Ubuntu ARM64 builder |
| `edge-ai-gstreamer-deb` | `compulab-edge-ai-gstreamer` | Build three plugins in a private Ubuntu ARM64 builder |
| `edge-ai-kernel-deb` | `compulab-edge-ai-kernel` | Matched kernel/OOT exports, module ABI checks and Ubuntu initrd generation |
| `edge-ai-device-trees-deb` | `compulab-edge-ai-device-trees` | Current DT deploy outputs and verified stock fallbacks |
| `edge-ai-uefi-capsules-deb` | `compulab-edge-ai-uefi-capsules` | Twelve machine/logo capsules from the firmware recipes |
| `edge-ai-boot-tools-deb` | `compulab-edge-ai-boot-tools` | Current helpers, sample and vendor-based Ubuntu boot menu |
| `edge-ai-camera-support-deb` | `compulab-edge-ai-camera-support` | Ubuntu launchers, helpers and selected matching NITOs |
| `edge-ai-bsp-policy-deb` | `compulab-edge-ai-bsp-policy` | Policy helper and exact-version APT configuration |
| `edge-ai-meta-deb` | `compulab-edge-ai` | Coordinated component versions and dependencies |
| `edge-ai-debs` | All nine archives | Verify and collect the complete matched package set |

Kernel/DT/firmware targets still build their required Yocto components
when inputs change. They do not build an Ubuntu OS image or unrelated
camera applications. Script/data targets do not require a native compiler.
The metapackage depends on the component package tasks; the aggregate
depends on the metapackage. Already current publications are verified
and reused without repeating native builds.

## Configuration

An existing SDK configuration using `edge-ai-sdk-manager.inc` already
enables deploy exports and the necessary firmware multiconfigs. The
standalone targets inherit its explicit enable switch, successful SDK
path, prepared Ubuntu builder and package version. They do not invoke
SDK creation. In that configuration, simply run the desired target.

Without the SDK include, use:

```bitbake
TEGRA_DEFAULT_KERNEL = "linux-noble-nvidia-tegra"
require conf/include/edge-ai-debs.inc
EDGE_AI_DEB_ENABLE = "1"
EDGE_AI_DEB_SDK = "/absolute/path/to/existing/Linux_for_Tegra"
EDGE_AI_DEB_BUILDER = "/absolute/path/to/ubuntu-runtime/builder"
LICENSE_FLAGS_ACCEPTED += "nvidia-argus-framos-demo"
```

The kernel selection above is required for the full matched set. The
include enables ADI integration, recipe-owned deploy exports and capsule
multiconfigs; it does not change your kernel provider or authorize/include
SDK Manager. The full set currently targets Ubuntu 24.04, NVIDIA R39.2.1
and the existing CompuLab Noble kernel ABI. Do not substitute an arbitrary
kernel or incompatible vendor baseline.

Kernel and boot-menu targets read verified original boot files from the
existing SDK's `SDK_BASELINE.json`/vendor backup. Kernel work uses a
separate SDK/rootfs copy; it never updates the original SDK, its rootfs,
archives or readiness manifest. Argus/GStreamer similarly copy the
prepared Ubuntu builder, excluding old work and transient directories.
No hardlinked build copies are used. Ensure enough free disk space.

The host needs Python 3.12+, Debian package tools, persistent ARM64 QEMU
binfmt, and the existing kernel/initrd host utilities where applicable.
Execution requires externally arranged noninteractive sudo authorization.
Do not run BitBake as root or place credentials in metadata. Missing
build dependencies are reported, not installed through host/target APT.

Optional common settings:

```bitbake
EDGE_AI_DEB_VERSION = "39.2.1+compulab1"
EDGE_AI_DEB_DEPLOY_ROOT = "${DEPLOY_DIR_IMAGE}/edge-ai-debs"
EDGE_AI_DEB_JOBS = "4"
```

Argus-specific overrides from its existing standalone recipe remain
supported; its enable, version, builder and job defaults also honor the
common settings. Other targets use a private
`${TOPDIR}/ubuntu-deb-work/${MACHINE}/<component>` directory.

## Build and outputs

```sh
bitbake edge-ai-camera-support-deb
bitbake edge-ai-gstreamer-deb
bitbake edge-ai-kernel-deb
# Or regenerate/verify the complete coordinated set:
bitbake edge-ai-debs
```

Component results:

```text
${DEPLOY_DIR_IMAGE}/edge-ai-debs/<component>/<input-fingerprint>/
  compulab-edge-ai-<component>_<version>_<architecture>.deb
  manifest.json
  SHA256SUMS
```

The metapackage is named `compulab-edge-ai`. Argus preserves its existing
`${DEPLOY_DIR_IMAGE}/edge-ai-argus-deb/<input-fingerprint>/` output path.
Each output root has an atomic `current.json` receipt pointing to the
verified result of its latest invocation. Changed inputs create new
fingerprint directories rather than overwriting published archives.

The complete set is collected under:

```text
${DEPLOY_DIR_IMAGE}/edge-ai-debs/bundle/<input-fingerprint>/
  [all nine .deb archives]
  manifest.json
  SHA256SUMS
```

The collector verifies actual archive metadata, payload hashes,
checksums, version compatibility and nonoverlapping package inventories.
It does not blindly copy archives from an old SDK package directory.
Build provenance and manifests are not claims of hardware qualification.
Failed work is retained for diagnosis, and only owned private mounts are
cleaned up. Existing publications are verified rather than overwritten.

## Installation and compatibility

Generating archives does not install them, stage a capsule, modify a
bootloader, start a service, access a DUT or reboot. Install explicitly
after reviewing compatibility and preserving a tested boot fallback.

Most existing packages require exact matching CompuLab component versions.
A same-version development rebuild can replace one compatible component;
a new release version needs a coordinated package set and metapackage.
Capsules retain their existing independently upgradeable dependency policy.
Do not increase only Argus/GStreamer/kernel versions against the old
exact-pinned metapackage. Kernel, DT and sensor/NITO changes must remain
matched even when package versions have not changed.

Kernel and GStreamer packages preserve guarded `dpkg-divert` handling.
The active extlinux menu, camera service drop-in and BSP policy settings
remain conffiles, preserving administrator edits. BSP-policy archives do
not contain a copied private hold/configuration-state snapshot: lifecycle
state belongs to the actual target and is captured there. Package scripts
do not perform nested package-manager selection writes or firmware actions.

## Offline tests

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -B -m unittest discover \
    -s recipes-devtools/edge-ai-debs/tests -v
```

Argus is maintained in this same recipe directory; see the
[Argus guide](ARGUS.md) for its application-only workflow. The test command
above now includes its safety and packaging tests too. Native build,
archive and loader validation do not qualify all sensor configurations,
boot media, encoders, UEFI updates or package upgrades on hardware.

See [validation results](VALIDATION.txt) for the real nine-package build,
archive audit, source-preservation checks and multiconfig-cache warnings.
