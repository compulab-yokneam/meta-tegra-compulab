#!/bin/bash
# SPDX-License-Identifier: MIT
# Preparation is read-only by default. Never runs apt, SDK Manager or flashing.
set -euo pipefail
bundle=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
action=check
case "${1-}" in check|build|stage) action=$1; shift ;; esac
rootfs=
source_dir=/usr/src/jetson_multimedia_api
source_deb=
gst_work_dir=
work_dir=
imx676=1
imx678=0
jobs=$(getconf _NPROCESSORS_ONLN)
suite=minimal
cuda_path=/usr/local/cuda-13.2
fail() { printf 'ERROR: %s\n' "$*" >&2; exit 2; }
usage() {
    printf '%s\n' \
        'Usage: runtime-port.sh [check|build|stage] [options]' \
        '  check (default): verify bundle; --rootfs PATH audits Ubuntu runtime.' \
        '  build: native Ubuntu aarch64 only, --work-dir NEWDIR required.' \
        '         --source-dir PATH selects pristine installed R39.2.1 MMAPI.' \
        '         --source-deb FILE extracts the pinned MMAPI .deb without install.' \
        '  stage: --rootfs PATH --work-dir BUILT_WORKDIR; needs Git-baselined LFT.' \
        '         --gst-work-dir DIR also stages explicitly rebuilt plugins.' \
        '  --imx676-extended 0|1  Matched NITO selection (default 1).' \
        '  --imx678-extended 0|1  Matched NITO selection (default 0).' \
        '  --jobs N               Native build parallelism.' \
        '  --suite minimal|full   Native Argus build selection (default minimal).' \
        '  --cuda-path PATH       Matching native CUDA toolkit for full suite.' \
        'No action installs packages, starts services, flashes or accesses a DUT.'
}
while [ "$#" -gt 0 ]; do
    case "$1" in
        -h|--help) usage; exit 0 ;;
        --rootfs|--source-dir|--source-deb|--work-dir|--gst-work-dir|--imx676-extended|--imx678-extended|--jobs|--suite|--cuda-path)
            [ "$#" -ge 2 ] || fail "$1 requires a value"
            key=$1; value=$2; shift 2
            case "$key" in
                --rootfs) rootfs=$value ;;
                --source-dir) source_dir=$value ;;
                --source-deb) source_deb=$value ;;
                --work-dir) work_dir=$value ;;
                --gst-work-dir) gst_work_dir=$value ;;
                --imx676-extended) imx676=$value ;;
                --imx678-extended) imx678=$value ;;
                --jobs) jobs=$value ;;
                --suite) suite=$value ;;
                --cuda-path) cuda_path=$value ;;
            esac ;;
        *) fail "unknown option: $1" ;;
    esac
done
case "$imx676:$imx678" in 0:0|0:1|1:0|1:1) ;; *) fail 'mode switches must be 0 or 1' ;; esac
case "$jobs" in ''|*[!0-9]*) fail 'jobs must be a positive integer' ;; esac
[ "$jobs" -gt 0 ] || fail 'jobs must be positive'
case "$suite" in minimal|full) ;; *) fail '--suite must be minimal or full' ;; esac

