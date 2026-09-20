#!/usr/bin/env python3
"""Parse CompuLab metadata without a BitBake server; run inside oe-init-build-env.

Writes resolved metadata and task bodies under the current build's metadata/.
--all-recipes parses all available recipes; --skip-docker-disk explicitly
excludes the recipe whose anonymous function requires a working Docker daemon.
"""
import os, sys, logging
from pathlib import Path
root=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(root/'layers/bitbake/lib')]
import bb, bb.cookerdata, bb.parse, bb.codeparser
logging.basicConfig(level=logging.INFO)
bb.utils.check_system_locale()
config=bb.cookerdata.CookerConfiguration()
config.env=dict(os.environ)
builder=bb.cookerdata.CookerDataBuilder(config, worker=True)
builder.parseBaseConfiguration(worker=True)
print('MACHINE',builder.data.getVar('MACHINE'))
print('OVERRIDES',builder.data.getVar('MACHINEOVERRIDES'))
print('KERNEL',builder.data.getVar('PREFERRED_PROVIDER_virtual/kernel'))
import glob, fnmatch, json, re
files=[]
priorities=[]
for collection in builder.data.getVar('BBFILE_COLLECTIONS').split():
    priorities.append((re.compile(builder.data.getVar('BBFILE_PATTERN_'+collection)), int(builder.data.getVar('BBFILE_PRIORITY_'+collection) or 0)))
def priority(path):
    return max((value for regex,value in priorities if regex.match(path)),default=0)
for pattern in builder.data.getVar('BBFILES').split():
    files.extend(glob.glob(pattern))
masks=[re.compile(mask) for mask in (builder.data.getVar('BBMASK') or '').split()]
files=[f for f in files if not any(mask.search(f) for mask in masks)]
appends=sorted((f for f in files if f.endswith('.bbappend')),key=lambda f:(priority(f),f))
recipes=sorted(f for f in files if f.endswith('.bb'))
selected={'balena-image','balena-image-flasher','balena-image-initramfs','packagegroup-resin-flasher','nvidia-kernel-oot','nvidia-kernel-oot-dtb','jetson-dtbs','linux-noble-nvidia-tegra','edk2-firmware-tegra','uefi-capsule-container','tegra-bootfiles','tegra-flashvars','tegra-flash-dry','tegra-nv-boot-control-config','setup-nv-boot-control','edgeai-orn-platform-selector','hostapp-update-hooks','jetson-qspi-manager','os-power-mode'}
for recipe in recipes:
    pn=Path(recipe).name.split('_')[0].removesuffix('.bb')
    if Path(recipe).name.endswith("_git.bb"): continue
    if pn not in selected: continue
    matching=[a for a in appends if fnmatch.fnmatch(Path(recipe).name,Path(a).name.removesuffix('append').replace('%','*'))]
    try:
        data=builder.parseRecipe(recipe,matching,None)
    except bb.parse.SkipRecipe:
        continue
    if data.getVar('__SKIPPED'): continue
    out=Path('metadata')
    out.mkdir(exist_ok=True)
    values={v:data.getVar(v) for v in ('PN','PV','MACHINE','PACKAGE_ARCH','SSTATE_PKGARCH','OVERRIDES','SRC_URI','FILESPATH','S','UNPACKDIR','WORKDIR','B','D','DEPLOY_DIR_IMAGE','DEFAULT_DTB','KERNEL_DEVICETREE','TNSPEC_MACHINE','TEGRA_BOARDSKU','TEGRA_FLASHVAR_ODMDATA','EDGE_AI_PLATFORM_SKUS','EDGE_AI_CAPSULE_DTBS','JETSON_BOARD_SPEC','UEFI_CAPSULE','HOSTAPP_HOOKS','IMAGE_INSTALL','PART_SPEC_FILE','PACKAGES','RDEPENDS','DEVICE_SPECIFIC_SPACE','BALENA_BOOT_SIZE','BALENA_STATE_SIZE','IMAGE_ROOTFS_SIZE','COMPAT_SPEC_NAME','do_configure','do_compile','do_install','do_patch','do_deploy','install_edge_ai_dtbs','do_deploy_clab_logo','base_do_configure')}
    values['PACKAGE_RDEPENDS']=data.getVar('RDEPENDS:'+values['PN'])
    for task in ('do_configure','do_compile','do_install','do_patch','do_deploy','install_edge_ai_dtbs','do_deploy_clab_logo','base_do_configure'):
        values[task+'_flags']=data.getVarFlags(task)
    for uri in data.getVar('SRC_URI').split():
        if not uri.startswith('file://'): continue
        name=uri[7:].split(';')[0]
        path=Path(name) if name.startswith('/') else next((Path(d)/name for d in data.getVar('FILESPATH').split(':') if (Path(d)/name).exists()),None)
        assert path and path.exists(), (pn,uri)
    (out/(pn+'.json')).write_text(json.dumps(values,indent=2,default=str))
    print('PARSED',pn,values['PV'],len(matching),'appends',flush=True)

