# Standalone Ubuntu Argus Debian package

`bitbake edge-ai-argus-deb` rebuilds all 23 Argus applications and creates
`compulab-edge-ai-argus` for NVIDIA Ubuntu 24.04 / L4T R39.2.1. It uses the
current layer's runtime patches, including the GTK EGL and cleanup fixes.
It is not a Yocto-userspace package and is not added to `IMAGE_INSTALL`.

The recipe, helper and tests live alongside the other standalone package
targets in this directory. See the [package guide](README.md) for common
configuration and the complete `edge-ai-debs` collection.

No SDK Manager, APT, kernel, device-tree, firmware, capsule or image build
is invoked. Nothing is installed on the host, an SDK rootfs or a DUT.

## Prepared build environment

A successful `edge-ai-sdk-manager` run retains an Ubuntu ARM64 build root
with the matching NVIDIA libraries, native compiler/development packages
and CUDA 13.2.86 toolkit. This target reuses that environment as a read-only
seed. It copies the environment into separate private work, excluding old
builds and transient device/process directories. It never uses hardlinks
or compiles into the original builder.

Allow disk space for another build-root copy and the full application
build. The existing SDK workflow must not be modifying the seed during
the copy. The shared SDK lock coordinates this snapshot; active seed
mounts or incompatible Ubuntu/NVIDIA/CUDA inputs are rejected.

Host prerequisites are Python 3.11+, dpkg tools, chroot/mount utilities,
working persistent ARM64 QEMU binfmt registration, and externally arranged
noninteractive sudo authorization for the build helper. BitBake runs as
the ordinary user. No password or NVIDIA login is needed by this target;
do not put credentials in recipe metadata or configuration.

The prepared builder must already contain the full SDK runtime build
dependencies. This target deliberately does not install missing packages
or silently fall back to a Yocto sysroot. A missing/incompatible builder
must be prepared separately before using it.

## Configuration

If the existing `local.conf` already sets `EDGE_AI_SDK_ENABLE = "1"` and
the successful `EDGE_AI_SDK_HOST_WORK`, no additional setting is needed.
The defaults select `${EDGE_AI_SDK_HOST_WORK}/ubuntu-runtime/builder`.

Otherwise configure an existing, prepared build root explicitly:

```bitbake
EDGE_AI_ARGUS_DEB_ENABLE = "1"
EDGE_AI_ARGUS_DEB_BUILDER = "/absolute/path/to/ubuntu-runtime/builder"
LICENSE_FLAGS_ACCEPTED += "nvidia-argus-framos-demo"
```

The standalone recipe does not require `edge-ai-sdk-manager.inc`. That
include can remain in an existing SDK build configuration, but it is not
a dependency of this target and does not cause SDK/firmware tasks to run.
Only the pinned MMAPI source `.deb` is fetched; NVIDIA proprietary license
acceptance still applies.

Optional settings and defaults:

```bitbake
EDGE_AI_ARGUS_DEB_HOST_WORK = "${TOPDIR}/argus-deb-work/${MACHINE}"
EDGE_AI_ARGUS_DEB_OUTPUT = "${DEPLOY_DIR_IMAGE}/edge-ai-argus-deb"
EDGE_AI_ARGUS_DEB_JOBS = "4"
EDGE_AI_ARGUS_DEB_VERSION = "39.2.1+compulab1"
```

The package version defaults to `EDGE_AI_DEB_VERSION`, then
`EDGE_AI_SDK_DEB_VERSION` when set, otherwise `39.2.1+compulab1`.
Existing CompuLab metapackage and camera-support
packages require an exact Argus version. Keep that version for a local
same-version development replacement; do not increase Argus alone on a
DUT with those dependencies. A new release version requires a coordinated
package upgrade. Kernel/L4T upgrades are outside this target's scope.

## Build and output

From the configured Yocto build shell:

```sh
bitbake edge-ai-argus-deb
```

The full suite is rebuilt from pristine pinned MMAPI sources with the
current runtime patch queue. The copied Ubuntu environment runs under
QEMU, with service startup blocked and only private minimal devices.
All application ELF architectures and loader relocations are checked.

Results are published into an input-fingerprinted output directory:

```text
${DEPLOY_DIR_IMAGE}/edge-ai-argus-deb/<input-fingerprint>/
  compulab-edge-ai-argus_<version>_arm64.deb
  manifest.json
  SHA256SUMS
```

The manifest records inputs, source/bundle/environment provenance,
dependencies and payload hashes. It does not claim camera/GPU hardware
validation. Artifacts belong to the ordinary build user. Existing outputs
are verified rather than overwritten; changed inputs produce a separate
fingerprint directory. Failed private work is retained for diagnosis.
No `cleansstate`, deletion of a ready SDK or fresh SDK Manager login is
required. The task checks external build inputs on each invocation.

Copy the selected `.deb` to a compatible DUT and install explicitly:

```sh
sudo dpkg -i ./compulab-edge-ai-argus_39.2.1+compulab1_arm64.deb
dpkg -V compulab-edge-ai-argus
```

Stop existing Argus clients before replacing their executables. Package
installation does not start a camera, update a bootloader or reboot.
The target changes only the Argus application package; it does not update
NITOs, camera launchers, GStreamer plugins or device-tree sensor profiles.

## Validation

Offline safety and packaging tests:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -B -m unittest discover \
    -s recipes-devtools/edge-ai-debs/tests -p test_argus_deb.py -v
```

Those tests do not use root, an SDK Manager session or camera hardware.
Successful compilation and native loader checks still require separate
qualification on each intended sensor, port, mode and desktop setup.
See [validation results](ARGUS-VALIDATION.txt) for the actual standalone build,
package audit and unchanged-source-builder checks.
