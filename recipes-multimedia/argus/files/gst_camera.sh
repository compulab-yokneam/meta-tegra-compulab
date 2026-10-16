#!/bin/sh
# SPDX-License-Identifier: MIT
set -eu
export PATH=/usr/sbin:/usr/bin:/sbin:/bin:$PATH
export LC_ALL=C

usage() {
    printf '%s\n' \
        "Usage: $0 {live|record|capture} [options]" \
        "       $0 --list-modes [--sensor-id INDEX]" \
        '' \
        '  --sensor-id INDEX  Compact Argus index, not physical port (default 0).' \
        '  --sensor MODEL     auto, imx676 or imx678 (default auto).' \
        '  --sensor-mode N    Advertised native sensor mode (default 0).' \
        '  --fullscreen       Start live preview fullscreen (default windowed).' \
        '  --output PATH      New MP4 file for record; new directory for capture.' \
        '  --duration SECONDS Stop recording automatically (otherwise Ctrl+C).' \
        '  --frames COUNT     Capture frames before stopping (default 10 seconds).' \
        '  --keep-all         Keep every JPEG, rather than only the final one.' \
        '  --dry-run          Print the pipeline without capturing or writing.' \
        '  -h, --help         Show this help.' \
        '' \
        'IMX676 modes: 0=3552x3556/10, 1=3552x3556/15,' \
        '              2=3552x2160/25 crop; all RAW12.' \
        'IMX678 modes: 0=3856x2180/10, 1=3856x2180/30,' \
        '              2=2608x1964/30 crop, 3=1920x1080/30 crop; all RAW12.' \
        'Actual runs require the selected mode in argus_oneshot --listdevices.' \
        'Auto identifies the sensor preset from native mode 0, not the crop.' \
        'It identifies the configured mode, not the physical sensor silicon.' \
        'An explicit --sensor also permits offline --dry-run without Argus.' \
        'Live uses Weston/Wayland; record and capture work without a display.' \
        'Capture defaults to ten seconds of frames at the selected native FPS.' \
        'These are native acquisition modes, not resized output formats.' \
        'Close any other application using the selected camera first.' \
        'Recording requires a working NVIDIA hardware H.264 encoder.' \
        'Stop recording with Ctrl+C once, then wait for MP4 finalization.'
}

fail() {
    printf 'ERROR: %s\n' "$*" >&2
    exit 2
}

number() {
    case "$2" in ''|*[!0-9]*) fail "$1 must be a decimal integer" ;; esac
    value=$(printf '%s' "$2" | sed 's/^0*//')
    value=${value:-0}
    [ "${#value}" -le 9 ] || fail "$1 is outside the supported range"
    [ "$value" -ge "$3" ] && [ "$value" -le "$4" ] ||
        fail "$1 must be between $3 and $4"
    printf '%s\n' "$value"
}

need_command() {
    command -v "$1" >/dev/null 2>&1 || fail "required command is missing: $1"
}

need_plugin() {
    gst-inspect-1.0 "$1" >/dev/null 2>&1 ||
        fail "required GStreamer element is missing or unusable: $1"
}

print_command() {
    printf 'Pipeline:'
    for argument do
        printf " '"
        printf '%s' "$argument" | sed "s/'/'\\\\''/g"
        printf "'"
    done
    printf '\n'
}

[ "$#" -gt 0 ] || { usage >&2; exit 2; }
case "$1" in
    -h|--help) usage; exit 0 ;;
    --list-modes) operation=list; shift ;;
    live|record|capture) operation=$1; shift ;;
    *) fail 'first argument must be live, record or capture' ;;
esac

sensor_id=0
sensor=auto
sensor_mode=0
output=
frames=100
duration=
keep_all=0
dry_run=0
fullscreen=0
seen_options=
while [ "$#" -gt 0 ]; do
    case "$1" in
        -h|--help) usage; exit 0 ;;
        --dry-run) dry_run=1; shift; continue ;;
        --keep-all) keep_all=1; shift; continue ;;
        --fullscreen) fullscreen=1; shift; continue ;;
        --sensor-id|--sensor|--sensor-mode|--output|--frames|--duration)
            [ "$#" -ge 2 ] || fail "$1 requires a value"
            option=$1
            argument=$2
            shift 2
            ;;
        --sensor-id=*|--sensor=*|--sensor-mode=*|--output=*|--frames=*|--duration=*)
            option=${1%%=*}
            argument=${1#*=}
            shift
            ;;
        *) fail "unknown argument: $1" ;;
    esac
    [ -n "$argument" ] || fail "$option requires a nonempty value"
    case "$argument" in --*) fail "$option requires a value before $argument" ;; esac
    case " $seen_options " in
        *" $option "*) fail "$option was specified more than once" ;;
    esac
    seen_options="$seen_options $option"
    case "$option" in
        --sensor-id) sensor_id=$(number "$option" "$argument" 0 255) ;;
        --sensor-mode) sensor_mode=$(number "$option" "$argument" 0 255) ;;
        --sensor)
            case "$argument" in
                auto|imx676|imx678) sensor=$argument ;;
                *) fail '--sensor must be auto, imx676 or imx678' ;;
            esac
            ;;
        --output) output=$argument ;;
        --frames) frames=$(number "$option" "$argument" 1 1000000) ;;
        --duration) duration=$(number "$option" "$argument" 1 86400) ;;
    esac
