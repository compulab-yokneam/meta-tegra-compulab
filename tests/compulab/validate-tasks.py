#!/usr/bin/env python3
"""Exercise resolved local recipe tasks and runtime behavior without hardware.

Run validate-metadata.py first, then pass its metadata directory and a directory
containing the ten DTBs compiled from patched L4T sources. This writes only
inside the build directories described by those metadata files.
"""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

root = Path(__file__).resolve().parents[2]
metadata = {p.stem: json.loads(p.read_text()) for p in Path(sys.argv[1]).glob('*.json')}
dtbs = Path(sys.argv[2]).resolve()
family = metadata['balena-image']['MACHINE'].removeprefix('edgeai-orn-')


def run_task(data, task):
    helpers = '\n'.join(f'{name}() {{\n{data[name]}\n}}' for name in ('install_edge_ai_dtbs', 'do_deploy_clab_logo', 'base_do_configure') if data.get(name))
    subprocess.run(['bash', '-e', '-c', helpers + '\n' + data[task]], cwd=data['B'], check=True, timeout=30)


for pn in ('edgeai-orn-platform-selector', 'tegra-nv-boot-control-config', 'setup-nv-boot-control', 'jetson-dtbs', 'jetson-qspi-manager', 'os-power-mode', 'tegra-flashvars', 'tegra-flash-dry'):
    data = metadata[pn]
    for key in ('UNPACKDIR', 'B', 'D'):
        path = Path(data[key]).resolve()
        assert path.is_relative_to(root) and any(part.startswith('build') for part in path.relative_to(root).parts), path
        path.mkdir(parents=True, exist_ok=True)
    patches = []
    for uri in data['SRC_URI'].split():
        if not uri.startswith('file://'):
            continue
        name = uri[7:].split(';')[0]
        source = Path(name) if name.startswith('/') else next(Path(p)/name for p in data['FILESPATH'].split(':') if (Path(p)/name).exists())
        destination = Path(data['UNPACKDIR'])/name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        if name.endswith('.patch'):
            patches.append(source)
    for patch in patches:
        subprocess.run(['patch', '-d', data['S'], '-p1', '--batch', '--fuzz=0'], input=patch.read_bytes(), check=True, stdout=subprocess.DEVNULL)
    if pn == 'jetson-dtbs':
        deploy = Path(data['DEPLOY_DIR_IMAGE'])/'devicetree'
        deploy.mkdir(parents=True, exist_ok=True)
        for dtb in dtbs.glob('*.dtb'):
            shutil.copy2(dtb, deploy/dtb.name)
    if pn in ('tegra-nv-boot-control-config', 'setup-nv-boot-control', 'tegra-flashvars'):
        run_task(data, 'do_compile')
    if pn == 'os-power-mode':
        run_task(data, 'do_configure')
    run_task(data, 'do_install')
    print('TASKS PASS:', pn)

selector = Path(metadata['edgeai-orn-platform-selector']['D'])/'usr/sbin/edgeai-orn-platform-selector'
config = Path(metadata['tegra-nv-boot-control-config']['D'])/'etc'
assert (config/'nv_boot_control.conf').is_symlink()
assert os.readlink(config/'nv_boot_control.conf') == '/run/nv_boot_control/nv_boot_control.conf'
assert '@TNSPEC@' in (config/'nv_boot_control.template').read_text()
setup = (Path(metadata['setup-nv-boot-control']['D'])/'usr/bin/setup-nv-boot-control').read_text()
assert 'TARGET="jetson-orin-nano-devkit-super"' in setup
flashvars = (Path(metadata['tegra-flashvars']['B'])/'flashvars').read_text()
for expected in ('ODMDATA="gbe-uphy-config-9,hsstp-lane-map-3,hsio-uphy-config-0"', 'PINMUX_CONFIG="tegra234-edgeai-orn-pinmux.dtsi"', 'MB2BCT_CFG="tegra234-edgeai-orn-mb2-bct-misc-p3767-0000.dts"'):
    assert expected in flashvars, expected
boot = Path(metadata['jetson-dtbs']['D'])/'boot'
assert len(list(boot.glob('*.dtb'))) == 10
for path in boot.glob('*.dtb'):
    assert path.read_bytes() == (dtbs/path.name).read_bytes()