verify_bundle() {
    [ -r "$bundle/SHA256SUMS" ] || fail 'bundle manifest is missing'
    (cd "$bundle" && sha256sum --check --strict SHA256SUMS)
}
package_version() {
    local target=$1 package=$2
    dpkg-query --admindir="$target/var/lib/dpkg" -W \
        -f='${db:Status-Status} ${Version}\n' "$package" 2>/dev/null || true
}
audit_rootfs() {
    local target=$1 package version bad=0
    [ -r "$target/etc/os-release" ] || fail 'rootfs has no os-release'
    grep -Eq '^ID=ubuntu$' "$target/etc/os-release" || fail 'Ubuntu rootfs required'
    grep -Eq '^VERSION_ID="24[.]04"$' "$target/etc/os-release" || fail 'Ubuntu 24.04 required'
    for package in nvidia-l4t-camera nvidia-l4t-gstreamer nvidia-l4t-multimedia; do
        version=$(package_version "$target" "$package")
        if [ "$version" != 'installed 39.2.1-20260806224157' ]; then
            printf 'MISSING/MISMATCH: %s (%s)\n' "$package" "$version" >&2
            bad=1
        fi
    done
    for package in gstreamer1.0-tools gstreamer1.0-plugins-base \
        gstreamer1.0-plugins-good \
        gstreamer1.0-plugins-bad gstreamer1.0-plugins-ugly gstreamer1.0-x \
        libx264-164 \
        libgtk-3-0t64 libx11-6 python3 python3-gi gir1.2-gtk-3.0 \
        gir1.2-gstreamer-1.0 gir1.2-gst-plugins-base-1.0; do
        version=$(package_version "$target" "$package")
        case "$version" in installed\ *) ;; *)
            printf 'MISSING: %s\n' "$package" >&2; bad=1 ;;
        esac
    done
    [ "$bad" -eq 0 ] || fail 'runtime dependencies incomplete; see DEPENDENCIES.txt'
    printf '%s\n' 'PASS: Ubuntu/NVIDIA runtime package audit (not GPU qualification).'
}
verify_bundle
case "$action" in
    check)
        if [ -n "$rootfs" ]; then
            rootfs=$(realpath -- "$rootfs")
            audit_rootfs "$rootfs"
        else
            printf '%s\n' 'PASS: bundle checks only; no runtime rootfs was audited.'
        fi
        exit 0 ;;
    build)
        [ -z "$rootfs" ] || fail 'build inside Ubuntu aarch64; --rootfs is not a cross-build option'
        [ "$(uname -m)" = aarch64 ] || fail 'native Ubuntu aarch64 build environment required'
        audit_rootfs /
        if [ -z "$source_deb" ]; then
            [ "$(package_version / nvidia-l4t-jetson-multimedia-api)" = \
                'installed 39.2.1-20260806224157' ] || fail 'matching MMAPI package or --source-deb required'
        else
            source_deb=$(realpath -- "$source_deb")
            actual=$(sha256sum "$source_deb"); actual=${actual%% *}
            [ "$actual" = fe88dbe8afe4158f5985e32fd0dddc83768091788b3bd1ffbc8d878492cee30b ] ||
                fail 'MMAPI source package hash mismatch'
            [ "$(dpkg-deb -f "$source_deb" Version)" = 39.2.1-20260806224157 ] ||
                fail 'MMAPI package version mismatch'
        fi
        for tool in cmake c++ pkg-config patch xxd readelf; do
            command -v "$tool" >/dev/null || fail "build command missing: $tool"
        done
        pkg-config --exists gtk+-3.0 gstreamer-1.0 gstreamer-video-1.0 expat ||
            fail 'Ubuntu build development libraries are incomplete'
        [ -n "$work_dir" ] || fail '--work-dir NEWDIR is required'
        [ ! -e "$work_dir" ] || fail 'build work directory must not already exist'
        mkdir -m 0700 -- "$work_dir"
        work_dir=$(realpath -- "$work_dir")
        if [ -n "$source_deb" ]; then
            dpkg-deb -x "$source_deb" "$work_dir/mmapi-package"
            source_dir="$work_dir/mmapi-package/usr/src/jetson_multimedia_api"
        fi
        source_dir=$(realpath -- "$source_dir")
        [ -f "$source_dir/argus/apps/camera/CMakeLists.txt" ] || fail 'MMAPI source missing'
        cp -a --no-preserve=ownership -- "$source_dir" "$work_dir/source"
        for patch_file in "$bundle"/patches/argus/*.patch; do
            patch --batch --forward --fuzz=0 --dry-run -p1 \
                -d "$work_dir/source" < "$patch_file"
            patch --batch --forward --fuzz=0 -p1 \
                -d "$work_dir/source" < "$patch_file"
        done
        binary_names=(argus_camera argus_oneshot)
        receipt=minimal-argus
        cuda_options=(-DEDGE_AI_MINIMAL_ARGUS=ON -DCMAKE_DISABLE_FIND_PACKAGE_CUDA=ON)
        if [ "$suite" = full ]; then
            cuda_path=$(realpath -- "$cuda_path")
            "$cuda_path/bin/nvcc" --version | grep -Fq V13.2.86 || fail 'exact CUDA nvcc 13.2.86 required'
            target="$cuda_path/targets/sbsa-linux"
            [ -f "$target/include/fatbinary_section.h" ] || fail 'native CUDA target headers missing'
            mapfile -t binary_names < "$bundle/files/argus-full-suite.txt"
            receipt=full-argus-23
            cuda_options=(-DEDGE_AI_MINIMAL_ARGUS=OFF
                -DCUDA_TOOLKIT_ROOT_DIR="$cuda_path"
                -DCUDA_TOOLKIT_ROOT_DIR_INTERNAL="$cuda_path"
                # Native FindCUDA normalizes TARGET_DIR to ROOT_DIR. Keep
                # its cache guards consistent so later sample directories
                # do not discard our explicit real nvgpu driver library.
                -DCUDA_TOOLKIT_TARGET_DIR="$cuda_path"
                -DCUDA_TOOLKIT_TARGET_DIR_INTERNAL="$cuda_path"
                -DCUDA_NVCC_EXECUTABLE="$cuda_path/bin/nvcc"
                -DCUDA_TOOLKIT_INCLUDE="$target/include"
                -DCUDA_CUDART_LIBRARY="$target/lib/libcudart.so"
                -DCUDA_CUDA_LIBRARY=/opt/nvidia/l4t-gpu-libs/nvgpu/libcuda.so.1.1
                -DCUDA_USE_STATIC_CUDA_RUNTIME=OFF
                '-DCUDA_NVCC_FLAGS=--target-directory=sbsa-linux;--gpu-architecture=sm_87')
        fi
        cmake -S "$work_dir/source/argus" -B "$work_dir/build" \
            -DCMAKE_BUILD_TYPE=Release -DCMAKE_INSTALL_PREFIX=/usr \
            "${cuda_options[@]}" \
            -DCMAKE_INCLUDE_PATH="$work_dir/source/include/libjpeg-8b-tegra" \
            -DJPEG_NAMES=libnvjpeg.so \
            '-DCMAKE_INSTALL_RPATH=/usr/lib/aarch64-linux-gnu/nvidia;/usr/local/cuda-13.2/targets/sbsa-linux/lib' \
            '-DCMAKE_EXE_LINKER_FLAGS=-L/opt/nvidia/l4t-gpu-libs/nvgpu -Wl,-rpath-link,/opt/nvidia/l4t-gpu-libs/nvgpu -Wl,-rpath-link,/usr/lib/aarch64-linux-gnu/nvidia' \
            -DCMAKE_LIBRARY_PATH=/usr/lib/aarch64-linux-gnu/nvidia
        cmake --build "$work_dir/build" --parallel "$jobs"
        DESTDIR="$work_dir/pkgroot" cmake --install "$work_dir/build"
        for binary in "${binary_names[@]}"; do
            file_path="$work_dir/pkgroot/usr/bin/$binary"
            readelf -h "$file_path" | grep -Eq 'Machine:.*AArch64' || fail 'wrong executable architecture'
            LD_LIBRARY_PATH=/opt/nvidia/l4t-gpu-libs/nvgpu:/usr/lib/aarch64-linux-gnu/nvidia:/usr/local/cuda-13.2/targets/sbsa-linux/lib \
                ldd -r "$file_path" > "$work_dir/$binary.ldd" 2>&1
            if grep -Eq 'not found|undefined symbol' "$work_dir/$binary.ldd"; then fail 'unresolved native dependencies'; fi
        done
        cp -- "$bundle/SHA256SUMS" "$work_dir/bundle.SHA256SUMS"
        printf '%s\n' "39.2.1-20260806224157 Ubuntu24.04 aarch64 $receipt" \
            > "$work_dir/BUILD-RECEIPT"
        printf '%s\n' 'PASS: native Argus build; no GPU/camera test performed.'
        exit 0 ;;
    stage)
        [ -n "$rootfs" ] && [ -n "$work_dir" ] || fail 'stage needs --rootfs and --work-dir'
        rootfs=$(realpath -- "$rootfs")
        work_dir=$(realpath -- "$work_dir")
        [ "$rootfs" != / ] || fail 'stage requires an SDK rootfs, never the running host'
        [ "$(id -u)" -eq 0 ] || fail 'stage needs root to preserve target ownership'
        audit_rootfs "$rootfs"
        lft=$(dirname -- "$rootfs")
        [ "$(git -c safe.directory="$lft" -C "$lft" rev-parse --show-toplevel 2>/dev/null)" = "$lft" ] ||
            fail 'Linux_for_Tegra needs its own Git repository and baseline first'
        git -c safe.directory="$lft" -C "$lft" rev-parse --verify HEAD >/dev/null || fail 'Git baseline commit missing'
        cmp -- "$bundle/SHA256SUMS" "$work_dir/bundle.SHA256SUMS" || fail 'build bundle changed'
        binary_names=(argus_camera argus_oneshot)
        if grep -Fxq '39.2.1-20260806224157 Ubuntu24.04 aarch64 full-argus-23' \
            "$work_dir/BUILD-RECEIPT"; then
            mapfile -t binary_names < "$bundle/files/argus-full-suite.txt"
        else
            grep -Fxq '39.2.1-20260806224157 Ubuntu24.04 aarch64 minimal-argus' \
                "$work_dir/BUILD-RECEIPT" || fail 'matching Ubuntu aarch64 build receipt missing'
        fi
        if [ -n "$gst_work_dir" ]; then
            gst_work_dir=$(realpath -- "$gst_work_dir")
            cmp -- "$bundle/SHA256SUMS" "$gst_work_dir/bundle.SHA256SUMS" || fail 'plugin bundle changed'
            grep -Fxq '39.2.1-20260806224157 Ubuntu24.04 aarch64 gst-three-plugins' \
                "$gst_work_dir/BUILD-RECEIPT" || fail 'matching native plugin receipt missing'
        fi
        backup="$work_dir/stage-backup"
        [ ! -e "$backup" ] || fail 'stage backup already exists; review previous staging first'
        mkdir -m 0700 -- "$backup"
        stage_file() {
            local input=$1 relative=$2 mode=$3 destination="$rootfs/$2"
            [ -f "$input" ] || fail "source missing: $input"
            # Do not follow a target symlink out of the selected rootfs.
            case "$(realpath -m -- "$destination")" in "$rootfs"/*) ;; *) fail 'destination escapes rootfs' ;; esac
            [ ! -L "$destination" ] || fail 'refusing to overwrite a destination symlink'
            if [ -e "$destination" ] || [ -L "$destination" ]; then
                mkdir -p -- "$backup/$(dirname -- "$relative")"
                cp -a -- "$destination" "$backup/$relative"
            fi
            install -D -o 0 -g 0 -m "$mode" -- "$input" "$destination"
            printf '%s\n' "$relative" >> "$backup/installed-paths.txt"
        }
        rendered="$work_dir/rendered"
        mkdir -- "$rendered"
        sed -e 's|@LOCALSTATEDIR@|/var|g' -e 's|@NITO_SELECTION@|auto|g' \
            "$bundle/files/edge-ai-argus-framos-demo-check.in" > "$rendered/check"
        sed -e 's|@LOCALSTATEDIR@|/var|g' -e 's|@NITO_SELECTION@|auto|g' \
            -e 's|@LIBEXECDIR@|/usr/libexec|g' \
            "$bundle/files/90-edgedes-framos-demo.conf.in" > "$rendered/service.conf"
        for binary in "${binary_names[@]}"; do
            stage_file "$work_dir/pkgroot/usr/bin/$binary" "usr/bin/$binary" 0755
        done
        if [ -n "$gst_work_dir" ]; then
            for plugin in libgstnvarguscamerasrc.so libgstnvvidconv.so libgstnvvideo4linux2.so; do
                stage_file "$gst_work_dir/plugins/$plugin" \
                    "usr/lib/aarch64-linux-gnu/gstreamer-1.0/$plugin" 0644
            done
        fi
        for script in argus_camera.sh gst_camera.sh; do
            stage_file "$bundle/files/$script" "opt/compulab/bin/$script" 0755
        done
        stage_file "$bundle/files/edge-ai-desktop-exec" usr/libexec/edge-ai-desktop-exec 0755
        stage_file "$bundle/files/edge-ai-gst-x11-preview" usr/libexec/edge-ai-gst-x11-preview 0755
        stage_file "$rendered/check" usr/libexec/edge-ai-argus-framos-demo-check 0755
        stage_file "$rendered/service.conf" \
            etc/systemd/system/nvargus-daemon.service.d/90-edgedes-framos-demo.conf 0644
        for sensor in imx676 imx678; do
            flag=$imx676; [ "$sensor" != imx678 ] || flag=$imx678
            profile="edgedes-$sensor-demo.nito"
            [ "$flag" -eq 0 ] || profile="edgedes-$sensor-extended-demo.nito"
            stage_file "$bundle/nito/$profile" "var/nvidia/nvcam/settings/edgedes-$sensor-demo.nito" 0644
        done
        for document in PROVENANCE.txt Tegra_Software_License_Agreement-Tegra-Linux.txt; do
            stage_file "$bundle/files/$document" "usr/share/edge-ai-argus-framos-demo/$document" 0644
        done
        printf '%s\n' 'PASS: runtime staged with backups; no service was started.' \
            'Regenerate target ldconfig/initramfs as appropriate, inspect Git diff,' \
            'and verify matching DT modes before boot. Hardware remains untested.'
        ;;
esac
