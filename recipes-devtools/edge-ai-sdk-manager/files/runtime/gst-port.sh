#!/bin/bash
# SPDX-License-Identifier: MIT
# Explicit scratch preparation/native build; no installation or package actions.
set -euo pipefail
bundle=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
action=${1:-check}
case "$action" in check|prepare|build) [ "$#" -eq 0 ] || shift ;; *)
    printf '%s\n' 'Usage: gst-port.sh [check|prepare|build] --work-dir NEWDIR [--mmapi-source PATH] [--cuda-path PATH]' >&2
    exit 2 ;;
esac
work_dir=
mmapi=/usr/src/jetson_multimedia_api
cuda_path=/usr/local/cuda
jobs=$(getconf _NPROCESSORS_ONLN)
fail() { printf 'ERROR: %s\n' "$*" >&2; exit 2; }
while [ "$#" -gt 0 ]; do
    [ "$#" -ge 2 ] || fail "$1 requires a value"
    case "$1" in
        --work-dir) work_dir=$2 ;;
        --mmapi-source) mmapi=$2 ;;
        --cuda-path) cuda_path=$2 ;;
        --jobs) jobs=$2 ;;
        *) fail "unknown option: $1" ;;
    esac
    shift 2
done
case "$jobs" in ''|*[!0-9]*) fail '--jobs must be a positive integer' ;; esac
[ "$jobs" -gt 0 ] || fail '--jobs must be positive'
bash "$bundle/runtime-port.sh" check
[ "$action" != check ] || exit 0
[ -n "$work_dir" ] && [ ! -e "$work_dir" ] || fail '--work-dir must be a new directory'
[[ ! "$work_dir" =~ [[:space:]] ]] || fail 'vendor Makefiles require a whitespace-free work path'
[[ ! "$mmapi" =~ [[:space:]] ]] || fail 'vendor Makefiles require a whitespace-free MMAPI path'
[[ ! "$cuda_path" =~ [[:space:]] ]] || fail 'vendor Makefiles require a whitespace-free CUDA path'
if [ "$action" = build ]; then
    [ "$(uname -m)" = aarch64 ] || fail 'Ubuntu aarch64 native build required'
    bash "$bundle/runtime-port.sh" check --rootfs /
    pkg-config --exists gstreamer-1.0 gstreamer-base-1.0 gstreamer-video-1.0 \
        gstreamer-allocators-1.0 glib-2.0 libv4l2 || fail 'GStreamer/libv4l2 development packages missing'
    [ -r "$mmapi/argus/include/Argus/Argus.h" ] || fail 'matching MMAPI source headers missing'
    mmapi=$(realpath -- "$mmapi")
    cuda_path=$(realpath -- "$cuda_path")
    cuda_target=
    for candidate in sbsa-linux aarch64-linux; do
        if [ -r "$cuda_path/targets/$candidate/include/cuda_runtime_api.h" ]; then
            cuda_target=$candidate
            break
        fi
    done
    [ -n "$cuda_target" ] || fail 'nvvidconv needs CUDA target development headers'
    [ -r "$cuda_path/targets/$cuda_target/include/crt/host_config.h" ] ||
        fail 'nvvidconv needs CUDA crt development headers (cuda-crt-13-2)'
fi
[ -d "$bundle/sources" ] || fail 'assemble the pinned public-source archives first'
mkdir -m 0700 -- "$work_dir"
work_dir=$(realpath -- "$work_dir")
mkdir -- "$work_dir/source"
for archive in "$bundle"/sources/*.tbz2; do
    tar -xf "$archive" -C "$work_dir/source"
done
patch --batch --forward --fuzz=0 -p1 -d "$work_dir/source/gst-nvvidconv" \
    < "$bundle/patches/gst/nvvidconv-caps.patch"
for patch_file in "$bundle"/patches/gst/v4l2-*.patch; do
    patch --batch --forward --fuzz=0 -p1 -d "$work_dir/source/gst-v4l2" < "$patch_file"
done
if [ "$action" = prepare ]; then
    printf '%s\n' 'PASS: R39.2.1 sources unpacked and functional patches applied; not compiled.'
    exit 0
fi
nvidia_lib=/usr/lib/aarch64-linux-gnu/nvidia
pkg_flags=$(pkg-config --libs gstreamer-1.0 gstreamer-base-1.0 \
    gstreamer-video-1.0 gstreamer-allocators-1.0 glib-2.0 libv4l2)
link_flags="-Wl,--no-undefined -L$nvidia_lib -L$cuda_path/targets/$cuda_target/lib"
link_flags+=" -Wl,-rpath,$nvidia_lib -Wl,-rpath,$cuda_path/targets/$cuda_target/lib"
link_flags+=" -Wl,-rpath-link,/opt/nvidia/l4t-gpu-libs/nvgpu"
for component in gst-nvarguscamera gst-v4l2 gst-nvvidconv; do
    includes="-I$work_dir/source/$component -I$work_dir/source -I$mmapi/include -I$mmapi/argus/include -I$mmapi/argus/samples/utils"
    includes+=" -I$cuda_path/include -I$cuda_path/targets/$cuda_target/include"
    case "$component" in
        gst-v4l2)
            # R39's helper is provided by the matching native NVIDIA package.
            make -C "$work_dir/source/$component" -j"$jobs" \
                LIB_INSTALL_DIR="$nvidia_lib/" INCLUDES="$includes" LDFLAGS="$link_flags" \
                LIBS="-lnvbufsurface -lnvbufsurftransform -lgstnvcustomhelper -ldl $pkg_flags"
            ;;
        gst-nvvidconv)
            make -C "$work_dir/source/$component" -j"$jobs" \
                LIB_INSTALL_DIR="$nvidia_lib/" CUDA_PATH="$cuda_path" \
                INCLUDES="$includes" \
                LDFLAGS="$link_flags"
            ;;
        *)
            make -C "$work_dir/source/$component" -j"$jobs" \
                LIB_INSTALL_DIR="$nvidia_lib/" INCLUDES="$includes" LDFLAGS="$link_flags"
            ;;
    esac
done
mkdir -- "$work_dir/plugins"
for item in gst-nvarguscamera:libgstnvarguscamerasrc.so \
    gst-v4l2:libgstnvvideo4linux2.so gst-nvvidconv:libgstnvvidconv.so; do
    component=${item%%:*}; plugin=${item#*:}
    readelf -h "$work_dir/source/$component/$plugin" | grep -Eq 'Machine:.*AArch64' || fail 'wrong ELF architecture'
    LD_LIBRARY_PATH=/opt/nvidia/l4t-gpu-libs/nvgpu:$nvidia_lib:$cuda_path/targets/$cuda_target/lib \
        ldd -r "$work_dir/source/$component/$plugin" > "$work_dir/$plugin.ldd" 2>&1
    if grep -Eq 'not found|undefined symbol' "$work_dir/$plugin.ldd"; then fail 'unresolved plugin dependency'; fi
    cp -- "$work_dir/source/$component/$plugin" "$work_dir/plugins/$plugin"
done
cp -- "$bundle/SHA256SUMS" "$work_dir/bundle.SHA256SUMS"
printf '%s\n' '39.2.1-20260806224157 Ubuntu24.04 aarch64 gst-three-plugins' > "$work_dir/BUILD-RECEIPT"
printf '%s\n' 'PASS: three native plugins built; GPU registration/capture are not tested.'
