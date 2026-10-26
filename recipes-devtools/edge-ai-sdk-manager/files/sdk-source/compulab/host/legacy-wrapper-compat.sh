#!/bin/bash
# SPDX-License-Identifier: MIT
# Source AFTER the legacy compulab-l4t.env. Never bind its R36 flash helper.

if [ -z "${BASH_VERSION:-}" ]; then
    printf 'CompuLab host compatibility requires Bash.\n' >&2
    return 2 2>/dev/null || exit 2
fi

source "$(dirname -- "${BASH_SOURCE[0]}")/platform-metadata.sh" || return 2
if ! declare -F create_disk_image >/dev/null || \
   ! declare -F l4t_compulab_support >/dev/null; then
    printf 'Source the legacy compulab-l4t.env before this adapter.\n' >&2
    return 2 2>/dev/null || exit 2
fi

_compulab_image_error()
{
    printf 'CompuLab image: %s\n' "$*" >&2
}

_compulab_image_sdk()
{
    (cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd -P)
}

_compulab_image_check_file()
{
    local image="$1" owner="$2" expected_bytes="${3:-}"
    local metadata actual_path
    [ ! -L "${image}" ] && [ -f "${image}" ] || return 1
    actual_path=$(readlink -e -- "${image}") || return 1
    [ "${actual_path}" = "${image}" ] || return 1
    metadata=$(stat -c '%u:%h' -- "${image}") || return 1
    [ "${metadata}" = "${owner}:1" ] || return 1
    if [ -n "${expected_bytes}" ]; then
        [ "$(stat -c '%s' -- "${image}")" = "${expected_bytes}" ] || return 1
    fi
}

_compulab_image_check_loop()
{
    local loop="$1" image="$2" owner="$3" backing
    [[ "${loop}" =~ ^/dev/loop[0-9]+$ ]] || return 1
    [ "$(LC_ALL=C stat -Lc '%F:%t' -- "${loop}" 2>/dev/null)" = \
      'block special file:7' ] || return 1
    _compulab_image_check_file "${image}" "${owner}" || return 1
    backing=$(sudo -n losetup --noheadings --raw --output BACK-FILE \
        -- "${loop}") || return 1
    # No deleted backing file, multiple lines, alternate path, or other disk.
    [ "${backing}" = "${image}" ] || return 1
}

_compulab_image_cleanup()
{
    local original_status="$1" final_status="$1" candidate loops
    trap - EXIT HUP INT TERM
    if [ -n "${_clab_loop:-}" ]; then
        loops="${_clab_loop}"
    else
        # Covers interruption immediately after losetup allocated the loop.
        loops=$(sudo -n losetup --noheadings --raw --output NAME \
            --associated "${_clab_image}" 2>/dev/null) || loops=""
    fi
    while IFS= read -r candidate; do
        [ -n "${candidate}" ] || continue
        if ! _compulab_image_check_loop "${candidate}" "${_clab_image}" \
            "${_clab_owner}"; then
            _compulab_image_error \
                "refusing to detach unverified loop '${candidate}'"
            [ "${final_status}" -ne 0 ] || final_status=1
        elif sudo -n losetup --detach -- "${candidate}"; then
            :
        else
            local detach_status="$?"
            _compulab_image_error "detach failed for ${candidate}; inspect it manually"
            [ "${final_status}" -ne 0 ] || final_status="${detach_status}"
        fi
    done <<< "${loops}"
    if [ "${final_status}" -ne 0 ]; then
        _compulab_image_error "image incomplete; retained at ${_clab_image}"
    fi
    # Keep the native failure/signal status even if cleanup also fails.
    [ "${original_status}" -eq 0 ] || final_status="${original_status}"
    exit "${final_status}"
}

