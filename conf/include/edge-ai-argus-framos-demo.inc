# Explicit opt-in for FRAMOS cameras; automatic NITO selection is default.
# One source-built application/plugin set serves both DT-selected sensors.
require conf/include/edge-ai-adi-gmsl-v18.inc

MACHINEOVERRIDES:append = ":edge-ai-framos-argus-demo-profile"
LICENSE_FLAGS_ACCEPTED:append = " nvidia-argus-framos-demo"
IMAGE_INSTALL:append = " ${@'edge-ai-argus-framos-demo' if d.getVar('MACHINE') in ('edge-ai-nx-16g', 'edge-ai-nx') else ''}"

# Generic uncalibrated NITO only. NVIDIA terms remain unchanged.
# Boot-profile selection is explicit and does not follow this include.
# EDGE_AI_ARGUS_NITO_SELECTION="auto" forces the matching demo file for a
# homogeneous connected subset, including a modular mixed-capable boot entry.
# Mixed active models require modular FDT_OVERLAYS and matching embedded NITO
# identities; automatic per-camera matching still requires validation.
# Explicit "single" and "per-camera" policies remain available for testing.
