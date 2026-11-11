# EdgeAI-ORN carrier and camera configuration

The `edgeai-orn-balena-7.2` branch uses Linux 6.18.48 with L4T 39.2.0.
Carrier peripheral and ADI v18 camera support is enabled in the default
`linux-yocto` provider. No switch to the Noble kernel is required.

## Build

Build each family with its own configured build directory:

```bitbake
MACHINE = "edgeai-orn-nx"
```

Use `edgeai-orn-nano` for the Nano family. Then build normally:

```sh
bitbake balena-image-flasher
```

The NX image contains P3767-0000/0001 profiles; the Nano image contains
P3767-0003/0004 profiles. Deploy the matching image through the existing
Balena provisioning or host OS update workflow. Kernel modules, the NVIDIA
camera integration and device trees must be updated together. A firmware
capsule alone does not install the new Linux drivers.

## Included kernel support

| Hardware | Kernel support |
| --- | --- |
| ADI GMSL2/3 | ADI v18 Maxim SerDes framework, MAX96717/MAX96793 serializer, MAX96724 and MAX9296A/MAX96716 deserializers, I2C address translation |
| TEVS AR0144 | NVIDIA tegracam driver and port-3 camera profile |
| Framos IMX678/IMX676 | NVIDIA tegracam drivers, individual port 0–3 and four-port profiles, reusable mixed-sensor overlays |
| RK628 HDMI-to-CSI | Receiver, CSI bridge and HDMI receiver class modules; CSI port 2, four lanes |
| ADV7280-M PAL-to-CSI | Standard ADV7180-family driver; CSI port 0, one lane |
| Expansion board | PCA9555 GPIO expander at I2C `0x20`, ISL1219 RTC at `0x6f` on `hdr40_i2c1` |
| RS-485 | Dedicated Tegra194 UART driver, `ttyTHSRS485<n>`, standard `TIOCSRS485` controls |
| External watchdog | `gpio_wdt_ext`, separate enable and ping GPIOs |

The kernel also retains the existing Intel Wi-Fi, Ethernet, TI camera and
Balena configurations, with the shared Linux 6.18 network-routing and USB
gadget configuration. The ADI Streams integration preserves the ordinary
NVIDIA sensor pipeline for devices that do not use a stream-aware bridge.

Drivers are available without enabling every physical adapter. Default boot
selection remains the detected module's normal Super carrier DTB.

## Select USB or camera profiles

The selector reads `edgeai_fdt_profile` from `/mnt/boot/extra_uEnv.txt`.
It detects the actual module SKU and stages the matching DTB under
`/mnt/boot/boot`, then updates `custom_fdt_file`. Other boot settings are
preserved. A missing profile file or invalid profile fails before changing
the active selection.

| Profile | Selection |
| --- | --- |
| `default` | Normal Super carrier DTB, existing USB OTG behavior |
| `host` | Fixed recovery-port USB host role; XUDC disabled |
| `device` | Fixed recovery-port USB device role |
| `gmsl-base` | Neutral module-specific base for custom GMSL compositions |
| `tevs-ar0144-port3` | TEVS AR0144 on port 3 |
| `framos-imx678-port0` … `framos-imx678-port3` | One IMX678 on the selected port |
| `framos-imx676-port0` … `framos-imx676-port3` | One IMX676 on the selected port |
| `framos-imx678-4port` | Four IMX678 cameras |
| `framos-imx676-4port` | Four IMX676 cameras |

For example, on the Balena host OS, select an IMX678 on port 0:

```sh
sed -i '/^edgeai_fdt_profile=/d' /mnt/boot/extra_uEnv.txt
printf 'edgeai_fdt_profile=framos-imx678-port0\n' >> /mnt/boot/extra_uEnv.txt
systemctl restart edgeai-orn-platform-selector.service
reboot
```

If the file does not exist yet, create it before running `sed`. Replace the
profile with `default` to restore the ordinary module-specific carrier tree.
The change takes effect after reboot. Camera profiles retain the base USB
OTG behavior; combining camera routing with fixed USB roles requires a
separately composed and validated device tree.

The complete camera profiles live under `/boot/dtb`, named, for example:

```
edgedes-adi-v18-framos-imx678-port0-p3767-0000.dtb
edgedes-adi-v18-framos-imx676-4port-p3767-0004.dtb
```

Reusable GMSL transport and per-port camera overlays are installed under
`/boot/devicetree`. The build validates all 81 empty/IMX676/IMX678 port
combinations for each family SKU. These overlays allow custom mixed-sensor
compositions without installing every possible merged DTB. The initial
implementation's fallback-based camera profile filenames remain available.

IMX676 extended modes are enabled by default. IMX678 extended modes remain
opt-in through `EDGE_AI_IMX678_EXTENDED_MODES = "1"`. Extended modes require
matching sensor tuning/NITO data in the camera application's environment;
this layer change does not install the Ubuntu SDK application's NITO assets
into a Balena container.

## Optional peripheral overlays

The following files are installed under `/boot/devicetree`:

| Overlay | Function |
| --- | --- |
| `tegra234-edge-ai-eb-edgerpi4.dtbo` | Expansion-board GPIO and RTC |
| `tegra234-edge-ai-rs485.dtbo` | UART `3110000`, alias `serial3`, dedicated RS-485 compatible |
| `tegra234-camera-HDMI-rk628.dtbo` | RK628 HDMI capture |
| `tegra234-camera-PAL-adv280-m.dtbo` | ADV7280-M PAL capture; reference filename retained |
| `tegra234-edge-ai-watchdog-template.dtbo` | Disabled watchdog template without GPIO assignments |

Integrate these into a custom DTB based on the fitted module, using
`fdtoverlay` or the image's device-tree build. The predefined selector
profiles do not automatically apply these peripheral overlays. HDMI and PAL
use the same VI channel and cannot be combined with each other or with a
GMSL camera profile without separately validated routing.

The watchdog GPIOs in the reference patch series are explicitly draft.
Confirm the board's `enable-gpios` and `ping-gpios` before enabling the
watchdog node. The shipped template does not claim pins or arm a watchdog.

## USB and PCIe fixes

The XUSB host now references `usb3-2` in both `phys` and `phy-names`; merely
enabling that padctl lane was insufficient to initialize the third
SuperSpeed host PHY.

ODMDATA remains `gbe-uphy-config-9,hsstp-lane-map-3,hsio-uphy-config-0`.
C7 and C9 each use one GBE UPHY lane and C10 is disabled. C1 (M.2 Key E,
HSIO lane 3) and C4 (M.2 Key M, HSIO lanes 4–7) retain their existing mapping.
The C7/C9 fix does not itself establish that an Intel AX210 on C1 links.
Check `lspci -nn -tv`, `dmesg`, and `lsusb -t` after deploying matched
firmware, kernel and device trees. A visible SuperSpeed root hub alone does
not prove downstream USB 3 enumeration.

## Validation limits

The branch's validation scripts check family metadata, local source inputs,
boot staging, carrier device trees, profile selection and overlay composition.
Driver compilation checks use the pinned Linux 6.18.48 source and the pinned
L4T 39.2.0 NVIDIA camera sources. Hardware capture, RS-485 direction timing,
watchdog pins and operation, USB enumeration, PCIe links and Balena A/B
updates still need testing on the corresponding hardware.
