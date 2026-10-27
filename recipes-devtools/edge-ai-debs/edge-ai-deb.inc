SUMMARY = "Standalone CompuLab NVIDIA Ubuntu component Debian package"
LICENSE = "MIT AND LicenseRef-Proprietary"
LIC_FILES_CHKSUM = " \
    file://${COMMON_LICENSE_DIR}/MIT;md5=0835ade698e0bcf8506ecda2f7b4f302 \
    file://${UNPACKDIR}/runtime/files/Tegra_Software_License_Agreement-Tegra-Linux.txt;md5=376d20bd5275442226fcdf54e4844ddf \
"
LICENSE_FLAGS += "nvidia-argus-framos-demo"
FILESEXTRAPATHS:prepend := "${THISDIR}/files:${THISDIR}/../edge-ai-sdk-manager/files:${THISDIR}/../edge-ai-sdk-manager/files/sdk-source/compulab/tools:${THISDIR}/../../recipes-bsp/uefi/edge-ai-uefi-update-capsules:${THISDIR}/../../recipes-multimedia/argus/files:"
SRC_URI = " \
    file://build-component-deb.py file://build-data-payloads.py \
    file://build-gstreamer-deb.py file://build-boot-payloads.py \
    file://build-argus-deb.py file://runtime file://runtime-assets.json \
    file://provision-runtime.py file://assemble-sdk.py file://package-rootfs.py \
    file://deb_packages.py file://rootfs_package_inventory.py \
    file://install-kernel.py file://check-module-abi.py \
    file://package-bsp-policy.py file://sdk-source \
    file://edge-ai-uefi-update file://apply-uefi-capsule \
"
inherit edge-ai-ubuntu-deb

python __anonymous() {
    import json
    import os
    with open(os.path.join(d.getVar('THISDIR'), '../edge-ai-sdk-manager/files/runtime-assets.json'),
              encoding='utf-8') as stream:
        manifest = json.load(stream)
    component = d.getVar('EDGE_AI_DEB_COMPONENT')
    wanted = set()
    if component == 'gstreamer':
        wanted = {'mmapi', 'publicsources'}
    elif component == 'camera-support':
        wanted = {'nito676ext' if (d.getVar('EDGE_AI_IMX676_EXTENDED_MODES') or '1') == '1' else 'nito676',
                  'nito678ext' if (d.getVar('EDGE_AI_IMX678_EXTENDED_MODES') or '0') == '1' else 'nito678'}
    uris = {}
    for asset in manifest['assets']:
        if asset['id'] not in wanted:
            continue
        if asset['source'] == 'local':
            uri = 'file://' + asset['path']
        else:
            uri = manifest['bases'][asset['source']] + asset['path']
            uri += ';downloadfilename=' + asset.get('file', os.path.basename(asset['path']))
        name = 'component_' + asset['id']
        uri += ';name=' + name + ';unpack=0'
        d.setVarFlag('SRC_URI', name + '.sha256sum', asset['sha256'])
        uris[asset['id']] = uri
        d.appendVar('SRC_URI', ' ' + uri)
    d.setVar('EDGE_AI_DEB_ASSET_URIS', json.dumps(uris, sort_keys=True))
}
