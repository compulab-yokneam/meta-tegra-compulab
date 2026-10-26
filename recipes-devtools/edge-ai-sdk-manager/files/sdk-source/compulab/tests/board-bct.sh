#!/bin/bash
# SPDX-License-Identifier: MIT
# Read/compile installed BCT data only; never run NVIDIA flash executables.
set -euo pipefail

sdk=$(cd -- "$(dirname -- "$0")/../.." && pwd)
assets="${sdk}/bootloader/generic/BCT"
work=$(mktemp -d /tmp/edge-ai-installed-bct-check.XXXXXXXX)

compile_bct()
{
    local input="$1" name="$2"
    cpp -nostdinc -x assembler-with-cpp -DIN_DTS_CONTEXT \
        -I "${sdk}/bootloader" -I "${assets}" \
        "${input}" -o "${work}/${name}.dts"
    dtc -q -I dts -O dtb -o "${work}/${name}.dtb" "${work}/${name}.dts"
}

compile_bct "${assets}/tegra234-mb1-bct-misc-p3767-0000.dts" vendor-mb1
compile_bct "${assets}/tegra234-edge-ai-mb1-bct-misc-p3767-0000.dts" private-mb1
test "$(fdtget -t u "${work}/vendor-mb1.dtb" /misc/debug enable_wdt)" = 0
test "$(fdtget -t u "${work}/private-mb1.dtb" /misc/debug enable_wdt)" = 1
diff -u \
    <(dtc -q -I dtb -O dts "${work}/vendor-mb1.dtb" | sed '/^[[:space:]]*enable_wdt[[:space:]]*=/d') \
    <(dtc -q -I dtb -O dts "${work}/private-mb1.dtb" | sed '/^[[:space:]]*enable_wdt[[:space:]]*=/d')
printf 'PASS: installed private MB1 changes only /misc/debug/enable_wdt 0->1\n'

compile_bct "${assets}/tegra234-edge-ai-pinmux.dtsi" pinmux
compile_bct "${assets}/tegra234-edge-ai-padvoltage-default.dtsi" padvoltage
compile_bct "${assets}/tegra234-edge-ai-mb2-bct-misc-p3767-0000.dts" mb2
test "$(fdtget -t u "${work}/mb2.dtb" /mb2-misc/eeprom cvb_eeprom_i2c_instance)" = 7
test "$(fdtget -t x "${work}/mb2.dtb" /mb2-misc/eeprom cvb_eeprom_i2c_slave_address)" = a0
test "$(fdtget -t u "${work}/mb2.dtb" /mb2-misc/eeprom cvb_eeprom_read_size)" = 256
fdtget -l "${work}/pinmux.dtb" /pinmux@2430000 >/dev/null
fdtget -l "${work}/pinmux.dtb" /gpio@2200000 >/dev/null
fdtget -l "${work}/padvoltage.dtb" /pmc@c360000 >/dev/null
printf 'PASS: installed GPIO/pinmux/padvoltage/MB2 compile; CVB EEPROM is 7:a0\n'
for sku in 0001 0004; do
    for kind in sdram wb0sdram; do
        compile_bct "${assets}/tegra234-p3767-${sku}-${kind}-l4t.dts" \
            "memory-${sku}-${kind}"
        fdtget -l "${work}/memory-${sku}-${kind}.dtb" / >/dev/null
    done
done
printf 'PASS: Nano8G shared 0001 and Nano4G 0004 SDRAM/WB0 BCTs compile unchanged\n'
printf 'Evidence: %s\n' "${work}"
