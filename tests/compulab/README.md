# CompuLab JP7.2 validation

Validation performed on 2026-09-16, with the target repository's existing layer
revisions and cached, checksum-verified NVIDIA L4T 39.2.0 sources.

| Check | Nano | NX |
| --- | --- | --- |
| In-process BitBake configuration/recipe parsing | PASS | PASS |
| Full available recipe set | 3050 parsed, 301 skipped | 3050 parsed, 301 skipped |
| Local file inputs and append matching | PASS | PASS |
| Fallback DTB, kernel provider, partition layout, OTA hook and capsule dependencies | PASS | PASS |
| Eight local recipes' compile/configure/install task bodies | PASS | PASS |
| Runtime SKU selection, idempotence, user settings, missing EFI/DTB and unsupported modules | PASS | PASS |
| Prepared capsule detection, including spaces/trailing slash in ESP paths | PASS | PASS |
| Actual normal/Super NVIDIA board configuration callbacks | Both SKUs pass | Both SKUs pass |
| Carrier pinmux/GPIO, pad voltage and MB2 BCT compilation | PASS | PASS |
| Full native UEFI patch set against pinned Git sources | PASS | PASS |

The full recipe parse explicitly excludes `docker-disk.bb`: its anonymous
function requires access to the Docker daemon, which this sandbox denies. No
Docker checks were faked. The remaining skips are normal recipe compatibility
and feature restrictions. This uses BitBake's `CookerDataBuilder`, layer
priorities, overrides, BBMASK and recipe finalization directly because the
sandbox also prevents the BitBake server from binding its Unix socket.

All ten DTBs packaged by the source family images compile, including the two
retained P3767-0005 variants. The eight variants for supported modules were
inspected for carrier model/compatible strings, enabled PCIe and UARTB, SPI TPM
and frequency, USB companion routing, display polarity and removed FUSB301.
All seven refreshed carrier patches apply without fuzz or offsets. DTC warnings
from NVIDIA's source trees are retained in the per-DTB logs.

The local task checks cover `edgeai-orn-platform-selector`,
`tegra-nv-boot-control-config`, `setup-nv-boot-control`, `jetson-dtbs`,
`jetson-qspi-manager`, `os-power-mode`, `tegra-flashvars`, and `tegra-flash-dry`.
They stage actual recipe file inputs, apply enabled patches, run resolved task
bodies, and inspect installed files; they do not build packages or rootfs images.

Regression comparisons with the CompuLab layer enabled and disabled found no
changes to the source lists, package choices, boot settings and task bodies or
flags of the seven existing machines. Build directory paths and generated
build timestamps were normalized for this comparison. Target submodule
revisions and existing board recipes remain unchanged.

## Repeat the checks

Use a fresh build directory for each family, with the default layer template,
`MACHINE = "edgeai-orn-nano"` or `MACHINE = "edgeai-orn-nx"` in local.conf, and
`BB_NO_NETWORK = "1"` for offline parsing. From the initialized build environment:

```sh
python3 ../tests/compulab/validate-metadata.py --all-recipes --skip-docker-disk
```

This writes resolved recipe metadata and task bodies under `metadata/` in the
build directory. Omit `--skip-docker-disk` on a host with usable Docker.

From the repository root, compile and inspect the carrier BSP:

```sh
python3 tests/compulab/validate-bsp.py \
    /path/to/Jetson-public_sources-39.2.0.tbz2 \
    build-compulab-validation/bsp \
    --bsp-dir /path/to/unpacked/Linux_for_Tegra \
    --git-cache /path/to/downloads/git2 \
    --metadata build-compulab-nano/metadata
```

The optional BSP tree must be L4T 39.2.0. The optional Git cache must contain the
recipe's pinned NVIDIA edk2 and edk2-nvidia revisions. Repeat with NX metadata
to check that family's fallback. The script uses temporary source trees and
writes compiled DTBs and logs under the output directory.

Then test local recipe tasks and runtime behavior for each family's metadata:

```sh
python3 tests/compulab/validate-tasks.py \
    build-compulab-nano/metadata build-compulab-validation/bsp/dtbs
python3 tests/compulab/validate-tasks.py \
    build-compulab-nx/metadata build-compulab-validation/bsp/dtbs
```

## Remaining validation

A complete BitBake dependency/task run, kernel and UEFI compilation, Docker
capsule generation, rootfs/flasher image builds, and boot/OTA tests on all four
module SKUs remain unverified. Run `bitbake balena-image-flasher` for each machine
on an unrestricted build host, then check first and subsequent boots, network,
NVMe, USB, UART, TPM, display, power modes, provisioning, and A/B update/rollback
from the source repository's L4T 36.5.0 image.

The inherited generic raw QSPI blob is not a validated CompuLab QSPI image.
Carrier-specific capsules are configured and their inputs validated, but their
production binaries and hardware application could not be tested here.
