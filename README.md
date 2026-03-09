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
bash <(wget -qO - https://raw.githubusercontent.com/compulab-yokneam/meta-tegra-compulab/refs/heads/edge-ai/tools/run.me)
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
