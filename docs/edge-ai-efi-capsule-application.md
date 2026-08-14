# Edge-AI EFI Capsule: Finding and Applying the Binary

> **Warning:** The current build artifacts show identical capsules for NX 16GB
> and NX 8GB, and identical capsules for Nano 8GB and Nano 4GB. Because the
> board specifications are SKU-specific, resolve this build-output isolation
> issue before deploying the capsules to production devices.

## 1. Find the capsule in the Yocto build

From the repository root:

```sh
cd /home/val/devel/balena/balena-jetson-orin
find build/tmp -type f -name 'TEGRA_BL*.Cap.gz'
```

The direct recipe outputs are normally located at:

```text
build/tmp/work/armv8a-poky-linux/uefi-capsule-container/36.5.0/build/out/TEGRA_BL_Orin_NX.Cap.gz
build/tmp/work/armv8a-poky-linux/uefi-capsule-container/36.5.0/build/out/TEGRA_BL_Orin_Nano.Cap.gz
```

Use the capsule from the root filesystem of the machine-specific image when
possible.

### Edge-AI NX 16GB

```sh
CAPSULE=build/tmp/work/edge_ai_nx_16g-poky-linux/balena-image/1.0/rootfs/opt/tegra-binaries/TEGRA_BL_Orin_NX.Cap.gz
```

### Edge-AI NX 8GB

```sh
CAPSULE=build/tmp/work/edge_ai_nx_8g-poky-linux/balena-image/1.0/rootfs/opt/tegra-binaries/TEGRA_BL_Orin_NX.Cap.gz
```

### Edge-AI Nano 8GB

```sh
CAPSULE=build/tmp/work/edge_ai_nano_8g-poky-linux/balena-image/1.0/rootfs/opt/tegra-binaries/TEGRA_BL_Orin_Nano.Cap.gz
```

### Edge-AI Nano 4GB

```sh
CAPSULE=build/tmp/work/edge_ai_nano_4g-poky-linux/balena-image/1.0/rootfs/opt/tegra-binaries/TEGRA_BL_Orin_Nano.Cap.gz
```

Validate the selected artifact:

```sh
ls -lh "$CAPSULE"
gzip -t "$CAPSULE"
sha256sum "$CAPSULE"
```

At the time this procedure was written, the current artifacts had these
identical hashes:

```text
NX 16GB and NX 8GB:
04ded31e0b847c55c9797bd3aec1dbe7ec76f68c9898ab111d7df34444a7b888

Nano 8GB and Nano 4GB:
212f2aec0fc05a476a6601992af60dd69dd7f73f9df548c5368af4d2b38422b6
```

## 2. Locate the capsule on an installed system

Connect to the balenaOS host OS, not an application container:

```sh
ssh -p 22222 root@DEVICE_IP
```

Find and validate the installed capsule:

```sh
find /opt/tegra-binaries -maxdepth 1 -type f -name 'TEGRA_BL*.Cap.gz' -ls
gzip -t /opt/tegra-binaries/TEGRA_BL_*.Cap.gz
sha256sum /opt/tegra-binaries/TEGRA_BL_*.Cap.gz
```

Expected filenames:

| Machine | Installed capsule |
| --- | --- |
| `edge-ai-nx-16g` | `/opt/tegra-binaries/TEGRA_BL_Orin_NX.Cap.gz` |
| `edge-ai-nx-8g` | `/opt/tegra-binaries/TEGRA_BL_Orin_NX.Cap.gz` |
| `edge-ai-nano-8g` | `/opt/tegra-binaries/TEGRA_BL_Orin_Nano.Cap.gz` |
| `edge-ai-nano-4g` | `/opt/tegra-binaries/TEGRA_BL_Orin_Nano.Cap.gz` |

Confirm that UEFI variables are accessible:

```sh
test -d /sys/firmware/efi/efivars
echo $?
```

The result must be `0`.

Record the board and bootloader state before updating:

```sh
tegra-boardspec
nvbootctrl dump-slots-info

tegra-boardspec > /mnt/data/boardspec-before-capsule.txt
nvbootctrl dump-slots-info > /mnt/data/nvbootctrl-before-capsule.txt
```

## 3. Normal application with `jetson-qspi-manager`

Confirm that the boot partition is mounted and writable:

```sh
findmnt /mnt/boot
mount -o remount,rw /mnt/boot
```

Check QSPI accessibility and prepare the update:

```sh
jetson-qspi-manager --check
jetson-qspi-manager --prepare-update
```

The manager should:

