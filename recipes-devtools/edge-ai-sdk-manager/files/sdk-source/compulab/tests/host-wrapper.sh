#!/bin/bash
# SPDX-License-Identifier: MIT
# Mock-only host adapter tests: no real sudo/losetup, mounts, or flashing.
set -eo pipefail

sdk=$(cd -- "$(dirname -- "$0")/../.." && pwd -P)
work=$(mktemp -d /tmp/edge-ai-host-wrapper-check.XXXXXXXX)
adapter="${sdk}/compulab/host/legacy-wrapper-compat.sh"
cases=0

if bash -c 'source "$1"' adapter-source-test "${adapter}" \
    >"${work}/source-order.txt" 2>&1; then
    printf 'FAIL: adapter loaded before the legacy wrapper\n' >&2
    exit 1
fi
grep -F 'Source the legacy compulab-l4t.env before this adapter' \
    "${work}/source-order.txt" >/dev/null
printf 'PASS: refuses incorrect source ordering\n'

fail()
{
    printf 'FAIL: %s\nEvidence: %s\n' "$*" "${work}" >&2
    exit 1
}

require_line()
{
    grep -Fx -- "$2" "$1" >/dev/null || fail "missing '$2' in $1"
}

# Stubs model the already sourced legacy wrapper. Every dangerous legacy
# function fails conspicuously if the adapter accidentally calls it.
create_disk_image() { fail 'old create_disk_image called'; }
l4t_compulab_support() { fail 'old downloader called'; }
create_disk_image_func() { fail 'old image function called'; }
_create_disk_image_proc() { fail 'old image proc called'; }
overlays_mount() { fail 'old bind mount called'; }
overlays_umount() { fail 'old bind unmount called'; }
l4t_compulab() { fail 'old SDK update generator called'; }
Linux_for_Tegra_sdk() { fail 'old SDK snapshot/updater called'; }
source "${adapter}"

stat()
{
    if [ "${*: -1}" = /dev/loop700 ]; then
        [ "$1" = -Lc ] && [ "$2" = '%F:%t' ] || return 98
        printf '%s\n' "${MOCK_LOOP_METADATA:-block special file:7}"
    elif [ "${MOCK_WRONG_OWNER:-0}" = 1 ] && [ "$1" = -c ] && \
         [ "$2" = '%u:%h' ] && [ -s "${mock_created:-/nonexistent}" ] && \
         [ "${*: -1}" = "$(command cat "${mock_created}")" ]; then
        printf '0:1\n'
    elif [ "$1" = -c ] && [ "$2" = '%s' ] && \
         [ -s "${mock_created:-/nonexistent}" ] && \
         [ "${*: -1}" = "$(command cat "${mock_created}")" ]; then
        command cat "${mock_bytes}"
    else
        command stat "$@"
    fi
}

truncate()
{
    [ "$1" = -s ] && [ "$3" = -- ] || return 98
    [ "${MOCK_TRUNCATE_RC:-0}" -eq 0 ] || return "${MOCK_TRUNCATE_RC}"
    # Keep the placeholder empty; no disk-sized images are created in tests.
    printf '%s\n' "$2" >"${mock_bytes}"
    printf '%s\n' "$4" >"${mock_created}"
    if [ "${MOCK_HARDLINK:-0}" = 1 ]; then
        ln -- "$4" "${case_dir}/unexpected-hardlink"
    fi
}

sha256sum()
{
    if [ "${MOCK_CHANGED_HELPER:-0}" = 1 ] && \
       [ "${*: -1}" = "${sdk}/tools/kernel_flash/l4t_flash_from_kernel.sh" ]; then
        printf '%s  %s\n' changed-helper "${*: -1}"
    else
        command sha256sum "$@"
    fi
}

