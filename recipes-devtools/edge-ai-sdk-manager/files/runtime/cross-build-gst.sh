#!/bin/bash
# SPDX-License-Identifier: MIT
# Cross-build only; never installs packages or executes a target plugin.
set -euo pipefail
bundle=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
action=${1:-check}
case "$action" in check|build) [ "$#" -eq 0 ] || shift ;; *) exit 2 ;; esac
sysroot=
work_dir=
mmapi=
cuda_prefix=/usr/local/cuda-13.2
fail() { printf 'ERROR: %s\n' "$*" >&2; exit 2; }
while [ "$#" -gt 0 ]; do
    [ "$#" -ge 2 ] || fail "$1 needs a value"
    case "$1" in
        --sysroot) sysroot=$2 ;;
        --work-dir) work_dir=$2 ;;
        --mmapi-source) mmapi=$2 ;;
        --cuda-prefix) cuda_prefix=$2 ;;
        *) fail "unknown option: $1" ;;
    esac
    shift 2
done
bash "$bundle/runtime-port.sh" check
[ "$action" != check ] || exit 0
[ -n "$sysroot" ] && [ -n "$work_dir" ] && [ -n "$mmapi" ] ||
    fail 'build requires --sysroot, --work-dir NEWDIR and --mmapi-source'
sysroot=$(realpath -- "$sysroot"); mmapi=$(realpath -- "$mmapi")
[ "$sysroot" != / ] || fail 'isolated Ubuntu ARM64 sysroot required'
for path in "$sysroot" "$work_dir" "$mmapi" "$cuda_prefix"; do
    [[ ! "$path" =~ [[:space:]] ]] || fail 'vendor Makefiles need whitespace-free paths'
done
case "$cuda_prefix" in /*) ;; *) fail '--cuda-prefix must be target-absolute' ;; esac
cuda_path="$sysroot$cuda_prefix"
[ -r "$mmapi/argus/include/Argus/Argus.h" ] || fail 'MMAPI headers missing'
cuda_target=
for candidate in sbsa-linux aarch64-linux; do
    if [ -r "$cuda_path/targets/$candidate/include/cuda_runtime_api.h" ]; then
        cuda_target=$candidate
        break
    fi
done
[ -n "$cuda_target" ] || fail 'CUDA runtime target headers missing'
[ -r "$cuda_path/targets/$cuda_target/include/crt/host_config.h" ] ||
    fail 'CUDA crt development headers missing (cuda-crt-13-2)'
bash "$bundle/gst-port.sh" prepare --work-dir "$work_dir"
work_dir=$(realpath -- "$work_dir")
export PKG_CONFIG_SYSROOT_DIR="$sysroot"
export PKG_CONFIG_LIBDIR="$sysroot/usr/lib/aarch64-linux-gnu/pkgconfig:$sysroot/usr/lib/pkgconfig:$sysroot/usr/share/pkgconfig"
export PKG_CONFIG_PATH=
pkg-config --exists gstreamer-1.0 gstreamer-base-1.0 gstreamer-video-1.0 \
    gstreamer-allocators-1.0 glib-2.0 libv4l2 || fail 'ARM64 sysroot development packages missing'
nvidia_lib="$sysroot/usr/lib/aarch64-linux-gnu/nvidia"
[ -r "$sysroot/opt/nvidia/l4t-gpu-libs/nvgpu/libcuda.so.1.1" ] || fail 'T234 nvgpu CUDA payload missing'
link_flags="-Wl,--no-undefined -L$nvidia_lib -L$cuda_path/targets/$cuda_target/lib"
link_flags+=" -Wl,-rpath,/usr/lib/aarch64-linux-gnu/nvidia -Wl,-rpath,$cuda_prefix/targets/$cuda_target/lib"
link_flags+=" -Wl,-rpath-link,$nvidia_lib -Wl,-rpath-link,$sysroot/usr/lib/aarch64-linux-gnu"
link_flags+=" -Wl,-rpath-link,$sysroot/opt/nvidia/l4t-gpu-libs/nvgpu"
pkg_flags=$(pkg-config --libs gstreamer-1.0 gstreamer-base-1.0 \
    gstreamer-video-1.0 gstreamer-allocators-1.0 glib-2.0 libv4l2)
for component in gst-nvarguscamera gst-v4l2 gst-nvvidconv; do
    compiler=aarch64-linux-gnu-gcc
    [ "$component" != gst-nvarguscamera ] || compiler=aarch64-linux-gnu-g++
    includes="-I$work_dir/source/$component -I$work_dir/source -I$mmapi/include -I$mmapi/argus/include -I$mmapi/argus/samples/utils"
    includes+=" -I$cuda_path/include -I$cuda_path/targets/$cuda_target/include"
    extra=()
    if [ "$component" = gst-v4l2 ]; then
        extra+=("LIBS=-lnvbufsurface -lnvbufsurftransform -lgstnvcustomhelper -ldl $pkg_flags")
    fi
    make -C "$work_dir/source/$component" -j"$(getconf _NPROCESSORS_ONLN)" \
        "CC=$compiler --sysroot=$sysroot" ARCH=aarch64 TARGET_DEVICE=aarch64 \
        "INCLUDES=$includes" "LIB_INSTALL_DIR=$nvidia_lib/" \
        "CUDA_PATH=$cuda_path" "LDFLAGS=$link_flags" "${extra[@]}"
done
mkdir -- "$work_dir/plugins"
for item in gst-nvarguscamera:libgstnvarguscamerasrc.so \
    gst-v4l2:libgstnvvideo4linux2.so gst-nvvidconv:libgstnvvidconv.so; do
    component=${item%%:*}; plugin=${item#*:}
    file_path="$work_dir/source/$component/$plugin"
    readelf -h "$file_path" | grep -Eq 'Machine:.*AArch64' || fail 'wrong plugin architecture'
    readelf -d "$file_path" > "$work_dir/$plugin.dynamic"
    readelf --version-info "$file_path" > "$work_dir/$plugin.versions"
    cp -- "$file_path" "$work_dir/plugins/$plugin"
done
cp -- "$bundle/SHA256SUMS" "$work_dir/bundle.SHA256SUMS"
printf '%s\n' '39.2.1-20260806224157 Ubuntu24.04 aarch64 gst-three-plugins' \
    'BUILD_METHOD=host aarch64-linux-gnu cross compiler against isolated Ubuntu sysroot' \
    > "$work_dir/BUILD-RECEIPT"
printf '%s\n' 'PASS: cross-plugin build complete; target relocation/registration checks remain separate.'
