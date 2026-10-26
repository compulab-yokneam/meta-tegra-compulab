SUMMARY = "Prepare the complete CompuLab NVIDIA Ubuntu JetPack SDK"
DESCRIPTION = "Opt-in privileged host workflow; never an image package"
LICENSE = "MIT AND LicenseRef-Proprietary"
LIC_FILES_CHKSUM = "file://${COMMON_LICENSE_DIR}/MIT;md5=0835ade698e0bcf8506ecda2f7b4f302"

inherit nopackages

SRC_URI = " \
    file://build-sdk.py \
    file://assemble-sdk.py \
    file://package-rootfs.py \
    file://sdk-source \
    file://tegra234-edge-ai-gpio-default.dtsi \
    file://tegra234-edge-ai-pinmux.dtsi \
    file://tegra234-edge-ai-padvoltage-default.dtsi \
    file://tegra234-edge-ai-mb2-bct-misc-p3767-0000.dts \
    file://edge-ai-uefi-update \
    file://apply-uefi-capsule \
"
FILESEXTRAPATHS:prepend := "${THISDIR}/../../recipes-bsp/tegra-binaries/tegra-flashvars:${THISDIR}/../../recipes-bsp/uefi/edge-ai-uefi-update-capsules:"
require edge-ai-sdk-manager-runtime.inc

S = "${UNPACKDIR}"
COMPATIBLE_MACHINE = "^(edge-ai-nx-16g|edge-ai-nx)$"
PACKAGE_ARCH = "${MACHINE_ARCH}"

EDGE_AI_SDK_ENABLE ?= "0"
EDGE_AI_SDK_ACCEPT_LICENSE ?= "0"
EDGE_AI_SDK_MANAGER ?= "/usr/bin/sdkmanager"
EDGE_AI_SDK_DOWNLOAD_DIR ?= "${DL_DIR}/sdkmanager"
EDGE_AI_SDK_OUTPUT ?= "${DEPLOY_DIR_IMAGE}/jetpack-${PV}-image-build"
# Outside WORKDIR/sstate: SDK Manager and chroot create root-owned files.
EDGE_AI_SDK_HOST_WORK ?= "${TOPDIR}/sdk-manager-work/${MACHINE}"
EDGE_AI_SDK_TIMEOUT ?= "21600"
# Bump for a changed, independently upgradeable Ubuntu add-on package set.
EDGE_AI_SDK_DEB_VERSION ?= "39.2.1+compulab1"

def edge_ai_sdk_firmware_inputs(d):
    result = []
    for machine in ("edge-ai-nx-16g", "edge-ai-nx-8g",
                    "edge-ai-nano-8g", "edge-ai-nano-4g"):
        for style in ("nvidia-logo", "clab-logo", "no-logo"):
            prefix = "edge-ai-uefi" if machine == "edge-ai-nx-16g" else \
                "edge-ai-uefi-" + machine.removeprefix("edge-ai-")
            mc = prefix + "-" + style
            directory = "%s/tmp-mc-%s/deploy/images/%s" % (
                d.getVar("TOPDIR"), mc, machine)
            result.append(dict(machine=machine, style=style, mc=mc,
                               deploy=directory))
    return result

# Override when firmware multiconfigs use custom TMPDIRs.
EDGE_AI_SDK_FIRMWARE_INPUTS ?= "${@__import__('json').dumps(edge_ai_sdk_firmware_inputs(d))}"

def edge_ai_sdk_mcdeps(d):
    import json
    return " ".join("mc:%s:%s:%s:do_deploy" % (
        d.getVar("BB_CURRENT_MC") or "", item["mc"], recipe)
        for item in json.loads(d.getVar("EDGE_AI_SDK_FIRMWARE_INPUTS"))
        for recipe in ("edk2-firmware-tegra", "edk2-firmware-tegra-rcmboot",
                       "tos-optee", "edk2-nvidia-standalone-mm"))

do_configure[noexec] = "1"
do_compile[noexec] = "1"
do_install[noexec] = "1"

