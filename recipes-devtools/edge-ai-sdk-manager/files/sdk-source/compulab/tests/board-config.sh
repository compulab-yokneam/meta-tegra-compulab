#!/bin/bash
# SPDX-License-Identifier: MIT
# Exercise installed board metadata/helper functions only. Never run flash.sh,
# SDK Manager, tegrarcm, or any other operation against a connected device.
set -eo pipefail

sdk=$(cd -- "$(dirname -- "$0")/../.." && pwd)
work=$(mktemp -d /tmp/edge-ai-installed-board-check.XXXXXXXX)

has_arg()
{
    case " ${CMDLINE_ADD:-} " in
        *" $1 "*) return 0 ;;
        *) return 1 ;;
    esac
}

load_profile()
{
    local target="$1"
    LDK_DIR="${sdk}"
    BL_DIR="${sdk}/bootloader"
    DTB_DIR="${sdk}/kernel/dtb"
    source "${sdk}/edge-ai-${target}.conf"
}

run_valid()
(
    target="$1" sku="$2" style="$3" early="$4"
    unset CHIP_SKU chip_SKU RAMCODE RAMCODE_ID FAB BOARDREV CHIPREV
    if [ "${style}" = default ]; then
        unset EDGE_AI_UEFI_LOGO_STYLE
        expected_style=clab-logo
    else
        EDGE_AI_UEFI_LOGO_STYLE="${style}"
        expected_style="${style}"
    fi
    EDGE_AI_EARLY_TTY1="${early}"
    load_profile "${target}"
    # A profile must not prevent native EEPROM discovery by forcing FAB.
    test -z "${FAB+x}" && test -z "${BOARDREV+x}" && test -z "${CHIPREV+x}"
    storage_before="${ROOTFSSIZE}|${EMMC_CFG}|${EXTERNAL_DEVICE}|${EXTERNAL_PT_LAYOUT}|${INTERNAL_PT_LAYOUT}"
    board_id=3767 board_sku="${sku}" board_FAB="${EDGE_AI_DEFAULT_FAB}"
    if [ "${style}" != default ]; then
        CHIP_SKU="${EDGE_AI_EXPECTED_CHIP_SKU}"
    fi
    process_board_version "${board_id}" "${board_FAB}" "${board_sku}" \
        "${EDGE_AI_DEFAULT_BOARDREV}" "${EDGE_AI_DEFAULT_CHIPREV:-0}"
    process_chip_sku_version "${CHIP_SKU:-}" '' '' "${RAMCODE:-}" \
        fuselevel_production "${board_FAB}"
    update_flash_args

    test "${MB2_BCT}" = tegra234-edge-ai-mb2-bct-misc-p3767-0000.dts
    test "${PINMUX_CONFIG}" = tegra234-edge-ai-pinmux.dtsi
    test "${PMC_CONFIG}" = tegra234-edge-ai-padvoltage-default.dtsi
    test "${MISC_CONFIG}" = tegra234-edge-ai-mb1-bct-misc-p3767-0000.dts
    test "${ODMDATA}" = gbe-uphy-config-9,hsstp-lane-map-3,hsio-uphy-config-0
    test "${DTB_FILE}" = "tegra234-edge-ai-${target}-nv-super.dtb"
    test "${TBCDTB_FILE}" = "${DTB_FILE}"
    test "${BPFDTB_FILE}" = "tegra234-bpmp-3767-${sku}-3768-super.dtb"
    test "${EMC_BCT}" = "${EDGE_AI_EMC_BCT}"
    test "${WB0SDRAM_BCT}" = "${EDGE_AI_WB0SDRAM_BCT}"
    test "${BPFFILE}" = "bootloader/bpmp_t234-${EDGE_AI_BPMP_FAMILY}_prod.bin"
    test -s "${sdk}/bootloader/generic/BCT/${EMC_BCT}"
    test -s "${sdk}/bootloader/generic/BCT/${WB0SDRAM_BCT}"
    test -s "${sdk}/${BPFFILE}"
    test -s "${sdk}/bootloader/generic/${BPFDTB_FILE}"
    test "${chip_SKU}" = "${EDGE_AI_EXPECTED_CHIP_SKU##*:}"
    if [ "${sku}" = 0004 ]; then
        test "${RAMCODE}" = 4
    fi
    test "${storage_before}" = "${ROOTFSSIZE}|${EMMC_CFG}|${EXTERNAL_DEVICE}|${EXTERNAL_PT_LAYOUT}|${INTERNAL_PT_LAYOUT}"

    stem="compulab-edge-ai-${target}-${expected_style}"
    test "${EDGE_AI_UEFI_LOGO_STYLE}" = "${expected_style}"
    test "${TBCFILE}" = "bootloader/uefi_bins/${stem}-uefi.bin"
    test "${RCM_TBCFILE}" = "bootloader/uefi_bins/${stem}-rcm.bin"
    test "${UEFIBL}" = "${stem}-uefi_with_dtb.bin"
    test "${RCM_UEFIBL}" = "${stem}-rcm_with_dtb.bin"
    test "${TOSFILE}" = "bootloader/${stem}-tos.img"
    test "${L4T_LAUNCHER}" = "${stem}-BOOTAA64.efi"
    test "${L4T_CONF_DTBO}" = "${sdk}/bootloader/compulab-L4TConfiguration.dtbo"
    case ",${OVERLAY_DTB_FILE}," in
        *,compulab-L4TConfiguration.dtbo,*) ;;
        *) printf 'FAIL: private L4T configuration was not selected\n' >&2; exit 1 ;;
    esac
    case ",${OVERLAY_DTB_FILE}," in
        *,L4TConfiguration.dtbo,*) exit 1 ;;
    esac
    has_arg iomem=relaxed
    has_arg pci=realloc
    has_arg pcie_aspm=off
    has_arg console=ttyTCU0,115200

    cmdline_before="${CMDLINE_ADD}"
    overlays_before="${OVERLAY_DTB_FILE}"
    update_flash_args
    test "${CMDLINE_ADD}" = "${cmdline_before}"
    test "${OVERLAY_DTB_FILE}" = "${overlays_before}"
    if [ "${early}" = 1 ]; then
        ! has_arg video=efifb:off
        ! has_arg console=tty0
        has_arg console=tty1
        has_arg fbcon=nodefer
    else
        has_arg video=efifb:off
        has_arg console=tty0
        ! has_arg console=tty1
    fi
    printf 'PASS: installed %s, logo=%s, early_tty1=%s\n' "${target}" "${style}" "${early}"
)