sudo()
{
    # This function is the only backend. Unknown operations always fail.
    [ "$1" = -n ] || return 98
    shift
    case "$*" in
        true) return "${MOCK_SUDO_RC:-0}" ;;
        'losetup --find --show --partscan -- '*)
            printf 'allocate\n' >>"${mock_log}"
            [ "${MOCK_ALLOC_RC:-0}" -eq 0 ] || return "${MOCK_ALLOC_RC}"
            printf '%s\n' "${*: -1}" >"${mock_backing}"
            # Models allocation followed by interruption before stdout capture.
            [ "${MOCK_ALLOC_PARTIAL:-0}" -ne 1 ] || return 77
            printf '/dev/loop700\n'
            ;;
        'losetup --noheadings --raw --output BACK-FILE -- /dev/loop700')
            if [ "${MOCK_WRONG_BACKING:-0}" = 1 ]; then
                printf '/dev/nvme0n1\n'
            else
                command cat "${mock_backing}"
            fi
            ;;
        'losetup --noheadings --raw --output NAME --associated '*)
            [ ! -s "${mock_backing}" ] || printf '/dev/loop700\n'
            ;;
        'losetup --detach /dev/loop700')
            printf 'detach\n' >>"${mock_log}"
            return "${MOCK_DETACH_RC:-0}"
            ;;
        'env '*)
            printf 'flash\n' >>"${mock_log}"
            printf '%s\n' "$@" >"${mock_args}"
            # Ensure a typo cannot reach some different executable even mocked.
            [[ " $* " = *' ./tools/kernel_flash/l4t_initrd_flash.sh '* ]] || return 98
            if [ "${MOCK_SWITCH_BACKING:-0}" = 1 ]; then
                printf '/dev/nvme0n1\n' >"${mock_backing}"
            fi
            if [ "${MOCK_SIGNAL:-}" = TERM ]; then
                kill -TERM "${BASHPID}"
            elif [ "${MOCK_SIGNAL:-}" = HUP ]; then
                kill -HUP "${BASHPID}"
            elif [ "${MOCK_SIGNAL:-}" = INT ]; then
                kill -INT "${BASHPID}"
            fi
            return "${MOCK_FLASH_RC:-0}"
            ;;
        *) printf 'Unexpected mocked sudo operation: %s\n' "$*" >&2; return 98 ;;
    esac
}

new_case()
{
    cases=$((cases + 1))
    case_dir="${work}/case-${cases}"
    mkdir -m 700 "${case_dir}"
    mock_log="${case_dir}/backend.log"
    mock_args="${case_dir}/args.txt"
    mock_backing="${case_dir}/backing.txt"
    mock_bytes="${case_dir}/bytes.txt"
    mock_created="${case_dir}/created.txt"
    : >"${mock_log}"
    : >"${mock_backing}"
    unset size MOCK_ALLOC_RC MOCK_DETACH_RC MOCK_WRONG_BACKING MOCK_SIGNAL
    unset MOCK_CHANGED_HELPER MOCK_FLASH_RC
    unset MOCK_LOOP_METADATA MOCK_HARDLINK MOCK_ALLOC_PARTIAL MOCK_TRUNCATE_RC
    unset MOCK_SUDO_RC
    unset MOCK_WRONG_OWNER MOCK_SWITCH_BACKING
    unset BOARDREV CHIPREV CHIP_SKU chip_SKU RAMCODE RAMCODE_ID
    L4T_ROOT="${sdk}" L4T_IMAGEDIR="${case_dir}" L4T_IMAGE=""
    EDGE_AI=edge-ai BOARDSKU=-1 BOARDID=3767 FAB=TS4
    EDGE_AI_UEFI_LOGO_STYLE=clab-logo EDGE_AI_EARLY_TTY1=0
    LOOP_DEV_SIZE_GB=32
}

run_expected()
{
    local expected="$1" actual
    if create_disk_image >"${case_dir}/stdout.txt" 2>"${case_dir}/stderr.txt"; then
        actual=0
    else
        actual="$?"
    fi
    [ "${actual}" -eq "${expected}" ] || \
        fail "case ${cases}: expected ${expected}, got ${actual}"
}

assert_no_backend()
{
    [ ! -s "${mock_log}" ] || fail "case ${cases}: unexpected loop/flash invocation"
}

