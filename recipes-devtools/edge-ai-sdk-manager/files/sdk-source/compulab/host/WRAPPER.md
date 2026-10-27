# Sourceable CompuLab SDK wrapper

Use the SDK's new `compulab-l4t.env`, not the R36 wrapper in `/tmp` or an
old support archive. It works from any directory, locates its own SDK and
does not flash, probe USB, run sudo, mount, download, modify firmware files
or change shell options/current directory when sourced. Use a clean Bash
if the old wrapper was already loaded; the new wrapper rejects that case.

From `Linux_for_Tegra`:

```bash
source ./compulab-l4t.env
compulab_help
devshell
```

`devshell` and `simple_shell` provide the same interactive menu. Selection
and operation functions can also be called directly or from automation.
Empty selectors display menus only with a terminal; otherwise pass a value.
No operation is run automatically when loading the wrapper or its menu.

## Target and bootloader selection

```bash
select_device edge-ai-nx-16g
select_bootloader clab-logo
current_device
current_bootloader
```

Supported targets are `edge-ai-nx-16g`, `edge-ai-nx-8g`, `edge-ai-nano-8g`,
`edge-ai-nano-4g` and `auto`. The compatibility names `NX16`, `NX8`, `NA8`
and `NA4` select those four modules respectively; `device` means `auto`.
Nano8G is SKU 0003 and Nano4G is SKU 0004, correcting the old wrapper's
reversed Nano labels. `select_target` and `select_config` are aliases for
the same supported target selector, not arbitrary board-configuration loaders.

Bootloader styles are `clab-logo` (default), `nvidia-logo` and `no-logo`.
The old `logo` and `nologo` names map to CompuLab and black-screen styles.
`bl_type=nologo select_bootloader` and `dev_type=NX16 select_device` remain
accepted. Selection changes variables only; it never replaces vendor files
with one UEFI blob. The board profile chooses the complete matched general
UEFI, minimal RCM, TOS/StandaloneMM and launcher set. `no-logo` retains version
and menu text. `current_bootloader` reports the host selection, not firmware
running on a connected device. Set `EDGE_AI_EARLY_TTY1=1` for early HDMI tty1;
the default is 0.

## Customize the SDK rootfs

`customize_rootfs` opens an interactive root Bash in this SDK's
`Linux_for_Tegra/rootfs`, without requiring a connected Jetson or a target
selection. It is also an entry in `devshell`/`simple_shell`.

```bash
customize_rootfs --dry-run
sudo -v
customize_rootfs
# Make the intended changes inside the target shell, then type exit.
```

Use the normal host user, not a root host shell. Execution asks for `YES`
before entering the writable rootfs. For automation, pass `--yes` and an
explicit command after `--`; arguments are kept separate, not evaluated by
the host shell:

```bash
customize_rootfs --yes -- /usr/bin/apt-get update
customize_rootfs --yes -- /usr/bin/apt-get install -y --no-install-recommends vim
```

For compatibility with the original wrapper, `chroot_command` is supported:

```bash
chroot_command='dpkg-query -W compulab-edge-ai-argus' customize_rootfs --yes
```

That string runs through Bash inside the target rootfs, never host `eval`.
Explicit command arguments take precedence over `chroot_command`. Without
a command, actual execution requires a terminal, even with `--yes`;
`--dry-run` can preview the interactive operation without a terminal.
Preview performs read-only checks only: no sudo, mounts or target command.
The wrapper does not automatically install packages or refresh APT lists.

The helper requires Linux, Python 3.12+ mount-namespace support and either
an ARM64 host or preconfigured persistent ARM64 QEMU binfmt. It never
installs or copies an emulator into the rootfs. Temporary service-blocking
policy and resolver state are restored, and only mounts created by this
invocation are removed. It uses private runtime/device mounts rather than
exposing host disks.
Failure and signal exit statuses are reported; failed mount cleanup is not
hidden by lazy unmounts. This is a chroot for trusted root commands, **not a
security sandbox** for untrusted scripts or packages.

Only the rootfs belonging to the sourced wrapper is accepted; changing
`ROOTFS` or `L4T_ROOT` to another directory is rejected. A host-global lock
coordinates cooperating SDK builds, and an SDK-scoped lock serializes
customizers sharing that workspace, including over NFS. Do not run SDK
Manager, flashing, image generation, massflash preparation or other rootfs
operations concurrently on any host: not every native tool takes these locks.