done

[ "$fullscreen" -eq 0 ] || [ "$operation" = live ] ||
    fail '--fullscreen is only valid for live mode'

case "$operation" in
    list)
        [ "$dry_run" -eq 0 ] && [ "$keep_all" -eq 0 ] ||
            fail '--list-modes only accepts --sensor-id'
        for option in $seen_options; do
            [ "$option" = --sensor-id ] ||
                fail '--list-modes only accepts --sensor-id'
        done
        ;;
    live)
        [ -z "$output" ] || fail '--output is not applicable to live mode'
        [ -z "$duration" ] || fail '--duration is only valid for record mode'
        [ "$keep_all" -eq 0 ] || fail '--keep-all is only valid for capture mode'
        case " $seen_options " in
            *" --frames "*) fail '--frames is only valid for capture mode' ;;
        esac
        ;;
    record)
        [ "$keep_all" -eq 0 ] || fail '--keep-all is only valid for capture mode'
        case " $seen_options " in
            *" --frames "*) fail '--frames is only valid for capture mode' ;;
        esac
        ;;
    capture)
        [ -z "$duration" ] || fail '--duration is only valid for record mode'
        ;;
esac

camera_enumerated=0
if [ "$sensor" = auto ] || [ "$dry_run" -eq 0 ]; then
    need_command argus_oneshot
    if ! camera_info=$(argus_oneshot --listdevices); then
        fail 'cannot enumerate Argus cameras; check nvargus-daemon (offline --dry-run requires an explicit --sensor)'
    fi
    camera_enumerated=1
fi

if [ "$operation" = list ]; then
    printf 'Advertised native sensor modes for Argus index %s:\n' "$sensor_id"
    if ! printf '%s\n' "$camera_info" | awk -v wanted="$sensor_id" '
        /^[[:space:]]*==== CameraDevice [0-9]+:/ {
            device=$3
            sub(/:$/, "", device)
            selected=(device == wanted)
            if (selected) devices++
        }
        selected { print }
        selected && /^[[:space:]]*SensorMode [0-9]+:/ { modes++ }
        END { if (devices != 1 || modes < 1) exit 1 }
    '; then
        fail "cannot uniquely enumerate Argus index $sensor_id"
    fi
    printf '%s\n' 'Listing describes the configured driver/DT modes, not physical chip identification or IQ qualification.'
    exit 0
fi

# Extract one mode without starting a capture or depending on a display.
describe_mode() {
    printf '%s\n' "$camera_info" | awk -v wanted="$sensor_id" -v selected="$1" '
        BEGIN { device=-1; mode=-1 }
        /^[[:space:]]*==== CameraDevice [0-9]+:/ {
            device=$3
            sub(/:$/, "", device)
            mode=-1
            if (device == wanted) devices++
        }
        /^[[:space:]]*SensorMode [0-9]+:/ {
            mode=$2
            sub(/:$/, "", mode)
            if (device == wanted && mode == selected) modes++
        }
        device == wanted && mode == selected {
            if ($1 == "Resolution:") { resolution=$2; resolutions++ }
            if ($1 == "InputBitDepth:") { input=$2; inputs++ }
            if ($1 == "OutputBitDepth:") { output=$2; outputs++ }
            if ($1 == "SensorModeType:") { bayer=$2; types++ }
            if ($1 == "FrameDurationRange:") {
                duration_fields++
                range=$0
                sub(/^[[:space:]]*FrameDurationRange:[[:space:]]*/, "", range)
                # Put ] first in the class: escaped brackets inside a
                # class are not portable to the target BusyBox awk.
                gsub(/[][]|,/, " ", range)
                count=split(range, values, " ")
                if (count == 2 && values[1] ~ /^[0-9]+$/ &&
                    values[2] ~ /^[0-9]+$/ && values[1] > 0 &&
                    values[2] >= values[1]) {
                    duration_min=values[1]
                    duration_max=values[2]
                    durations++
                }
            }
        }
        END {
            if (devices != 1 || modes != 1 || resolutions != 1 ||
                inputs != 1 || outputs != 1 || types != 1 ||
                input !~ /^[0-9]+$/ || output !~ /^[0-9]+$/ ||
                resolution !~ /^[0-9]+x[0-9]+$/ ||
                duration_fields != 1 || durations != 1) exit 1
            split(resolution, size, "x")
            if (size[1] <= 0 || size[2] <= 0) exit 1
            printf "%s %s %s %s %s %.0f %.0f\n", size[1], size[2],
                input, output, bayer, duration_min, duration_max
        }
    '
}

