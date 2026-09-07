# NVIDIA EDK2 treats an empty TNSPEC token as a wildcard.  For the universal
# Edge-AI update bundle, blank only the target-name token generated from
# MACHINE; the module board ID and SKU remain exact compatibility keys.
EDGE_AI_UEFI_WILDCARD_TNSPEC ?= "0"

tegraflash_custom_sign_bup() {
    if [ "${EDGE_AI_UEFI_WILDCARD_TNSPEC}" != "1" ]; then
        ./generate_bup_payload.sh ${TEGRA_SIGNING_ARGS}
        return
    fi

    wildcard_script=./generate_bup_payload-wildcard-tnspec.sh
    sed "s/^MACHINE=${TNSPEC_MACHINE} /MACHINE= /" \
        ./generate_bup_payload.sh > "$wildcard_script"
    chmod 0755 "$wildcard_script"
    "$wildcard_script" ${TEGRA_SIGNING_ARGS}
}
