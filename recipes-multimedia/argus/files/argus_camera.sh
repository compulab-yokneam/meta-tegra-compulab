#!/bin/sh
set -eu

run_camera() {
    export PATH=/usr/sbin:/usr/bin:/sbin:/bin
    export GDK_BACKEND=x11
    export DISPLAY=${DISPLAY:-:0}
    export XDG_RUNTIME_DIR=${XDG_RUNTIME_DIR:-/run/user/$(id -u)}

    exec argus_camera \
        --device=0 \
        --sensormode=0 \
        --framerate=10 \
        --kpi=1
}

if [ "$(id -un)" = "weston" ]; then
    run_camera
fi

if [ "$(id -u)" -eq 0 ]; then
    exec su -s /bin/sh weston -c '
        export PATH=/usr/sbin:/usr/bin:/sbin:/bin
        export GDK_BACKEND=x11
        export DISPLAY=:0
        export XDG_RUNTIME_DIR=/run/user/$(id -u)

        exec argus_camera \
            --device=0 \
            --sensormode=0 \
            --framerate=10 \
            --kpi=1
    '
fi

printf '%s\n' "ERROR: run this script as root or weston" >&2
exit 1
