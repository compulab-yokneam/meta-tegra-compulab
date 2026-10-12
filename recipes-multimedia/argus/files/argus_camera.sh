#!/bin/sh
set -eu

usage() {
    printf '%s\n' \
        "Usage: $0 [--device INDEX | --list]" \
        '' \
        '  -d, --device INDEX  Select a connected Argus camera (default: 0).' \
        '  -l, --list          List connected Argus devices and sensor modes.' \
        '  -h, --help          Show this help.' \
        '' \
        'INDEX is an Argus device index, not a physical EDGEDES port number.' \
        'A single connected camera on any port uses index 0.'
}

fail() {
    printf '%s\n' "ERROR: $*" >&2
    printf '%s\n' "Use $0 --help for usage." >&2
    exit 2
}

device=0
device_selected=0
list_devices=0
while [ "$#" -gt 0 ]; do
    case "$1" in
        -d|--device)
            [ "$#" -ge 2 ] || fail "$1 requires an index"
            device=$2
            device_selected=1
            shift 2
            ;;
        --device=*)
            device=${1#--device=}
            device_selected=1
            shift
            ;;
        -l|--list)
            list_devices=1
            shift
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *) fail "unknown option '$1'" ;;
    esac
done

case "$device" in
    ''|*[!0-9]*) fail 'device index must be a non-negative decimal integer' ;;
esac
if [ "$list_devices" -eq 1 ] && [ "$device_selected" -eq 1 ]; then
    fail '--list cannot be combined with --device'
fi

# Pass arguments separately, including across su; never interpolate shell code.
if [ "$list_devices" -eq 1 ]; then
    set -- --info --exit
else
    set -- "--device=$device" --sensormode=0 --framerate=10 --kpi=1
fi

run_camera() {
    export PATH=/usr/sbin:/usr/bin:/sbin:/bin
    export GDK_BACKEND=x11
    export DISPLAY=${DISPLAY:-:0}
    export XDG_RUNTIME_DIR=${XDG_RUNTIME_DIR:-/run/user/$(id -u)}

    exec argus_camera "$@"
}

if [ "$(id -un)" = "weston" ]; then
    run_camera "$@"
fi

if [ "$(id -u)" -eq 0 ]; then
    exec su -s /bin/sh weston -c '
        export PATH=/usr/sbin:/usr/bin:/sbin:/bin
        export GDK_BACKEND=x11
        export DISPLAY=:0
        export XDG_RUNTIME_DIR=/run/user/$(id -u)

        exec argus_camera "$@"
    ' -- argus_camera "$@"
fi

printf '%s\n' "ERROR: run this script as root or weston" >&2
exit 1
