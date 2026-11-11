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
source <(wget -qO - https://raw.githubusercontent.com/compulab-yokneam/meta-tegra-compulab/refs/heads/jetpack-7.2-blacksail/tools/run.me)
```

The bootstrap script uses a tested integration baseline by default. It checks
out detached revisions of `tegra-demo-distro`, `meta-tegra-compulab`, and
`meta-browser`; the `tegra-demo-distro` commit in turn pins BitBake, OE-Core,
`meta-tegra`, and its other submodules. Existing repositories are fetched but
never pulled or merged, and the script refuses to change a repository that has
tracked modifications.

Every default can be overridden with a branch, tag, or complete commit ID. Use
complete commit IDs for reproducible builds:

```
SRC_REV_NVIDIA="<tested-tegra-demo-distro-commit>" \
SRC_REV_CLAB="<tested-meta-tegra-compulab-commit>" \
SRC_REV_BROWSER="<tested-meta-browser-commit>" \
source <(wget -qO - https://raw.githubusercontent.com/compulab-yokneam/meta-tegra-compulab/refs/heads/jetpack-7.2-blacksail/tools/run.me)
```

Using `HEAD` or a branch name is intended only for development because the
resolved commit can change between invocations. The script prints the exact
commit selected for each repository so it can be recorded with build results.

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

## Distro compatibility and revision updates

`LAYERSERIES_COMPAT_meta-tegra-compulab` identifies the Yocto release series
whose metadata interfaces this layer has been tested against. It does not pin
the source repositories and must not be extended merely to silence a layer
compatibility error.

The default revisions in `tools/run.me` are the current known-good integration
lock. Do not move them automatically to the newest upstream commits. Update the
three revisions together in a dedicated change, then validate the new
combination before making it the default. Keep the CompuLab revision in
`scripts/meta-tegra-compulab.xml` synchronized with the corresponding
`SRC_REV_CLAB` default.

At minimum, check that every append still has a matching recipe and that all
metadata parses:

```
bitbake-layers show-appends
bitbake -p
```

Force the patch tasks for recipes whose upstream source layout is extended by
this layer:

```
bitbake -f -c patch edk2-firmware-tegra
bitbake -f -c patch nvidia-kernel-oot
bitbake -f -c patch tegra-minimal-init
bitbake -f -c patch wasi-sdk-toolchain-native
```

Then build the primary integration targets:

```
bitbake -k edge-ai-universal-bundle
bitbake edge-ai-uefi-update-image
```

The universal bundle exercises the shared runtime and the four module-specific
flash profiles. Before publishing a new baseline, also test NVMe flashing and
UEFI capsule updates on the applicable hardware. Tag the resulting
`meta-tegra-compulab` commit so downstream builds can select a stable layer
revision instead of a moving branch.

## Carrier peripheral options

The layer ports the missing carrier features from the
[edge-ai-linux devel DTS patches](https://github.com/compulab-yokneam/edge-ai-linux/tree/devel/patches/dts)
and their matching
[kernel patches](https://github.com/compulab-yokneam/edge-ai-linux/tree/devel/patches/kernel).
The RK628 CSI bridge, dedicated RS-485 UART, and external-watchdog driver
ports target the Noble NVIDIA 6.8 kernel. They are not added to this branch's
default Linux 6.18 kernel. The expansion board uses the existing PCA953x GPIO and
ISL1208/ISL1219 RTC drivers; PAL capture uses the standard ADV7180/ADV7280 driver.

To use these driver ports with the `tegrademo` distro, select Noble in
`conf/local.conf` and deploy its matching kernel and modules together:

```bitbake
TEGRA_DEFAULT_KERNEL = "linux-noble-nvidia-tegra"
```

Normal images include `nvidia-kernel-oot-dtb`, `nvidia-kernel-oot-dtbo`, and
the kernel modules. Optional peripherals remain unselected until the matching
hardware is fitted. The default device tree and USB OTG role remain available.

### Fixed USB recovery-port roles

Each supported module has two additional DTBs:

```
tegra234-p3768-0000+p3767-<SKU>-nv-super-host.dtb
tegra234-p3768-0000+p3767-<SKU>-nv-super-device.dtb
```

Use SKU `0000` for NX 16 GB, `0001` for NX 8 GB, `0003` for Nano 8 GB, or
`0004` for Nano 4 GB. The reference series' `0005` variants are also built.
These variants inherit the module's Super base DTB and its compatibility,
identity, PCIe, and USB PHY fixes. The host variant also disables XUDC so the
gadget driver cannot claim the recovery port.

For example, select the NX 16 GB host variant in `local.conf`:

```bitbake
FDT_FILE = "tegra234-p3768-0000+p3767-0000-nv-super-host.dtb"
```

The variants are installed under `/boot/dtb` for selection on a running
system with `edge-ai-select-fdt`. Use `FDT_FILE`, rather than overriding
`UBOOT_EXTLINUX_FDT`, to retain the package ownership described above.

### Expansion board, RS-485, and camera overlays

The following overlays are installed under `/boot/devicetree`:

| Overlay | Hardware and driver |
| --- | --- |
| `tegra234-edge-ai-eb-edgerpi4.dtbo` | PCA9555 at I2C address `0x20` and ISL1219 RTC at `0x6f` on `hdr40_i2c1` |
| `tegra234-edge-ai-rs485.dtbo` | Dedicated RS-485 driver on UART `3110000`, alias `serial3`, device name `ttyTHSRS485<n>` |
| `tegra234-camera-HDMI-rk628.dtbo` | RK628 HDMI-to-CSI adapter, CSI port 2, four data lanes |
| `tegra234-camera-PAL-adv280-m.dtbo` | ADV7280-M PAL-to-CSI adapter, CSI port 0, one data lane; filename retained from the reference series |
| `tegra234-edge-ai-watchdog-template.dtbo` | Disabled external-watchdog template with no GPIO assignments |

Select overlays against an explicit base DTB for the fitted module. For
example, an NX 16 GB with the expansion board and RS-485 interface uses:

```bitbake
FDT_FILE = "tegra234-p3768-0000+p3767-0000-nv-super.dtb"
FDT_OVERLAYS = "tegra234-edge-ai-eb-edgerpi4.dtbo tegra234-edge-ai-rs485.dtbo"
```

Select exactly one of the HDMI/PAL overlays for camera capture. These use
the same VI channel and must not be combined with each other or with an
EDGEDES camera profile without a separately validated routing configuration.
For PAL, the normal V4L2 standard-selection controls remain available; the
driver's defaults are not changed globally for other ADV7180-family devices.

The RS-485 overlay uses only the dedicated compatible string, avoiding a
race with the ordinary Tegra UART driver. Applications configure direction
control through the standard `TIOCSRS485` interface. Ordinary UART behavior
is retained when this overlay is not selected.

### External watchdog

The `gpio_wdt_ext` module supports separate `ping-gpios` and `enable-gpios`.
The reference DTS explicitly marks its GPIO assignments as draft. The supplied
template therefore leaves `watchdog-ext` disabled and does not change the
board model or claim any GPIOs. Add confirmed GPIO assignments to a custom
overlay before changing that node's status to `okay`; its remaining binding
properties are `compatible = "linux,wdt-gpio-ext"`, `hw_algo = "toggle"`,
and `hw_margin_ms = <1600>`.

### Build and verify

```sh
bitbake demo-image-weston
```

Deploy the rebuilt kernel, modules, and selected DTBs/overlays together.
A UEFI capsule alone can update the firmware DTB, but does not install these
new Linux drivers or select optional rootfs overlays on an existing system.
For Ubuntu, regenerate the matched CompuLab kernel and device-tree packages
and install them using the package workflow before selecting the overlays.

After boot, verify the selected tree and available devices:

```sh
edge-ai-select-fdt --show
gpiodetect
ls /sys/class/rtc
ls /dev/ttyTHSRS485*
v4l2-ctl --list-devices
media-ctl -p
```

Hardware capture, RS-485 direction timing, and watchdog operation require
testing with the corresponding adapters fitted.

## PCIe lane configuration

Edge-AI selects `gbe-uphy-config-9,hsstp-lane-map-3,hsio-uphy-config-0`
in ODMDATA. The carrier DTS must match that firmware lane allocation:

| Controller | DT node | Configuration |
| --- | --- | --- |
| C1 | `pcie@14100000` | M.2 Key E, x1 on HSIO lane 3 |
| C4 | `pcie@14160000` | M.2 Key M, x4 on HSIO lanes 4–7 |
| C7 | `pcie@141e0000` | x1 on GBE lane 0 |
| C9 | `pcie@140c0000` | x1 on GBE lane 1 |
| C10 | `pcie@140e0000` | Disabled; not exposed as a general-purpose port on Orin NX/Nano |

The PCIe carrier patch sets C7/C9 lane counts and PHY references explicitly.
Setting only `status = "okay"` on the SoC nodes leaves C9/C10 without the
`phy-names` and `phys` properties required by the driver. Do not allocate a
second GBE lane to C7 while selecting the split C7/C9 firmware configuration.
See NVIDIA's [Orin NX/Nano PCIe and UPHY documentation](https://docs.nvidia.com/jetson/archives/r39.2.1/DeveloperGuide/HR/JetsonModuleAdaptationAndBringUp/JetsonOrinNxNanoSeries.html).

For an Intel AX210 in M.2 Key E, diagnose C1 separately. A `Phy link never
came up` message occurs before the card can enumerate and bind to the Intel
Wi-Fi driver. Correcting C7/C9/C10 does not establish that the AX210 link
works. Compare the failing and known-good firmware with the same card fitted,
including a full power-off test, and collect:

```sh
lspci -nn -tv
dmesg | grep -iE 'pcie|pci |iwlwifi|regulator'
```

Check the active device tree and the flashed pinmux/BCT configuration together
with the card's 3.3 V supply, PERST#, reference clock, and CLKREQ# signals.
Validate the running tree after deploying a rebuilt firmware capsule because
the default boot path uses a UEFI-provided DTB.

## USB 3 host PHY configuration

The Edge-AI device-tree patches enable the third SuperSpeed port (`usb3-2`)
and include its lane in the XUSB host controller's `phys` and `phy-names`.
Enabling only the padctl port and lane is insufficient: Linux must acquire
and initialize the PHY through the host controller as well.

After changing these patches, rebuild the image and deploy the regenerated
flash package using the flashing procedure below:

```sh
bitbake demo-image-weston
```

To test the fix through a boot-firmware update while retaining the installed
OS, enable `conf/include/edge-ai-uefi-update-capsules.inc` in `local.conf` and
build only the removable update image:

```sh
bitbake edge-ai-uefi-update-image
```

The complete capsules include the bootloader device tree. Follow
[Removable UEFI update media](#removable-uefi-update-media) to apply one matching
capsule, then boot the installed OS and check its running tree and `lsusb -t`.

The default boot path uses a UEFI-provided device tree. Replacing a DTB under
`/boot` alone does not select it. Verify the selected tree with
`edge-ai-select-fdt --show`; in the running tree, the host controller at
`/bus@0/usb@3610000` must list `usb3-2` in `phy-names` and reference its lane
in `phys`. Use `lsusb -t` to verify downstream SuperSpeed enumeration after
deployment; the presence of a SuperSpeed root hub alone is insufficient.

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

To suppress vendor branding while retaining the UEFI boot display, add:

```bitbake
MACHINEOVERRIDES =. "no_logo:"
```

The `no_logo` override keeps EDK2's logo/display path and
`CONFIG_DISPLAY_BOOT_INFO` enabled, but substitutes a full-screen black bitmap.
No NVIDIA or Compulab artwork is displayed, while the firmware version and
F11/ESC boot-menu prompts remain visible. If both overrides are present,
`no_logo` takes precedence and the Compulab binary logo patch is not applied.

Build the firmware directly, or build an image that depends on it:

```
bitbake edk2-firmware-tegra
```

To restore the default NVIDIA logo, remove or comment out the logo-related
`MACHINEOVERRIDES` assignment and rebuild.

### Early HDMI tty1 console

By default, the NVIDIA Orin kernel command line contains `video=efifb:off`.
This disables the framebuffer supplied by the UEFI Graphics Output Protocol,
so the HDMI virtual console cannot display kernel messages until the NVIDIA
DRM driver has initialized.

Enable an early HDMI `tty1` console in `conf/local.conf` with:

```bitbake
MACHINEOVERRIDES =. "early_tty1:"
```

The override removes `video=efifb:off`, changes the virtual-terminal console
from `tty0` to `tty1`, and adds `fbcon=nodefer`. The serial `ttyTCU0` console
remains enabled. It applies to both the L4TLauncher `extlinux.conf` used by
flashed images and the GRUB command line generated for removable WIC images.

Rebuild and deploy the OS image so that its boot configuration is regenerated;
rebuilding only `edk2-firmware-tegra` or a UEFI capsule is not sufficient. The
monitor must be attached while UEFI starts, and UEFI must successfully create
a GOP framebuffer. A display mode change can occur later when NVIDIA DRM takes
ownership of the display.

### Post-deployment full UEFI update capsules

The layer can build a universal set of complete, module-specific boot-firmware
capsules without changing the firmware selected for the normal OS image. The payload includes
the Wrynose boot firmware, UEFI, firmware device trees, and other boot-chain
components generated by `tegra-uefi-capsules`; it is not a bitmap-only update.

Include the capsule configuration in `conf/local.conf`:

```bitbake
require conf/include/edge-ai-uefi-update-capsules.inc
```

Then build:

```
bitbake edge-ai-uefi-update-capsules
```

The old `edge-ai-uefi-logo-capsules` name remains available as a compatibility
target. Each capsule multiconfig sets `EDGE_AI_UEFI_LOGO_STYLE` directly; it
does not modify `MACHINEOVERRIDES`. The latter remains only the normal-image
and `local.conf` interface described above.

The directory
`tmp/deploy/images/${MACHINE}/edge-ai-uefi-update-capsules/` contains three
complete boot-firmware variants for each supported module:

* `edge-ai-nx-16g-uefi-{nvidia-logo,clab-logo,no-logo}.cap`
* `edge-ai-nx-8g-uefi-{nvidia-logo,clab-logo,no-logo}.cap`
* `edge-ai-nano-8g-uefi-{nvidia-logo,clab-logo,no-logo}.cap`
* `edge-ai-nano-4g-uefi-{nvidia-logo,clab-logo,no-logo}.cap`
* `apply-uefi-capsule`
* `SHA256SUMS`

Each module-specific BUP is generated using the exact board ID and SKU. Before
the BUP is wrapped in a capsule, its image-entry TNSPEC metadata is cleared.
NVIDIA EDK2 accepts an empty TNSPEC without applying its token-count-sensitive
platform comparison, so the same capsule accepts the current CompuLab machine
name, historical `edge-ai` names, NVIDIA devkit names such as
`jetson-orin-nano-devkit-super`, and other earlier target names. Always use
`edge-ai-uefi-update` to stage these capsules: it retains the hardware safety
check by selecting the payload from the module board ID and SKU.

Copy the required capsule and `apply-uefi-capsule` to the running device, then
stage the update as root. The EFI System Partition must be mounted at
`/boot/efi`, contain `EFI/BOOT/BOOTAA64.EFI`, and the device image must provide
`efibootmgr` and `setup-nv-boot-control`:

```
chmod +x apply-uefi-capsule
sudo ./apply-uefi-capsule <capsule-file>
sudo reboot
```

The helper installs the selected full boot-firmware capsule as
`/boot/efi/EFI/UpdateCapsule/TEGRA_BL.Cap`, sets the UEFI `OsIndications`
capsule-update flag, and creates a `BootNext` entry pointing to that ESP. The
explicit `BootNext` is required because EDK2 capsule-on-disk discovery searches
only the ESPs referenced by `BootNext` and `BootOrder`; a removable device
started through the fallback `EFI/BOOT/BOOTAA64.EFI` path is not necessarily in
`BootOrder`. The dedicated entry is created without adding it to persistent
`BootOrder`, and the reboot remains under operator control. Firmware consumes
`BootNext` and may reboot a second time while switching the updated bootloader
slot.

#### Updating a deployed Ubuntu system with Debian packages

On an already deployed CompuLab Ubuntu system, `compulab-edge-ai-boot-tools`
provides `edge-ai-uefi-update` and the supporting boot helpers. The firmware
payloads are supplied separately by `compulab-edge-ai-uefi-capsules`. Use the
newly rebuilt capsule package containing the desired device-tree changes.

Copy the compatible `.deb` archives to the target. From their directory,
install them using the package version in the archive filenames, for example:

```sh
package_version=39.2.1+compulab1
sudo apt install --reinstall \
    "./compulab-edge-ai-boot-tools_${package_version}_all.deb" \
    "./compulab-edge-ai-uefi-capsules_${package_version}_all.deb"
```

`--reinstall` also installs a development rebuild whose package version is
already installed. Use the actual version of the supplied archives.

The boot-tools package requires matching CompuLab kernel and device-tree
package versions. Supply those compatible packages if they are not already
installed or available from the configured package repository. These are
Ubuntu packages; this method is separate from installing packages in a Yocto
root filesystem.

Installing the archives updates files but does not stage a firmware update
or reboot. With the EFI System Partition mounted at `/boot/efi`, explicitly
stage one logo variant and reboot:

```sh
sudo edge-ai-uefi-update clab-logo
sudo reboot
```

Use `nvidia-logo` or `no-logo` instead to select another variant. The helper
checks the module board ID/SKU and capsule checksums before staging. After
the update, boot the installed OS, confirm the running device tree includes
the corrected USB host PHY reference, and check downstream enumeration with
`lsusb -t`. If boot-tools is already installed and compatible, updating only
`compulab-edge-ai-uefi-capsules` is sufficient before running the helper.

#### Removable UEFI update media

The `edge-ai-uefi-update-image` target creates a small, bootable removable-media
image containing the kernel, initramfs, EFI bootloader, NVIDIA boot-control
support, update helper, and all twelve complete UEFI capsule variants. It does
not contain the normal graphical or application stack. `MACHINE` determines
only the kernel and boot files used by the removable image itself:

```bitbake
MACHINE = "edge-ai-nx-16g"
require conf/include/edge-ai-uefi-update-capsules.inc
```

Build the image with:

```
bitbake edge-ai-uefi-update-image
```

The deploy directory contains a compressed `*.wic.zst` disk image and its
`*.wic.bmap`. Write them to the whole removable device, not to one of its
partitions. The selected device is overwritten, so verify it carefully:

```
sudo bmaptool copy \
    --bmap edge-ai-uefi-update-image-<machine>.rootfs.wic.bmap \
    edge-ai-uefi-update-image-<machine>.rootfs.wic.zst /dev/sdX
```

Boot the USB drive or SD card from the UEFI boot menu. The serial console logs
in as root without a password. The media never updates firmware automatically;
select exactly one variant after checking that the media matches the module:

```
edge-ai-uefi-update nvidia-logo
edge-ai-uefi-update clab-logo
edge-ai-uefi-update no-logo
reboot
```

The update root filesystem has its own `uefi-update` GPT partition name and
boots by the PARTUUID generated into its GRUB configuration. Its initramfs is
instructed to honor that explicit root device instead of probing for an `APP`
partition, so an internal system disk may remain installed while the removable
update media is used.

The command reads `TegraPlatformCompatSpec` (falling back to
`TegraPlatformSpec`), identifies the module from board ID and SKU, and selects
the matching module-specific capsule. The installed target-name portion of the
TNSPEC does not affect runtime selection. It then verifies all capsule
checksums, stages the selected file, registers the removable ESP as a UEFI boot
option without changing persistent `BootOrder`, and verifies that `BootNext`
selects it. Keep the removable media connected until capsule processing and
any additional firmware-initiated reboot have finished. For firmware built
with a custom legacy FMP image-type GUID, pass that GUID as the second argument,
for example:

```
edge-ai-uefi-update clab-logo 11111111-2222-3333-4444-555555555555
```

#### Upgrading firmware from an earlier release

The standard full UEFI configurations for Orin in L4T R35/R36 (including the
Scarthgap L4T R36.5.0 build) and the Wrynose R39 general configuration use FMP
image-type GUID `bf0d4599-20d4-414e-b2c5-3595b1cda402`. Earlier CompuLab
firmware can record `edge-ai`, a complete CompuLab machine name, or an NVIDIA
devkit name as its platform TNSPEC target. NVIDIA firmware requires the BUP
and installed specifications to have the same number of hyphen-delimited
tokens even when individual empty tokens are used as wildcards. That makes a
target-name-only wildcard unreliable because target names contain different
numbers of hyphens. Each capsule therefore has empty image-entry TNSPEC
metadata, while `edge-ai-uefi-update` supplies the hardware compatibility
check using the module board ID and SKU.
For example,
`3767--0001--1--jetson-orin-nano-devkit-super-` selects the
`edge-ai-nx-8g` capsule.

If an earlier product firmware was built with a custom FMP image-type GUID,
list it before building:

```bitbake
EDGE_AI_UEFI_LEGACY_FMP_GUIDS = "11111111-2222-3333-4444-555555555555"
```

The bundle will additionally contain files ending in
`-from-<legacy-guid>.cap`. Use that file only on a device whose running
firmware advertises the matching legacy GUID. Do not put the current standard
GUID in `EDGE_AI_UEFI_LEGACY_FMP_GUIDS`, because the normal capsule already
uses it.

By default, Wrynose sets the capsule and installed firmware's lowest-supported
version to its own L4T version. The upgrade is therefore one-way. A product
that intentionally permits rollback to Scarthgap R36.5.0 can opt in with:

```bitbake
EDGE_AI_UEFI_LOWEST_SUPPORTED_VERSION = "0x00240500"
```

Lowering this value weakens rollback protection and should be done only when
the product security policy requires it.

Capsules remain specific to the detected module SKU, flash layout,
FMP image-type GUID, and signing configuration. An earlier firmware must
already support capsule updates and trust the certificate used to sign the new
capsule. This mechanism cannot migrate a cboot-era or capsule-disabled device.
For a major L4T transition, deploy an OS/kernel compatible with the Wrynose
boot firmware; continuing to run an arbitrary older OS after updating only the
boot chain is not a supported compatibility guarantee.

Production systems must replace the EDK2 test certificates through
`UEFI_CAPSULE_SIGNER_PRIVATE_CERT`, `UEFI_CAPSULE_OTHER_PUBLIC_CERT`, and
`UEFI_CAPSULE_TRUSTED_PUBLIC_CERT` with the certificates trusted by deployed
firmware. Test the update and A/B recovery behavior on every supported module
SKU before field deployment.

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

The universal bundle contains one shared Weston root filesystem, four
module-specific Tegra flash profiles, and the complete UEFI update capsule
package. The installed `edge-ai-uefi-update` command can select the appropriate
module and logo capsule at runtime. The bundle supports these P3767 module
SKUs:

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
`tmp/deploy/images/${MACHINE}/`.

### Installing the image on the board NVMe

The default flash target is the NVMe physically installed in the Edge-AI
board. It is not a `/dev/nvme*` device belonging to the build host. Prepare and
flash it as follows:

1. Power off and disconnect the board before installing or replacing its NVMe.
   Install a compatible NVMe module securely in the board NVMe socket. The
   drive must be large enough for the generated partition layout; it does not
   need to be formatted or partitioned in advance.

2. Extract the universal archive on a Linux host. Preserve its directory
   layout, executable permissions, and symbolic links:

   ```
   tar --zstd -xf demo-image-weston-edge-ai-universal-*.tar.zst
   cd demo-image-weston-edge-ai-universal-*
   ```

3. Put the board into USB recovery mode using the recovery procedure for the
   carrier board, connect its recovery USB port to the host, and power it on.
   Only one recovery-mode NVIDIA target should be connected. Detection can be
   checked without modifying either the NVMe or boot firmware:

   ```
   sudo ./flash-edge-ai.sh --detect-only
   ```

   The command must report the module SKU and one of the four supported
   `edge-ai-*` profiles before flashing is attempted.

4. Flash the board-installed NVMe and the matching QSPI boot firmware:

   ```
   sudo ./flash-edge-ai.sh
   ```

   This erases and repartitions the board NVMe. Do not remove power, disconnect
   USB, or leave recovery mode until the command reports successful completion.
   The dispatcher reads the module EEPROM, selects the matching flash profile,
   boots the flashing initrd over USB, and writes the NVMe known inside the
   target as `nvme0n1` (`nvme0n1p1` is its boot partition). No host block-device
   argument is required.

5. After a successful flash, power off the board, remove the force-recovery
   condition, and power it on again. UEFI should then boot the newly installed
   system from NVMe. If flashing fails, inspect the newest
   `profiles/<selected-machine>/log.initrd-flash.*` file.

The normal command updates both the NVMe and the module-specific QSPI boot
firmware. If compatible boot firmware is already installed, write only the
board NVMe with:

```
sudo ./flash-edge-ai.sh -- --external-only
```

The `--external-only` option refers to the NVMe installed in the board; it does
not select storage connected directly to the host.

### Writing host-connected media

Writing an NVMe or USB storage device connected directly to the build host is
still available, but must be requested explicitly:

```
sudo ./flash-edge-ai.sh --host-device /dev/sdX
```

Replace `/dev/sdX` with the host name of the intended device. Verify the name
and contents carefully before confirming the operation; the selected host
device is erased and overwritten. Never use the host system disk.

The root filesystem is runtime-neutral: UEFI supplies the DTB from the selected
flash profile, while the image selects the matching NVIDIA `nvpmodel`
configuration and boot-control machine name during startup. Do not interchange
the individual profile directories manually; the QSPI/BCT payloads remain
module-specific.

## Docker with the NVIDIA runtime

`demo-image-weston` includes Docker and the NVIDIA Container Toolkit through
this layer's image bbappend. See the [Docker how-to](recipes-demo/images/DOCKER.md)
for layer requirements, build instructions, and target validation.

## Precompiled Images
* edge-ai-nx-16g
  * [demo-image-weston](https://drive.google.com/drive/folders/1Kj6_xZBRThOyjulUS2X3prKE2pX6xgyA)
  * [demo-image-full](https://drive.google.com/drive/folders/1dG4C0DaF26InvtGSQA88-71Qc9tyARQX)
