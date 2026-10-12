# Explicit opt-in for one to four IMX676 cameras or one IMX678 camera.
# One source-built application/plugin set serves both DT-selected sensors.
require conf/include/edge-ai-adi-gmsl-v18.inc

MACHINEOVERRIDES:append = ":edge-ai-framos-argus-demo-profile"
LICENSE_FLAGS_ACCEPTED:append = " nvidia-argus-framos-demo"
IMAGE_INSTALL:append = " ${@'edge-ai-argus-framos-demo' if d.getVar('MACHINE') in ('edge-ai-nx-16g', 'edge-ai-nx') else ''}"

# Generic uncalibrated NITO only. NVIDIA terms remain unchanged.
# Boot-profile selection is explicit and does not follow this include.