1. Decompress the installed capsule.
2. Write it to `/mnt/boot/EFI/UpdateCapsule/TEGRA_BL.Cap`.
3. Create the NVIDIA platform compatibility EFI variables.
4. Set the UEFI `OsIndications` capsule-update flag.
5. Create the retry counter under `/mnt/boot`.

### 3.1 NVIDIA platform compatibility EFI variables

The capsule is a multi-spec BUP. NVIDIA UEFI uses two vendor EFI variables to
select the matching entry from that payload:

```text
TegraPlatformSpec-781e084c-a330-417c-b678-38e696380cb9
TegraPlatformCompatSpec-781e084c-a330-417c-b678-38e696380cb9
```

`TegraPlatformSpec` contains the complete hardware specification returned by
`tegra-boardspec`, followed by the UEFI device type. `TegraPlatformCompatSpec`
contains a normalized form in which revision-specific fields are removed or
normalized so that the value matches the compatibility records in the BUP.

For all four supported Edge-AI machines, the device type is:

```text
jetson-orin-nano-devkit-super
```

Preview the values that the installed QSPI helper will use:

```sh
bash -c '
    source /usr/libexec/jetson-qspi-helpers
    printf "boardspec:                %s\n" "$boardspec"
    printf "TegraPlatformSpec:        %s\n" "$TegraPlatformSpec"
    printf "compat boardspec:         %s\n" "$compatspec"
    printf "TegraPlatformCompatSpec:  %s\n" "$TegraPlatformCompatSpec"
'
```

The normal manager path calls `write_jetson_update_efivars`, but it can also be
invoked directly:

```sh
bash -c '
    source /usr/libexec/jetson-qspi-helpers
    write_jetson_update_efivars
'
```

Before creating a variable, the helper prefixes its text value with the four
efivarfs attribute bytes `07 00 00 00`. Attribute value `0x00000007` means
non-volatile, boot-service access, and runtime access. The platform string is
stored immediately after those four bytes without a terminating NUL.

The variables are normally treated as write-once. If they already exist, the
helper leaves them unchanged. The compatibility variable is rewritten only by
the legacy-update handling for selected older L4T releases. Do not manually
overwrite an existing value unless its current contents have first been
recorded and it is known to be incorrect.

Inspect the stored attributes and text values:

```sh
EFIVARS=/sys/firmware/efi/efivars
NVIDIA_GUID=781e084c-a330-417c-b678-38e696380cb9

for name in TegraPlatformSpec TegraPlatformCompatSpec; do
    path="$EFIVARS/$name-$NVIDIA_GUID"
    if [ -e "$path" ]; then
        printf '%s attributes: ' "$name"
        od -An -tx1 -N4 "$path"
        printf '%s value: ' "$name"
        dd if="$path" bs=1 skip=4 status=none | tr -d '\000'
        echo
    else
        echo "$name is missing"
    fi
done
```

The first four bytes should be:

```text
07 00 00 00
```

The text must end with `-jetson-orin-nano-devkit-super-` and the board ID/SKU
must agree with `tegra-boardspec` and the target machine.

### 3.2 UEFI `OsIndications` capsule-update flag

The standard UEFI variable is:

```text
OsIndications-8be4df61-93ca-11d2-aa0d-00e098032b8c
```

Its payload is a little-endian 64-bit bitmask. Bit 2, value `0x4`, is
`EFI_OS_INDICATIONS_FILE_CAPSULE_DELIVERY_SUPPORTED`. Setting it tells UEFI to
scan `EFI/UpdateCapsule` during the next boot.

The efivarfs file written by the manager is 12 bytes:

```text
07 00 00 00 04 00 00 00 00 00 00 00
| attributes | |------- value -------|
```

The preferred way to set it is through the same helper that also creates the
NVIDIA variables:

```sh
bash -c '
    source /usr/libexec/jetson-qspi-helpers
    write_jetson_update_efivars
'
```

Alternatively, when the OE4T utility is installed, it sets only
`OsIndications`:

```sh
oe4t-set-uefi-OSIndications
```

Verify the exact binary value:

```sh
OS_INDICATIONS=/sys/firmware/efi/efivars/OsIndications-8be4df61-93ca-11d2-aa0d-00e098032b8c

test -e "$OS_INDICATIONS"
stat -c 'size=%s bytes' "$OS_INDICATIONS"
od -An -tx1 -v "$OS_INDICATIONS"
```

Expected output includes a size of 12 bytes and the byte sequence shown above.
Creating only this flag is insufficient: the capsule file and correct NVIDIA
platform variables must also be present before rebooting.

### 3.3 Retry counter under `/mnt/boot`