python do_create_sdk() {
    import json
    import os
    import subprocess
    from pathlib import Path

    for name in ("EDGE_AI_SDK_ENABLE", "EDGE_AI_SDK_ACCEPT_LICENSE",
                 "EDGE_AI_SDK_EXPORTS"):
        if d.getVar(name) != "1":
            bb.fatal("Set %s = \"1\" explicitly; read the SDK recipe README first" % name)
    if d.getVar("PREFERRED_PROVIDER_virtual/kernel") != "linux-noble-nvidia-tegra":
        bb.fatal("SDK generation requires linux-noble-nvidia-tegra")
    private = Path(d.getVar("EDGE_AI_SDK_HOST_WORK"))
    private.mkdir(parents=True, exist_ok=True, mode=0o700)
    if private.is_symlink() or private.stat().st_uid != os.getuid():
        bb.fatal("SDK host work directory must be owned by this user, not a symlink")
    marker = private / ".edge-ai-sdk-work"
    if not marker.exists():
        if any(private.iterdir()):
            bb.fatal("Refusing an existing non-SDK work directory; choose a new EDGE_AI_SDK_HOST_WORK")
        marker.write_text("CompuLab SDK Manager private work directory, version 1\n")
    if marker.is_symlink() or not marker.is_file():
        bb.fatal("Invalid SDK private-work ownership marker")
    private.chmod(0o700)
    assets = private / "assets"
    if assets.is_symlink():
        bb.fatal("SDK asset directory must not be a symlink")
    edge_ai_sdk_runtime_prepare_assets(d, str(assets))
    configuration = {
        "format_version": 1,
        "uid": os.getuid(),
        "gid": os.getgid(),
        "sdkmanager": d.getVar("EDGE_AI_SDK_MANAGER"),
        "download": d.getVar("EDGE_AI_SDK_DOWNLOAD_DIR"),
        "output": d.getVar("EDGE_AI_SDK_OUTPUT"),
        "work": str(private),
        "assets": str(assets),
        "sources": d.getVar("UNPACKDIR"),
        "deploy": d.getVar("DEPLOY_DIR_IMAGE"),
        "firmware": json.loads(d.getVar("EDGE_AI_SDK_FIRMWARE_INPUTS")),
        "timeout": int(d.getVar("EDGE_AI_SDK_TIMEOUT")),
        "machine": d.getVar("MACHINE"),
        "deb_version": d.getVar("EDGE_AI_SDK_DEB_VERSION"),
        "imx676_extended": d.getVar("EDGE_AI_IMX676_EXTENDED_MODES") or "1",
        "imx678_extended": d.getVar("EDGE_AI_IMX678_EXTENDED_MODES") or "0",
    }
    path = private / "configuration.json"
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "w") as stream:
        json.dump(configuration, stream, indent=2)
    # SDK Manager runs as the authenticated ordinary user, never root.
    original = d.getVar("BB_ORIGENV", False)
    environment = dict(os.environ)
    environment["PATH"] = original.getVar("PATH") or "/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
    for name in ("LD_LIBRARY_PATH", "PYTHONPATH", "PSEUDO_PREFIX", "PSEUDO_LOCALSTATEDIR"):
        environment.pop(name, None)
    subprocess.run(["/usr/bin/python3", "-B", str(Path(d.getVar("UNPACKDIR")) / "build-sdk.py"),
                    "--config", str(path)], env=environment, check=True)
}

# No sstate/clean operation may own the privileged SDK tree or credentials.
do_create_sdk[nostamp] = "1"
do_create_sdk[network] = "1"
# BB_ORIGENV is a DataSmart instance, not a serializable build input. Its
# process-specific repr would otherwise change the basehash in every worker.
# In particular, authentication/host environment state must not enter hashes.
do_create_sdk[vardepsexclude] += "BB_ORIGENV"
do_create_sdk[depends] = " \
    virtual/kernel:do_deploy \
    nvidia-kernel-oot:do_deploy \
    kernel-devsrc:do_deploy \
    virtual/dtb:do_deploy \
    virtual/dtbo:do_deploy \
    edgedes-adi-v18-devicetree:do_deploy \
    edge-ai-uefi-update-capsules:do_deploy \
"
do_create_sdk[mcdepends] = "${@edge_ai_sdk_mcdeps(d)}"
addtask create_sdk after do_unpack before do_build
