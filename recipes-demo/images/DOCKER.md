# Docker with the NVIDIA runtime on demo-image-weston

This layer's `demo-image-weston.bbappend` adds Docker, the NVIDIA Container
Toolkit, and Docker daemon configuration to the Weston image. It follows
`demo-image-docker-minimal.inc` from `meta-tegrademo` and retains the existing
Edge-AI camera packages.

## Build configuration

Use the matching revisions of the layers supplied by `tegra-demo-distro`.
The build's `conf/bblayers.conf` must include these layers alongside OE-Core,
`meta-tegra`, `meta-tegrademo`, and `meta-tegra-compulab`:

- `meta-virtualization`
- `meta-oe`
- `meta-networking`
- `meta-python`
- `meta-filesystems`

The standard CompuLab build configuration already includes these layers.
Adding a layer only makes its recipes available; the bbappend selects the
packages to install in the image.

The supplied `tegrademo` distro already enables the `virtualization` distro
feature and supplies these Docker settings:

```bitbake
DOCKER_OCI_RUNTIMES ?= '{"nvidia":{"args":[],"path":"nvidia-container-runtime"}}'
DOCKER_DEFAULT_RUNTIME ?= "nvidia"
```

If using a custom distro, enable the feature and define the runtime settings
in its configuration, or in `conf/local.conf` while developing:

```bitbake
DISTRO_FEATURES:append = " virtualization"
DOCKER_OCI_RUNTIMES = '{"nvidia":{"args":[],"path":"nvidia-container-runtime"}}'
DOCKER_DEFAULT_RUNTIME = "nvidia"
```

These settings must be visible to `docker-registry-config`; do not put them
only in the image recipe. That package generates `/etc/docker/daemon.json`
with the NVIDIA runtime registered and selected as the default. No private
container registry is required for this configuration.

## Build and deploy

From the `tegra-demo-distro` directory, initialize the build environment:

```sh
export MACHINE=edge-ai-nx-16g
source compulab-setup-env build-${MACHINE}
```

Check the layers and append, then build:

```sh
bitbake-layers show-layers
bitbake-layers show-appends
bitbake demo-image-weston
```

Confirm that `show-appends` lists this layer's
`recipes-demo/images/demo-image-weston.bbappend`. Deploy the rebuilt image
using the flashing procedure in the [layer README](../../README.md).
The packages are included automatically; no additional image configuration
is needed when using `tegrademo`.

## Verify on the target

Run these commands as root after booting the rebuilt image:

```sh
systemctl status docker nvidia-container-setup --no-pager
cat /etc/docker/daemon.json
docker info --format '{{json .Runtimes}}'
docker info --format '{{.DefaultRuntime}}'
docker run --rm --runtime=runc hello-world
```

Both services should be successful, the runtime list should include `nvidia`,
and the default runtime should be `nvidia`. The `hello-world` command needs
network access and tests basic Docker operation with `runc`.

For GPU validation, choose an ARM64 Jetson container compatible with the
image's JetPack/L4T release and run a CUDA test provided by that container:

```sh
docker run --rm --runtime=nvidia <compatible-jetson-image:tag> <cuda-test-command>
```

Replace both placeholders before running the command. A successful basic
container launch does not establish GPU access; the CUDA test must find and
use the GPU. Include host CUDA, TensorRT, cuDNN, or Jetson GStreamer packages
when required by the chosen container and workload.

If Docker fails to start or create containers, inspect:

```sh
journalctl -b -u docker -u nvidia-container-setup --no-pager
```

For a custom kernel, verify that its configuration supports cgroups,
namespaces, overlay filesystems, veth, bridge networking, and the netfilter
features required by Docker. Adding userspace packages alone does not enable
missing kernel features.

## References

- [OE4T NVIDIA Container Runtime support](https://github.com/OE4T/meta-tegra/blob/master/docs/NVIDIA-Container-Runtime-support.md)
- [NVIDIA Container Toolkit runtime documentation](https://github.com/NVIDIA/nvidia-container-toolkit/tree/main/cmd/nvidia-container-runtime)
