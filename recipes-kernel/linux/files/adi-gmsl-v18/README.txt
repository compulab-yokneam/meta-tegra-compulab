EDGEDES ADI v18 integration for Edge-AI Yocto / Linux 6.18.48
==========================================================

This is an opt-in adaptation. Add the following to the build configuration:

    require conf/include/edge-ai-adi-gmsl-v18.inc

The include adds adi-gmsl-v18 to MACHINEOVERRIDES. Without that override,
neither the kernel patch series nor the NVIDIA camera changes are selected.
The test kernel release is 6.18.48-yocto-standard-adi-v18, deliberately separate
from the original 6.18.48-yocto-standard module tree.

Source organization
-------------------
0001-0023: published ADI v18 GMSL series, preserving upstream patch boundaries.
0024: Linux 6.18 set_fmt signature and driver-local dynamic bitfield helpers.
0025: preserve a reachable MAX96793 GMSL2 link on a GMSL2-only deserializer;
      use its discovered address as the readdressing source when reset is skipped.
0026: use the qualified MAX96793 pixel-mode path, explicitly clearing tunnel
      mode even when advertised capabilities contain only pixel mode.

The NVIDIA OOT bbappend conditionally adds 0100 (stream-aware bridge graph,
format propagation, sensor metadata/control registration) and 0101 (TEVS and
native FRAMOS IMX678 sensor modules), followed by 0102 (native FRAMOS IMX676).
NVIDIA interfaces remain the leaf-sensor
API; ADI owns serializer/deserializer routing and nested I2C address translation.

The edgedes-adi-v18-devicetree recipe builds the modified CompuLab/NVIDIA base,
both overlays, and complete DTBs for Edge-AI NX 16G (including the edge-ai-nx
alias). Other Jetson modules require a matching base DT and are excluded from
this recipe. Boot one complete camera DTB at a time:

    edgedes-adi-v18-tevs-ar0144-port3.dtb
    edgedes-adi-v18-framos-imx678-port0.dtb

Normal Edge-AI images install kernel-modules and nvidia-kernel-oot-cameras, so
the opt-in transport and sensor packages are included in those images. The
FRAMOS demo package also installs all three complete camera profiles under
/boot/dtb through its edgedes-adi-v18-devicetree dependency. The DT recipe
continues to emit standalone deploy artifacts as well. Neither mechanism
changes the regular virtual/dtb provider, tegraflash DT selection or extlinux
FDT; select one complete camera DTB for the test boot. Turnkey production
flash-profile selection is a separate integration step.

Build targets used in the Edge-AI runtime multiconfig:

    bitbake mc:edge-ai-runtime:linux-yocto \
            mc:edge-ai-runtime:nvidia-kernel-oot \
            mc:edge-ai-runtime:tegra-minimal-initramfs \
            mc:edge-ai-runtime:edgedes-adi-v18-devicetree

Build the matching initramfs: NVMe, Tegra PCIe and P2U PHY are modular here.
Use the raw tegra-minimal-initramfs-*.cpio.gz as extlinux INITRD, not the .cboot
container. Install kernel and NVIDIA OOT modules for the same kernel release,
then run depmod for that release. Do not mix modules from the original kernel.

Hardware and routing
--------------------
EDGEDES is on physical i2c-2 / 3180000.i2c, native deserializer address 0x27.
The qualified output is MAX96724 PHY2 (source pad 6) -> Tegra CSI-C/port-index2
-> VI, VC0, four identity lanes <1 2 3 4>, zero polarity swaps, 2.5 Gb/s/lane.
Sensor endpoints carry both standard data-lanes and NVIDIA bus-width/port-index
metadata. Coax port number and Tegra CSI port number are different concepts.

TEVS profile: coax 3, MAX96717 native 0x40, alias 0x34; TEVS native 0x48 and
PCA9554 native 0x25 behind the serializer. P4 resets the sensor; P2 is the legacy
standby/boot-mode GPIO, low during normal operation. Normal standby is controlled
through ISP I2C SYSTEM_START. The alias pool contains 0x24/0x3c; use the nested adapter's
native addresses for ordinary Linux I2C access.