The manager stores its retry state on the boot partition so it survives a
reboot and remains shared between host OS root filesystem slots:

```text
/mnt/boot/jetson-qspi-retry-count
```

On the first preparation attempt, its contents are:

```text
jetson_capsule_retries=1
```

The manager creates the file atomically by writing a temporary file and moving
it into place, then calls `sync`. If another boot still requires the update,
the sourced value is incremented and the capsule is prepared again. After the
retry limit is exceeded, the manager stops and requests manual intervention.

Normally this file is created automatically by:

```sh
jetson-qspi-manager --prepare-update
```

For a forced update, `try_capsule_update` creates it as part of the same
operation:

```sh
bash -c '
    source /usr/libexec/jetson-qspi-helpers
    try_capsule_update /mnt/boot /mnt/boot force
'
```

Inspect the file without executing it:

```sh
ls -l /mnt/boot/jetson-qspi-retry-count
grep -E '^jetson_capsule_retries=[0-9]+$' \
    /mnt/boot/jetson-qspi-retry-count
```

If manual creation is required, use an atomic write and synchronize it:

```sh
retry_tmp=$(mktemp /mnt/boot/jetson-qspi-retry-count.XXXXXX)
printf '%s\n' 'jetson_capsule_retries=1' > "$retry_tmp"
mv "$retry_tmp" /mnt/boot/jetson-qspi-retry-count
sync
```

Reset a stale or exhausted counter with the supported manager command:

```sh
jetson-qspi-manager --reset
```

Then prepare the update again. Resetting the counter does not by itself set
`OsIndications` or install the capsule.

Verify the prepared update:

```sh
ls -lh /mnt/boot/EFI/UpdateCapsule/TEGRA_BL.Cap
cat /mnt/boot/jetson-qspi-retry-count
ls /sys/firmware/efi/efivars/OsIndications-*
sync
```

Reboot and do not disconnect power while UEFI processes the capsule:

```sh
reboot
```

## 4. Force an update when QSPI is already accessible

The normal command skips the update when `/dev/mtd0` exists. To force the
capsule already installed under `/opt/tegra-binaries`:

```sh
mount -o remount,rw /mnt/boot

bash -c '
    source /usr/libexec/jetson-qspi-helpers
    try_capsule_update /mnt/boot /mnt/boot force
'
```

Verify and reboot:

```sh
ls -lh /mnt/boot/EFI/UpdateCapsule/TEGRA_BL.Cap
cat /mnt/boot/jetson-qspi-retry-count
ls /sys/firmware/efi/efivars/OsIndications-*
sync
reboot
```

## 5. Apply a capsule copied separately to the device

Copy the exact machine-specific artifact from the build host:

```sh
scp -P 22222 "$CAPSULE" root@DEVICE_IP:/tmp/
```

On the device, validate the copy:

```sh
sha256sum /tmp/TEGRA_BL_*.Cap.gz
gzip -t /tmp/TEGRA_BL_*.Cap.gz
```

Install it into the EFI capsule directory:

```sh
mount -o remount,rw /mnt/boot
mkdir -p /mnt/boot/EFI/UpdateCapsule

gunzip -c /tmp/TEGRA_BL_*.Cap.gz \
    | dd of=/mnt/boot/EFI/UpdateCapsule/TEGRA_BL.Cap \
         bs=1M conv=fsync
```

Set the required NVIDIA and UEFI variables:

```sh
bash -c '
    source /usr/libexec/jetson-qspi-helpers
    write_jetson_update_efivars
'
```

Verify and reboot:

```sh
ls -lh /mnt/boot/EFI/UpdateCapsule/TEGRA_BL.Cap
ls /sys/firmware/efi/efivars/OsIndications-*
sync
reboot
```

## 6. Verify after reboot

Reconnect to the host OS and inspect the bootloader state and logs:

```sh
nvbootctrl dump-slots-info
journalctl -b --no-pager | grep -Ei 'capsule|qspi|uefi|firmware'
```

Check whether UEFI consumed the capsule and inspect the retry state:

```sh
ls -l /mnt/boot/EFI/UpdateCapsule/
cat /mnt/boot/jetson-qspi-retry-count 2>/dev/null || true
```

Inspect the running device tree for the Edge-AI changes:

```sh
dtc -I fs -O dts /sys/firmware/devicetree/base \
    > /tmp/running-device-tree.dts

grep -nEi 'edge-ai|compulab|3210000|140c0000|140e0000' \
    /tmp/running-device-tree.dts
```

Finally, confirm that the CompuLab logo is displayed during the UEFI boot
stage.