Cleanup stops surviving child processes; do not use this command to launch
persistent background services. If cleanup reports retained
`.compulab-customize-*` backups, stop surviving processes and inspect/restore
the original files before reusing the SDK. A subsequent customization is
refused while those temporary backups remain. SIGKILL or a host/power failure
cannot run normal cleanup. Back up the rootfs first: application/configuration
changes made by your command are not rolled back when that command fails.

Changes persist in the SDK rootfs, not on a DUT or in previously generated
images, archives or `.deb` files. Regenerate the intended image after
customization. Keep CompuLab/NVIDIA BSP package holds and managed kernel,
firmware, DT and camera files intact. Ordinary extra application packages
and configuration files can be added, but managed changes must still pass
the existing checksum/ABI checks before flashing:

```bash
python3 -B "$L4T_ROOT/compulab/tools/verify-flash-inputs.py" --sdk-root "$L4T_ROOT"
```

Customization never rewrites baseline, package, integration or readiness
receipts to approve changes. The immutable `verify-sdk.py` snapshot may
report deliberate drift afterward; that does not authorize bypassing the
flash-input verifier or replacing protected BSP files piecemeal.

## Offline loop-backed image

No Jetson connection is required. Select the exact production module first:

```bash
select_device edge-ai-nano-8g  # or any of the other three supported boards
select_bootloader clab-logo
LOOP_DEV_SIZE_GB=32
L4T_IMAGE=""
create_disk_image --dry-run
sudo -v
create_disk_image
printf 'Image: %s\n' "$L4T_IMAGE"
```

The operation asks for `YES` before creating a new image. Use
`create_disk_image --yes` only when explicit noninteractive execution is
intended and sudo authorization is already available. `auto` is not an
offline board selection: the wrapper does not guess NX16G when no device
is connected. Metadata defaults are derived per board, including Nano BPMP,
memory and RAM code, without inheriting stale R36/NX environment values.

The default is a new private subdirectory of `$L4T_IMAGEDIR`, normally
`$L4T_ROOT/workdir/images.d`. A custom `$L4T_IMAGE` must be a new absolute
`.img` path in an existing, user-owned, non-group/other-writable directory.
Existing files, symlinks and host block-device paths are refused. After a
successful operation `L4T_IMAGE` identifies the completed file; reset it to
empty or select another new path before creating a second image.

Only the newly allocated, verified loop backing is written. The SDK's native
`--direct` and explicit `--external-only` paths are used, so an attached
Jetson is not flashed by offline image creation. The 32-GiB example uses a
30-GiB partition layout and a 24-GiB APP. Failed images are retained for
diagnosis; cleanup detaches only verified owned loops. This raw image does
not itself install/update a board's QSPI firmware. Partclone restore is a
separate operation; no old partclone or massflash scripts are run here.

## Connected-device flashing

Use an unfused/development module with stable power, the intended NVMe
installed and exactly one Jetson in Force Recovery mode on the host USB.
The stock layout expects a 64-GB-or-larger NVMe. Back up target data first.

```bash
select_device auto
select_bootloader clab-logo
EDGE_AI_EARLY_TTY1=1
detect_device
deploy_bootloader_rootfs --dry-run
sudo -v
deploy_bootloader_rootfs
```

**`deploy_bootloader_rootfs` overwrites QSPI firmware and the board's NVMe.**
The default board device is `nvme0n1p1`; set `COMPULAB_EXTERNAL_DEVICE` to
another board NVMe APP partition, such as `nvme1n1p1`, only when intended.
This setting never names a host disk. The wrapper prints the command and
requires `YES`, or an explicit `--yes` for unattended use. `--dry-run`
performs only read-only validation/detection, without sudo or native flashing.

Full deployment explicitly runs two native commands. `[1/2]` generates the
images with `--no-flash`; after validating fresh parameters, the selected
target/logo, NVMe layout, initrd and referenced images, `[2/2]` invokes
`--flash-only` to actually flash the board. The second command never contains
`--no-flash`. Generation, validation or device-selection failures stop before
physical flashing and report the failed phase. USB absence is retried briefly
for recovery re-enumeration; multiple or mismatched devices are rejected.

