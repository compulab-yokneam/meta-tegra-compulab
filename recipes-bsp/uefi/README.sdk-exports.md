# Optional Edge-AI SDK firmware exports

Set `EDGE_AI_SDK_EXPORTS = "1"` through the SDK-manager configuration
include. The default is `0`: ordinary image/capsule builds gain no exports
and the TOS dependency graph is unchanged. The gated exports currently
support Tegra234 only and never invoke SDK Manager, sudo or a device.

Each multiconfig exports its own inputs through `do_deploy`, below that
multiconfig's `deploy/images/${MACHINE}/edge-ai-sdk/firmware/` directory:

| Recipe subdirectory | Payload |
| --- | --- |
| `edk2-firmware-tegra` | `uefi.bin`, signed `BOOTAA64.efi`, `general.cfg`, `fmp-image-type-id.txt`, all built `*.dtbo` |
| `edk2-firmware-tegra-rcmboot` | `uefi-rcm.bin`, `minimal.cfg` |
| `edk2-nvidia-standalone-mm` | `standalone_mm_optee.bin`, `StandaloneMmOptee.dsc` |
| `tos-optee` | `tos.img`, `tegra234-optee.dtb` |

Every subdirectory also contains `manifest.json`, `SHA256SUMS` and complete
original notices under `licenses/`, copied from the recipe's declared
`LIC_FILES_CHKSUM` inputs. SHA256SUMS covers every exported payload/notice
and the manifest. Manifest origin labels are logical build-relative paths,
not transient absolute WORKDIR paths. Metadata records the machine,
multiconfig, recipe/version, public source revisions and source-date epoch.

The general launcher is taken from `B/images/BOOTAA64.efi` after its normal
signing task, not copied from another recipe or machine's sysroot. The raw
general and minimal RCM binaries stay separate. General `logo_style` uses
the SDK's `clab-logo`, `nvidia-logo` and `no-logo` names; its source config
remains an exact snapshot. Normal and RCM L4T configurations are required;
other built boot-control overlays are preserved as well.

StandaloneMM builds directly from its DSC and has no generated Kconfig.
The export therefore retains the DSC and records the platform, compiler,
build mode and effective debug level; it does not invent a `.config`.

When enabled, TOS explicitly depends on the same multiconfig's StandaloneMM
sysroot input. Its export verifies that the exact staged `tee-raw.bin` is
embedded in TOS and that a zlib payload in that TEE expands to the exact
staged StandaloneMM. `matched_trusted_os` records those two SHA256s, the
staged BL31 hash and discovered offsets. It does not hard-code offsets from
an earlier build or copy raw TEE/BL31 blobs into the SDK bundle. An assembler
can compare the standalone-MM export hash against the TOS proof before
accepting the firmware set. No NX/Nano or logo-style fallback is performed.

The existing top-level TOS deployment and all standard firmware outputs
remain intact. All new writes use `DEPLOYDIR`, so deploy.bbclass owns their
sstate publication and cleanup. SDK consumers must depend on all four
recipes' `do_deploy` for each of the twelve machine/style multiconfigs.
They must not recover launchers/configs by guessing another recipe's WORKDIR.

Run the unprivileged, isolated helper tests without starting BitBake:

```sh
python3 -B recipes-bsp/uefi/tests/test_sdk_firmware_export.py
```

These tests verify gating, payload selection, exact notices, checksums,
deterministic manifests, and failure on missing or unmatched TEE/MM inputs.
They do not validate hardware boot, authentication keys or production
capsule trust. The export does not generate or copy private signing keys.
