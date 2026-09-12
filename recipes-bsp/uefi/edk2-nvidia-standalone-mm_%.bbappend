# Keep Standalone MM warnings and errors on the debug UART, but suppress the
# DEBUG_INIT, DEBUG_LOAD and DEBUG_FS messages enabled by NVIDIA's platform
# DSC.  In particular, DEBUG_LOAD produces the protocol-installation and
# PE/COFF mapping flood during every boot.
TEGRA_UEFI_STMM_DEBUG_PRINT_ERROR_LEVEL ?= "0x80000002"

EDK2_EXTRA_BUILD:append = " --pcd gEfiMdePkgTokenSpaceGuid.PcdDebugPrintErrorLevel=${TEGRA_UEFI_STMM_DEBUG_PRINT_ERROR_LEVEL}"