NVIDIA's APP row may have a blank filename in `flash.idx`. The deployment and
massflash validators resolve the payload using `APP_ext` in `flash.cfg` and
verify its `.sha1sum` sidecar before proceeding. They parse literal metadata
without sourcing shell code, and still reject missing APP partitions,
missing/unsafe payloads, conflicting mappings and checksum mismatches.

Both phases retain their native stdout/stderr in a private directory printed
as `Deployment logs (on this host)`. The default is
`/tmp/compulab-deploy.XXXXXXXX`, or the host's `TMPDIR` when set. Use a local
temporary filesystem on an external flashing PC. Logs are not written into
the NFS SDK, and their restricted permissions do not alter native image-file
permissions. Generation and actual flashing use `generate.log` and `flash.log`;
image checks use `images.log`. Failures retain these logs and exit statuses.
Long interactive operations may ask to renew expired sudo authorization before
phase 2; unattended operations require authorization that remains available.

For an NFS-mounted SDK, the external PC must also be able to export the
generated images for NVIDIA's initrd network-flashing stage. An export error
is separate from `--no-flash`; inspect the complete `flash.log` instead of
only the RCM-generation tail. Do not run another SDK operation concurrently
while generation and physical flashing share the generated image directories.

For QSPI-only firmware flashing, leaving the NVMe rootfs untouched:

```bash
deploy_bootloader --dry-run
sudo -v
deploy_bootloader
```

QSPI-only flashing still replaces persistent boot firmware. Make sure it is
compatible with the OS/kernel already installed; it does not update that OS.

Both deploy functions flash by default. To generate images without flashing,
add the optional `--no-flash` flag:

```bash
deploy_bootloader_rootfs --no-flash --dry-run  # Preview only
deploy_bootloader_rootfs --no-flash            # Generate, do not flash
# The same option is supported by deploy_bootloader.
```

`--no-flash` still runs the native tools, writes generated SDK files and may
read the connected module's EEPROM; it is not a dry run. Deploy commands
still require one matching recovery device. The mode is printed before the
command and confirmation. Offline massflash preparation is described below.
An inner RCM-generation `--no-flash` message is expected in phase 1; it does
not disable phase 2 unless `--no-flash` was explicitly passed to the deploy
function. The mode and both planned native commands are printed up front.

USB recovery IDs identify module candidates only. The native CompuLab board
profile still checks actual EEPROM/SKU metadata. An explicit selected target
must agree with the USB candidate; unsupported or multiple recovery devices
are rejected. Offline identity overrides, `SKIP_EEPROM_CHECK` and fuse-level
overrides are removed from physical-flash commands, not forced onto hardware.
`compulab_status`/`detect_device` read sysfs; they do not download bootloaders
or invoke `nvautoflash --print_boardid`. Device selection is rechecked before
the write command. The SDK's outer initrd tool is not a multi-device selector.

## Massflash package preparation

`prepare_massflash_boot` and `prepare_massflash_boot_rootfs` retain the old
wrapper's preparation-only behavior and default to five devices. Both always
pass `--no-flash --massflash 5`; neither programs a connected board's QSPI or
NVMe. The first builds a QSPI-only package with `--qspi-only` and
`--no-systemimg`. The second includes QSPI and the board NVMe rootfs, using
the same NVMe layout as `deploy_bootloader_rootfs`.

For preparation without a connected board, select an explicit target and
bootloader style. Preview the required package type:

```bash
select_device edge-ai-nx-16g
select_bootloader clab-logo
prepare_massflash_boot --dry-run
# Or preview a complete QSPI + NVMe package:
prepare_massflash_boot_rootfs --dry-run
```

Then run only the chosen operation, for example:

```bash
sudo -v
prepare_massflash_boot_rootfs
```

As with other operations, confirmation requires `YES`; `--yes` explicitly
allows unattended preparation. `--massflash N` changes the device limit
from five to a value between 1 and 64. For example:

```bash
prepare_massflash_boot_rootfs --massflash 8 --dry-run
```

