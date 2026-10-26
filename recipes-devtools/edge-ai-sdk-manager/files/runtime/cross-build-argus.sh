#!/bin/bash
# SPDX-License-Identifier: MIT
# Explicit Ubuntu sysroot build using the host's aarch64-linux-gnu toolchain.
set -euo pipefail
bundle=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
action=${1:-check}
case "$action" in check|build) [ "$#" -eq 0 ] || shift ;; *) exit 2 ;; esac
sysroot=
work_dir=
source_deb=
suite=minimal
cuda_host=
fail() { printf 'ERROR: %s\n' "$*" >&2; exit 2; }
while [ "$#" -gt 0 ]; do
    [ "$#" -ge 2 ] || fail "$1 needs a value"
    case "$1" in
        --sysroot) sysroot=$2 ;;
        --work-dir) work_dir=$2 ;;
        --source-deb) source_deb=$2 ;;
        --suite) suite=$2 ;;
        --cuda-host) cuda_host=$2 ;;
        *) fail "unknown option: $1" ;;
    esac
    shift 2
done
case "$suite" in minimal|full) ;; *) fail '--suite must be minimal or full' ;; esac
bash "$bundle/runtime-port.sh" check
[ "$action" != check ] || exit 0
[ -n "$sysroot" ] && [ -n "$work_dir" ] && [ -n "$source_deb" ] ||
    fail 'build requires --sysroot, --work-dir NEWDIR and --source-deb'
sysroot=$(realpath -- "$sysroot")
source_deb=$(realpath -- "$source_deb")
[ "$sysroot" != / ] || fail 'an isolated Ubuntu aarch64 sysroot is required'
[[ ! "$sysroot" =~ [[:space:]] ]] || fail 'use a whitespace-free sysroot path'
[ ! -e "$work_dir" ] || fail 'work directory must not already exist'
bash "$bundle/runtime-port.sh" check --rootfs "$sysroot"
[ -r "$sysroot/opt/nvidia/l4t-gpu-libs/nvgpu/libcuda.so.1.1" ] ||
    fail 'the matching T234 NVIDIA nvgpu CUDA payload is missing'
actual=$(sha256sum "$source_deb"); actual=${actual%% *}
[ "$actual" = fe88dbe8afe4158f5985e32fd0dddc83768091788b3bd1ffbc8d878492cee30b ] ||
    fail 'source package hash mismatch'
for tool in cmake pkg-config patch aarch64-linux-gnu-gcc aarch64-linux-gnu-g++ readelf; do
    command -v "$tool" >/dev/null || fail "command missing: $tool"
done
cuda_target="$sysroot/usr/local/cuda-13.2/targets/sbsa-linux"
cmake_cuda=(-DEDGE_AI_MINIMAL_ARGUS=ON -DCMAKE_DISABLE_FIND_PACKAGE_CUDA=ON)
binary_names=(argus_camera argus_oneshot)
receipt=minimal-argus
if [ "$suite" = full ]; then
    [ -n "$cuda_host" ] || fail 'full suite requires --cuda-host EXTRACTED_CUDA_TOOLKIT'
    cuda_host=$(realpath -- "$cuda_host")
    "$cuda_host/bin/nvcc" --version | grep -Fq 'V13.2.86' || fail 'exact NVIDIA nvcc 13.2.86 required'
    readelf -h "$cuda_host/bin/nvcc" | grep -Fq 'Advanced Micro Devices X86-64' ||
        fail 'this cross build requires the official x86 NVIDIA nvcc'
    for header in cuda_runtime.h crt/host_config.h fatbinary_section.h; do
        [ -r "$cuda_target/include/$header" ] || fail "target CUDA header missing: $header"
        [ -r "$cuda_host/targets/sbsa-linux/include/$header" ] ||
            fail "host toolkit must contain exact target headers: $header"
    done
    [ -r "$cuda_target/lib/libcudart.so" ] || fail 'Ubuntu ARM64 cudart development package required'
    cmake_cuda=(-DEDGE_AI_MINIMAL_ARGUS=OFF
        -DCUDA_TOOLKIT_ROOT_DIR="$cuda_host"
        -DCUDA_TOOLKIT_ROOT_DIR_INTERNAL="$cuda_host"
        -DCUDA_TOOLKIT_TARGET_DIR="$cuda_target"
        -DCUDA_TOOLKIT_TARGET_DIR_INTERNAL="$cuda_target"
        -DCUDA_NVCC_EXECUTABLE="$cuda_host/bin/nvcc"
        -DCUDA_HOST_COMPILER=/usr/bin/aarch64-linux-gnu-g++
        -DCUDA_TOOLKIT_INCLUDE="$cuda_target/include"
        -DCUDA_CUDART_LIBRARY="$cuda_target/lib/libcudart.so"
        -DCUDA_CUDA_LIBRARY="$sysroot/opt/nvidia/l4t-gpu-libs/nvgpu/libcuda.so.1.1"
        "-DCUDA_NVCC_FLAGS=--target-directory=sbsa-linux;--gpu-architecture=sm_87;-Xcompiler=--sysroot=$sysroot")
    mapfile -t binary_names < "$bundle/files/argus-full-suite.txt"
    receipt=full-argus-23