_compulab_image_check_sdk()
(
    local sdk="$1" target="$2" sku="$3" logo="$4" early="$5"
    local helper="${sdk}/tools/kernel_flash/l4t_flash_from_kernel.sh" checksum
    [ -s "${sdk}/compulab/kernel-release.txt" ] || {
        _compulab_image_error 'matched Noble kernel readiness marker is missing'
        exit 1
    }
    checksum=$(sha256sum -- "${helper}") || exit 1
    [ "${checksum%% *}" = \
      983153e4b80ff4b36f6e7012d11542b4216a0eb42937f54f63382a82c7328bd7 ] || {
        _compulab_image_error 'native R39.2.1 flash helper changed or is overmounted'
        exit 1
    }
    [ -x "${sdk}/tools/kernel_flash/l4t_initrd_flash.sh" ] || exit 1
    # The installed callback validates the matched firmware/kernel/DT assets.
    # This is metadata validation only, not an invocation of flash.sh.
    set +u
    LDK_DIR="${sdk}" BL_DIR="${sdk}/bootloader" DTB_DIR="${sdk}/kernel/dtb"
    EDGE_AI_UEFI_LOGO_STYLE="${logo}" EDGE_AI_EARLY_TTY1="${early}"
    board_id=3767 board_sku="${sku}" board_FAB="${FAB}"
    source "${sdk}/${target}.conf" || exit 1
    process_board_version "${board_id}" "${board_FAB}" "${board_sku}" \
        "${BOARDREV:-}" "${CHIPREV:-0}" >/dev/null || exit 1
    process_chip_sku_version "${CHIP_SKU}" '' '' "${RAMCODE:-}" \
        fuselevel_production "${board_FAB}" >/dev/null || exit 1
    update_flash_args || exit 1
)

_compulab_image_worker()
(
    local sdk="$1" target="$2" sku="$3" image="$4" size_gib="$5"
    local logo="$6" early="$7" owner="$8" bytes="$9" flash_status
    local _clab_loop="" _clab_image="${image}" _clab_owner="${owner}"

    # noclobber plus an owner-only directory prevents replacing existing files.
    if ! (umask 077; set -o noclobber; : > "${image}"); then
        _compulab_image_error 'output appeared before exclusive creation'
        exit 1
    fi
    if truncate -s "${bytes}" -- "${image}"; then
        :
    else
        flash_status="$?"
        _compulab_image_error "cannot size new image: ${image}"
        exit "${flash_status}"
    fi
    if ! _compulab_image_check_file "${image}" "${owner}" "${bytes}"; then
        _compulab_image_error "cannot prepare owned image: ${image}"
        exit 1
    fi
    trap '_compulab_image_cleanup "$?"' EXIT
    trap 'exit 129' HUP
    trap 'exit 130' INT
    trap 'exit 143' TERM

    if _clab_loop=$(sudo -n losetup --find --show --partscan -- "${image}"); then
        :
    else
        exit "$?"
    fi
    if ! _compulab_image_check_loop "${_clab_loop}" "${image}" "${owner}"; then
        _compulab_image_error 'allocated loop does not match the owned image'
        exit 1
    fi
    # Use one size consistently: 32GiB disk -> 30GiB layout -> 24GiB APP.
    # Explicit env assignments survive sudo and cannot redirect to a real disk.
    cd -- "${sdk}" || exit 1
    if sudo -n env \
        EXT_NUM_SECTORS="$(((size_gib - 2) << 21))" \
        BOARDID=3767 BOARDSKU="${sku}" FAB="${FAB}" \
        BOARDREV="${BOARDREV:-}" CHIPREV="${CHIPREV:-}" \
        CHIP_SKU="${CHIP_SKU}" RAMCODE_ID="${RAMCODE_ID:-}" RAMCODE="${RAMCODE:-}" \
        EDGE_AI_UEFI_LOGO_STYLE="${logo}" EDGE_AI_EARLY_TTY1="${early}" \
        EXTDEV_ON_TARGET="${_clab_loop##*/}" \
        ./tools/kernel_flash/l4t_initrd_flash.sh \
        -c tools/kernel_flash/flash_l4t_t234_nvme.xml \
        --external-device nvme0n1p1 -S "$((size_gib - 8))GiB" \
        --direct "${_clab_loop##*/}" "${target}" external; then
        flash_status=0
    else
        flash_status="$?"
    fi
    exit "${flash_status}"
)