run_rejected()
{
    local target="$1" board="$2" sku="$3"
    local log="${work}/reject-${target}-${board:-empty}-${sku:-empty}.log"
    if (
        unset CHIP_SKU chip_SKU RAMCODE RAMCODE_ID FAB BOARDREV CHIPREV
        EDGE_AI_EARLY_TTY1=0
        load_profile "${target}"
        board_id="${board}" board_sku="${sku}" board_FAB=TS4
        update_flash_args
    ) >"${log}" 2>&1; then
        printf 'FAIL: accepted %s board=%s SKU=%s\n' "${target}" "${board}" "${sku}" >&2
        exit 1
    fi
    grep -Eq 'expected BOARDID|expected SKU' "${log}"
    printf 'PASS: rejected %s board=%s SKU=%s\n' "${target}" "${board}" "${sku}"
}

for early in 0 1; do
    for style in clab-logo nvidia-logo no-logo; do
        run_valid nx-16g 0000 "${style}" "${early}"
        run_valid nx-8g 0001 "${style}" "${early}"
        run_valid nano-8g 0003 "${style}" "${early}"
        run_valid nano-4g 0004 "${style}" "${early}"
    done
done
run_valid nx-16g 0000 default 0
run_valid nx-8g 0001 default 0
run_valid nano-8g 0003 default 0
run_valid nano-4g 0004 default 0
run_rejected nx-16g 3767 0001
run_rejected nx-8g 3767 0000
run_rejected nx-16g 3701 0000
run_rejected nx-8g 3767 0003
run_rejected nx-16g '' ''
run_rejected nano-8g 3767 0004
run_rejected nano-4g 3767 0003
run_rejected nano-8g 3767 0000
run_rejected nano-8g 3767 0005

run_bad_metadata()
{
    local target="$1" setting="$2" log="${work}/metadata-${1}-${2//[:=]/_}.log"
    if (
        unset CHIP_SKU chip_SKU RAMCODE RAMCODE_ID FAB BOARDREV CHIPREV
        export "${setting}"
        EDGE_AI_EARLY_TTY1=0
        load_profile "${target}"
    ) >"${log}" 2>&1; then
        printf 'FAIL: accepted %s %s\n' "${target}" "${setting}" >&2
        exit 1
    fi
    grep -F 'conflicts with' "${log}" >/dev/null
    printf 'PASS: rejected %s %s\n' "${target}" "${setting}"
}
run_bad_metadata nano-8g CHIP_SKU=00:00:00:D3
run_bad_metadata nano-4g CHIP_SKU=00:00:00:D5
run_bad_metadata nano-4g RAMCODE=0
run_bad_metadata nano-4g RAMCODE_ID=0
run_bad_metadata nx-16g CHIP_SKU=00:00:00:D6