for target in edge-ai edge-ai-nx-16g edge-ai-nx-8g edge-ai-nano-8g edge-ai-nano-4g; do
    for logo in clab-logo nvidia-logo no-logo; do
        new_case
        EDGE_AI="${target}" EDGE_AI_UEFI_LOGO_STYLE="${logo}"
        EDGE_AI_EARLY_TTY1=1
        case "${target}" in edge-ai-nano-*) unset FAB ;; esac
        run_expected 0
        [ -f "${L4T_IMAGE}" ] || fail 'successful result not exported'
        require_line "${mock_log}" allocate
        require_line "${mock_log}" flash
        require_line "${mock_log}" detach
        require_line "${mock_args}" EXT_NUM_SECTORS=62914560
        require_line "${mock_args}" 24GiB
        require_line "${mock_args}" EXTDEV_ON_TARGET=loop700
        require_line "${mock_args}" "EDGE_AI_UEFI_LOGO_STYLE=${logo}"
        require_line "${mock_args}" EDGE_AI_EARLY_TTY1=1
        case "${target}" in
            edge-ai|edge-ai-nx-16g) expected_sku=0000; expected_chip=D3; expected_fab=TS4 ;;
            edge-ai-nx-8g) expected_sku=0001; expected_chip=D4; expected_fab=TS4 ;;
            edge-ai-nano-8g) expected_sku=0003; expected_chip=D5; expected_fab=300 ;;
            edge-ai-nano-4g) expected_sku=0004; expected_chip=D6; expected_fab=RC1 ;;
        esac
        require_line "${mock_args}" "BOARDSKU=${expected_sku}"
        require_line "${mock_args}" "CHIP_SKU=00:00:00:${expected_chip}"
        require_line "${mock_args}" "FAB=${expected_fab}"
        case "${target}" in
            edge-ai) require_line "${mock_args}" edge-ai-nx-16g ;;
            *) require_line "${mock_args}" "${target}" ;;
        esac
        case "${target}" in
            edge-ai-nano-8g)
                require_line "${mock_args}" BOARDREV=P.1
                require_line "${mock_args}" CHIPREV=0
                require_line "${mock_args}" RAMCODE_ID=
                ;;
            edge-ai-nano-4g)
                require_line "${mock_args}" BOARDREV=B.4
                require_line "${mock_args}" CHIPREV=0
                require_line "${mock_args}" RAMCODE_ID=4
                require_line "${mock_args}" RAMCODE=4
                ;;
        esac
        printf 'PASS: %s / %s invokes native helper and cleans up\n' "${target}" "${logo}"
    done
done

for setting in FAB=TS4 BOARDREV=A.3 CHIPREV=1 CHIP_SKU=00:00:00:D3 \
    BOARDSKU=0000 RAMCODE=4 RAMCODE_ID=4; do
    new_case
    EDGE_AI=edge-ai-nano-8g
    unset FAB
    export "${setting}"
    run_expected 2
    assert_no_backend
    printf 'PASS: Nano8G rejects conflicting offline %s\n' "${setting}"
done
for setting in FAB=TS4 BOARDREV=P.1 CHIPREV=1 CHIP_SKU=00:00:00:D5 \
    BOARDSKU=0003 RAMCODE=0 RAMCODE_ID=0; do
    new_case
    EDGE_AI=edge-ai-nano-4g
    unset FAB
    export "${setting}"
    run_expected 2
    assert_no_backend
    printf 'PASS: Nano4G rejects conflicting offline %s\n' "${setting}"
done

new_case
EDGE_AI=edge-ai-nano-4g BOARDSKU=4 FAB=RC1 BOARDREV=B.4 CHIPREV=0
CHIP_SKU=00:00:00:D6 RAMCODE_ID=4
run_expected 0
require_line "${mock_args}" BOARDSKU=0004
require_line "${mock_args}" RAMCODE_ID=4
printf 'PASS: accepts explicitly matching Nano4G metadata and short legacy SKU\n'

new_case
size=40
L4T_IMAGE="${case_dir}/new image.img"
run_expected 0
require_line "${mock_args}" EXT_NUM_SECTORS=79691776
require_line "${mock_args}" 32GiB
[ "$(stat -c '%s' -- "${L4T_IMAGE}")" = 42949672960 ] || fail 'size override mismatch'
[ "$(command stat -c '%s' -- "${L4T_IMAGE}")" = 0 ] || fail 'test created a real image'
printf 'PASS: explicit new path with spaces and consistent per-call size\n'

new_case
L4T_IMAGEDIR="${case_dir}/new/owned-images"
run_expected 0
[ "$(command stat -c '%a' -- "${L4T_IMAGEDIR}")" = 700 ] || fail 'new image directory is not private'
printf 'PASS: fresh default image directory is private regardless of caller umask\n'

for variable in 'EDGE_AI=unknown' 'BOARDSKU=0001' 'BOARDID=3701' \
    'EDGE_AI_UEFI_LOGO_STYLE=wrong' 'EDGE_AI_EARLY_TTY1=2' \
    'LOOP_DEV_SIZE_GB=08' 'LOOP_DEV_SIZE_GB=8' 'LOOP_DEV_SIZE_GB=9999'; do
    new_case
    export "${variable}"
    run_expected 2
    assert_no_backend
    printf 'PASS: rejects %s before backend\n' "${variable}"
done

for destination in /dev/sda /dev/null /proc/new.img /sys/new.img relative.img; do
    new_case
    L4T_IMAGE="${destination}"
    run_expected 2
    assert_no_backend
    printf 'PASS: rejects unsafe output %s\n' "${destination}"
