#!/bin/bash
# SPDX-License-Identifier: MIT
# Source AFTER the legacy compulab-l4t.env. Never bind its R36 flash helper.

if [ -z "${BASH_VERSION:-}" ]; then
    printf 'CompuLab host compatibility requires Bash.\n' >&2
    return 2 2>/dev/null || exit 2
fi

if ! declare -F create_disk_image >/dev/null || \
   ! declare -F l4t_compulab_support >/dev/null; then
    printf 'Source the legacy compulab-l4t.env before this adapter.\n' >&2
    return 2 2>/dev/null || exit 2
fi

source "$(dirname -- "${BASH_SOURCE[0]}")/image-builder.sh" || return 2

# Preserve the existing public API; the backend is also usable by the native
# sourceable SDK wrapper without loading any legacy code.
create_disk_image()
{
    _compulab_create_disk_image "$@"
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
