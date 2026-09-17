# CompuLab EdgeAI-ORN support for balenaOS on JetPack 7.2

This is a vendored, JP7.2 adaptation of `meta-tegra-compulab` revision
`8b28d488683a85378d58cf6d6c4c350113e43d57` from the source
`balena-jetson-orin` repository (parent revision `1096ee1`). It is kept as
ordinary files so the recipe changes are reviewable together with this port.
The original upstream is https://github.com/compulab-yokneam/meta-tegra-compulab,
branch `edgeai-orn-balena`. Existing target submodule revisions are retained.

The layer depends on `core`, `tegra`, and `balena-jetson` and supports the
`wrynose` layer series and L4T 39.2.0. The default build template enables it.
For an existing build directory, add `layers/meta-tegra-compulab` to BBLAYERS.

| Machine | Supported P3767 modules | First-boot fallback |
| --- | --- | --- |
| `edgeai-orn-nano` | 0003 (8GB), 0004 (4GB) | 0004 Super DTB |
| `edgeai-orn-nx` | 0000 (16GB), 0001 (8GB) | 0001 Super DTB |

Both images retain the source's NVMe partition layout and normal/Super DTBs.
The runtime selector reads the module SKU from `TegraPlatformSpec`, preserves
other settings in `extra_uEnv.txt`, and selects the family member's Super DTB
for subsequent boots. Each capsule includes normal and Super compatibility
entries for both modules in that family.

The carrier changes enable PCIe, USB routing, UARTB and the SPI TPM, set display
hotplug polarity and carrier identity, and remove the unused Type-C controller.
CompuLab pinmux, pad voltage, EEPROM configuration and UPHY routing are installed
in both tegraflash inputs and the capsule's L4T tree. The native JP7.2 UEFI recipe
uses the target's balena integration, family fallback DTB and CompuLab logos.
Both families use the Nano UEFI integration and OTA hook because their NVMe
rootfs partitions are 15/16; the Xavier NX layout uses 7/8.

The QSPI manager retains JP7.2's firmware version/marker checks and `/tmp`
migration search, with a family-specific capsule filename and a corrected
prepared-capsule path. Obsolete container-based UEFI builds and the old
QSPI-accessibility polling patch are omitted. Local inputs use UNPACKDIR, the
kernel provider is `linux-noble-nvidia-tegra`, and the device-tree package is
`nvidia-kernel-oot-dtb`.

As in the source repository, `tegra-flash-dry` uses the generic Orin Nano Super
raw QSPI blob. A CompuLab-generated raw QSPI dump has not been supplied or
validated. The family capsules contain the carrier-specific configuration.
Raw QSPI provisioning and the upgrade from JP6 must be tested on hardware before
release; JP7 upgrades require an L4T 36.5.0 starting point.

See [validation instructions and results](tests/compulab/README.md).
