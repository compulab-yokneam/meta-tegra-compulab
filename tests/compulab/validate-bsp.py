#!/usr/bin/env python3
"""Compile and inspect carrier DTBs from the pinned JP7.2 public sources.

Optional --bsp-dir checks capsule board aliases and BCT compilation using an
unpacked L4T tree. Optional --git-cache and --metadata check all native UEFI
patches against the recipe's pinned Git revisions, without fetching anything.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile

root = Path(__file__).resolve().parents[2]
layer = root/'layers/meta-tegra-compulab'
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('public_sources', type=Path)
parser.add_argument('output', type=Path)
parser.add_argument('--bsp-dir', type=Path)
parser.add_argument('--git-cache', type=Path)
parser.add_argument('--metadata', type=Path)
args = parser.parse_args()
args.output = args.output.resolve()
args.output.mkdir(parents=True, exist_ok=True)
with args.public_sources.open('rb') as source:
    assert hashlib.file_digest(source, 'sha256').hexdigest() == '87d2e31ff55beaf2373e2f288538585995b231fd5745ec21f39a668e36efab2f', 'Expected pinned L4T 39.2.0 sources'
dtbs = args.output/'dtbs'
dtbs.mkdir(exist_ok=True)


def run(argv, **kwargs):
    return subprocess.run(argv, check=True, capture_output=True, **kwargs)


def prop(path, node, key, kind='s'):
    return run(['fdtget', '-t', kind, str(path), node, key]).stdout.decode().strip()


with tempfile.TemporaryDirectory(prefix='bsp-', dir=args.output) as scratch:
    scratch = Path(scratch)
    nested = scratch/'kernel_oot_modules_src.tbz2'
    with nested.open('wb') as output:
        subprocess.run(['tar', '-xjf', str(args.public_sources.resolve()), '-O', 'Linux_for_Tegra/source/kernel_oot_modules_src.tbz2'], stdout=output, check=True)
    run(['tar', '-xjf', str(nested), '-C', str(scratch), 'hardware'])
    for patch in sorted((layer/'recipes-kernel/nvidia-kernel-oot/nvidia-kernel-oot').glob('*.patch')):
        result = run(['patch', '-d', str(scratch), '-p1', '--batch', '--fuzz=0'], input=patch.read_bytes())
        assert b'offset' not in result.stdout and b'fuzz' not in result.stdout
    nv = scratch/'hardware/nvidia'
    includes = [nv/'tegra/nv-public/include/kernel', nv/'tegra/nv-public/include/nvidia-oot', nv/'tegra/nv-public', nv/'t23x/nv-public/include/nvidia-oot', nv/'t23x/nv-public/include/platforms', nv/'t23x/nv-public', nv/'t23x/nv-public/nv-platform']
    for sku in ('0000', '0001', '0003', '0004', '0005'):
        for mode in ('', '-super'):
            name = f'tegra234-p3768-0000+p3767-{sku}-nv{mode}'
            pp = run(['cpp', '-nostdinc', '-undef', '-D__DTS__', '-x', 'assembler-with-cpp', '-DLINUX_VERSION=600', '-DTEGRA_HOST1X_DT_VERSION=2', '-DOS_LINUX', *[f'-I{x}' for x in includes], str(includes[-1]/(name+'.dts'))]).stdout
            (dtbs/(name+'.pp')).write_bytes(pp)
            path = dtbs/(name+'.dtb')
            result = run(['dtc', '-I', 'dts', '-O', 'dtb', '-@', '-E', 'no-duplicate_label', '-o', str(path), str(dtbs/(name+'.pp'))])
            (dtbs/(name+'.log')).write_bytes(result.stderr)
            if sku != '0005':
                expected_model = 'NVIDIA Jetson Orin '+('NX' if sku in ('0000', '0001') else 'Nano')+' EdgeAI-ORN'
                assert prop(path, '/', 'model') == expected_model
                assert prop(path, '/', 'compatible').startswith('compulab,edgeai-orn ')
                for node in ('/bus@0/pcie@140c0000', '/bus@0/pcie@140e0000', '/bus@0/serial@3110000'):
                    assert prop(path, node, 'status') == 'okay'
                assert prop(path, '/bus@0/spi@3210000/spi@0', 'compatible') == 'infineon,slb9670'
                assert prop(path, '/bus@0/spi@3210000/spi@0', 'spi-max-frequency', 'i') == '5000000'
                assert prop(path, '/bus@0/padctl@3520000/ports/usb3-1', 'nvidia,usb2-companion', 'i') == '1'
                assert prop(path, '/bus@0/padctl@3520000/ports/usb3-2', 'nvidia,usb2-companion', 'i') == '2'
                assert prop(path, '/display@13800000', 'os_gpio_hotplug_a', 'i').split()[-1] == '1'
                assert subprocess.run(['fdtget', str(path), '/bus@0/i2c@c240000/fusb301@25', 'compatible'], capture_output=True).returncode != 0
            print('DTB PASS:', name, flush=True)

    if args.bsp_dir:
        original = args.bsp_dir.resolve()
        script = (layer/'recipes-bsp/tegra-binaries/uefi-capsule-container/build.sh').read_text()
        case = script.split('case "${DEVICE_TYPE}" in\n', 1)[1].split('\t"jetson-agx-orin-devkit-64gb"', 1)[0]
        for family, skus in (('nano', ('0003', '0004')), ('nx', ('0000', '0001'))):
            fixture = scratch/family
            tree = fixture/'Linux_for_Tegra'
            tree.mkdir(parents=True)
            for name in ('p3767.conf.common', 'p3768-0000-p3767-0000-a0.conf', 'p3768-0000-p3767-0000-super.conf', 'jetson-orin-nano-devkit.conf', 'jetson-orin-nano-devkit-super.conf'):
                shutil.copy2(original/name, tree/name, follow_symlinks=False)
            (tree/'bootloader/generic/BCT').mkdir(parents=True)
            (tree/'kernel/dtb').mkdir(parents=True)
            shutil.copytree(layer/'recipes-bsp/tegra-binaries/tegra-flashvars', fixture/'edgeai-orn')
            shutil.copytree(dtbs, fixture/'edgeai-orn/dtbs')
            setup = ('case "${DEVICE_TYPE}" in\n'+case+'esac\n').replace('/build_dir', str(fixture))
            run(['bash', '-e', '-c', setup], cwd=tree, env={'DEVICE_TYPE': 'edgeai-orn-'+family, 'PATH': '/usr/bin:/bin'})
            body = '''set -e
LDK_DIR=$PWD
board_sku=$1
board_FAB=300
bup_blob=1
source "$2"
update_flash_args
[[ "$PINMUX_CONFIG" == "tegra234-edgeai-orn-pinmux.dtsi" ]]
[[ "$PMC_CONFIG" == "tegra234-edgeai-orn-padvoltage-default.dtsi" ]]
[[ "$MB2_BCT" == "tegra234-edgeai-orn-mb2-bct-misc-p3767-0000.dts" ]]
[[ "$ODMDATA" == "gbe-uphy-config-9,hsstp-lane-map-3,hsio-uphy-config-0" ]]
[[ -s "kernel/dtb/$DTB_FILE" ]]
'''
            for sku in skus:
                for mode in ('', '-super'):
                    run(['bash', '-c', body, 'validation', sku, 'jetson-orin-nano-devkit'+mode+'.conf'], cwd=tree)
                if family == 'nx':
                    run(['bash', '-c', body + '[[ "$ext_target_board" == "edge-ai" ]]\n',
                         'validation', sku, 'edge-ai.conf'], cwd=tree)
            if family == 'nx':
                board_spec = (layer/'recipes-bsp/tegra-binaries/uefi-capsule-container/jetson_board_spec_edge_ai_nx.cfg').read_text()
                for sku in skus:
                    assert f'boardsku={sku};' in board_spec
                    assert any(f'boardsku={sku};' in line and 'board=edge-ai;' in line
                               for line in board_spec.splitlines())
            # Compile the actual carrier pinmux, GPIO, voltage, and MB2 inputs.
            bct = tree/'bootloader/generic/BCT'
            for name in ('tegra234-mb2-bct-common.dtsi', 'pinctrl-tegra.h', 'tegra234-gpio.h'):
                shutil.copy2(original/'bootloader'/name, bct/name)
            for name in ('tegra234-edgeai-orn-pinmux.dtsi', 'tegra234-edgeai-orn-padvoltage-default.dtsi', 'tegra234-edgeai-orn-mb2-bct-misc-p3767-0000.dts'):
                pp = run(['cpp', '-nostdinc', '-undef', '-D__DTS__', '-x', 'assembler-with-cpp', '-I'+str(bct), str(bct/name)]).stdout
                run(['dtc', '-I', 'dts', '-O', 'dtb', '-o', str(scratch/(name+'.dtb'))], input=pp)
            print('Capsule aliases and BCT inputs: PASS', family, flush=True)

    if args.git_cache and args.metadata:
        data = json.loads((args.metadata/'edk2-firmware-tegra.json').read_text())
        for name, revision in (('edk2', '5acf429321649bc191baf19de19670216a75cfb0'), ('edk2-nvidia', 'bd49b331a0bbdeef7a34c224a3767f77e36da0c4')):
            tree = scratch/name
            tree.mkdir()
            archive = run(['git', '--git-dir='+str(args.git_cache/f'github.com.NVIDIA.{name}.git'), 'archive', revision]).stdout
            run(['tar', '-x', '-C', str(tree)], input=archive)
        for uri in data['SRC_URI'].split():
            if not uri.startswith('file://') or '.patch' not in uri:
                continue
            name = uri[7:].split(';')[0]
            source = next(Path(p)/name for p in data['FILESPATH'].split(':') if (Path(p)/name).exists())
            tree = scratch/('edk2-nvidia' if 'patchdir=../edk2-nvidia' in uri else 'edk2')
            run(['patch', '-d', str(tree), '-p1', '--batch', '--fuzz=0'], input=source.read_bytes())
        header = scratch/'edk2-nvidia/Silicon/NVIDIA/Application/L4TLauncher/L4TLauncher.h'
        text = header.read_text().replace('@@DEFAULT_DTB@@', data['DEFAULT_DTB'])
        assert '#define BALENA_ROOTFS_INDEX_A          15' in text
        assert '#define BALENA_ROOTFS_INDEX_B          16' in text
        assert data['DEFAULT_DTB'] in text and '@@DEFAULT_DTB@@' not in text
        logo = scratch/'edk2-nvidia/Silicon/NVIDIA/Drivers/Logo'
        for size in ('480', '720', '1080'):
            source = layer/f'recipes-bsp/uefi/edk2-firmware-tegra/EdgeAI-ORN{size}.bmp'
            assert source.read_bytes().startswith(b'BM')
            shutil.copy2(source, logo/f'nvidiagray{size}.bmp')
        print('Native UEFI patch set, fallback, partition indexes and logos: PASS', flush=True)