validate_mode() {
    checked_mode=$1
    expected_width=$2
    expected_height=$3
    expected_fps=$4
    if ! mode_values=$(describe_mode "$checked_mode"); then
        fail "Argus index $sensor_id does not advertise a unique valid mode $checked_mode; rebuild the matching sensor driver and DT profile"
    fi
    # All fields are normalized numeric values or one enum name from awk.
    set -- $mode_values
    [ "$#" -eq 7 ] || fail 'invalid sensor-mode metadata'
    [ "$1" = "$expected_width" ] && [ "$2" = "$expected_height" ] &&
        [ "$3" = 12 ] && [ "$4" = 12 ] &&
        [ "$5" = SENSOR_MODE_TYPE_BAYER ] ||
        fail "Argus index $sensor_id mode $checked_mode is not the expected ${expected_width}x${expected_height} RAW12 Bayer mode"
    expected_duration=$((1000000000 / expected_fps))
    # Integer nanosecond metadata may round a fixed frame period slightly.
    # Reject broad/variable ranges as well as a different native frame rate.
    [ "$6" -ge "$((expected_duration - 10))" ] &&
        [ "$7" -le "$((expected_duration + 10))" ] ||
        fail "Argus index $sensor_id mode $checked_mode is not fixed $expected_fps FPS"
}

if [ "$camera_enumerated" -eq 1 ]; then
    if ! base_mode=$(describe_mode 0); then
        fail "Argus index $sensor_id has no unique native mode 0"
    fi
    case "$base_mode" in
        '3552 3556 '*) detected_sensor=imx676; base_width=3552; base_height=3556 ;;
        '3856 2180 '*) detected_sensor=imx678; base_width=3856; base_height=2180 ;;
        *) fail "Argus index $sensor_id has no supported native mode-0 geometry" ;;
    esac
    [ "$sensor" = auto ] || [ "$sensor" = "$detected_sensor" ] ||
        fail "explicit --sensor $sensor conflicts with Argus index $sensor_id native mode 0 ($detected_sensor)"
    sensor=$detected_sensor
    validate_mode 0 "$base_width" "$base_height" 10
fi

video_height=1080
case "$sensor:$sensor_mode" in
    imx676:0) width=3552; height=3556; fps=10; live_width=720; live_height=720; video_width=1080 ;;
    imx676:1) width=3552; height=3556; fps=15; live_width=720; live_height=720; video_width=1080 ;;
    imx676:2) width=3552; height=2160; fps=25; live_width=1184; live_height=720; video_width=1776 ;;
    imx678:0) width=3856; height=2180; fps=10; live_width=1280; live_height=724; video_width=1920 ;;
    imx678:1) width=3856; height=2180; fps=30; live_width=1280; live_height=724; video_width=1920 ;;
    imx678:2) width=2608; height=1964; fps=30; live_width=1304; live_height=982; video_width=1434 ;;
    imx678:3) width=1920; height=1080; fps=30; live_width=1280; live_height=720; video_width=1920 ;;
    *) fail "unsupported $sensor sensor mode $sensor_mode" ;;
esac
if [ "$camera_enumerated" -eq 1 ]; then
    validate_mode "$sensor_mode" "$width" "$height" "$fps"
fi
case " $seen_options " in
    *" --frames "*) ;;
    *) frames=$((fps * 10)) ;;
esac
caps="video/x-raw(memory:NVMM),format=NV12,width=$width,height=$height,framerate=$fps/1"
printf 'Mode: %s; Argus sensor-id: %s; preset: %s; sensor-mode: %s; native: %sx%s at %s FPS\n' \
    "$operation" "$sensor_id" "$sensor" "$sensor_mode" "$width" "$height" "$fps"

