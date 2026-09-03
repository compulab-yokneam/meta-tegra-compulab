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

The override enables the binary logo patch for `edk2-firmware-tegra`, replacing
the 480p, 720p, and 1080p logos. BitBake applies the replacements as Git
commits, so the EDK2 source worktree remains clean.

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