for append in (root/'layers/meta-tegra-compulab').rglob('*.bbappend'):
    pattern=append.name.removesuffix('append').replace('%','*')
    assert any(fnmatch.fnmatch(Path(r).name,pattern) for r in recipes), f"Dangling append: {append}"
machine=builder.data.getVar('MACHINE')
if machine in ('edgeai-orn-nano','edgeai-orn-nx'):
    metadata={p.stem:json.loads(p.read_text()) for p in Path('metadata').glob('*.json')}
    family=machine.removeprefix('edgeai-orn-')
    fallback='0004' if family=='nano' else '0001'
    dtb=f'tegra234-p3768-0000+p3767-{fallback}-nv-super.dtb'
    assert builder.data.getVar('PREFERRED_PROVIDER_virtual/kernel')=='linux-noble-nvidia-tegra'
    assert metadata['jetson-dtbs']['KERNEL_DEVICETREE'].split()[0]==dtb
    assert metadata['edk2-firmware-tegra']['DEFAULT_DTB']==dtb
    assert metadata['linux-noble-nvidia-tegra']['KERNEL_DEVICETREE']==''
    assert metadata['balena-image']['PART_SPEC_FILE']=='partition_specification234_orin_nano.txt'
    assert 'edgeai-orn-platform-selector' in metadata['balena-image']['IMAGE_INSTALL'].split()
    assert 'nvidia-kernel-oot-devicetrees' not in metadata['balena-image']['IMAGE_INSTALL'].split()
    assert 'nvidia-kernel-oot-display' in metadata['balena-image']['IMAGE_INSTALL'].split()
    assert 'tegra-configs-display-driver' in metadata['balena-image']['IMAGE_INSTALL'].split()
    assert 'nvidia-drm-loadconf' not in metadata['balena-image']['IMAGE_INSTALL'].split()
    assert 'kernel-modules' not in metadata['balena-image-flasher']['IMAGE_INSTALL'].split()
    assert 'nvidia-kernel-oot' not in metadata['balena-image-flasher']['IMAGE_INSTALL'].split()
    assert 'nvidia-kernel-oot-display' not in metadata['balena-image-flasher']['IMAGE_INSTALL'].split()
    assert 'nvidia-drm-loadconf' not in metadata['balena-image-flasher']['IMAGE_INSTALL'].split()
    assert 'kernel-modules' not in metadata['packagegroup-resin-flasher']['PACKAGE_RDEPENDS'].split()
    assert metadata['hostapp-update-hooks']['HOSTAPP_HOOKS'].split().count('99-resin-bootfiles-orin-nano-devkit-nvme')==1
    assert '99-resin-bootfiles-orin-nx-xavier-nx-devkit' not in metadata['hostapp-update-hooks']['HOSTAPP_HOOKS'].split()
    for pn in ('jetson-qspi-manager','os-power-mode'):
        assert not metadata[pn]['do_patch_flags'].get('noexec')
        assert metadata[pn]['PACKAGE_ARCH']==machine.replace('-','_')
        assert metadata[pn]['SSTATE_PKGARCH']==machine.replace('-','_')
    capsule=metadata['uefi-capsule-container']
    assert len(capsule['EDGE_AI_CAPSULE_DTBS'].split())==4
    assert 'nvidia-kernel-oot-dtb:do_deploy' in capsule['do_compile_flags']['depends']
    assert metadata['tegra-flashvars']['TEGRA_FLASHVAR_ODMDATA']=='gbe-uphy-config-9,hsstp-lane-map-3,hsio-uphy-config-0'
    assert metadata['edgeai-orn-platform-selector']['EDGE_AI_PLATFORM_SKUS']==('0003 0004' if family=='nano' else '0000 0001')
print('Metadata assertions and local sources: PASS',flush=True)
if '--all-recipes' in sys.argv:
    ok=skipped=excluded=0
    for recipe in recipes:
        if '--skip-docker-disk' in sys.argv and Path(recipe).name=='docker-disk.bb':
            excluded+=1
            continue
        matching=[a for a in appends if fnmatch.fnmatch(Path(recipe).name,Path(a).name.removesuffix('append').replace('%','*'))]
        try:
            variants=builder.parseRecipeVariants(recipe,matching,mc='',layername=None)
            if all(d.getVar('__SKIPPED') for d in variants.values()): skipped+=1
            else: ok+=1
        except bb.parse.SkipRecipe:
            skipped+=1
        if (ok+skipped)%500==0: print('PROGRESS',ok,skipped,flush=True)
    print('FULL PARSE',ok,'parsed',skipped,'skipped',excluded,'explicitly excluded',flush=True)