fi
mkdir -m 0700 -- "$work_dir"
work_dir=$(realpath -- "$work_dir")
dpkg-deb -x "$source_deb" "$work_dir/mmapi-package"
source_dir="$work_dir/mmapi-package/usr/src/jetson_multimedia_api"
for patch_file in "$bundle"/patches/argus/*.patch; do
    patch --batch --forward --fuzz=0 -p1 -d "$source_dir" < "$patch_file"
done
export PKG_CONFIG_SYSROOT_DIR="$sysroot"
export PKG_CONFIG_LIBDIR="$sysroot/usr/lib/aarch64-linux-gnu/pkgconfig:$sysroot/usr/lib/pkgconfig:$sysroot/usr/share/pkgconfig"
export PKG_CONFIG_PATH=
pkg-config --exists gtk+-3.0 gstreamer-1.0 gstreamer-video-1.0 expat ||
    fail 'Ubuntu aarch64 sysroot development packages are incomplete'
cmake -S "$source_dir/argus" -B "$work_dir/build" \
    -DCMAKE_SYSTEM_NAME=Linux -DCMAKE_SYSTEM_PROCESSOR=aarch64 \
    -DCMAKE_C_COMPILER=aarch64-linux-gnu-gcc \
    -DCMAKE_CXX_COMPILER=aarch64-linux-gnu-g++ \
    -DCMAKE_SYSROOT="$sysroot" -DCMAKE_FIND_ROOT_PATH="$sysroot" \
    -DCMAKE_FIND_ROOT_PATH_MODE_PROGRAM=NEVER \
    -DCMAKE_FIND_ROOT_PATH_MODE_LIBRARY=ONLY \
    -DCMAKE_FIND_ROOT_PATH_MODE_INCLUDE=ONLY \
    -DCMAKE_FIND_ROOT_PATH_MODE_PACKAGE=ONLY \
    -DCMAKE_BUILD_TYPE=Release -DCMAKE_INSTALL_PREFIX=/usr \
    '-DCMAKE_INSTALL_RPATH=/usr/lib/aarch64-linux-gnu/nvidia;/usr/local/cuda-13.2/targets/sbsa-linux/lib' \
    "-DCMAKE_EXE_LINKER_FLAGS=-L$sysroot/opt/nvidia/l4t-gpu-libs/nvgpu -Wl,-rpath-link,$sysroot/opt/nvidia/l4t-gpu-libs/nvgpu -Wl,-rpath-link,$sysroot/usr/lib/aarch64-linux-gnu/nvidia -Wl,-rpath-link,$cuda_target/lib" \
    "${cmake_cuda[@]}" \
    -DCMAKE_INCLUDE_PATH="$source_dir/include/libjpeg-8b-tegra" \
    -DJPEG_NAMES=libnvjpeg.so \
    -DCMAKE_LIBRARY_PATH=/usr/lib/aarch64-linux-gnu/nvidia
cmake --build "$work_dir/build" --parallel "$(getconf _NPROCESSORS_ONLN)"
DESTDIR="$work_dir/pkgroot" cmake --install "$work_dir/build"
for binary in "${binary_names[@]}"; do
    readelf -h "$work_dir/pkgroot/usr/bin/$binary" | grep -Eq 'Machine:.*AArch64' || fail 'wrong executable architecture'
    readelf --version-info "$work_dir/pkgroot/usr/bin/$binary" > "$work_dir/$binary.versions"
    readelf -d "$work_dir/pkgroot/usr/bin/$binary" > "$work_dir/$binary.dynamic"
done
cp -- "$bundle/SHA256SUMS" "$work_dir/bundle.SHA256SUMS"
printf '%s\n' "39.2.1-20260806224157 Ubuntu24.04 aarch64 $receipt" \
    'BUILD_METHOD=host aarch64-linux-gnu cross compiler against isolated Ubuntu sysroot' \
    > "$work_dir/BUILD-RECEIPT"
printf '%s\n' 'PASS: cross-build complete. Check target loader/relocations separately.' \
    'No target binary, camera or GPU was executed by this build script.'
