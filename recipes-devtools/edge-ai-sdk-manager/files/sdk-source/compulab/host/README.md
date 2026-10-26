# Legacy image-wrapper compatibility

The original `compulab-l4t.env` cannot be used unchanged with this prepared
JetPack 7.2.1 / L4T R39.2.1 SDK. Its image command binds an older complete
flash helper, hardcodes NX16G, masks errors, and lacks reliable cleanup. Its
bulk support downloader would overwrite the matched board/UEFI setup.

The additive `legacy-wrapper-compat.sh` must be sourced **after** that wrapper.
It replaces `create_disk_image` and blocks the legacy bulk-update functions
`l4t_compulab_support`, `l4t_compulab`, and `Linux_for_Tegra_sdk`. It never
calls the legacy overlay functions, modifies NVIDIA scripts, or imports the
old archive. Other legacy compile/install/bootloader functions are not ported
or approved by this shim; do not use them to replace the prepared artifacts.

## Source and create

Use Bash as your normal user, with the original wrapper stored outside this
SDK. Do not extract the legacy support archive into the SDK first. Replace
only the original-wrapper path below with its actual location:

```bash
clab_sdk=/home/val/nvidia/jetpack-7.2.1-image-build
clab_sdk+=/JetPack_7.2.1_Linux_JETSON_ORIN_NX_TARGETS/Linux_for_Tegra
cd "$clab_sdk"
source /path/to/original/compulab-l4t.env
source "$PWD/compulab/host/legacy-wrapper-compat.sh"

export EDGE_AI=edge-ai-nx-16g
export BOARDSKU=-1
export EDGE_AI_UEFI_LOGO_STYLE=clab-logo
export EDGE_AI_EARLY_TTY1=0
export LOOP_DEV_SIZE_GB=32
export L4T_IMAGE=""
create_disk_image
printf '%s\n' "$L4T_IMAGE"
```

`create_disk_image` is a real host image-generation operation: it invokes
noninteractive `sudo -n`, allocates a loop backed only by a new regular image,
and uses NVIDIA's native `l4t_initrd_flash.sh --direct`. It does not flash a
connected Jetson or accept physical disk outputs. The resulting image does
not itself update the target's QSPI bootloader; that remains a separate,
explicit deployment operation. Actual image creation and hardware/partclone
restore require validation before production use. End-to-end native image
generation has **not been run**; mocked tests are not a flash validation.

Offline assumptions are BOARDID 3767 and the following reviewed profiles.
Chip values in the command environment use the full `00:00:00:Dx` form:

| EDGE_AI | SKU | Chip | FAB | BOARDREV | CHIPREV | RAMCODE_ID |
| --- | --- | --- | --- | --- | --- | --- |
| edge-ai-nx-16g | 0000 | D3 | TS4 | NVIDIA default | default | default |
| edge-ai-nx-8g | 0001 | D4 | TS4 | NVIDIA default | default | default |
| edge-ai-nano-8g | 0003 | D5 | 300 | P.1 | 0 | no override |
| edge-ai-nano-4g | 0004 | D6 | RC1 | B.4 | 0 | 4 |

The shared `platform-metadata.sh` takes Nano defaults from the existing
Yocto machine definitions and NVIDIA's R39.2.1 SKU callbacks. Nano uses
TE950M-A1 BPMP firmware, not the NX TE980M-A1 firmware. Nano8 uses the 0001
SDRAM/WB0 configuration, while Nano4 uses the 0004 configuration. The board
callback verifies the selected BPMP and memory files before proceeding.
Do not use an NX image's boot configuration unchanged on Nano.

The old wrapper unconditionally exports NX's `FAB=TS4`; it is deliberately
rejected for Nano. After sourcing both files, select a Nano like this:

```bash
unset FAB BOARDREV CHIPREV CHIP_SKU chip_SKU RAMCODE RAMCODE_ID
export BOARDSKU=-1
export EDGE_AI=edge-ai-nano-8g  # or edge-ai-nano-4g
export L4T_IMAGE=""
create_disk_image
```

Nano offline calls accept only the reviewed FAB/revision/chip defaults above;
conflicting values fail before output creation. An alternate module revision
needs a reviewed profile, not a silent substitution. No EEPROM has been read
or physical module qualified by these tests. Secure Boot/fused setups need
their own verified metadata and signing process. Regular board profiles
still allow NVIDIA's actual EEPROM/fuse discovery; these offline defaults
do not force or replace discovered module identity. This shim is not a
universal bootloader updater.

The compatibility alias `edge-ai` continues to mean NX16G only. Conflicting
`BOARDSKU`/`BOARDID` values fail. `BOARDSKU=-1` means unspecified and avoids
stale selections from the original wrapper. Nano EVK SKU 0005 is not aliased
to production Nano8G SKU 0003. Camera profiles remain qualified on NX16G
only; Nano recording must use a software encoder rather than the NX-only
hardware-encoder path. Logo options are `clab-logo`, `nvidia-logo`, `no-logo`.

## Output and size rules

- Default output is a fresh, private subdirectory of `L4T_IMAGEDIR`, normally
  `workdir/images.d`. A successful call exports the resulting `L4T_IMAGE` for
  the existing partclone API; the partclone implementation is not changed.
- To create another image, clear `L4T_IMAGE` first. Existing paths, symlinks,
  physical devices, `/dev`, `/proc`, and `/sys` outputs are refused.
- An explicit `L4T_IMAGE` must be a new absolute `.img` path in an existing
  directory owned by the caller and not writable by group/others. Root-shell
  invocation is refused. The same ownership rule applies to `L4T_IMAGEDIR`.
- `LOOP_DEV_SIZE_GB` defaults to 32. The legacy per-call `size=40
  create_disk_image` form is also supported; one size controls the whole
  operation. Values are integer GiB, 12 through 2048. The disk has `size`
  GiB, partition-layout capacity is `size-2` GiB, and APP is `size-8` GiB.
  Thus the historical defaults remain 32/30/24 GiB.
- The loop's major number, backing path, and image ownership are checked
  before writes and again before detach. Failures and HUP/INT/TERM retain
  their status and trigger cleanup. An incomplete file is retained and
  reported, never silently reused or deleted. SIGKILL/power loss cannot be
  trapped; inspect any leftover loop association manually in that case.
- Every privileged command uses `sudo -n`. A noninteractive sudo preflight
  fails before creating the image if unavailable; no password prompt is used.
  Configure suitable noninteractive authorization for the full operation.
  If credentials expire and detach is refused, the command reports failure
  and the remaining association must be inspected/cleaned up manually.
- A missing matched-kernel marker, missing board assets, or changed native
  R39 flash helper fails before loop allocation. After a deliberate BSP
  upgrade, review/update the helper checksum in the shim rather than bypass
  the guard or import an old overlay.

## Read-only validation

```bash
bash -n compulab/host/platform-metadata.sh
bash -n compulab/host/legacy-wrapper-compat.sh
bash compulab/tests/host-wrapper.sh
```

Tests mock every `sudo`/loop/native-flash invocation and use temporary regular
files only. They do not allocate loops, mount filesystems, generate an image,
contact a device, or execute NVIDIA's flash scripts.

Audited upstream wrapper revision:
`5543b4fa98f9ed7bdb584235ca051d6e8f914729` in
`compulab-yokneam/compulab-l4t` (`Linux_for_Tegra` branch). Native R39 helper
SHA256: `983153e4b80ff4b36f6e7012d11542b4216a0eb42937f54f63382a82c7328bd7`.
