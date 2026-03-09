# Tegra CompuLab meta layer

## NVidia resources:
* NVidia [tegra-demo-distro](https://github.com/OE4T/tegra-demo-distro) Yocto repository.

## Prepare build environment:

* WorkDir
```
mkdir tegra-compulab && cd tegra-compulab
```

* Download Tegra CompuLab repo:
```
SRC_REV_NVIDIA="068529e2b78153332a84045e2ea6c9d555024d23" \
SRC_REV_CLAB="edge-ai_linux-yocto-v6.12" \
bash <(wget -qO - https://raw.githubusercontent.com/compulab-yokneam/meta-tegra-compulab/refs/heads/edge-ai_linux-yocto-v6.12/tools/run.me)
```

* Set environment variables:

| NVidia CompuLab Machine | Environment variable |
| --- | --- |
|`edge-ai-nx-16g`|`export MACHINE=edge-ai-nx-16g`
|`edge-ai-nx-8g`|`export MACHINE=edge-ai-nx-8g`
|`edge-ai-nano-8g`|`export MACHINE=edge-ai-nano-8g`
|`edge-ai-nano-4g`|`export MACHINE=edge-ai-nano-4g`

## Setup build environment

* Initialize the build environment:
```
source compulab-setup-env build-${MACHINE}
```

## Build targets
* demo-image-weston
```
bitbake -k demo-image-weston
```

* demo-image-full	
```
bitbake -k demo-image-full
```
