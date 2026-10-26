# Maintained code is local; proprietary NVIDIA inputs remain fetched and pinned.
FILESEXTRAPATHS:prepend := "${THISDIR}/files:${THISDIR}/../../recipes-multimedia/argus/files:"
SRC_URI += "file://runtime file://provision-runtime.py file://runtime-assets.json file://test_provision_runtime.py"
LICENSE_FLAGS += "nvidia-argus-framos-demo"
LIC_FILES_CHKSUM += "file://${UNPACKDIR}/runtime/files/Tegra_Software_License_Agreement-Tegra-Linux.txt;md5=376d20bd5275442226fcdf54e4844ddf"

python __anonymous() {
    import json
    import os
    filename = os.path.join(d.getVar('THISDIR'), 'files', 'runtime-assets.json')
    manifest = json.load(open(filename, encoding='utf-8'))
    uris = []
    for asset in manifest['assets']:
        name = asset['id']
        leaf = asset.get('file', os.path.basename(asset['path']))
        if asset['source'] == 'local':
            uri = 'file://' + asset['path']
        else:
            uri = manifest['bases'][asset['source']] + asset['path']
            uri += ';downloadfilename=' + leaf
            d.setVarFlag('SRC_URI', name + '.sha256sum', asset['sha256'])
        uri += ';name=' + name + ';unpack=0'
        uris.append(uri)
    d.setVar('EDGE_AI_SDK_RUNTIME_ASSET_URIS', ' '.join(uris))
    d.appendVar('SRC_URI', ' ' + ' '.join(uris))
}

def edge_ai_sdk_runtime_prepare_assets(d, destination):
    """Copy fetcher-resolved immutable inputs; never read a prepared host SDK."""
    import bb.fetch2
    import json
    import os
    import shutil
    manifest = json.load(open(os.path.join(d.getVar('THISDIR'), 'files',
                                          'runtime-assets.json'), encoding='utf-8'))
    uris = d.getVar('EDGE_AI_SDK_RUNTIME_ASSET_URIS').split()
    fetcher = bb.fetch2.Fetch(uris, d)
    os.makedirs(destination, exist_ok=True)
    for asset, uri in zip(manifest['assets'], uris):
        leaf = asset.get('file', os.path.basename(asset['path']))
        shutil.copy2(fetcher.localpath(uri), os.path.join(destination, leaf))
