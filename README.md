# Tegra CompuLab meta layer

## NVidia resources:
* NVidia [tegra-demo-distro](https://github.com/OE4T/tegra-demo-distro) Yocto repository.

## Prepare build environment:

* WorkDir
```
mkdir tegra-compulab && cd tegra-compulab
```

* Download Tegra CompuLab repo:
```
SRC_REV_NVIDIA="HEAD" \
SRC_REV_CLAB="master" \
source <(wget -qO - https://raw.githubusercontent.com/compulab-yokneam/meta-tegra-compulab/refs/heads/master/tools/run.me)
```

* Set environment variables:

| NVidia CompuLab Machine | Environment variable |
| --- | --- |
|`edge-ai-nx-16g`|`export MACHINE=edge-ai-nx-16g`
|`edge-ai-nx-8g`|`export MACHINE=edge-ai-nx-8g`
|`edge-ai-nano-8g`|`export MACHINE=edge-ai-nano-8g`
|`edge-ai-nano-4g`|`export MACHINE=edge-ai-nano-4g`

## Setup build environment

* Initialize the build environment:
```
source compulab-setup-env build-${MACHINE}
```

## UEFI boot logo options

The default build uses the NVIDIA UEFI boot logo. The following optional
overrides can be selected from the build's `conf/local.conf`.

To replace the NVIDIA logos with the Compulab Edge AI branding, add:

```bitbake
MACHINEOVERRIDES =. "clab_logo:"
```

The override adds and enables EDK2's `CONFIG_CLAB_LOGO` option. It selects a
dedicated `LogoClabGray` driver with `clab_gray480.bmp`, `clab_gray720.bmp`,
and `clab_gray1080.bmp` assets. The original NVIDIA logo files remain
unchanged. Scaling is disabled so the driver selects the largest native-size
logo that fits the current display. BitBake applies the source changes as a
Git commit, so the EDK2 source worktree remains clean.

To disable the UEFI boot logo completely, add:

```bitbake
MACHINEOVERRIDES =. "no_logo:"
```

The `no_logo` override disables NVIDIA's `CONFIG_LOGO` firmware option. No
NVIDIA or Compulab bitmap is embedded or displayed; the screen contains only
the normal EDK2 console messages. If both overrides are present, `no_logo`
takes precedence and the Compulab binary logo patch is not applied.

Build the firmware directly, or build an image that depends on it:

```
bitbake edk2-firmware-tegra
```

To restore the default NVIDIA logo, remove or comment out the logo-related
`MACHINEOVERRIDES` assignment and rebuild.

### Post-deployment UEFI logo update capsules

The layer can build three machine-specific bootloader capsules without
changing the logo selected for the normal OS image. Set the target machine and
include the capsule configuration in `conf/local.conf`:

```bitbake
EDGE_AI_UEFI_CAPSULE_MACHINE = "edge-ai-nx-16g"
require conf/include/edge-ai-uefi-logo-capsules.inc
```

`EDGE_AI_UEFI_CAPSULE_MACHINE` supports `edge-ai-nx-16g`, `edge-ai-nx-8g`,
`edge-ai-nano-8g`, and `edge-ai-nano-4g`; it defaults to
`edge-ai-nx-16g` when omitted.

Then build:

```
bitbake edge-ai-uefi-logo-capsules
```

The directory
`tmp/deploy/images/${MACHINE}/edge-ai-uefi-logo-capsules/` contains the three
variants prefixed by `${EDGE_AI_UEFI_CAPSULE_MACHINE}`:

* `${EDGE_AI_UEFI_CAPSULE_MACHINE}-uefi-nvidia-logo.cap`
* `${EDGE_AI_UEFI_CAPSULE_MACHINE}-uefi-clab-logo.cap`
* `${EDGE_AI_UEFI_CAPSULE_MACHINE}-uefi-no-logo.cap`
* `apply-uefi-capsule`
* `SHA256SUMS`

Copy the required capsule and `apply-uefi-capsule` to the running device, then
stage the update as root. The EFI System Partition must be mounted at
`/boot/efi`, and the device image must provide `setup-nv-boot-control`:

```
chmod +x apply-uefi-capsule
sudo ./apply-uefi-capsule <capsule-file>
sudo reboot
```

The helper installs the capsule as
`/boot/efi/EFI/UpdateCapsule/TEGRA_BL.Cap`, sets the UEFI `OsIndications`
capsule-update flag, and leaves the reboot under operator control. Firmware may
reboot a second time while switching the updated bootloader slot.

Capsules are specific to the selected `${MACHINE}`, L4T release, FMP image-type
GUID, flash layout, and signing configuration. Build them from the same release
configuration used for the deployed device. Production systems must replace
the EDK2 test certificates through `UEFI_CAPSULE_SIGNER_PRIVATE_CERT`,
`UEFI_CAPSULE_OTHER_PUBLIC_CERT`, and `UEFI_CAPSULE_TRUSTED_PUBLIC_CERT` with
the certificates trusted by their deployed firmware. A capsule contains the
complete Tegra bootloader BUP payload, not only the bitmap.

## Build targets
* demo-image-weston
```
bitbake -k demo-image-weston
```

* demo-image-full	
```
bitbake -k demo-image-full
```

## Universal Edge-AI release bundle

The universal bundle contains one shared Weston root filesystem and four
module-specific Tegra flash profiles. It supports these P3767 module SKUs:

| Module | Machine | SKU |
| --- | --- | --- |
| Orin NX 16GB | `edge-ai-nx-16g` | `0000` |
| Orin NX 8GB | `edge-ai-nx-8g` | `0001` |
| Orin Nano 8GB | `edge-ai-nano-8g` | `0003` |
| Orin Nano 4GB | `edge-ai-nano-4g` | `0004` |

Enable the supplied multiconfigs in `conf/local.conf`:

```
require conf/include/edge-ai-universal-bundle.inc
```

Then build the release archive from the normal build environment:

```
bitbake edge-ai-universal-bundle
```

The archive and its SHA-256 file are written to
`tmp/deploy/images/${MACHINE}/`. Extract the archive, put one target into USB
recovery mode, and run:

```
sudo ./flash-edge-ai.sh
```

The dispatcher reads the module EEPROM, selects the matching profile, and
flashes the shared runtime to NVMe. To inspect the detected profile without
flashing, use `sudo ./flash-edge-ai.sh --detect-only`.

The root filesystem is runtime-neutral: UEFI supplies the DTB from the selected
flash profile, while the image selects the matching NVIDIA `nvpmodel`
configuration and boot-control machine name during startup. Do not interchange
the individual profile directories manually; the QSPI/BCT payloads remain
module-specific.

## Precompiled Images
* edge-ai-nx-16g
  * [demo-image-weston](https://drive.google.com/drive/folders/1Kj6_xZBRThOyjulUS2X3prKE2pX6xgyA)
  * [demo-image-full](https://drive.google.com/drive/folders/1dG4C0DaF26InvtGSQA88-71Qc9tyARQX)
