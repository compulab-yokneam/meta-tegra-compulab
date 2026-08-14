# Why balenaOS Updates the Jetson Bootloader

BalenaOS needs a separate bootloader update on Jetson because the early boot
firmware is stored in QSPI, outside the normal balenaOS root filesystem update
mechanism.

A host OS update replaces the root filesystem slots, but it does not
automatically replace:

- MB1 and MB2 configuration
- UEFI firmware
- The bootloader device tree
- Pinmux and pad-voltage BCT data
- Other QSPI partition contents

For Edge-AI machines, these components contain carrier-specific device-tree,
BCT, pinmux, and UEFI logo changes. Updating only the root filesystem can leave
old or generic NVIDIA firmware in QSPI.

## Bootloader-update triggers

There are two separate paths that can request an update in this repository.

### 1. First-boot QSPI manager

`jetson-qspi-manager.service` runs during boot using:

```ini
ExecStart=/bin/sh -c '/usr/bin/jetson-qspi-manager -u'
```

Its update decision is based on whether `/dev/mtd0` exists:

```text
/dev/mtd0 exists    -> QSPI is accessible; skip the normal update
/dev/mtd0 missing   -> QSPI is inaccessible; prepare a capsule update
```

This path does not compare the installed and required bootloader versions. It
also does not compare the installed firmware with the capsule hash or inspect
whether the QSPI contents are Edge-AI-specific. It exists primarily to
initialize or recover access to QSPI.

A forced invocation can request an update even when `/dev/mtd0` exists:

```sh
bash -c '
    source /usr/libexec/jetson-qspi-helpers
    try_capsule_update /mnt/boot /mnt/boot force
'
```

### 2. Hostapp-update hook

The Edge-AI machines reuse the NVIDIA Orin NX and Nano hostapp-update hooks:

```bitbake
HOSTAPP_HOOKS:append:edge-ai-nx = " \
    99-resin-bootfiles-orin-nx-xavier-nx-devkit \
"

HOSTAPP_HOOKS:append:edge-ai-nano = " \
    99-resin-bootfiles-orin-nano-devkit-nvme \
"
```

These hooks obtain the current firmware version with:

```sh
nvbootctrl dump-slots-info
```

The version check establishes only whether the installed firmware is a
supported source for the update. Firmware versions 35.5, 36.3, 36.4, and 36.5
are accepted by the current NX and Nano hooks.

After validating the source version, the hooks unconditionally call their
`do_capsule_update` function. Therefore, an applicable hostapp update prepares
a bootloader capsule even when the currently installed firmware already reports
L4T 36.5.

There is currently no equivalent of:

```text
installed bootloader equals required bootloader -> skip update
```

The firmware-version test is a compatibility check, not a test of whether an
update is needed.

## Edge-AI initial-flash consideration

The Edge-AI `tegra-flash-dry` metadata currently includes this warning:

```text
FIXME: Replace this generic developer-kit blob with a validated Edge-AI QSPI
image generated using the CompuLab pinmux and flash variables.
```

Both Edge-AI families currently select:

```bitbake
BOOTBLOB = "boot0_orin_nano_devkit_nvme_super.img.gz"
```

This is a generic developer-kit boot blob. An initially provisioned device can
therefore have generic QSPI firmware while its root filesystem is already
Edge-AI-specific. Applying the Edge-AI capsule is currently the mechanism for
replacing that generic QSPI content with the carrier-specific firmware.

## Determine which path requested an update

Inspect the first-boot manager:

```sh
systemctl status jetson-qspi-manager
journalctl -u jetson-qspi-manager --no-pager
```

Messages similar to these indicate the QSPI manager path:

```text
QSPI is inaccessible
Attempt 1: The QSPI will be updated on the next boot
```

Inspect the complete journal for hostapp-hook messages:

```sh
journalctl --no-pager |
    grep -Ei 'Bootloader blob|Will extract UEFI Capsule|OsIndications|hostapp'
```

Messages similar to these indicate the hostapp-update hook:

```text
Bootloader blob is ...
Firmware version ... is suitable for Jetpack 6 upgrade
Will extract UEFI Capsule...
OsIndications variable written
```

Other useful checks are:

```sh
test -e /dev/mtd0 && echo 'QSPI accessible' || echo 'QSPI inaccessible'
nvbootctrl dump-slots-info
ls -l /mnt/boot/EFI/UpdateCapsule/
cat /mnt/boot/jetson-qspi-retry-count 2>/dev/null || true
```

## When an update is genuinely necessary

A bootloader update is necessary when:

- Moving between incompatible L4T or JetPack firmware generations
- QSPI contains generic NVIDIA developer-kit firmware
- Edge-AI DTB, pinmux, BCT, or UEFI branding changed
- QSPI must be made accessible for future OTA maintenance or recovery

However, the current hostapp hook is broader than necessary. It schedules a
capsule for every supported hostapp update because it validates only the source
firmware version and does not determine whether the target capsule is already
installed.

## Possible improvement

A more selective implementation should associate a persistent version, build
identifier, or digest with the Edge-AI capsule and skip the update when that
exact capsule is already installed.

Comparing only the L4T version is insufficient: a stock NVIDIA capsule and an
Edge-AI-customized capsule can both report version 36.5 while containing
different DTBs, BCT data, and UEFI assets.
