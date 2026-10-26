#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Mock-only public wrapper tests: no real sudo, USB, loops or flashing."""
import json
import os
from pathlib import Path
import pty
import shutil
import subprocess
import tempfile
import unittest


SDK_SOURCE = Path(__file__).resolve().parents[2]
TARGETS = ("edge-ai-nx-16g", "edge-ai-nx-8g", "edge-ai-nano-8g",
           "edge-ai-nano-4g")
IDENTITY_FIELDS = ("BOARDID", "BOARDSKU", "FAB", "BOARDREV", "CHIPREV",
                   "CHIP_SKU", "chip_SKU", "RAMCODE", "RAMCODE_ID",
                   "SKIP_EEPROM_CHECK", "FUSELEVEL")
SETUP = r'''
source "$SDK_ROOT/compulab-l4t.env" || exit $?
_compulab_wrapper_check_sdk() {
    printf '%s\n' "$*" >> "$CHECK_LOG"
    return "${MOCK_CHECK_RC:-0}"
}
_compulab_recovery_devices() {
    [ -z "${MOCK_RECOVERY:-}" ] || printf '%s\n' "$MOCK_RECOVERY"
}
sleep() { :; }
'''


class SourceableWrapperTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="edge-ai-wrapper-fixture-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.sdk = self.root / "sdk"
        self.other = self.root / "unrelated"
        self.bin = self.root / "bin"
        self.temp = self.root / "tmp"
        for directory in (self.sdk, self.other, self.bin, self.temp):
            directory.mkdir()
        shutil.copy2(SDK_SOURCE / "compulab-l4t.env", self.sdk)
        host = self.sdk / "compulab/host"
        host.mkdir(parents=True)
        # Copy only maintained scripts, never a prepared SDK/rootfs payload.
        for path in (SDK_SOURCE / "compulab/host").glob("*.sh"):
            shutil.copy2(path, host / path.name)
        for path in SDK_SOURCE.glob("edge-ai*.conf"):
            shutil.copy2(path, self.sdk / path.name)
        for relative in ("rootfs", "bootloader/generic/cfg", "kernel/dtb",
                         "tools/kernel_flash"):
            (self.sdk / relative).mkdir(parents=True, exist_ok=True)
        (self.sdk / "compulab/kernel-release.txt").write_text(
            "6.8.12-l4t-r39.2.1-1021.21-clab-adi-v18\n")
        for relative in ("flash.sh", "tools/kernel_flash/l4t_initrd_flash.sh"):
            path = self.sdk / relative
            path.write_text("#!/bin/bash\nexit 97\n")
            path.chmod(0o755)
        for relative in ("bootloader/generic/cfg/flash_t234_qspi.xml",
                         "tools/kernel_flash/flash_l4t_t234_nvme.xml"):
            (self.sdk / relative).write_text("<partition_layout/>\n")
        (self.sdk / "kernel/dtb/BootOrderNvme.dtbo").write_bytes(b"fixture")
        helper = self.sdk / "compulab/tools/prepare-massflash-package.py"
        helper.parent.mkdir(parents=True, exist_ok=True)
        # sudo is intercepted; this sentinel must never execute as a backend.
        helper.write_text("raise SystemExit(97)\n")
        self.sudo_log = self.root / "sudo.jsonl"
        self.guard_log = self.root / "guard.jsonl"
        self.check_log = self.root / "checks.txt"
        self.images_log = self.root / "images.jsonl"
        self.events_log = self.root / "events.jsonl"
        self.environment = {
            "PATH": str(self.bin) + ":/usr/bin:/bin",
            "HOME": str(self.root), "LC_ALL": "C", "SDK_ROOT": str(self.sdk),
            "CHECK_LOG": str(self.check_log),
            "MOCK_SUDO_LOG": str(self.sudo_log),
            "MOCK_GUARD_LOG": str(self.guard_log),
            "TMPDIR": str(self.temp),
            "MOCK_IMAGES_LOG": str(self.images_log),
            "MOCK_EVENT_LOG": str(self.events_log),
            "MOCK_SUDO_RENEW_FILE": str(self.root / "sudo-renewed"),
        }
        images = self.sdk / "compulab/tools/check-deployment-images.py"
        images.write_text('''#!/usr/bin/python3
import json, os, sys
args = sys.argv[1:]
phase = "snapshot" if "--snapshot" in args else "validate"
with open(os.environ["MOCK_IMAGES_LOG"], "a") as stream:
    stream.write(json.dumps({"argv": args, "cwd": os.getcwd()}) + "\\n")
with open(os.environ["MOCK_EVENT_LOG"], "a") as stream:
    stream.write(json.dumps(phase) + "\\n")
if phase == "snapshot":
    print("{}")
    sys.exit(int(os.environ.get("MOCK_SNAPSHOT_RC", "0")))
print('{"status": "verified"}')
sys.exit(int(os.environ.get("MOCK_IMAGES_RC", "0")))
''')
        sudo = self.bin / "sudo"
        sudo.write_text('''#!/usr/bin/python3
import json, os, sys
args = sys.argv[1:]
mask = os.umask(0)
os.umask(mask)
with open(os.environ["MOCK_SUDO_LOG"], "a") as stream:
    stream.write(json.dumps({"argv": args, "cwd": os.getcwd(),
                             "umask": mask}) + "\\n")
if args == ["-n", "true"]:
    if (os.environ.get("MOCK_SUDO_EXPIRES_AFTER_GENERATE") == "1" and
            os.path.isfile(os.environ["MOCK_EVENT_LOG"]) and
            not os.path.exists(os.environ["MOCK_SUDO_RENEW_FILE"])):
        with open(os.environ["MOCK_EVENT_LOG"]) as stream:
            if "generate" in [json.loads(line) for line in stream]:
                sys.exit(1)
    sys.exit(int(os.environ.get("MOCK_SUDO_PREFLIGHT_RC", "0")))
if args == ["-v"]:
    status = int(os.environ.get("MOCK_SUDO_RENEW_RC", "0"))
    if status == 0:
        with open(os.environ["MOCK_SUDO_RENEW_FILE"], "w") as stream:
            stream.write("fixture renewed authorization\\n")
    sys.exit(status)
if (args[:3] == ["-n", "/usr/bin/python3", "-B"] and
        any(value.endswith("/prepare-massflash-package.py") for value in args)):
    sys.exit(int(os.environ.get("MOCK_PACKAGE_RC", "0")))
allowed = ("/flash.sh", "/l4t_initrd_flash.sh")
if args[:2] == ["-n", "env"] and any(
        value.endswith(allowed) for value in args):
    phase = ("flash" if "--flash-only" in args else
             "generate" if "--no-flash" in args else "direct")
    with open(os.environ["MOCK_EVENT_LOG"], "a") as stream:
        stream.write(json.dumps(phase) + "\\n")
    print("MOCK native phase: " + phase)
    variable = "MOCK_DEPLOY_RC" if phase == "flash" else "MOCK_GENERATE_RC"
    sys.exit(int(os.environ.get(variable, os.environ.get("MOCK_FLASH_RC", "0"))))
sys.exit(98)
''')
        sudo.chmod(0o755)
        for name in ("lsusb", "losetup", "mount", "umount", "truncate",
                     "dd", "tegrarcm_v2"):
            guard = self.bin / name
            guard.write_text('''#!/usr/bin/python3
import json, os, sys
with open(os.environ["MOCK_GUARD_LOG"], "a") as stream:
    stream.write(json.dumps(sys.argv) + "\\n")
sys.exit(98)
''')
            guard.chmod(0o755)

    def shell(self, body, *, setup=True, env=None, stdin=None):
        environment = self.environment | (env or {})
        return subprocess.run(
            ["/bin/bash", "--noprofile", "--norc", "-c",
             (SETUP if setup else "") + body],
            cwd=self.other, env=environment, input=stdin, text=True,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=15)

    def successful(self, body, **kwargs):
        result = self.shell(body, **kwargs)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result

    def terminal(self, body, data, env=None):
        """Give Bash a synthetic input TTY; it never reaches host devices."""
        master, slave = pty.openpty()
        process = subprocess.Popen(
            ["/bin/bash", "--noprofile", "--norc", "-c", SETUP + body],
            cwd=self.other, env=self.environment | (env or {}), stdin=slave,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        os.close(slave)
        try:
            os.write(master, data.encode())
            stdout, stderr = process.communicate(timeout=15)
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()
            os.close(master)
        return subprocess.CompletedProcess(process.args, process.returncode,
                                           stdout, stderr)

    def calls(self):
        return [json.loads(line) for line in self.sudo_log.read_text().splitlines()] \
            if self.sudo_log.exists() else []

    def flash_calls(self):
        return [call for call in self.calls() if any(
            value.endswith(("/flash.sh", "/l4t_initrd_flash.sh"))
            for value in call["argv"])]

    def package_calls(self):
        return [call for call in self.calls() if any(
            value.endswith("/prepare-massflash-package.py")
            for value in call["argv"])]

    def image_calls(self):
        return [json.loads(line) for line in self.images_log.read_text().splitlines()] \
            if self.images_log.exists() else []

    def events(self):
        return [json.loads(line) for line in self.events_log.read_text().splitlines()] \
            if self.events_log.exists() else []

    def no_backend(self):
        self.assertFalse(self.calls(), "Unexpected sudo invocation")
        self.assertFalse(self.guard_log.exists(), "Unexpected device/mount/loop operation")

    def recovery(self, target="edge-ai-nx-16g", usb="1-2", pid="7323"):
        return {"MOCK_RECOVERY": "\t".join((usb, target, pid))}

    def test_source_is_passive_and_independent_of_caller_directory(self):
        before = sorted(str(path.relative_to(self.sdk)) for path in self.sdk.rglob("*"))
        self.successful(r'''
before_pwd=$PWD
before_options=$(set +o)
before_traps=$(trap -p)
source "$SDK_ROOT/compulab-l4t.env" || exit $?
test "$PWD" = "$before_pwd" || exit 71
test "$(set +o)" = "$before_options" || exit 72
test "$(trap -p)" = "$before_traps" || exit 73
test "$L4T_ROOT" = "$SDK_ROOT" || exit 74
for fn in select_device select_target current_device select_bootloader \
          current_bootloader detect_device create_disk_image \
          deploy_bootloader deploy_bootloader_rootfs \
          prepare_massflash_boot prepare_massflash_boot_rootfs; do
    declare -F "$fn" >/dev/null || exit 75
done
''', setup=False)
        self.assertEqual(before, sorted(str(path.relative_to(self.sdk))
                                        for path in self.sdk.rglob("*")))
        self.no_backend()

    def test_source_preserves_strict_shell_options(self):
        self.successful(r'''
set -euo pipefail
before_options=$(set +o)
source "$SDK_ROOT/compulab-l4t.env"
test "$(set +o)" = "$before_options"
''', setup=False)
        self.no_backend()

    def test_repeated_source_preserves_selected_state(self):
        self.successful(r'''
select_device edge-ai-nano-4g
select_bootloader nvidia-logo
before=$PWD
source "$SDK_ROOT/compulab-l4t.env" || exit $?
test "$(current_device)" = edge-ai-nano-4g || exit 70
test "$(current_bootloader)" = nvidia-logo || exit 71
test "$PWD" = "$before" || exit 72
''')
        self.no_backend()

    def test_direct_execution_refuses_to_run_operations(self):
        result = subprocess.run(
            ["/bin/bash", str(self.sdk / "compulab-l4t.env")],
            cwd=self.other, env=self.environment, text=True,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=15)
        self.assertNotEqual(result.returncode, 0)
        self.no_backend()

    def test_defaults(self):
        self.successful(r'''
test "$(current_device)" = auto || exit 70
test "$(current_bootloader)" = clab-logo || exit 71
test "$EDGE_AI_EARLY_TTY1" = 0 || exit 72
test "$LOOP_DEV_SIZE_GB" = 32 || exit 73
''')
        self.no_backend()

    def test_canonical_and_legacy_board_selection(self):
        mapping = dict(zip(TARGETS, TARGETS)) | {
            "NX16": TARGETS[0], "NX8": TARGETS[1],
            "NA8": TARGETS[2], "NA4": TARGETS[3],
            "auto": "auto", "device": "auto",
        }
        for value, expected in mapping.items():
            with self.subTest(value=value):
                result = self.successful(r'''
select_device "$CHOICE" || exit $?
current_device
test "$EDGE_AI" = "$EXPECTED" || exit 70
''', env={"CHOICE": value, "EXPECTED": expected})
                self.assertEqual(result.stdout.strip().splitlines()[-1], expected)
        self.successful('select_target edge-ai-nano-8g; '
                        'test "$(current_device)" = edge-ai-nano-8g')
        self.no_backend()

    def test_logo_selection_and_legacy_variable(self):
        for value, expected in {
                "clab-logo": "clab-logo", "nvidia-logo": "nvidia-logo",
                "no-logo": "no-logo", "logo": "clab-logo", "nologo": "no-logo"}.items():
            with self.subTest(value=value):
                self.successful(r'''
select_bootloader "$CHOICE" || exit $?
test "$(current_bootloader)" = "$EXPECTED" || exit 70
test "$EDGE_AI_UEFI_LOGO_STYLE" = "$EXPECTED" || exit 71
''', env={"CHOICE": value, "EXPECTED": expected})
        self.successful('bl_type=nologo select_bootloader; '
                        'test "$(current_bootloader)" = no-logo')
        self.no_backend()

    def test_invalid_selection_preserves_previous_value(self):
        for function, valid, invalid, current in (
                ("select_device", "edge-ai-nx-8g", "../../bad", "current_device"),
                ("select_device", "edge-ai-nx-8g", "bad;touch injected", "current_device"),
                ("select_bootloader", "nvidia-logo", "wrong", "current_bootloader")):
            with self.subTest(function=function, invalid=invalid):
                self.successful(r'''
"$FUNCTION" "$VALID" || exit $?
"$FUNCTION" "$INVALID" && exit 70
test "$?" = 2 || exit 71
test "$("$CURRENT")" = "$VALID" || exit 72
''', env={"FUNCTION": function, "VALID": valid, "INVALID": invalid,
          "CURRENT": current})
        self.assertFalse((self.other / "injected").exists())
        self.no_backend()

    def test_noninteractive_empty_selection_refuses_without_hanging(self):
        for function in ("select_device", "select_bootloader"):
            with self.subTest(function=function):
                result = self.shell('"$FUNCTION"', env={"FUNCTION": function}, stdin="")
                self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.no_backend()

    def test_interactive_selection_works_with_a_synthetic_terminal(self):
        for function, number, current, expected in (
                ("select_device", "4", "current_device", "edge-ai-nano-4g"),
                ("select_bootloader", "2", "current_bootloader", "nvidia-logo")):
            with self.subTest(function=function):
                result = self.terminal('"$FUNCTION" || exit $?; "$CURRENT"',
                                       number + "\n",
                                       {"FUNCTION": function, "CURRENT": current})
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertEqual(result.stdout.strip().splitlines()[-1], expected)
        self.no_backend()

    def test_offline_image_dry_run_supports_each_explicit_board(self):
        for target in TARGETS:
            with self.subTest(target=target):
                result = self.successful('select_device "$TARGET"; '
                                         'create_disk_image --dry-run', env={"TARGET": target})
                self.assertIn(target, result.stdout)
        self.no_backend()

    def test_offline_image_auto_without_device_refuses(self):
        result = self.shell('create_disk_image --yes')
        self.assertNotEqual(result.returncode, 0)
        self.no_backend()

    def test_image_guard_calls_only_the_owned_image_engine(self):
        self.successful(r'''
select_device edge-ai-nano-4g
select_bootloader no-logo
_compulab_create_disk_image() {
    test "$EDGE_AI" = edge-ai-nano-4g || return 70
    test "$EDGE_AI_UEFI_LOGO_STYLE" = no-logo || return 71
    L4T_IMAGE="$SDK_ROOT/fixture-result.img"
    printf 'IMAGE_ENGINE\n'
}
create_disk_image --yes || exit $?
test "$L4T_IMAGE" = "$SDK_ROOT/fixture-result.img" || exit 72
''')
        self.assertFalse((self.sdk / "fixture-result.img").exists())
        self.no_backend()

    def test_image_engine_failure_propagates_without_a_real_loop(self):
        result = self.shell('select_device NX8; '
                            '_compulab_create_disk_image() { return 39; }; '
                            'create_disk_image --yes')
        self.assertEqual(result.returncode, 39, result.stdout + result.stderr)
        self.no_backend()

    def test_legacy_size_cannot_override_the_selected_image_size(self):
        result = self.successful(r'''
select_device NX16
size=64
LOOP_DEV_SIZE_GB=32
_compulab_create_disk_image() {
    test "$size" = 32 || return 70
    test "$LOOP_DEV_SIZE_GB" = 32 || return 71
}
create_disk_image --yes || exit $?
test "$size" = 64 || exit 72
''')
        self.assertIn("disk=32GiB APP=24GiB", result.stdout)
        self.no_backend()

    def test_invalid_image_outputs_and_sizes_refuse_before_backend(self):
        existing = self.root / "existing.img"
        existing.write_text("KEEP")
        symbolic = self.root / "symlink.img"
        symbolic.symlink_to(existing)
        for variable, value in (
                ("L4T_IMAGE", str(existing)), ("L4T_IMAGE", str(symbolic)),
                ("L4T_IMAGE", "/dev/sda.img"), ("L4T_IMAGE", "/proc/new.img"),
                ("L4T_IMAGE", "/sys/new.img"), ("L4T_IMAGE", "relative.img"),
                ("LOOP_DEV_SIZE_GB", "08"), ("LOOP_DEV_SIZE_GB", "1"),
                ("LOOP_DEV_SIZE_GB", "2049")):
            with self.subTest(variable=variable, value=value):
                result = self.shell('select_device NX16; create_disk_image --dry-run',
                                    env={variable: value})
                self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertEqual(existing.read_text(), "KEEP")
        self.no_backend()

    def test_real_shared_preflight_rejects_wrong_modes_and_sdk_root(self):
        # Restore the production preflight after SETUP's fixture override.
        # Stub only its final metadata-only profile validator, not its guards.
        body = r'''
source "$SDK_ROOT/compulab-l4t.env" || exit $?
_compulab_image_check_sdk() { return 0; }
_compulab_recovery_devices() { printf '%s\n' "$MOCK_RECOVERY"; }
deploy_bootloader_rootfs --dry-run
'''
        for values in ({"EDGE_AI_EARLY_TTY1": "2"}, {"ROOTFS_AB": "1"},
                       {"ROOTFS_ENC": "1"}):
            with self.subTest(values=values):
                result = self.shell(body, env=self.recovery() | values)
                self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        result = self.shell(body.replace('deploy_bootloader_rootfs --dry-run',
                                        'L4T_ROOT=/tmp; deploy_bootloader_rootfs --dry-run'),
                            env=self.recovery())
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.no_backend()

    def test_online_dry_run_never_calls_sudo(self):
        for function in ("deploy_bootloader_rootfs", "deploy_bootloader"):
            with self.subTest(function=function):
                result = self.successful('"$FUNCTION" --dry-run', env=self.recovery() |
                                         {"FUNCTION": function})
                self.assertIn("edge-ai-nx-16g", result.stdout)
                self.assertIn("flash", result.stdout)
        self.no_backend()

    def test_online_no_flash_dry_run_prints_native_flag_without_sudo(self):
        before = sorted(str(path.relative_to(self.sdk))
                        for path in self.sdk.rglob("*"))
        for function in ("deploy_bootloader_rootfs", "deploy_bootloader"):
            with self.subTest(function=function):
                result = self.successful('"$FUNCTION" --no-flash --dry-run',
                                         env=self.recovery() |
                                         {"FUNCTION": function})
                self.assertIn("--no-flash", result.stdout)
                self.assertEqual(before, sorted(str(path.relative_to(self.sdk))
                                               for path in self.sdk.rglob("*")))
        self.no_backend()

    def test_online_no_flash_yes_forwards_flag_before_target(self):
        for function in ("deploy_bootloader_rootfs", "deploy_bootloader"):
            with self.subTest(function=function):
                self.sudo_log.unlink(missing_ok=True)
                self.successful('"$FUNCTION" --yes --no-flash',
                                env=self.recovery() | {"FUNCTION": function})
                calls = self.flash_calls()
                self.assertEqual(len(calls), 1)
                argv = calls[0]["argv"]
                self.assertEqual(argv.count("--no-flash"), 1)
                self.assertLess(argv.index("--no-flash"), len(argv) - 2)
                self.assertEqual(argv[-2:], ["edge-ai-nx-16g", "external"])
                self.assertIn("--usb-instance", argv)
                self.assertNotIn("--flash-only", argv)
                self.assertNotIn("--direct", argv)
                self.assertEqual(calls[0]["cwd"], str(self.sdk))
                self.assertEqual(self.package_calls(), [])
        self.assertFalse(self.guard_log.exists())

    def test_online_default_does_not_inherit_legacy_no_flash_options(self):
        for function in ("deploy_bootloader_rootfs", "deploy_bootloader"):
            with self.subTest(function=function):
                self.sudo_log.unlink(missing_ok=True)
                self.successful('"$FUNCTION" --yes', env=self.recovery() | {
                    "FUNCTION": function,
                    "massflash_mode_opt": "--no-flash --massflash 5",
                })
                calls = self.flash_calls()
                expected = 2 if function == "deploy_bootloader_rootfs" else 1
                self.assertEqual(len(calls), expected)
                argv = calls[-1]["argv"]
                self.assertNotIn("--no-flash", argv)
                for call in calls:
                    self.assertNotIn("--massflash", call["argv"])
                if function == "deploy_bootloader_rootfs":
                    self.assertIn("--no-flash", calls[0]["argv"])
                    self.assertIn("--flash-only", argv)
        self.assertFalse(self.guard_log.exists())

    def test_online_no_flash_prompt_describes_preparation_not_overwrite(self):
        for function in ("deploy_bootloader_rootfs", "deploy_bootloader"):
            with self.subTest(function=function):
                result = self.terminal('"$FUNCTION" --no-flash', "NO\n",
                                       self.recovery() | {"FUNCTION": function})
                self.assertNotEqual(result.returncode, 0)
                prompt = result.stderr.lower()
                self.assertIn("prepare", prompt)
                self.assertIn("qspi", prompt)
                self.assertIn("nvme", prompt)
                self.assertRegex(prompt, r"(no|not|without).*flash")
                self.assertNotIn("overwrite", prompt)
                self.no_backend()
                result = self.terminal('"$FUNCTION"', "NO\n",
                                       self.recovery() | {"FUNCTION": function})
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("overwrite", result.stderr.lower())
                self.no_backend()

    def test_online_no_flash_still_requires_one_recovery_device(self):
        for function in ("deploy_bootloader_rootfs", "deploy_bootloader"):
            for records in ("", "1-2\tedge-ai-nx-16g\t7323\n"
                                 "1-3\tedge-ai-nx-8g\t7423"):
                with self.subTest(function=function, records=records):
                    result = self.shell(
                        'select_device NX16; "$FUNCTION" --no-flash --yes',
                        env={"FUNCTION": function, "MOCK_RECOVERY": records})
                    self.assertEqual(result.returncode, 2,
                                     result.stdout + result.stderr)
                    self.no_backend()

    def test_online_no_flash_preserves_state_and_native_failure(self):
        for function in ("deploy_bootloader_rootfs", "deploy_bootloader"):
            with self.subTest(function=function):
                self.sudo_log.unlink(missing_ok=True)
                result = self.successful(r'''
set -euo pipefail
select_device NX16
select_bootloader no-logo
EDGE_AI_EARLY_TTY1=1
before_pwd=$PWD
before_options=$(set +o)
before_identity=$(declare -p BOARDID BOARDSKU FAB BOARDREV CHIPREV CHIP_SKU \
    chip_SKU RAMCODE RAMCODE_ID SKIP_EEPROM_CHECK FUSELEVEL)
if "$FUNCTION" --no-flash --yes; then exit 70; else rc=$?; fi
test "$rc" = 41
test "$PWD" = "$before_pwd"
test "$(set +o)" = "$before_options"
test "$(declare -p BOARDID BOARDSKU FAB BOARDREV CHIPREV CHIP_SKU \
    chip_SKU RAMCODE RAMCODE_ID SKIP_EEPROM_CHECK FUSELEVEL)" = "$before_identity"
test "$(current_device)" = edge-ai-nx-16g
test "$(current_bootloader)" = no-logo
test "$EDGE_AI_EARLY_TTY1" = 1
''', env=self.recovery() |
                    {name: "stale" for name in IDENTITY_FIELDS} |
                    {"FUNCTION": function, "MOCK_FLASH_RC": "41"})
                self.assertIn("--no-flash", result.stdout)
                argv = self.flash_calls()[0]["argv"]
                self.assertIn("--no-flash", argv)
                self.assertIn("EDGE_AI_UEFI_LOGO_STYLE=no-logo", argv)
                self.assertIn("EDGE_AI_EARLY_TTY1=1", argv)
                self.assertEqual(self.package_calls(), [])
        self.assertFalse(self.guard_log.exists())

    def test_online_operation_requires_confirmation_without_yes(self):
        for function in ("deploy_bootloader_rootfs", "deploy_bootloader"):
            with self.subTest(function=function):
                result = self.shell('"$FUNCTION"', env=self.recovery() |
                                    {"FUNCTION": function}, stdin="")
                self.assertNotEqual(result.returncode, 0)
        self.no_backend()

    def test_interactive_decline_never_reaches_sudo(self):
        result = self.terminal('deploy_bootloader_rootfs', "NO\n", self.recovery())
        self.assertNotEqual(result.returncode, 0)
        self.no_backend()

    def test_detector_is_read_only_for_all_four_supported_modules(self):
        for target, pid in zip(TARGETS, ("7323", "7423", "7523", "7623")):
            with self.subTest(target=target):
                result = self.successful('detect_device', env=self.recovery(target, pid=pid))
                self.assertEqual(result.stdout.strip(), target)
        self.no_backend()

    def test_malformed_usb_records_are_rejected(self):
        for record in ("../1-2\tedge-ai-nx-16g\t7323",
                       "1-2;bad\tedge-ai-nx-16g\t7323",
                       "1-2\tedge-ai-nx-16g\tzzzz",
                       "1-2\tedge-ai-nx-16g\t7323\textra"):
            with self.subTest(record=record):
                result = self.shell('deploy_bootloader_rootfs --yes',
                                    env={"MOCK_RECOVERY": record})
                self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.no_backend()

    def test_online_full_flash_uses_target_nvme_qspi_and_clears_identity(self):
        old = {name: "stale" for name in IDENTITY_FIELDS}
        self.successful(r'''
select_bootloader nvidia-logo
EDGE_AI_EARLY_TTY1=1
before=$PWD
deploy_bootloader_rootfs --yes || exit $?
test "$PWD" = "$before" || exit 70
''', env=self.recovery() | old)
        calls = self.flash_calls()
        self.assertEqual(len(calls), 2)
        argv = calls[0]["argv"]
        self.assertEqual(calls[0]["cwd"], str(self.sdk))
        self.assertEqual(argv[:2], ["-n", "env"])
        for name in IDENTITY_FIELDS:
            self.assertTrue(any(argv[index:index + 2] == ["-u", name]
                                for index in range(len(argv))), name)
            self.assertNotIn(name + "=stale", argv)
        self.assertIn("EDGE_AI_UEFI_LOGO_STYLE=nvidia-logo", argv)
        self.assertIn("EDGE_AI_EARLY_TTY1=1", argv)
        self.assertIn("BootOrderNvme.dtbo", " ".join(argv))
        self.assertIn("nvme0n1p1", argv)
        self.assertIn("tools/kernel_flash/flash_l4t_t234_nvme.xml", " ".join(argv))
        self.assertIn("bootloader/generic/cfg/flash_t234_qspi.xml", " ".join(argv))
        self.assertIn("usb0", argv)
        self.assertIn("--usb-instance", argv)
        self.assertIn("1-2", argv)
        self.assertIn("--no-flash", argv)
        self.assertNotIn("--flash-only", argv)
        self.assertNotIn("--direct", argv)
        self.assertNotIn("--external-only", argv)
        self.assertEqual(argv[-2:], ["edge-ai-nx-16g", "external"])
        runtime = calls[1]["argv"]
        self.assertEqual(calls[1]["cwd"], str(self.sdk))
        self.assertIn("--flash-only", runtime)
        self.assertNotIn("--no-flash", runtime)
        self.assertNotIn("--external-device", runtime)
        self.assertNotIn("--direct", runtime)
        self.assertNotIn("--external-only", runtime)
        self.assertNotIn("-p", runtime)
        self.assertEqual(runtime[runtime.index("--usb-instance") + 1], "1-2")
        self.assertEqual(runtime[runtime.index("--network") + 1], "usb0")
        self.assertEqual(runtime[-2:], ["edge-ai-nx-16g", "external"])
        for name in IDENTITY_FIELDS:
            self.assertTrue(any(runtime[index:index + 2] == ["-u", name]
                                for index in range(len(runtime))), name)
            self.assertNotIn(name + "=stale", runtime)
        self.assertIn("EDGE_AI_UEFI_LOGO_STYLE=nvidia-logo", runtime)
        self.assertIn("EDGE_AI_EARLY_TTY1=1", runtime)
        self.assertFalse(self.guard_log.exists())

    def test_bootloader_only_uses_native_qspi_without_system_image(self):
        self.successful('deploy_bootloader --yes', env=self.recovery())
        calls = self.flash_calls()
        self.assertEqual(len(calls), 1)
        argv = calls[0]["argv"]
        self.assertIn("--no-systemimg", argv)
        self.assertIn("bootloader/generic/cfg/flash_t234_qspi.xml", " ".join(argv))
        self.assertTrue(any(value.endswith("/flash.sh") for value in argv))
        self.assertNotIn("--external-device", argv)
        self.assertNotIn("--direct", argv)
        self.assertEqual(argv[-2:], ["edge-ai-nx-16g", "external"])

    def test_full_deployment_runs_generate_validate_then_explicit_flash(self):
        result = self.successful('deploy_bootloader_rootfs --yes',
                                 env=self.recovery())
        self.assertEqual(self.events(),
                         ["snapshot", "generate", "validate", "flash"])
        self.assertIn("[1/2]", result.stdout)
        self.assertIn("[2/2]", result.stdout)
        calls = self.image_calls()
        self.assertEqual(len(calls), 2)
        self.assertIn("--snapshot", calls[0]["argv"])
        validation = calls[1]["argv"]
        for option, value in (("--sdk-root", str(self.sdk)),
                              ("--target", "edge-ai-nx-16g"),
                              ("--external-device", "nvme0n1p1"),
                              ("--logo", "clab-logo")):
            self.assertEqual(validation[validation.index(option) + 1], value)
        self.assertIn("--before-json", validation)
        self.assertEqual(json.loads(validation[
            validation.index("--before-json") + 1]), {})

    def test_full_deployment_no_flash_skips_runtime_and_post_validation(self):
        self.successful('deploy_bootloader_rootfs --no-flash --yes',
                        env=self.recovery())
        self.assertEqual(len(self.flash_calls()), 1)
        self.assertNotIn("flash", self.events())
        self.assertNotIn("validate", self.events())

    def test_full_deployment_generation_failure_never_flashes(self):
        result = self.shell('deploy_bootloader_rootfs --yes',
                            env=self.recovery() | {"MOCK_GENERATE_RC": "41"})
        self.assertEqual(result.returncode, 41, result.stdout + result.stderr)
        self.assertEqual(self.events(), ["snapshot", "generate"])
        self.assertEqual(len(self.flash_calls()), 1)
        self.assertNotIn("--flash-only", self.flash_calls()[0]["argv"])

    def test_full_deployment_invalid_generated_images_never_flash(self):
        result = self.shell('deploy_bootloader_rootfs --yes',
                            env=self.recovery() | {"MOCK_IMAGES_RC": "46"})
        self.assertEqual(result.returncode, 46, result.stdout + result.stderr)
        self.assertEqual(self.events(), ["snapshot", "generate", "validate"])
        self.assertEqual(len(self.flash_calls()), 1)

    def test_full_deployment_snapshot_failure_never_generates(self):
        result = self.shell('deploy_bootloader_rootfs --yes',
                            env=self.recovery() | {"MOCK_SNAPSHOT_RC": "45"})
        self.assertEqual(result.returncode, 45, result.stdout + result.stderr)
        self.assertEqual(self.events(), ["snapshot"])
        self.assertEqual(self.flash_calls(), [])

    def test_full_deployment_runtime_failure_is_not_reported_as_success(self):
        result = self.shell('deploy_bootloader_rootfs --yes',
                            env=self.recovery() | {"MOCK_DEPLOY_RC": "49"})
        self.assertEqual(result.returncode, 49, result.stdout + result.stderr)
        self.assertEqual(self.events(),
                         ["snapshot", "generate", "validate", "flash"])
        self.assertEqual(len(self.flash_calls()), 2)

    def test_full_deployment_rechecks_usb_after_generation(self):
        for replacement in ("", "1-3\tedge-ai-nx-16g\t7323",
                            "1-2\tedge-ai-nx-8g\t7423",
                            "1-2\tedge-ai-nx-16g\t7323\n"
                            "1-3\tedge-ai-nx-8g\t7423"):
            with self.subTest(replacement=replacement):
                self.sudo_log.unlink(missing_ok=True)
                self.images_log.unlink(missing_ok=True)
                self.events_log.unlink(missing_ok=True)
                result = self.shell(r'''
_compulab_recovery_devices() {
    if [ -e "$MOCK_EVENT_LOG" ] && \
       /usr/bin/grep -q '"generate"' "$MOCK_EVENT_LOG"; then
        [ -z "$REPLACEMENT" ] || printf '%s\n' "$REPLACEMENT"
    else
        printf '%s\n' "$MOCK_RECOVERY"
    fi
}
deploy_bootloader_rootfs --yes
''', env=self.recovery() | {"REPLACEMENT": replacement})
                self.assertNotEqual(result.returncode, 0,
                                    result.stdout + result.stderr)
                self.assertEqual(len(self.flash_calls()), 1)
                self.assertNotIn("flash", self.events())

    def test_full_deployment_tolerates_brief_recovery_reenumeration(self):
        self.successful(r'''
_compulab_recovery_devices() {
    if [ -e "$MOCK_EVENT_LOG" ] && \
       /usr/bin/grep -q '"generate"' "$MOCK_EVENT_LOG" && \
       [ ! -e "$SDK_ROOT/recovery-gap-seen" ]; then
        : > "$SDK_ROOT/recovery-gap-seen"
        return 0
    fi
    printf '%s\n' "$MOCK_RECOVERY"
}
deploy_bootloader_rootfs --yes
''', env=self.recovery())
        self.assertEqual(len(self.flash_calls()), 2)
        self.assertTrue((self.sdk / "recovery-gap-seen").exists())

    def test_full_deployment_missing_image_guard_refuses_before_sudo(self):
        (self.sdk / "compulab/tools/check-deployment-images.py").unlink()
        result = self.shell('deploy_bootloader_rootfs --yes',
                            env=self.recovery())
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.flash_calls(), [])
        self.no_backend()

    def test_full_deployment_dry_run_prints_both_phases_without_backend(self):
        result = self.successful('deploy_bootloader_rootfs --dry-run',
                                 env=self.recovery())
        self.assertIn("--no-flash", result.stdout)
        self.assertIn("--flash-only", result.stdout)
        self.assertEqual(self.image_calls(), [])
        self.assertFalse(list(self.temp.iterdir()))
        self.no_backend()

    def test_full_deployment_keeps_private_local_logs_not_sdk_files(self):
        before = sorted(str(path.relative_to(self.sdk))
                        for path in self.sdk.rglob("*"))
        result = self.successful('deploy_bootloader_rootfs --yes',
                                 env=self.recovery())
        self.assertEqual(before, sorted(str(path.relative_to(self.sdk))
                                        for path in self.sdk.rglob("*")))
        logs = list(self.temp.rglob("*.log"))
        self.assertTrue(logs, result.stdout + result.stderr)
        contents = "\n".join(path.read_text() for path in logs)
        self.assertIn("MOCK native phase: generate", contents)
        self.assertIn("MOCK native phase: flash", contents)
        for path in logs:
            self.assertEqual(path.stat().st_mode & 0o077, 0)
            self.assertEqual(path.parent.stat().st_mode & 0o077, 0)
        self.assertIn(str(self.temp), result.stdout + result.stderr)

    def test_full_deployment_log_failure_never_launches_flash(self):
        result = self.shell(r'''
tee() { /usr/bin/tee "$@"; return 67; }
deploy_bootloader_rootfs --yes
''', env=self.recovery())
        self.assertNotEqual(result.returncode, 0,
                            result.stdout + result.stderr)
        self.assertEqual(len(self.flash_calls()), 1)
        self.assertNotIn("flash", self.events())

    def test_full_deployment_strict_shell_state_is_preserved(self):
        self.successful(r'''
set -euo pipefail
select_device NX16
select_bootloader no-logo
EDGE_AI_EARLY_TTY1=1
before_pwd=$PWD
before_options=$(set +o)
before_umask=$(umask)
before_identity=$(declare -p BOARDID BOARDSKU FAB BOARDREV CHIPREV CHIP_SKU \
    chip_SKU RAMCODE RAMCODE_ID SKIP_EEPROM_CHECK FUSELEVEL)
deploy_bootloader_rootfs --yes
test "$PWD" = "$before_pwd"
test "$(set +o)" = "$before_options"
test "$(umask)" = "$before_umask"
test "$(declare -p BOARDID BOARDSKU FAB BOARDREV CHIPREV CHIP_SKU \
    chip_SKU RAMCODE RAMCODE_ID SKIP_EEPROM_CHECK FUSELEVEL)" = "$before_identity"
test "$(current_device)" = edge-ai-nx-16g
test "$(current_bootloader)" = no-logo
test "$EDGE_AI_EARLY_TTY1" = 1
''', env=self.recovery() |
            {name: "stale" for name in IDENTITY_FIELDS})
        self.assertEqual(len(self.flash_calls()), 2)

    def test_full_deployment_native_umask_is_not_restricted_for_logging(self):
        self.successful(r'''
umask 022
deploy_bootloader_rootfs --yes
test "$(umask)" = 0022
''', env=self.recovery())
        calls = self.flash_calls()
        self.assertEqual(len(calls), 2)
        self.assertEqual([call["umask"] for call in calls], [0o022, 0o022])
        logs = list(self.temp.rglob("*.log"))
        self.assertTrue(logs)
        for path in logs:
            self.assertEqual(path.stat().st_mode & 0o077, 0)

    def test_full_deployment_noninteractive_expired_sudo_never_flashes(self):
        result = self.shell('deploy_bootloader_rootfs --yes',
                            env=self.recovery() |
                            {"MOCK_SUDO_EXPIRES_AFTER_GENERATE": "1"})
        self.assertNotEqual(result.returncode, 0,
                            result.stdout + result.stderr)
        self.assertIn("sudo authorization expired", result.stderr.lower())
        self.assertIn("flash not started", result.stderr.lower())
        self.assertNotIn("[2/2] Start", result.stdout)
        self.assertEqual(self.events(), ["snapshot", "generate", "validate"])
        self.assertEqual(len(self.flash_calls()), 1)
        self.assertFalse(any(call["argv"] == ["-v"] for call in self.calls()))

    def test_full_deployment_interactive_sudo_renewal_proceeds_to_flash(self):
        result = self.terminal('deploy_bootloader_rootfs --yes', "",
                               self.recovery() |
                               {"MOCK_SUDO_EXPIRES_AFTER_GENERATE": "1"})
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("sudo authorization expired", result.stderr.lower())
        self.assertIn("[2/2]", result.stdout)
        self.assertEqual(self.events(),
                         ["snapshot", "generate", "validate", "flash"])
        self.assertEqual(len(self.flash_calls()), 2)
        self.assertEqual(sum(call["argv"] == ["-v"] for call in self.calls()), 1)

    def test_full_deployment_failed_sudo_renewal_never_flashes(self):
        result = self.terminal('deploy_bootloader_rootfs --yes', "",
                               self.recovery() | {
                                   "MOCK_SUDO_EXPIRES_AFTER_GENERATE": "1",
                                   "MOCK_SUDO_RENEW_RC": "54",
                               })
        self.assertEqual(result.returncode, 54, result.stdout + result.stderr)
        self.assertEqual(self.events(), ["snapshot", "generate", "validate"])
        self.assertEqual(len(self.flash_calls()), 1)
        self.assertNotIn("[2/2] Start", result.stdout)

    def test_full_deployment_rechecks_recovery_after_sudo_renewal(self):
        result = self.terminal(r'''
_compulab_recovery_devices() {
    if [ -e "$MOCK_SUDO_RENEW_FILE" ]; then
        printf '1-3\tedge-ai-nx-16g\t7323\n'
    else
        printf '%s\n' "$MOCK_RECOVERY"
    fi
}
deploy_bootloader_rootfs --yes
''', "", self.recovery() | {"MOCK_SUDO_EXPIRES_AFTER_GENERATE": "1"})
        self.assertNotEqual(result.returncode, 0,
                            result.stdout + result.stderr)
        self.assertEqual(len(self.flash_calls()), 1)
        self.assertTrue(any(call["argv"] == ["-v"] for call in self.calls()))
        self.assertNotIn("flash", self.events())

    def test_full_deployment_no_flash_does_not_request_sudo_renewal(self):
        self.successful('deploy_bootloader_rootfs --no-flash --yes',
                        env=self.recovery() |
                        {"MOCK_SUDO_EXPIRES_AFTER_GENERATE": "1"})
        self.assertEqual(len(self.flash_calls()), 1)
        self.assertNotIn("flash", self.events())
        self.assertFalse(any(call["argv"] == ["-v"] for call in self.calls()))

    def test_online_rejects_no_multiple_unsupported_or_mismatched_devices(self):
        cases = (
            "", "1-2\tunsupported\t7023",
            "1-2\tedge-ai-nx-16g\t7323\n1-3\tedge-ai-nx-8g\t7423",
            "1-2\tedge-ai-nx-16g\t7323\n1-3\tunsupported\t7023",
        )
        for records in cases:
            with self.subTest(records=records):
                result = self.shell('deploy_bootloader_rootfs --yes',
                                    env={"MOCK_RECOVERY": records})
                self.assertNotEqual(result.returncode, 0)
                self.no_backend()
        result = self.shell('select_device edge-ai-nx-8g; '
                            'deploy_bootloader_rootfs --yes', env=self.recovery())
        self.assertNotEqual(result.returncode, 0)
        self.no_backend()

    def test_online_native_failure_and_sdk_validation_failure_propagate(self):
        result = self.shell('deploy_bootloader_rootfs --yes',
                            env=self.recovery() | {"MOCK_FLASH_RC": "41"})
        self.assertEqual(result.returncode, 41, result.stdout + result.stderr)
        self.assertEqual(len(self.flash_calls()), 1)
        self.sudo_log.unlink()
        result = self.shell('deploy_bootloader_rootfs --yes',
                            env=self.recovery() | {"MOCK_CHECK_RC": "43"})
        self.assertNotEqual(result.returncode, 0)
        self.no_backend()

    def test_sudo_preflight_failure_does_not_reach_flash(self):
        result = self.shell('deploy_bootloader_rootfs --yes', env=self.recovery() |
                            {"MOCK_SUDO_PREFLIGHT_RC": "1"})
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.flash_calls(), [])
        self.assertFalse(self.guard_log.exists())

    def test_device_disappearing_after_sudo_preflight_refuses_flash(self):
        result = self.shell(r'''
_compulab_recovery_devices() {
    if [ -e "$SDK_ROOT/device-checked" ]; then return 0; fi
    : > "$SDK_ROOT/device-checked"
    printf '%s\n' "$MOCK_RECOVERY"
}
deploy_bootloader_rootfs --yes
''', env=self.recovery())
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.flash_calls(), [])
        self.assertFalse(self.guard_log.exists())

    def test_unknown_and_injected_operation_arguments_are_rejected(self):
        for function in ("deploy_bootloader", "deploy_bootloader_rootfs",
                         "create_disk_image", "prepare_massflash_boot",
                         "prepare_massflash_boot_rootfs"):
            for argument in ("--external-only", "--direct", "--yes;touch injected"):
                with self.subTest(function=function, argument=argument):
                    result = self.shell('"$FUNCTION" "$ARGUMENT"',
                                        env=self.recovery() | {"FUNCTION": function,
                                                               "ARGUMENT": argument})
                    self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                    self.no_backend()
        self.assertFalse((self.other / "injected").exists())

    def test_massflash_dry_run_supports_each_offline_board_without_sudo(self):
        for target in TARGETS:
            for function in ("prepare_massflash_boot",
                             "prepare_massflash_boot_rootfs"):
                with self.subTest(target=target, function=function):
                    result = self.successful(
                        'select_device "$TARGET"; "$FUNCTION" --dry-run',
                        env={"TARGET": target, "FUNCTION": function})
                    self.assertIn(target, result.stdout)
                    self.assertIn("--no-flash", result.stdout)
                    self.assertIn("--massflash", result.stdout)
        self.no_backend()

    def test_massflash_offline_identity_uses_reviewed_defaults(self):
        identities = (
            (TARGETS[0], "0000", "TS4", "", "", "00:00:00:D3", ""),
            (TARGETS[1], "0001", "TS4", "", "", "00:00:00:D4", ""),
            (TARGETS[2], "0003", "300", "P.1", "0", "00:00:00:D5", ""),
            (TARGETS[3], "0004", "RC1", "B.4", "0", "00:00:00:D6", "4"),
        )
        for target, sku, fab, revision, chip_revision, chip_sku, ramcode in identities:
            with self.subTest(target=target):
                self.sudo_log.unlink(missing_ok=True)
                old = {name: "stale" for name in IDENTITY_FIELDS}
                self.successful(
                    'select_device "$TARGET"; prepare_massflash_boot --yes',
                    env=old | {"TARGET": target})
                calls = self.flash_calls()
                self.assertEqual(len(calls), 1)
                argv = calls[0]["argv"]
                expected = {
                    "BOARDID": "3767", "BOARDSKU": sku, "FAB": fab,
                    "BOARDREV": revision, "CHIPREV": chip_revision,
                    "CHIP_SKU": chip_sku, "RAMCODE": ramcode,
                    "RAMCODE_ID": ramcode, "FUSELEVEL": "fuselevel_production",
                }
                for key, value in expected.items():
                    self.assertIn(key + "=" + value, argv)
                for name in IDENTITY_FIELDS:
                    self.assertNotIn(name + "=stale", argv)
                self.assertNotIn("--usb-instance", argv)
                self.assertEqual(argv[-2:], [target, "external"])
        self.assertFalse(self.guard_log.exists())

    def test_massflash_boot_prepares_qspi_only_without_system_image(self):
        self.successful('select_device NX16; prepare_massflash_boot --yes')
        calls = self.flash_calls()
        self.assertEqual(len(calls), 1)
        argv = calls[0]["argv"]
        self.assertEqual(calls[0]["cwd"], str(self.sdk))
        self.assertIn("./tools/kernel_flash/l4t_initrd_flash.sh", argv)
        self.assertIn("--no-flash", argv)
        self.assertEqual(argv[argv.index("--massflash") + 1], "5")
        self.assertIn("--keep", argv)
        self.assertIn("--qspi-only", argv)
        internal = argv[argv.index("-p") + 1]
        self.assertIn("bootloader/generic/cfg/flash_t234_qspi.xml", internal)
        self.assertIn("--no-systemimg", internal)
        for forbidden in ("--external-device", "--direct", "--flash-only",
                          "--external-only", "--reuse"):
            self.assertNotIn(forbidden, argv)
        self.assertFalse(self.guard_log.exists())

    def test_massflash_full_prepares_qspi_and_nvme_without_flashing(self):
        self.successful(
            'select_device NX8; prepare_massflash_boot_rootfs --yes')
        argv = self.flash_calls()[0]["argv"]
        self.assertIn("--no-flash", argv)
        self.assertEqual(argv[argv.index("--massflash") + 1], "5")
        self.assertIn("--keep", argv)
        self.assertEqual(argv[argv.index("--external-device") + 1], "nvme0n1p1")
        self.assertIn("tools/kernel_flash/flash_l4t_t234_nvme.xml", argv)
        self.assertIn("bootloader/generic/cfg/flash_t234_qspi.xml",
                      argv[argv.index("-p") + 1])
        for forbidden in ("--qspi-only", "--direct", "--flash-only",
                          "--external-only", "--no-systemimg"):
            self.assertNotIn(forbidden, argv)
        self.assertEqual(argv[-2:], ["edge-ai-nx-8g", "external"])
        self.assertFalse(self.guard_log.exists())

    def test_massflash_online_uses_usb_but_not_offline_identity(self):
        old = {name: "stale" for name in IDENTITY_FIELDS}
        self.successful('prepare_massflash_boot_rootfs --yes',
                        env=self.recovery() | old)
        argv = self.flash_calls()[0]["argv"]
        self.assertEqual(argv[argv.index("--usb-instance") + 1], "1-2")
        self.assertIn("--no-flash", argv)
        for name in IDENTITY_FIELDS:
            self.assertTrue(any(argv[index:index + 2] == ["-u", name]
                                for index in range(len(argv))), name)
            self.assertFalse(any(value.startswith(name + "=") for value in argv),
                             name)
        self.assertEqual(argv[-2:], ["edge-ai-nx-16g", "external"])
        self.assertFalse(self.guard_log.exists())

    def test_massflash_selection_and_environment_do_not_leak(self):
        self.successful(r'''
set -euo pipefail
select_device NA4
select_bootloader no-logo
EDGE_AI_EARLY_TTY1=1
before_pwd=$PWD
before_options=$(set +o)
before_identity=$(declare -p BOARDID BOARDSKU FAB BOARDREV CHIPREV CHIP_SKU \
    chip_SKU RAMCODE RAMCODE_ID SKIP_EEPROM_CHECK FUSELEVEL)
massflash_mode_opt='--flash-only --direct /dev/sda'
prepare_massflash_boot --yes
test "$PWD" = "$before_pwd"
test "$(set +o)" = "$before_options"
test "$(declare -p BOARDID BOARDSKU FAB BOARDREV CHIPREV CHIP_SKU \
    chip_SKU RAMCODE RAMCODE_ID SKIP_EEPROM_CHECK FUSELEVEL)" = "$before_identity"
test "$(current_device)" = edge-ai-nano-4g
test "$(current_bootloader)" = no-logo
test "$EDGE_AI_EARLY_TTY1" = 1
test "$massflash_mode_opt" = '--flash-only --direct /dev/sda'
''', env={name: "stale" for name in IDENTITY_FIELDS})
        argv = self.flash_calls()[0]["argv"]
        self.assertIn("EDGE_AI_UEFI_LOGO_STYLE=no-logo", argv)
        self.assertIn("EDGE_AI_EARLY_TTY1=1", argv)
        self.assertNotIn("--flash-only", argv)
        self.assertNotIn("--direct", argv)
        self.assertNotIn("/dev/sda", argv)
        self.assertFalse(self.guard_log.exists())

    def test_massflash_custom_counts_are_validated_and_forwarded(self):
        for count in ("1", "8", "64"):
            with self.subTest(count=count):
                self.sudo_log.unlink(missing_ok=True)
                self.successful(
                    'select_device NX16; '
                    'prepare_massflash_boot --massflash "$COUNT" --yes',
                    env={"COUNT": count})
                argv = self.flash_calls()[0]["argv"]
                self.assertEqual(argv[argv.index("--massflash") + 1], count)
                package = self.package_calls()[0]["argv"]
                self.assertEqual(package[package.index("--massflash") + 1], count)
        self.assertFalse(self.guard_log.exists())

    def test_massflash_bad_counts_and_missing_value_refuse_before_sudo(self):
        for count in ("0", "65", "-1", "01", "1.5", "", "all",
                      "5;touch injected", "99999999999999999999999999"):
            with self.subTest(count=count):
                result = self.shell(
                    'select_device NX16; '
                    'prepare_massflash_boot --massflash "$COUNT" --yes',
                    env={"COUNT": count})
                self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                self.no_backend()
        result = self.shell('set -u; select_device NX16; '
                            'prepare_massflash_boot --massflash')
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertFalse((self.other / "injected").exists())
        self.no_backend()

    def test_massflash_auto_requires_a_recovery_device(self):
        for function in ("prepare_massflash_boot",
                         "prepare_massflash_boot_rootfs"):
            result = self.shell('"$FUNCTION" --yes', env={"FUNCTION": function})
            self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.no_backend()

    def test_massflash_explicit_board_does_not_bypass_bad_recovery(self):
        for records in (
                "1-2\tunsupported\t7023",
                "1-2\tedge-ai-nx-16g\t7323\n1-3\tedge-ai-nx-8g\t7423",
                "1-2\tedge-ai-nx-8g\t7423",
                "../1-2\tedge-ai-nx-16g\t7323"):
            with self.subTest(records=records):
                result = self.shell('select_device NX16; '
                                    'prepare_massflash_boot --yes',
                                    env={"MOCK_RECOVERY": records})
                self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                self.no_backend()

    def test_massflash_requires_confirmation_without_yes(self):
        for function in ("prepare_massflash_boot",
                         "prepare_massflash_boot_rootfs"):
            result = self.shell('select_device NX16; "$FUNCTION"',
                                env={"FUNCTION": function}, stdin="")
            self.assertNotEqual(result.returncode, 0)
        self.no_backend()

    def test_massflash_interactive_decline_does_not_call_sudo(self):
        result = self.terminal('select_device NX16; prepare_massflash_boot', "NO\n")
        self.assertNotEqual(result.returncode, 0)
        self.no_backend()

    def test_massflash_existing_outputs_are_never_overwritten(self):
        for target, kind in zip(TARGETS, ("directory", "tar", "symlink", "dangling")):
            with self.subTest(target=target, kind=kind):
                path = self.sdk / ("mfi_" + target)
                if kind == "directory":
                    path.mkdir()
                    (path / "KEEP").write_text("retained")
                elif kind == "tar":
                    path = path.with_name(path.name + ".tar.gz")
                    path.write_bytes(b"retained archive")
                else:
                    destination = self.root / ("target-" + kind)
                    if kind == "symlink":
                        destination.mkdir()
                        (destination / "KEEP").write_text("retained")
                    path.symlink_to(destination, target_is_directory=True)
                for function in ("prepare_massflash_boot",
                                 "prepare_massflash_boot_rootfs"):
                    result = self.shell(
                        'select_device "$TARGET"; "$FUNCTION" --yes',
                        env={"TARGET": target, "FUNCTION": function})
                    self.assertEqual(result.returncode, 2,
                                     result.stdout + result.stderr)
                    self.no_backend()
                if kind == "directory":
                    self.assertEqual((path / "KEEP").read_text(), "retained")
                elif kind == "tar":
                    self.assertEqual(path.read_bytes(), b"retained archive")
                else:
                    self.assertTrue(path.is_symlink())

    def test_massflash_native_failure_does_not_run_package_helper(self):
        result = self.shell('select_device NX16; prepare_massflash_boot --yes',
                            env={"MOCK_FLASH_RC": "41"})
        self.assertEqual(result.returncode, 41, result.stdout + result.stderr)
        self.assertEqual(len(self.flash_calls()), 1)
        self.assertEqual(self.package_calls(), [])
        self.assertFalse(self.guard_log.exists())

    def test_massflash_private_lock_does_not_restrict_native_umask(self):
        for function in ("prepare_massflash_boot",
                         "prepare_massflash_boot_rootfs"):
            with self.subTest(function=function):
                self.sudo_log.unlink(missing_ok=True)
                self.successful(r'''
umask 022
select_device NX16
"$FUNCTION" --yes
test "$(umask)" = 0022
''', env={"FUNCTION": function})
                calls = self.flash_calls()
                self.assertEqual(len(calls), 1)
                self.assertEqual(calls[0]["umask"], 0o022)
                lock = self.sdk / ".compulab-massflash.lock"
                self.assertEqual(lock.stat().st_mode & 0o777, 0o600)
        self.assertFalse(self.guard_log.exists())

    def test_massflash_package_failure_propagates(self):
        result = self.shell('select_device NX16; prepare_massflash_boot --yes',
                            env={"MOCK_PACKAGE_RC": "47"})
        self.assertEqual(result.returncode, 47, result.stdout + result.stderr)
        self.assertEqual(len(self.flash_calls()), 1)
        self.assertEqual(len(self.package_calls()), 1)
        self.assertFalse(self.guard_log.exists())

    def test_massflash_sdk_and_sudo_failures_prevent_preparation(self):
        result = self.shell('select_device NX16; prepare_massflash_boot --yes',
                            env={"MOCK_CHECK_RC": "43"})
        self.assertNotEqual(result.returncode, 0)
        self.no_backend()
        result = self.shell('select_device NX16; prepare_massflash_boot --yes',
                            env={"MOCK_SUDO_PREFLIGHT_RC": "1"})
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.flash_calls(), [])
        self.assertEqual(self.package_calls(), [])
        self.assertFalse(self.guard_log.exists())

    def test_massflash_package_helper_receives_selected_profile(self):
        for function, scope in (("prepare_massflash_boot", "bootloader"),
                                ("prepare_massflash_boot_rootfs", "full")):
            with self.subTest(function=function):
                self.sudo_log.unlink(missing_ok=True)
                self.successful('select_device NA4; select_bootloader nvidia-logo; '
                                'EDGE_AI_EARLY_TTY1=1; "$FUNCTION" --yes',
                                env={"FUNCTION": function})
                calls = self.package_calls()
                self.assertEqual(len(calls), 1)
                argv = calls[0]["argv"]
                self.assertEqual(argv[:3], ["-n", "/usr/bin/python3", "-B"])
                for option, value in (
                        ("--sdk-root", str(self.sdk)),
                        ("--target", "edge-ai-nano-4g"), ("--scope", scope),
                        ("--massflash", "5"), ("--logo", "nvidia-logo"),
                        ("--early-tty1", "1")):
                    self.assertEqual(argv[argv.index(option) + 1], value)
                self.assertEqual(calls[0]["cwd"], str(self.sdk))
        self.assertFalse(self.guard_log.exists())

    def test_massflash_missing_package_helper_refuses_before_sudo(self):
        (self.sdk / "compulab/tools/prepare-massflash-package.py").unlink()
        for function in ("prepare_massflash_boot",
                         "prepare_massflash_boot_rootfs"):
            result = self.shell('select_device NX16; "$FUNCTION" --yes',
                                env={"FUNCTION": function})
            self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
            self.no_backend()

    def test_massflash_dry_run_does_not_change_the_sdk_tree(self):
        def snapshot():
            return {
                str(path.relative_to(self.sdk)): (
                    path.lstat().st_mode,
                    path.read_bytes() if path.is_file() else None)
                for path in self.sdk.rglob("*")
            }
        before = snapshot()
        for function in ("prepare_massflash_boot",
                         "prepare_massflash_boot_rootfs"):
            self.successful('select_device NX16; "$FUNCTION" --dry-run',
                            env={"FUNCTION": function})
            self.assertEqual(snapshot(), before)
        self.no_backend()

    def test_massflash_offline_device_appearing_after_preflight_refuses(self):
        result = self.shell(r'''
select_device NX16
_compulab_recovery_devices() {
    if [ -e "$SDK_ROOT/device-checked" ]; then
        printf '1-2\tedge-ai-nx-16g\t7323\n'
    else
        : > "$SDK_ROOT/device-checked"
    fi
}
prepare_massflash_boot --yes
''')
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertEqual(self.flash_calls(), [])
        self.assertEqual(self.package_calls(), [])
        self.assertFalse(self.guard_log.exists())

    def test_massflash_concurrent_preparation_lock_refuses_native_call(self):
        result = self.shell(r'''
select_device NX16
exec {held_lock}> "$SDK_ROOT/.compulab-massflash.lock" || exit $?
flock -n "$held_lock" || exit $?
prepare_massflash_boot --yes
''')
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn("another massflash preparation", result.stderr)
        self.assertEqual(self.flash_calls(), [])
        self.assertEqual(self.package_calls(), [])
        self.assertFalse(self.guard_log.exists())

    def test_massflash_menu_lists_both_actions_without_running_them(self):
        result = self.terminal('select_device NX16; devshell', "9\n")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        output = result.stdout + result.stderr
        self.assertIn("prepare_massflash_boot", output)
        self.assertIn("prepare_massflash_boot_rootfs", output)
        self.no_backend()

    def test_massflash_menu_actions_accept_explicit_confirmation(self):
        for choice, scope in (("6", "bootloader"), ("7", "full")):
            with self.subTest(choice=choice):
                self.sudo_log.unlink(missing_ok=True)
                result = self.terminal('select_device NX16; devshell',
                                       choice + "\nYES\n9\n")
                self.assertEqual(result.returncode, 0,
                                 result.stdout + result.stderr)
                calls = self.flash_calls()
                self.assertEqual(len(calls), 1)
                self.assertIn("--no-flash", calls[0]["argv"])
                package = self.package_calls()
                self.assertEqual(len(package), 1)
                argv = package[0]["argv"]
                self.assertEqual(argv[argv.index("--scope") + 1], scope)
        self.assertFalse(self.guard_log.exists())


if __name__ == "__main__":
    unittest.main()
