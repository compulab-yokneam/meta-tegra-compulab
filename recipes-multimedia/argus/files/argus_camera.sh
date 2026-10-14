#!/bin/sh
set -eu

usage() {
    printf '%s\n' \
        "Usage: $0 [-d PORT | --ports PORTS | --all | --device INDEX | --list]" \
        '' \
        '  -d, --port PORT     Select physical EDGEDES port 0, 1, 2 or 3.' \
        '      --ports PORTS   Preview a comma-separated physical port list together.' \
        '  -a, --all           Preview all connected EDGEDES cameras together.' \
        '      --device INDEX  Select a compact Argus device index.' \
        '  -l, --list          List physical ports, Argus indexes and modes.' \
        '  -h, --help          Show this help.' \
        '' \
        'Without options, preview the first connected camera (Argus index 0).' \
        'Port selection uses the camera identity, not /dev/videoN numbering.' \
        'A camera alone on physical port 1 is selected with -d 1 or --device 0.' \
        'Examples: --ports 0,1 or --all. Multi-camera preview uses one tiled window.'
}

fail() {
    printf '%s\n' "ERROR: $*" >&2
    printf '%s\n' "Use $0 --help for usage." >&2
    exit 2
}

device=0
selection=
port=
ports=
list_devices=0
while [ "$#" -gt 0 ]; do
    case "$1" in
        -d|--port)
            [ "$#" -ge 2 ] || fail "$1 requires a port"
            [ -z "$selection" ] || fail 'select only one port or device'
            port=$2
            selection=port
            shift 2
            ;;
        --port=*)
            [ -z "$selection" ] || fail 'select only one port or device'
            port=${1#--port=}
            selection=port
            shift
            ;;
        --ports)
            [ "$#" -ge 2 ] || fail "$1 requires a comma-separated port list"
            [ -z "$selection" ] || fail 'select only one port, port list or device'
            ports=$2
            selection=ports
            shift 2
            ;;
        --ports=*)
            [ -z "$selection" ] || fail 'select only one port, port list or device'
            ports=${1#--ports=}
            selection=ports
            shift
            ;;
        -a|--all)
            [ -z "$selection" ] || fail 'select only one port, port list or device'
            selection=all
            shift
            ;;
        --device)
            [ "$#" -ge 2 ] || fail "$1 requires an index"
            [ -z "$selection" ] || fail 'select only one port or device'
            device=$2
            selection=device
            shift 2
            ;;
        --device=*)
            [ -z "$selection" ] || fail 'select only one port or device'
            device=${1#--device=}
            selection=device
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
if [ "$selection" = port ]; then
    case "$port" in
        0|1|2|3) ;;
        *) fail 'physical port must be 0, 1, 2 or 3' ;;
    esac
fi
if [ "$selection" = ports ]; then
    case "$ports" in
        ''|,*|*,|*,,*|*[!0-3,]*)
            fail 'port list must contain unique ports 0..3 separated by commas'
            ;;
    esac
    saved_ifs=$IFS
    IFS=,
    seen_ports=
    for requested in $ports; do
        case "$requested" in
            0|1|2|3) ;;
            *) fail 'physical port must be 0, 1, 2 or 3' ;;
        esac
        case ",$seen_ports," in
            *,"$requested",*) fail "duplicate physical port $requested" ;;
        esac
        seen_ports=${seen_ports:+$seen_ports,}$requested
    done
    IFS=$saved_ifs
fi
if [ "$list_devices" -eq 1 ] && [ -n "$selection" ]; then
    fail '--list cannot be combined with a port or device selection'
fi

camera() {
    if [ "$(id -un)" = "weston" ]; then
        export PATH=/usr/sbin:/usr/bin:/sbin:/bin
        export GDK_BACKEND=x11
        export DISPLAY=${DISPLAY:-:0}
        export XDG_RUNTIME_DIR=${XDG_RUNTIME_DIR:-/run/user/$(id -u)}
        exec argus_camera "$@"
    elif [ "$(id -u)" -eq 0 ]; then
        # Pass arguments separately across su; never interpolate shell code.
        exec su -s /bin/sh weston -c '
            export PATH=/usr/sbin:/usr/bin:/sbin:/bin
            export GDK_BACKEND=x11
            export DISPLAY=:0
            export XDG_RUNTIME_DIR=/run/user/$(id -u)

            exec argus_camera "$@"
        ' -- argus_camera "$@"
    else
        printf '%s\n' 'ERROR: run this script as root or weston' >&2
        return 1
    fi
}

port_map() {
    # Confirm the native identity against enabled live DT modules. Never infer
    # Argus enumeration order from moduleN, position, VC or /dev/videoN.
    badges=
    for module in /proc/device-tree/tegra-camera-platform/modules/module*; do
        [ -r "$module/badge" ] || continue
        status=okay
        if [ -r "$module/status" ]; then
            status=$(tr -d '\000' < "$module/status")
        fi
        case "$status" in okay|ok) ;; *) continue ;; esac
        badge=$(tr -d '\000' < "$module/badge")
        case "$badge" in
            imx676_port[0-3]_framos|imx678_port[0-3]_framos) ;;
            *) continue ;;
        esac
        badges="${badges}${badge}