done

new_case
L4T_IMAGE="${case_dir}/existing.img"
printf 'do not overwrite\n' >"${L4T_IMAGE}"
run_expected 2
assert_no_backend
require_line "${L4T_IMAGE}" 'do not overwrite'
printf 'PASS: existing image remains unchanged\n'

new_case
L4T_IMAGE="${case_dir}/symlink.img"
ln -s "${case_dir}/not-created.img" "${L4T_IMAGE}"
run_expected 2
assert_no_backend
printf 'PASS: rejects dangling output symlink\n'

new_case
chmod g+w "${case_dir}"
run_expected 2
assert_no_backend
printf 'PASS: rejects group-writable output directory\n'

new_case
MOCK_CHANGED_HELPER=1
run_expected 1
assert_no_backend
printf 'PASS: refuses changed/overmounted native helper\n'

new_case
MOCK_SUDO_RC=1
run_expected 1
assert_no_backend
[ "$(find "${case_dir}" -name '*.img' -print -quit)" = '' ] || fail 'created image without sudo'
printf 'PASS: unavailable noninteractive sudo fails before image creation\n'

new_case
MOCK_ALLOC_RC=23
run_expected 23
! grep -Fx flash "${mock_log}" >/dev/null || fail 'flashed after allocation failure'
printf 'PASS: preserves allocation failure status\n'

new_case
MOCK_ALLOC_PARTIAL=1
run_expected 77
require_line "${mock_log}" detach
! grep -Fx flash "${mock_log}" >/dev/null || fail 'flashed after partial allocation failure'
printf 'PASS: allocation-before-output failure discovers and detaches owned loop\n'

new_case
MOCK_TRUNCATE_RC=29
run_expected 29
assert_no_backend
printf 'PASS: sizing error status is preserved before loop allocation\n'

new_case
MOCK_HARDLINK=1
run_expected 1
assert_no_backend
printf 'PASS: refuses multiply linked output before loop allocation\n'

new_case
MOCK_WRONG_OWNER=1
run_expected 1
assert_no_backend
printf 'PASS: rejects output ownership change before loop allocation\n'

new_case
MOCK_LOOP_METADATA='block special file:8'
run_expected 1
! grep -Eq '^(flash|detach)$' "${mock_log}" || fail 'used wrong-major block device'
printf 'PASS: a non-loop block-device major is refused\n'

new_case
MOCK_FLASH_RC=37
run_expected 37
require_line "${mock_log}" detach
[ -z "${L4T_IMAGE}" ] || fail 'exported incomplete image as a success'
printf 'PASS: native failure status preserved with cleanup\n'

new_case
MOCK_FLASH_RC=37 MOCK_DETACH_RC=69
run_expected 37
require_line "${mock_log}" detach
printf 'PASS: cleanup error does not mask native failure\n'

new_case
MOCK_DETACH_RC=69
run_expected 69
printf 'PASS: cleanup failure prevents success\n'

new_case
MOCK_WRONG_BACKING=1
run_expected 1
! grep -Eq '^(flash|detach)$' "${mock_log}" || fail 'used mismatched backing device'
printf 'PASS: mismatched backing cannot be flashed or detached\n'

new_case
MOCK_SWITCH_BACKING=1
run_expected 1
require_line "${mock_log}" flash
! grep -Fx detach "${mock_log}" >/dev/null || fail 'detached backing changed after flash'
printf 'PASS: cleanup revalidates backing and refuses a changed association\n'

for signal in HUP INT TERM; do
    new_case
    MOCK_SIGNAL="${signal}"
    case "${signal}" in HUP) expected=129 ;; INT) expected=130 ;; TERM) expected=143 ;; esac
    run_expected "${expected}"
    require_line "${mock_log}" detach
    printf 'PASS: %s preserves signal status and detaches\n' "${signal}"
done

for downloader in l4t_compulab_support l4t_compulab Linux_for_Tegra_sdk; do
    if "${downloader}" >"${work}/${downloader}.txt" 2>&1; then
        fail "${downloader} was not blocked"
    fi
    grep -F 'legacy bulk support downloads are disabled' \
        "${work}/${downloader}.txt" >/dev/null || fail 'missing downloader explanation'
    printf 'PASS: blocks %s\n' "${downloader}"
done

printf 'Completed %s image scenarios; all host operations mocked.\nEvidence: %s\n' \
    "${cases}" "${work}"
