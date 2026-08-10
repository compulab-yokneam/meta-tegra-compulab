FILESEXTRAPATHS:prepend := "${THISDIR}/${PN}:"

# wasi-sdk uses ExternalProject to obtain this source while compiling. Fetch it
# through BitBake instead so do_compile remains reproducible and network-free.
SRC_URI += " \
    https://download.gnome.org/sources/libxml2/2.15/libxml2-2.15.2.tar.xz;subdir=wasi-sdk-libxml2;striplevel=1;name=wasi-sdk-libxml2 \
    file://0001-cmake-Allow-using-a-pre-fetched-libxml2-source-tree.patch \
"
SRC_URI[wasi-sdk-libxml2.sha256sum] = "c8b9bc81f8b590c33af8cc6c336dbff2f53409973588a351c95f1c621b13d09d"

EXTRA_OECMAKE += "-DWASI_SDK_LIBXML2_SOURCE_DIR=${UNPACKDIR}/wasi-sdk-libxml2"