qspi = (Path(metadata['jetson-qspi-manager']['D'])/'usr/libexec/jetson-qspi-helpers').read_text()
cap = 'TEGRA_BL_Orin_Nano.Cap.gz' if family == 'nano' else 'TEGRA_BL_Orin_NX.Cap.gz'
assert f'find /tmp -xdev -type f -name "{cap}"' in qspi
assert f'find / -xdev -type f -name "{cap}"' in qspi
assert 'TEGRA_BL*.Cap.gz' not in qspi
assert 'qspi_flashed && l4t_firmware_match' in qspi
power = (Path(metadata['os-power-mode']['D'])/'usr/bin/os-power-mode').read_text()
assert '|edgeai-orn-nx)' in power and '|edgeai-orn-nano)' in power
for text in (selector.read_text(), qspi, power, setup):
    subprocess.run(['bash', '-n'], input=text.encode(), check=True)

# Test the installed selector using fixture paths, including EFI attributes.
with tempfile.TemporaryDirectory(prefix='edgeai-runtime-') as temp:
    temp = Path(temp)
    boot = temp/'boot'
    (boot/'boot').mkdir(parents=True)
    efivars = temp/'efivars'
    efivars.mkdir()
    script = selector.read_text().replace('efivar_dir=/sys/firmware/efi/efivars', f'efivar_dir={efivars}').replace('boot_mount=/mnt/boot', f'boot_mount={boot}')
    envfile = boot/'extra_uEnv.txt'
    efivar = efivars/'TegraPlatformSpec-781e084c-a330-417c-b678-38e696380cb9'
    def select(sku, board='3767', expected=0):
        efivar.write_bytes(b'\x07\0\0\0'+f'{board}-301-{sku}-F.1-1-0-jetson-orin-nano-devkit-super-'.encode()+b'\0')
        result = subprocess.run(['bash', '-e', '-c', script], capture_output=True)
        assert result.returncode == expected, result.stderr
    envfile.write_text('user_setting=keep\ncustom_fdt_file=old.dtb\ncustom_fdt_file=duplicate.dtb\n')
    subprocess.run(['bash', '-e', '-c', script], check=True, capture_output=True)
    assert envfile.read_text().count('custom_fdt_file=') == 2  # missing EFI: unchanged
    skus = ('0003', '0004') if family == 'nano' else ('0000', '0001')
    for sku in skus:
        dtb = f'tegra234-p3768-0000+p3767-{sku}-nv-super.dtb'
        (boot/'boot'/dtb).write_bytes((dtbs/dtb).read_bytes())
        select(sku)
        assert envfile.read_text() == f'user_setting=keep\ncustom_fdt_file={dtb}\n'
        stamp = envfile.stat().st_mtime_ns
        select(sku)
        assert envfile.stat().st_mtime_ns == stamp  # no rewrite on subsequent boots
    previous = envfile.read_bytes()
    select('0000' if family == 'nano' else '0003')
    select('9999')
    select(skus[0], board='3701')
    assert envfile.read_bytes() == previous
    (boot/'boot'/f'tegra234-p3768-0000+p3767-{skus[0]}-nv-super.dtb').unlink()
    select(skus[0], expected=1)
    assert envfile.read_bytes() == previous
    assert not list(boot.glob('.extra_uEnv.txt.*'))
    # Prepared-capsule detection must use the configured ESP mountpoint.
    function = qspi.split('capsule_update_prepared() {', 1)[1].split('\n}', 1)[0]
    mount = temp/'ESP with spaces'
    target = mount/'EFI/UpdateCapsule/TEGRA_BL.Cap'
    target.parent.mkdir(parents=True)
    target.write_bytes(b'capsule')
    flags = temp/'OsIndications'
    flags.touch()
    body = 'capsule_update_prepared() {'+function+'\n}\ncapsule_update_prepared\n'
    env = dict(os.environ, UEFI_CAPSULE_TARGET_MOUNTPOINT=str(mount)+'/', CAPSULE_TARGET_PATH='/EFI/UpdateCapsule/TEGRA_BL.Cap', os_indications_efivar=str(flags))
    assert subprocess.run(['bash', '-e', '-c', body], env=env).returncode == 0
    target.unlink()
    assert subprocess.run(['bash', '-e', '-c', body], env=env).returncode == 1
print('Runtime assertions: PASS', family)
