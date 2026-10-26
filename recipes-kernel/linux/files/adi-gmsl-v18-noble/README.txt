Edge-AI Noble kernel integration -- R39.2.1
=========================================

Purpose and provider selection
------------------------------
The layer defaults to linux-noble-nvidia-tegra, retaining the vendor 6.8.12
baseline used by JetPack 7.2.1. It remains a Yocto build: this change does
not replace the rootfs with Ubuntu or implement SDK Manager hardware entries.

An explicit local.conf setting selects either provider:

    TEGRA_DEFAULT_KERNEL = "linux-noble-nvidia-tegra"

or the unchanged Linux 6.18 fallback:

    TEGRA_DEFAULT_KERNEL = "linux-yocto"

The tegrademo distro assigns PREFERRED_PROVIDER_virtual/kernel:tegra from
TEGRA_DEFAULT_KERNEL. Its active override wins over a plain, unqualified
PREFERRED_PROVIDER_virtual/kernel assignment. The Edge-AI machine supplies
a weak Noble default, preserving an explicit TEGRA_DEFAULT_KERNEL choice
in local.conf. Other distros without that policy use the layer's weak
PREFERRED_PROVIDER_virtual/kernel default in the usual way.

Both wildcard bbappend files are symlinks to linux.inc. That shared include
continues to add compulab.cfg and export the resolved kernel configuration.
The new version-specific Noble append adds its platform fragment and, only
for edge-ai:adi-gmsl-v18, the two backport patches and ADI configuration.
The Linux 6.18 append and its original 28-patch series are not replaced.

Enable the ADI transport alone with:

    require conf/include/edge-ai-adi-gmsl-v18.inc

The FRAMOS demo/camera-menu includes already enable that override and add
their matching userspace and DT packages. IMX676 extended modes default to
1; IMX678 extended modes remain independently opt-in. Do not select new DT
modes without the matching sensor module and per-mode NITO profile.

Patch organization
------------------
0001 carries the working address-based I2C ATR implementation and header
from the Linux 6.18 integration, adapted to Noble. It includes the ADI v18
transfer/attach serialization fix, static/passthrough modes and private
alias pools. All existing TI DS90UB913/953/960 consumers are adapted rather
than disabled. The TI deserializer retains static client-bound mappings.
The patch records the source revision and retains upstream GPL notices.

0002 carries the exact ADI v18 framework/bindings plus the CompuLab routing,
MAX96793 GMSL2 pixel-mode and optional-link discovery policies already used
by the Linux 6.18 build. Noble compatibility changes cover token-valued
module namespaces, regmap bit assignment, GPIO output callbacks, I2C mux
arguments and the internal media-bus link-frequency field. These internal
kernel interfaces require rebuilding all their consumers together.

The legacy staging MAX96712 driver remains available in the source for
non-ADI configurations, but is disabled when selecting the replacement
ADI MAX96724 framework. The existing NVIDIA OOT board/camera patch queue
is shared by both providers, not duplicated into the in-tree kernel.

Development-source overrides
----------------------------
An active devtool externalsrc append bypasses normal source fetching and
patching. A successful build of an old development source tree therefore
does not prove the Noble recipe's backports were applied. Save development
work before resetting a workspace, or temporarily mask its relevant append
files while validating the normal recipes. Do not delete source trees.

For the existing build-edge-ai-nx-16g workspace, the validation configuration
masks only its Noble, NVIDIA OOT and camera-DT development appends:

    BBMASK += "/workspace/appends/(linux-noble-nvidia-tegra_6[.]8|nvidia-kernel-oot_39[.]2[.]1|edgedes-adi-v18-devicetree)[.]bbappend$"

The original workspace sources remain intact. Remove the mask only when
those development trees deliberately contain the required patch queues.

Build and deployment contract
-----------------------------
For the normal single-machine image, comment out the universal-bundle
include in local.conf and build the complete image:

    # require conf/include/edge-ai-universal-bundle.inc

    bitbake -k demo-image-weston

Keep the desired camera and UEFI capsule includes enabled. Disabling the
universal bundle removes its shared-runtime multiconfig, not independent
firmware multiconfigs requested by the capsule include.

For the universal shared runtime, build the matched set:

    bitbake mc:edge-ai-runtime:linux-noble-nvidia-tegra \
            mc:edge-ai-runtime:nvidia-kernel-oot \
            mc:edge-ai-runtime:edgedes-adi-v18-devicetree \
            mc:edge-ai-runtime:tegra-minimal-initramfs

For a non-multiconfig build, omit mc:edge-ai-runtime:. A complete image or
universal bundle rebuild is required before normal image deployment.

The Noble release retains the vendor suffix and appends -clab, with a
further -adi-v18 for this profile. It is intentionally not the SDK binary
kernel's 6.8.12-1021-tegra ABI. Never copy its modules into the stock Ubuntu
kernel's module directory or merely rename the release to force a match.
Keep Image, all in-tree/NVIDIA OOT modules, DTs, headers and initramfs
matched. Rebuild Ubuntu initramfs/boot configuration when exporting this
kernel into Linux_for_Tegra; preserve the stock kernel as a boot fallback
and protect the custom boot entry from unattended kernel-package upgrades.

Validation scope
----------------
The integration starts from the R39.2.1 Noble source revision pinned by
meta-tegra, including its two compiler-compatibility patches. Initial
host checks compile the ATR core, all three TI consumers and the full ADI
framework using the SDK's 6.8 configuration plus the required fragments.
Metadata fixtures check provider selection, gating, configuration coverage
and preservation of the existing wildcard symlinks and Linux 6.18 fallback.
The 109 shared/platform/ADI configuration requests resolve both with the
SDK configuration and with arm64 defconfig plus the recipe's five vendor
fragments. The metadata suite also exercises the real BitBake override
datastore, including tegrademo's provider precedence and local.conf fallback.
The ATR test extracts actual patched C functions and checks mapping/error
paths with address/undefined-behavior sanitizers; it does not replace kernel
logic with a separately implemented model.

On 2026-10-25, the single-machine NX16G build completed successfully with
bitbake -k demo-image-weston: 11,668 tasks, no errors. Both kernel and
NVIDIA OOT modules compiled, and image QA passed. The final configuration
resolved all 109 requests, and the generated kernel release was:

    6.8.12-l4t-r39.2.1-1021.21-clab-adi-v18

The final EXT4 and tegraflash artifacts carry timestamp 20261025225546.
The final image also includes all four configured camera boot entries.
Its rebuild fixes a pre-existing return in the extlinux Python prepend:
BitBake inlines prepend/base/append into one task, so that return previously
skipped configuration generation and retained a stale primary-only menu.
Sixteen kernel metadata and ten actual-task composition tests pass.

All 1,555 installed modules and their 73,451 imported symbol CRCs match the
effective base/NVIDIA export providers, not just any CRC in their union.
The minimal and flashing initramfs also pass their matching ABI checks.
This is build evidence, not a record of booting or testing a Noble DUT.

Successful compilation is not hardware qualification. Compare the final
resolved configuration and test Ethernet, Wi-Fi, USB, NVMe, UART, GPIO/TPM,
display, suspend/resume and required cameras/modes before promoting a new
release. Cold-start and simultaneous/mixed camera limitations from the
existing demo validation still apply. The camera DT/NITO recipes remain
NX16G-scoped; this port does not implicitly qualify NX8 camera profiles.

No running DUT is flashed or rebooted by selecting this provider. Firmware,
UEFI logo/capsule features and Ubuntu userspace porting remain separate
integration steps.