for corruption in chip bpmp memory; do
    if (
        unset CHIP_SKU chip_SKU RAMCODE RAMCODE_ID FAB BOARDREV CHIPREV
        EDGE_AI_EARLY_TTY1=0
        load_profile nano-8g
        board_id=3767 board_sku=0003 board_FAB=300
        CHIP_SKU=00:00:00:D5
        process_board_version 3767 300 0003 P.1 0
        process_chip_sku_version "${CHIP_SKU}" '' '' '' fuselevel_production 300
        case "${corruption}" in
            chip) chip_SKU=D3 ;;
            bpmp) BPFFILE=bootloader/bpmp_t234-TE980M-A1_prod.bin ;;
            memory) EMC_BCT=tegra234-p3767-0004-sdram-l4t.dts ;;
        esac
        update_flash_args
    ) >"${work}/corrupt-${corruption}.log" 2>&1; then
        printf 'FAIL: accepted corrupted Nano %s selection\n' "${corruption}" >&2
        exit 1
    fi
    grep -Eq 'conflicts with|selection does not match' "${work}/corrupt-${corruption}.log"
    printf 'PASS: rejects resolved Nano %s mismatch\n' "${corruption}"
done

if (
    EDGE_AI_EARLY_TTY1=0
    load_profile nx-16g
    BOARDID=3767 BOARDSKU=0000
    board_id=3767 board_sku=0001 board_FAB=TS4
    update_flash_args
) >"${work}/resolved-sku.log" 2>&1; then
    printf 'FAIL: environment override defeated resolved module metadata\n' >&2
    exit 1
fi
grep -F 'expected SKU 0000' "${work}/resolved-sku.log" >/dev/null
printf 'PASS: resolved EEPROM SKU takes precedence\n'

if (
    EDGE_AI_EARLY_TTY1=0
    EDGE_AI_UEFI_LOGO_STYLE=invalid
    load_profile nx-16g
    board_id=3767 board_sku=0000 board_FAB=TS4
    update_flash_args
) >"${work}/invalid-logo.log" 2>&1; then
    printf 'FAIL: invalid logo style was accepted\n' >&2
    exit 1
fi
grep -F 'unsupported logo style' "${work}/invalid-logo.log" >/dev/null
printf 'PASS: invalid logo style rejected\n'

if (
    EDGE_AI_EARLY_TTY1=invalid
    load_profile nx-16g
) >"${work}/invalid-early.log" 2>&1; then
    printf 'FAIL: invalid early-console setting was accepted\n' >&2
    exit 1
fi
grep -F 'EDGE_AI_EARLY_TTY1 must be 0 or 1' "${work}/invalid-early.log" >/dev/null
printf 'PASS: invalid early-console setting rejected\n'

if (
    EDGE_AI_EARLY_TTY1=0
    load_profile nx-16g
    board_id=3767 board_sku=0000 board_FAB=TS4
    # Change only this subshell's path variable; never rename SDK files.
    LDK_DIR="${work}/intentionally-missing-sdk"
    update_flash_args
) >"${work}/missing-marker.log" 2>&1; then
    printf 'FAIL: missing Noble artifact marker was accepted\n' >&2
    exit 1
fi
grep -F 'matched Noble artifact marker is missing' "${work}/missing-marker.log" >/dev/null
printf 'PASS: missing matched Noble marker rejected\n'

if (
    EDGE_AI_EARLY_TTY1=0
    load_profile nx-16g
    board_id=3767 board_sku=0000 board_FAB=TS4
    DTB_DIR="${work}/intentionally-missing-dtb-dir"
    update_flash_args
) >"${work}/missing-dtb.log" 2>&1; then
    printf 'FAIL: missing selected carrier DTB was accepted\n' >&2
    exit 1
fi
grep -F 'missing carrier DTB' "${work}/missing-dtb.log" >/dev/null
printf 'PASS: missing selected carrier DTB rejected\n'
printf 'Evidence: %s\n' "${work}"
