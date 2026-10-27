Edge-AI Ubuntu 24.04 / JetPack 7.2.1 runtime port (preparation bundle)
==================================================================

This directory is a source/configuration staging bundle, not an installed
SDK extension or a claim of camera hardware qualification. Nothing here
automatically runs SDK Manager, apt, flashes a device or changes an SDK tree.

runtime-port.sh defaults to check. See its --help and DEPENDENCIES.txt.
Build must run in an Ubuntu 24.04 aarch64 environment using the matching
R39.2.1 NVIDIA libraries. Stage is explicit and requires a Git baseline in
the parent Linux_for_Tegra directory. Keep the vendor kernel/boot entry as
a fallback when installing the separately rebuilt kernel and camera DTs.

cross-build-argus.sh is the explicit alternative for an x86_64 host with
an aarch64-linux-gnu compiler and an isolated Ubuntu 24.04 aarch64 sysroot.
It never installs packages into that sysroot or executes a target binary;
target-loader/relocation checks are a separate validation step. Do not use
the actual SDK rootfs concurrently with its kernel/initramfs installer.

The default minimal Argus build produces argus_camera and argus_oneshot.
The optional cross-build --suite full builds the complete 23-app image
sample set, including CUDA SM87 samples; see FULL-ARGUS.txt. Both preserve
the CompuLab application patches and keep libnvscf/libnvargus intact.

The camera's 2D compositor accepts depthless EGL configurations when they
match its realized GTK/X11 visual. Other GL renderers retain the 24-bit
depth requirement. Capture GUI cleanup also handles unsuccessful startup
and stopping without leaving freed controls attached to their parent.

The NITO files are generic uncalibrated demo profiles, not FRAMOS factory
tuning. Their original proprietary notices and provenance are included.
IMX676 extended modes default on; IMX678 extended modes default off. Keep
the chosen DT sensor-mode table and NITO profile synchronized.

Shell launcher adaptations delegate preview to an explicitly selected
Ubuntu desktop user rather than assuming a weston account. See
SESSION-ADAPTATION.txt. Capture/record remain usable without a display.

Recording accepts --encoder auto|hardware|software. Auto keeps NVENC on
Orin NX and selects CPU x264 on Orin Nano from read-only platform metadata;
unknown/conflicting metadata requires an explicit choice. This does not
enable an NX camera DT on Nano or qualify any Nano camera configuration.
See NANO-RECORDING.txt for examples, runtime dependencies and limitations.

Known validation limits: compilation and hardware-free QEMU loader/plugin
registration checks do not qualify capture, CUDA execution, displays or
multi-camera synchronization. VALIDATION.txt records initial preparation;
UBUNTU-BUILD-RESULTS.txt, when present, records the subsequent actual build
and SDK rootfs installation results.