if [ "$operation" != live ]; then
    if [ -z "$output" ]; then
        stamp=$(date +%Y%m%d-%H%M%S)
        output="imx67x-$operation-sensor$sensor_id-$stamp-$$"
        [ "$operation" != record ] || output=$output.mp4
    fi
    case "$output" in /*) ;; *) output=$(pwd)/$output ;; esac
    if [ -e "$output" ] || [ -L "$output" ]; then
        fail "output already exists; choose a new file/directory: $output"
    fi
    [ -d "$(dirname "$output")" ] || fail "output parent does not exist: $output"
    printf 'Output: %s\n' "$output"
fi

# Paths never enter GStreamer parsing: record uses exclusive FD 3; capture
# changes into its new directory before using a fixed JPEG filename pattern.
set -- gst-launch-1.0 -e nvarguscamerasrc \
    "sensor-id=$sensor_id" "sensor-mode=$sensor_mode" wbmode=1 awblock=false
case "$operation" in
    live)
        set -- "$@" '!' "$caps" '!' nvvidconv '!' \
            "video/x-raw,format=BGRx,width=$live_width,height=$live_height" \
            '!' waylandsink sync=false
        [ "$fullscreen" -eq 0 ] || set -- "$@" fullscreen=true
        ;;
    record)
        # The source timeout includes startup and can produce no frames for
        # a short recording. Bound actual frames at the selected native rate.
        [ -z "$duration" ] || set -- "$@" "num-buffers=$((duration * fps))"
        printf 'Encoded output: %sx%s at %s FPS\n' "$video_width" "$video_height" "$fps"
        set -- "$@" '!' "$caps" '!' nvvidconv '!' \
            "video/x-raw(memory:NVMM),format=NV12,width=$video_width,height=$video_height,pixel-aspect-ratio=1/1" \
            '!' nvv4l2h264enc bitrate=8000000 '!' h264parse '!' \
            mp4mux '!' fdsink fd=3
        ;;
    capture)
        retained=1
        [ "$keep_all" -eq 0 ] || retained=0
        set -- "$@" "num-buffers=$frames" '!' "$caps" '!' \
            nvjpegenc quality=95 '!' multifilesink \
            location=still-%03d.jpg "max-files=$retained"
        printf 'Capturing %s frames; %s\n' "$frames" \
            'AE/AWB settling depends on the scene; this is not IQ calibration.'
        ;;
esac
print_command "$@"
[ "$dry_run" -eq 0 ] || exit 0

need_command gst-launch-1.0
need_command gst-inspect-1.0
need_plugin nvarguscamerasrc
case "$operation" in
    live)
        need_plugin nvvidconv
        need_plugin waylandsink
        if [ "$(id -u)" -eq 0 ]; then
            need_command su
            id weston >/dev/null 2>&1 ||
                fail 'no weston user; run live mode inside the desktop session'
            case "$0" in /*) script=$0 ;; *) script=$(pwd)/$0 ;; esac
            set -- "$script" live --sensor-id "$sensor_id" \
                --sensor "$sensor" --sensor-mode "$sensor_mode"
            [ "$fullscreen" -eq 0 ] || set -- "$@" --fullscreen
            exec su -s /bin/sh weston -c '
                export XDG_RUNTIME_DIR=/run/user/$(id -u)
                exec "$@"
            ' -- gst_camera "$@"
        fi
        XDG_RUNTIME_DIR=${XDG_RUNTIME_DIR:-/run/user/$(id -u)}
        export XDG_RUNTIME_DIR
        if [ -z "${WAYLAND_DISPLAY:-}" ]; then
            sockets=0
            for socket in "$XDG_RUNTIME_DIR"/wayland-*; do
                [ -S "$socket" ] || continue
                sockets=$((sockets + 1))
                WAYLAND_DISPLAY=${socket##*/}
            done
            [ "$sockets" -eq 1 ] ||
                fail 'set WAYLAND_DISPLAY to the active Weston socket'
        fi
        case "$WAYLAND_DISPLAY" in
            /*) socket=$WAYLAND_DISPLAY ;;
            *) socket=$XDG_RUNTIME_DIR/$WAYLAND_DISPLAY ;;
        esac
        [ -S "$socket" ] || fail "Wayland display socket is not available: $socket"
        export WAYLAND_DISPLAY
        ;;
    record)
        for plugin in nvvidconv nvv4l2h264enc h264parse mp4mux fdsink; do
            need_plugin "$plugin"
        done
        printf '%s\n' 'Stop with Ctrl+C once and wait for EOS. Failed/forced stops may leave a partial MP4.'
        # Noclobber atomically refuses an existing path. FD 3 stays seekable
        # for MP4 finalization, and is inherited by the foreground pipeline.
        umask 077
        set -C
        exec 3>"$output"
        set +C
        ;;
    capture)
        need_plugin nvjpegenc
        need_plugin multifilesink
        mkdir -m 0755 -- "$output" ||
            fail "cannot create a new capture directory: $output"
        cd -- "$output"
        ;;
esac

# Foreground exec gives gst-launch SIGINT directly. Its -e handler sends EOS
# and finalizes the muxer without an intermediary background shell.
exec "$@"
