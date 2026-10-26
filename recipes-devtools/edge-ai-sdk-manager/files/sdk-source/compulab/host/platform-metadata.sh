#!/bin/bash
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 CompuLab Ltd.
# Shared R39.2.1 profile data. This file only defines metadata functions.

compulab_platform_metadata()
{
    EDGE_AI_DEFAULT_FAB=TS4
    EDGE_AI_DEFAULT_BOARDREV=""
    EDGE_AI_DEFAULT_CHIPREV=""
    EDGE_AI_EXPECTED_RAMCODE=""
    EDGE_AI_BPMP_FAMILY=TE980M-A1
    case "$1" in
        edge-ai|edge-ai-nx-16g|0000)
            EDGE_AI_TARGET=edge-ai-nx-16g
            EDGE_AI_EXPECTED_SKU=0000
            EDGE_AI_EXPECTED_CHIP_SKU=00:00:00:D3
            EDGE_AI_MEMORY_SKU=0000
            ;;
        edge-ai-nx-8g|0001)
            EDGE_AI_TARGET=edge-ai-nx-8g
            EDGE_AI_EXPECTED_SKU=0001
            EDGE_AI_EXPECTED_CHIP_SKU=00:00:00:D4
            EDGE_AI_MEMORY_SKU=0001
            ;;
        edge-ai-nano-8g|0003)
            EDGE_AI_TARGET=edge-ai-nano-8g
            EDGE_AI_EXPECTED_SKU=0003
            EDGE_AI_EXPECTED_CHIP_SKU=00:00:00:D5
            EDGE_AI_MEMORY_SKU=0001
            EDGE_AI_BPMP_FAMILY=TE950M-A1
            EDGE_AI_DEFAULT_FAB=300
            EDGE_AI_DEFAULT_BOARDREV=P.1
            EDGE_AI_DEFAULT_CHIPREV=0
            ;;
        edge-ai-nano-4g|0004)
            EDGE_AI_TARGET=edge-ai-nano-4g
            EDGE_AI_EXPECTED_SKU=0004
            EDGE_AI_EXPECTED_CHIP_SKU=00:00:00:D6
            EDGE_AI_MEMORY_SKU=0004
            EDGE_AI_BPMP_FAMILY=TE950M-A1
            EDGE_AI_DEFAULT_FAB=RC1
            EDGE_AI_DEFAULT_BOARDREV=B.4
            EDGE_AI_DEFAULT_CHIPREV=0
            EDGE_AI_EXPECTED_RAMCODE=4
            ;;
        *)
            printf 'CompuLab metadata: unsupported target/SKU: %s\n' "$1" >&2
            return 1
            ;;
    esac
    EDGE_AI_DTB_FILE="tegra234-${EDGE_AI_TARGET}-nv-super.dtb"
    EDGE_AI_EMC_BCT="tegra234-p3767-${EDGE_AI_MEMORY_SKU}-sdram-l4t.dts"
    EDGE_AI_WB0SDRAM_BCT="tegra234-p3767-${EDGE_AI_MEMORY_SKU}-wb0sdram-l4t.dts"
}

compulab_check_module_metadata()
{
    local value variable
    for variable in CHIP_SKU chip_SKU; do
        value="${!variable:-}"
        case "${value}" in
            ''|"${EDGE_AI_EXPECTED_CHIP_SKU}"|"${EDGE_AI_EXPECTED_CHIP_SKU##*:}") ;;
            *)
                printf 'CompuLab metadata: %s=%s conflicts with %s (%s).\n' \
                    "${variable}" "${value}" "${EDGE_AI_TARGET}" \
                    "${EDGE_AI_EXPECTED_CHIP_SKU}" >&2
                return 1
                ;;
        esac
    done
    if [ -n "${EDGE_AI_EXPECTED_RAMCODE}" ]; then
        for variable in RAMCODE RAMCODE_ID; do
            value="${!variable:-}"
            if [ -n "${value}" ] && [ "${value}" != "${EDGE_AI_EXPECTED_RAMCODE}" ]; then
                printf 'CompuLab metadata: %s=%s conflicts with %s RAMCODE=%s.\n' \
                    "${variable}" "${value}" "${EDGE_AI_TARGET}" \
                    "${EDGE_AI_EXPECTED_RAMCODE}" >&2
                return 1
            fi
        done
    fi
}