FRAMOS profile: coax 0, MAX96793 DT address 0x40 / reachable upstream alias 0x42;
its actual cold-power-up address is not qualified. IMX678
native 0x1a and TCA6408 native 0x21 behind the serializer. ATR allocates remote
aliases dynamically from 0x22/0x1b: allocation order is not a stable pinout.
MFP4 provides 37.125-MHz INCK, MFP0 is XCLR, MFP6 is TENABLE, MFP8 is PW_EN_0.
The sensor driver holds TENABLE low, cycles PW_EN low 5 ms/high, enables INCK,
holds active-low XCLR asserted 200 ms, releases XCLR and waits 40 ms. GPIO/clock
ownership is balanced across power-off and capture. TCA6408 strap states are
not changed; no configuration EEPROM image is required.

Validation to date (2026-10-04, root@192.168.122.250)
-------------------------------------------------
TEVS-AR0144: five 640x480 UYVY frames captured, total 3,072,000 bytes; all frame
checksums differ and the decoded picture shows the room ceiling.
IMX678: five 3856x2180 RG12 frames captured, total 84,060,800 bytes; a 100-frame
run completed at 10.00 fps. Native RAW12 is stored by VI in 16-bit containers,
stride 7712 and frame size 16,812,160 bytes. The decoded Bayer image shows the
ceiling; ISP/white-balance quality is not part of this raw-capture validation.

The FRAMOS tunnel-mode experiment produced no frames; with the same sensor,
clock, reset and lanes, pixel mode succeeded. Deskew trace status 0x01c00000 /
0x00c00000 denotes calibration completion, not a physical-layer error.

For a useful IMX678 preview, explicitly set exposure 10000 (10 ms) and gain 0
before capture; NVIDIA's initial V4L2 exposure control was 30 us on this target.
Do not assume the DT's default_exp_time is automatically selected by every app.

Current raw capture commands (terminate externally if no frame arrives):
Stop all Argus clients and nvargus-daemon first. Set bypass_mode=0 when
switching back from Argus to direct V4L2; Argus leaves this control enabled.

    v4l2-ctl -d /dev/video0 \
      --set-fmt-video=width=640,height=480,pixelformat=UYVY \
      --stream-mmap=4 --stream-count=5 --stream-poll --stream-to=tevs.uyvy

    v4l2-ctl -d /dev/video0 \
      --set-fmt-video=width=3856,height=2180,pixelformat=RG12 \
      --set-ctrl=bypass_mode=0,exposure=10000,gain=0 \
      --stream-mmap=4 --stream-count=5 --stream-poll --stream-to=imx678.raw

IMX676 uses its separate edgedes-adi-v18-framos-imx676-port0.dtb profile:

    v4l2-ctl -d /dev/video0 \
      --set-fmt-video=width=3552,height=3556,pixelformat=RG12 \
      --set-ctrl=bypass_mode=0,exposure=10000,gain=0 \
      --stream-mmap=4 --stream-count=5 --stream-poll --stream-to=imx676.raw

The leaf preserves 200 ms XCLR reset and native 720-Mb/s/lane RAW12 output.
MAX96724 PHY2 -> CSI-C lane order, VC0 and 2.5-Gb/s output remain unchanged.
See recipes-multimedia/argus/IMX676-VALIDATION.txt for the separate qualification.

Limits and follow-up
-------------------
Only one camera is enabled per profile. Mixed simultaneous capture, dynamic
routing and other TEVS models/modes are not qualified by these tests.
An explicit internal IMX678 Argus/ISP demo was validated on this Yocto graph
on 2026-10-06: native JPEG, 100 frames at 10 FPS with AE/AWB convergence,
native Wayland GStreamer preview and GTK/Xwayland preview. See
recipes-multimedia/argus/README.md and ARGUS-DEMO-VALIDATION.txt. Its reused
NITO is an uncalibrated migration baseline, not factory sensor/lens tuning.
NVIDIA firmware direct-I2C metadata must not assume an ATR alias order;
this sensor uses the normal Linux control/regmap path through ATR.
MAX96793 pixel-only advertisement is a conservative EDGEDES qualification
policy, not a claim that the hardware lacks tunnel support.
All target validation so far uses warm reboot, not cold-power startup. 0025
preserves an already reachable GMSL2 configuration; it cannot bootstrap a
serializer that powers up unreachable in GMSL3. Qualify cold boot separately.
Keep the original kernel, module tree and primary/noble boot entries for rollback.