"
    done

    printf '%s\n' "$camera_info" | awk -v badges="$badges" '
        BEGIN {
            n = split(badges, live, "\n")
            for (i = 1; i <= n; ++i)
                if (live[i] != "")
                    enabled[live[i]]++
            count = -1
            current = -1
        }
        /^Number of camera devices: [0-9]+$/ {
            if (count != -1) bad = 1
            count = $5 + 0
        }
        /^Device: [0-9]+$/ {
            current = $2 + 0
            if (seen[current]++) bad = 1
            devices++
        }
        /^[[:space:]]*Module String:/ {
            if (current < 0 || identities[current]++) bad = 1
            badge = $0
            sub(/^[[:space:]]*Module String:[[:space:]]*/, "", badge)
            if (badge !~ /^imx67[68]_port[0-3]_framos$/ || enabled[badge] != 1) {
                bad = 1
                next
            }
            physical = substr(badge, 12, 1) + 0
            if (physical_seen[physical]++) bad = 1
            argus_index[physical] = current
            identity[physical] = badge
        }
        END {
            if (count < 0 || count > 4) exit 1
            if (devices != count) bad = 1
            for (i = 0; i < count; ++i)
                if (seen[i] != 1 || identities[i] != 1) bad = 1
            if (bad) exit 1
            for (i = 0; i < 4; ++i)
                if (physical_seen[i] == 1)
                    printf "%d %d %s\n", i, argus_index[i], identity[i]
        }
    '
}

if [ "$list_devices" -eq 1 ] || [ "$selection" = port ] || \
    [ "$selection" = ports ] || [ "$selection" = all ]; then
    if ! camera_info=$(camera --info --exit); then
        fail 'could not enumerate Argus cameras'
    fi
    if mapping=$(port_map); then
        if [ "$list_devices" -eq 1 ]; then
            printf '%s\n' 'Physical port -> Argus device (camera identity):'
            if [ -n "$mapping" ]; then
                printf '%s\n' "$mapping" | while read -r physical index badge; do
                    printf '  port %s -> device %s (%s)\n' \
                        "$physical" "$index" "$badge"
                done
            else
                printf '%s\n' '  No connected EDGEDES cameras.'
            fi
        elif [ "$selection" = port ]; then
            device=$(printf '%s\n' "$mapping" | awk -v port="$port" \
                '$1 == port { print $2 }')
            if [ -z "$device" ]; then
                connected=$(printf '%s\n' "$mapping" | awk \
                    'NF { printf "%s%s", sep, $1; sep = ", " }')
                fail "no connected camera on physical port $port (connected ports: ${connected:-none})"
            fi
            printf 'Physical port %s -> Argus device %s\n' "$port" "$device"
        else
            if [ "$selection" = all ]; then
                ports=$(printf '%s\n' "$mapping" | awk \
                    'NF { printf "%s%s", sep, $1; sep = "," }')
                [ -n "$ports" ] || fail 'no connected EDGEDES cameras'
            fi
            devices=
            selections=
            saved_ifs=$IFS
            IFS=,
            for requested in $ports; do
                index=$(printf '%s\n' "$mapping" | awk -v port="$requested" \
                    '$1 == port { print $2 }')
                if [ -z "$index" ]; then
                    connected=$(printf '%s\n' "$mapping" | awk \
                        'NF { printf "%s%s", sep, $1; sep = ", " }')
                    fail "no connected camera on physical port $requested (connected ports: ${connected:-none})"
                fi
                [ -n "$devices" ] || device=$index
                devices=${devices:+$devices,}$index
                selections="${selections}  port $requested -> device $index
"
            done
            IFS=$saved_ifs
            printf 'Simultaneous camera preview:\n%s' "$selections"
        fi
    elif [ "$list_devices" -eq 1 ]; then
        printf '%s\n' 'WARNING: physical-port identities unavailable; use the Argus indexes below.' >&2
    else
        fail 'cannot verify physical ports; install the matching argus-samples package or use --device INDEX'
    fi
    if [ "$list_devices" -eq 1 ]; then
        printf '\n%s\n' "$camera_info"
        exit 0
    fi
fi

if [ "$selection" = ports ] || [ "$selection" = all ]; then
    # Set the list before changing modules. The sample sorts native indexes
    # for its tiled view; camera sessions run concurrently, not synchronized.
    camera "--device=$device" --sensormode=0 --framerate=10 --kpi=1 \
        "--multidevices=$devices" '--module=Multi Session'
fi

camera "--device=$device" --sensormode=0 --framerate=10 --kpi=1
