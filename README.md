# Configuring the build

* WorkDir

```
mkdir tegra-compulab && cd tegra-compulab
```

* NVidia Yocto build environment</br>
Follow the instructions and prepare the [Nvidia Yocto Build environemt.](https://github.com/OE4T/tegra-demo-distro?tab=readme-ov-file#tegra-demo-distro)


* Initialize and sync CompuLab Mender repo manifest:

```
wget --directory-prefix .repo/local_manifests https://raw.githubusercontent.com/compulab-yokneam/meta-tegra-compulab/refs/heads/edge-ai/scripts/meta-tegra-compulab.xml
repo sync
```

* Set environment variables:

| NVidia CompuLab Machine | Environment variable |
| --- | --- |
|`edge-ai-nx-16g`|`export MACHINE=edge-ai-nx-16g`
|`edge-ai-nx-8g`|`export MACHINE=edge-ai-nx-8g`
|`edge-ai-nano-8g`|`export MACHINE=edge-ai-nano-8g`
|`edge-ai-nano-4g`|`export MACHINE=edge-ai-nano-4g`

# Setup build environment

* Initialize the build environment:
```
source compulab-setup-env build-${MACHINE}
```

# Build targets
* demo-image-weston
```
bitbake -k demo-image-weston
```

* demo-image-full	
```
bitbake -k demo-image-full
```
