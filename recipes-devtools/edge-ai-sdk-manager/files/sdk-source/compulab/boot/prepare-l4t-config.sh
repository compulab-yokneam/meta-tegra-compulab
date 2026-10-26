#!/bin/bash
# Derive an immutable SDK input template without changing the Yocto artifact.
set -euo pipefail
if [[ $# != 2 ]]; then
    printf 'Usage: %s INPUT_L4TConfiguration.dtbo NEW_OUTPUT.dtbo\n' "$0" >&2
    exit 2
fi
input=$1
output=$2
node=/fragment@0/__overlay__/firmware/uefi
property=fmp-lowest-supported-version
if [[ ! -s $input || -e $output || -L $output || ! -d $(dirname "$output") ]]; then
    printf '%s\n' 'Input must exist; output must be new in an existing directory.' >&2
    exit 1
fi
minimum=$(fdtget -tx "$input" "$node" "$property")
if [[ $minimum != 270201 ]]; then
    printf 'Unexpected FMP minimum %s; expected R39.2.1 (0x270201).\n' \
        "$minimum" >&2
    exit 1
fi
temporary=$(mktemp "$(dirname "$output")/.compulab-l4t-config.XXXXXXXX.dtbo")
trap 'rm -f -- "$temporary"' EXIT
cp -- "$input" "$temporary"
fdtput -d "$temporary" "$node" "$property"
chmod 0644 "$temporary"
# link(2) provides no-clobber publication even if another process creates it.
ln -- "$temporary" "$output"
printf 'Prepared %s; SDK will set FMP minimum from its R39.2.1 BSP version.\n' \
    "$output"
