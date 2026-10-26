# The wildcard append already imports linux.inc and the shared compulab.cfg.
# Keep the Noble-specific platform configuration separate from the Linux 6.18
# ADI queue, and retain the upstream/vendor part of the kernel release string.
FILESEXTRAPATHS:prepend := "${THISDIR}/files:"

SRC_URI:append:edge-ai = " \
    file://adi-gmsl-v18-noble/edge-ai-noble.cfg \
"
LINUX_VERSION_EXTENSION:append:edge-ai = "-clab"

# This independent queue targets the R39.2.1 Ubuntu/NVIDIA 6.8 source. The ATR
# backport includes matching TI DS90UB9xx consumers; do not disable their
# existing shared configurations or add the Linux 6.18-only adapter patch.
SRC_URI:append:edge-ai:adi-gmsl-v18 = " \
    file://adi-gmsl-v18-noble/0001-i2c-atr-backport-address-mapping-for-noble.patch \
    file://adi-gmsl-v18-noble/0002-media-maxim-serdes-backport-ADI-v18-to-noble.patch \
    file://adi-gmsl-v18-noble/edgedes-adi-v18.cfg \
"
LINUX_VERSION_EXTENSION:append:edge-ai:adi-gmsl-v18 = "-adi-v18"

python __anonymous() {
    overrides = (d.getVar("OVERRIDES") or "").split(":")
    if "edge-ai" not in overrides or "adi-gmsl-v18" not in overrides:
        return
    if d.getVar("L4T_VERSION") != "39.2.1":
        raise bb.parse.SkipRecipe("Edge-AI Noble ADI v18 requires L4T 39.2.1")
}
