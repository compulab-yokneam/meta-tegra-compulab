#!/bin/sh
set -eu

here=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
machine=
detect_only=0

usage() {
    echo "Usage: $0 [--detect-only] [--force-machine MACHINE] [-- FLASH_ARGUMENTS...]"
    echo "Supported machines: edge-ai-nx-16g, edge-ai-nx-8g, edge-ai-nano-8g, edge-ai-nano-4g"
}

while [ "$#" -gt 0 ]; do
    case "$1" in
        --detect-only)
            detect_only=1
            shift
            ;;
        --force-machine)
            [ "$#" -ge 2 ] || { usage >&2; exit 2; }
            machine=$2
            echo "WARNING: module detection bypassed; forcing profile $machine" >&2
            shift 2
            ;;
        --help|-h)
            usage
            exit 0
            ;;
        --)
            shift
            break
            ;;
        *)
            break
            ;;
    esac
done

case "$machine" in
    '')
        probe="$here/profiles/edge-ai-nx-16g"
        echo "Reading module EEPROM from the device in recovery mode..."
        (
            cd "$probe"
            rm -f boardvars.sh
            CHECK_BOARDSKU= BOARDID= FAB= BOARDSKU= BOARDREV= CHIPREV= \
                CHIP_SKU= RAMCODE= \
                ./tegra-flash-helper.sh --get-board-info \
                flash.xml.in boot.img edge-ai-flash-profile.ext4
        )
        BOARDID=$(sed -n 's/^BOARDID="\([0-9][0-9]*\)"$/\1/p' \
            "$probe/boardvars.sh")
        BOARDSKU=$(sed -n 's/^BOARDSKU="\([0-9][0-9]*\)"$/\1/p' \
            "$probe/boardvars.sh")
        [ "${BOARDID:-}" = "3767" ] || {
            echo "Unsupported module board ID: ${BOARDID:-unknown}" >&2
            exit 1
        }
        case "${BOARDSKU:-}" in
            0000) machine=edge-ai-nx-16g ;;
            0001) machine=edge-ai-nx-8g ;;
            0003) machine=edge-ai-nano-8g ;;
            0004) machine=edge-ai-nano-4g ;;
            *)
                echo "Unsupported P3767 module SKU: ${BOARDSKU:-unknown}" >&2
                exit 1
                ;;
        esac
        ;;
    edge-ai-nx-16g|edge-ai-nx-8g|edge-ai-nano-8g|edge-ai-nano-4g)
        ;;
    *)
        echo "Unsupported machine: $machine" >&2
        usage >&2
        exit 2
        ;;
esac

echo "Selected flash profile: $machine"
[ "$detect_only" -eq 0 ] || exit 0

profile="$here/profiles/$machine"
[ -x "$profile/doexternal.sh" ] || {
    echo "Incomplete flash profile: $profile" >&2
    exit 1
}

(
    cd "$profile"
    exec ./doexternal.sh "$@"
)