With no recovery device, preparation uses the selected module's reviewed
offline metadata, not stale board/fuse environment overrides. If a recovery
device is present, the wrapper requires exactly one matching module and
preserves native EEPROM/fuse discovery. `select_device auto` requires that
connected device. Native preparation may communicate with it over USB; it
does not flash persistent storage. A package is for a homogeneous batch with
matching module SKU, FAB/revision, RAM code and security configuration, not
a universal NX/Nano image. Use connected discovery when the offline defaults
do not describe the intended batch.

The output is `$L4T_ROOT/mfi_<target>/` and the corresponding
`mfi_<target>.tar.gz`. Both package types and all logo styles use those same
native names. Existing directories, archives and symlinks are refused;
preserve or move both old outputs before preparing another package for that
target. Failed outputs are retained for diagnosis. The wrapper finalizes the
new package with a minimal prebuilt-only board configuration and repacks its
archive, so deployment does not depend on the full SDK's CompuLab source
includes. The original SDK board configuration is not replaced.

Preparation is serialized against another wrapper massflash preparation.
Do not run SDK Manager, native flashing or loop-image creation concurrently
in the same SDK: they share generated bootloader and image directories.
Actual massflash deployment is a separate, destructive operation; follow the
README inside the prepared package. These functions do not import or invoke
the old `deploy_massflash` function or source the legacy file in `/tmp`.

The R39.2.1 native generator reuses its initrd extraction directory between
device slots. That makes slot 1 fail after slot 0 with `mkdir: ... File exists`
and can retain the previous slot's configuration. SDK preparation applies a
version/hash-checked patch giving every initrd build a fresh subdirectory.
The original script is preserved under `compulab/patches/`; unexpected script
changes are rejected rather than overwritten. Preflight verifies the exact
reviewed patched script and the original backup. Failed temporary work is
retained when the native `--keep` option is used; no old work is deleted by
the fix.

## Validation and limits

Image/flash preflight uses `compulab/tools/verify-flash-inputs.py` to check SDK
integrity and the selected matched firmware set. NVIDIA's normal flash flow
regenerates the runtime/recovery initrds and adds resolved root arguments to
the live extlinux menu. The flash-input check therefore validates initrd
payloads and matching copies rather than requiring the original compressed
archive hash. Static kernel/module/DT/firmware inputs keep their checksum and
ABI checks. Snapshot manifests are not refreshed or bypassed: the separate
`verify-sdk.py` still describes the initial prepared snapshot and can report
expected archive/menu changes after flashing. Native tools and the old
bulk-download/update paths are not bind-mounted. The only native-script
change is the reviewed massflash initrd-isolation patch described above;
the old bulk-download/update paths remain disabled.

Read-only input verification supports NFS-mounted SDKs whose server and
client users have different numeric UIDs. Checksums, canonical paths and
link checks still apply; checking valid input bytes does not require local
ownership. The package finalizer also accepts foreign-owned read-only
inputs preserved by native copying, while enforcing ownership on the new
package directory, profile and archive it modifies.

Write operations still require suitable NFS permissions and authorization.
In particular, massflash preparation's shared lock must be accessible to the
invoking user. Align numeric UIDs/GIDs on the participating hosts when sharing
that writable workspace; matching account names alone is not sufficient.
Do not run `devshell` as root or recursively change SDK ownership to bypass
these guards. Applying or replacing the native fix remains an owner-checked
operation, separate from read-only verification.

Standard unencrypted single-rootfs NVMe images/flashes are supported here.
Rootfs A/B, encryption, production/fused signing keys, backup/restore,
partclone, manufacturing services and actual massflash deployment remain
separate reviewed workflows. Old kernel compile/install commands remain
unsupported. `customize_rootfs` uses the new guarded helper, not the R36
mount/copy/cleanup implementation.

Mock tests exercise passive loading, all selections, offline loop ownership,
command construction, confirmations, USB ambiguity, metadata isolation and
failures without running sudo, a real loop or a flash. End-to-end raw-image
creation, massflash preparation/deployment and physical flashing still
require testing on the actual setup.

Rootfs customization tests also cover temporary-file restoration, private
mount ownership, signals, terminal handoff, locks and descendant cleanup
using fixtures and mocked privileged operations. Read-only preflight was
checked against a prepared SDK; these tests do not execute a real privileged
chroot or install packages into that SDK.
