#!/bin/bash
# Source from the CompuLab board profile, then call only from its late hook.
# The stock R39.2.1 flash.sh sets L4T_CONF_DTBO after sourcing board profiles.
compulab_select_l4t_config()
{
    local private_name=compulab-L4TConfiguration.dtbo
    local token
    local count=0
    local result=
    local -a tokens=()

    if [[ -z ${BL_DIR:-} || -z ${DTB_DIR:-} ]]; then
        printf '%s\n' 'CompuLab: BL_DIR and DTB_DIR must be resolved first.' >&2
        return 1
    fi
    if [[ ! -s ${DTB_DIR}/${private_name} ]]; then
        printf 'CompuLab: missing configuration template: %s\n' \
            "${DTB_DIR}/${private_name}" >&2
        return 1
    fi

    IFS=, read -r -a tokens <<< "${OVERLAY_DTB_FILE:-}"
    for token in "${tokens[@]}"; do
        case "$token" in
            L4TConfiguration.dtbo|"$private_name")
                token=$private_name
                count=$((count + 1))
                ;;
        esac
        result+="${result:+,}${token}"
    done
    if [[ $count != 1 ]]; then
        printf 'CompuLab: expected one L4T configuration overlay, found %s.\n' \
            "$count" >&2
        return 1
    fi

    OVERLAY_DTB_FILE=$result
    L4T_CONF_DTBO="${BL_DIR}/${private_name}"
}