# Keep the public wrapper API and successful L4T_IMAGE result. The legacy
# create_disk_image_func/_proc and overlays_mount are deliberately never called.
create_disk_image()
{
    local sdk caller_root owner target sku size_gib image image_dir parent mode
    local logo="${EDGE_AI_UEFI_LOGO_STYLE:-clab-logo}"
    local early="${EDGE_AI_EARLY_TTY1:-0}" bytes command_name status
    # Dynamic locals keep the shared metadata helper from changing the shell's
    # selected target, while making its checked values visible to the worker.
    local EDGE_AI_TARGET EDGE_AI_DTB_FILE EDGE_AI_EXPECTED_SKU
    local EDGE_AI_EXPECTED_CHIP_SKU EDGE_AI_MEMORY_SKU EDGE_AI_BPMP_FAMILY
    local EDGE_AI_DEFAULT_FAB EDGE_AI_DEFAULT_BOARDREV EDGE_AI_DEFAULT_CHIPREV
    local EDGE_AI_EXPECTED_RAMCODE EDGE_AI_EMC_BCT EDGE_AI_WB0SDRAM_BCT
    sdk=$(_compulab_image_sdk) || return 1
    caller_root=$(readlink -e -- "${L4T_ROOT:-.}") || return 1
    [ "${caller_root}" = "${sdk}" ] || {
        _compulab_image_error "L4T_ROOT must identify this SDK: ${sdk}"
        return 2
    }
    owner=$(id -u) || return 1
    [ "${owner}" -ne 0 ] || {
        _compulab_image_error 'run from your normal user shell, not a root shell'
        return 2
    }
    for command_name in sudo losetup truncate readlink stat sha256sum mktemp; do
        command -v "${command_name}" >/dev/null || {
            _compulab_image_error "required command missing: ${command_name}"
            return 2
        }
    done
    target="${EDGE_AI:-edge-ai}"
    compulab_platform_metadata "${target}" || return 2
    target="${EDGE_AI_TARGET}" sku="${EDGE_AI_EXPECTED_SKU}"
    compulab_check_module_metadata || return 2
    case "${BOARDSKU:--1}" in
        -1|'') ;;
        "${sku}"|"${sku#000}") ;;
        *) _compulab_image_error 'BOARDSKU conflicts with EDGE_AI; select a matching target'; return 2 ;;
    esac
    [ "${BOARDID:-3767}" = 3767 ] || {
        _compulab_image_error 'BOARDID must be 3767'; return 2
    }
    local FAB="${FAB:-${EDGE_AI_DEFAULT_FAB}}"
    local BOARDREV="${BOARDREV:-${EDGE_AI_DEFAULT_BOARDREV}}"
    local CHIPREV="${CHIPREV:-${EDGE_AI_DEFAULT_CHIPREV}}"
    local CHIP_SKU="${EDGE_AI_EXPECTED_CHIP_SKU}"
    local RAMCODE_ID="${RAMCODE_ID:-${RAMCODE:-${EDGE_AI_EXPECTED_RAMCODE}}}"
    local RAMCODE="${RAMCODE_ID}"
    [[ "${FAB}" =~ ^[A-Za-z0-9_-]{1,16}$ ]] || {
        _compulab_image_error 'invalid FAB'; return 2
    }
    case "${target}" in
        edge-ai-nano-*)
            if [ "${FAB}" != "${EDGE_AI_DEFAULT_FAB}" ] || \
               [ "${BOARDREV}" != "${EDGE_AI_DEFAULT_BOARDREV}" ] || \
               [ "${CHIPREV}" != "${EDGE_AI_DEFAULT_CHIPREV}" ]; then
                _compulab_image_error \
                    "Nano offline metadata conflicts with ${target}; unset FAB BOARDREV CHIPREV to use its reviewed defaults"
                return 2
            fi
            if [ "${sku}" = 0003 ] && [ -n "${RAMCODE_ID}" ]; then
                _compulab_image_error 'Nano8G has no reviewed RAMCODE override; unset RAMCODE RAMCODE_ID'
                return 2
            fi
            ;;
    esac
    case "${logo}" in
        clab-logo|nvidia-logo|no-logo) ;;
        *) _compulab_image_error 'invalid EDGE_AI_UEFI_LOGO_STYLE'; return 2 ;;
    esac
    case "${early}" in
        0|1) ;;
        *) _compulab_image_error 'EDGE_AI_EARLY_TTY1 must be 0 or 1'; return 2 ;;
    esac
    size_gib="${size:-${LOOP_DEV_SIZE_GB:-32}}"
    [[ "${size_gib}" =~ ^[1-9][0-9]{0,3}$ ]] && \
        [ "${size_gib}" -ge 12 ] && [ "${size_gib}" -le 2048 ] || {
        _compulab_image_error 'image size must be an integer from 12 to 2048 GiB'
        return 2
    }
    bytes=$((size_gib * 1024 * 1024 * 1024))
    _compulab_image_check_sdk "${sdk}" "${target}" "${sku}" "${logo}" "${early}" || return 1
    if ! sudo -n true; then
        _compulab_image_error 'noninteractive sudo is unavailable; no image was created'
        return 1
    fi

    image="${L4T_IMAGE:-}"
    if [ -z "${image}" ]; then
        image_dir="${L4T_IMAGEDIR:-${sdk}/workdir/images.d}"
        case "${image_dir}" in
            /*) ;;
            *) _compulab_image_error 'L4T_IMAGEDIR must be absolute'; return 2 ;;
        esac
        case "${image_dir}" in
            /dev|/dev/*|/proc|/proc/*|/sys|/sys/*)
                _compulab_image_error 'output cannot be a device or kernel path'; return 2 ;;
        esac
        (umask 077; mkdir -p -- "${image_dir}") || return 1
        image_dir=$(readlink -e -- "${image_dir}") || return 1
        [ "$(stat -c '%u' -- "${image_dir}")" = "${owner}" ] || {
            _compulab_image_error 'image directory is not owned by the invoking user'; return 2
        }
        mode=$(stat -c '%a' -- "${image_dir}") || return 1
        (( (8#${mode} & 0022) == 0 )) || {
            _compulab_image_error 'image directory must not be group/other-writable'; return 2
        }
        parent=$(mktemp -d "${image_dir}/image-XXXXXXXX") || return 1
        image="${parent}/${size_gib}g.img"
    else
        case "${image}" in
            /dev|/dev/*|/proc|/proc/*|/sys|/sys/*)
                _compulab_image_error 'output cannot be a device or kernel path'; return 2 ;;
            /*.img) ;;
            *) _compulab_image_error 'L4T_IMAGE must be a new absolute .img path'; return 2 ;;
        esac
        [ ! -e "${image}" ] && [ ! -L "${image}" ] || {
            _compulab_image_error 'output already exists; no images or devices are overwritten'; return 2
        }
        parent=$(readlink -e -- "$(dirname -- "${image}")") || {
            _compulab_image_error 'output parent directory must already exist'; return 2
        }
        image="${parent}/$(basename -- "${image}")"
        [ "$(stat -c '%u' -- "${parent}")" = "${owner}" ] || {
            _compulab_image_error 'output parent is not owned by the invoking user'; return 2
        }
        mode=$(stat -c '%a' -- "${parent}") || return 1
        (( (8#${mode} & 0022) == 0 )) || {
            _compulab_image_error 'output parent must not be group/other-writable'; return 2
        }
    fi
    if _compulab_image_worker "${sdk}" "${target}" "${sku}" "${image}" \
        "${size_gib}" "${logo}" "${early}" "${owner}" "${bytes}"; then
        export L4T_IMAGE="${image}"
        printf 'Created a disk image %s\n' "${L4T_IMAGE}"
    else
        status="$?"
        return "${status}"
    fi
}

# The R36 archive would overwrite the matched R39 board/UEFI configuration.
l4t_compulab_support()
{
    _compulab_image_error 'legacy bulk support downloads are disabled in this SDK'
    _compulab_image_error 'retain the matched R39.2.1 adapter and use its Git/provenance workflow'
    return 2
}

# The old SDK-update generator embeds another bulk archive extraction.
l4t_compulab()
{
    l4t_compulab_support
}

Linux_for_Tegra_sdk()
{
    l4t_compulab_support
}

printf 'CompuLab R39.2.1 native image adapter loaded; legacy bulk updates blocked.\n'
