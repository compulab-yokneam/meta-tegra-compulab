FILESEXTRAPATHS:prepend := "${THISDIR}/${PN}:"

SRC_URI:append = " file://clear-bup-tnspec.py"

# NVIDIA EDK2 accepts an image-info entry with an empty TNSPEC without running
# its token-count-sensitive platform comparison.  The BUP is generated for one
# exact module first; only then is the image-info TNSPEC metadata cleared.
EDGE_AI_UEFI_WILDCARD_TNSPEC ?= "0"

tegraflash_custom_sign_bup() {
    ./generate_bup_payload.sh ${TEGRA_SIGNING_ARGS}

    if [ "${EDGE_AI_UEFI_WILDCARD_TNSPEC}" = "1" ]; then
        bup=${BUP_PAYLOAD_DIR}/bl_only_payload
        [ -s "$bup" ] || bbfatal "Cannot clear BUP TNSPEC: missing $bup"
        ${PYTHON} ${UNPACKDIR}/clear-bup-tnspec.py "$bup"
    fi
}
