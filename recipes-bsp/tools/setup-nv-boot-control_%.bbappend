EDGE_AI_PLATFORM_TARGET:edge-ai-family = "jetson-orin-nano-devkit-super"

# TNSPEC_MACHINE must remain the Yocto machine name because tegraflash uses it
# to locate machine configuration.  Only the persistent EFI platform alias is
# changed so it matches the board aliases packaged in the combined BUP.
do_compile:append:edge-ai-family() {
    sed -i 's/^TARGET=.*/TARGET="${EDGE_AI_PLATFORM_TARGET}"/' \
        ${B}/setup-nv-boot-control.sh
}
