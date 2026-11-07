#!/usr/bin/env python3
"""Host-only AOSP17 USB ownership and ConfigFS serial safety regression tests.

This validates only archived source packaging and the changed shell fragment.
It does NOT test USB hardware, ADB boot, a modern AIDL HAL, CTS/VTS or mondrian.
"""
from pathlib import Path
import os
import re
import subprocess
import tempfile
import unittest
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
USB_INIT = ROOT / "etc/init.qcom.usb.sh"


class UsbSourceGuardTest(unittest.TestCase):
    def evaluate_makefile(self, device, platform="taro", gadget_hal="true",
                          build_variant="userdebug", kernel="5.10"):
        with tempfile.TemporaryDirectory(prefix="pe-a17-usb-make-") as td:
            mk = Path(td) / "test.mk"
            mk.write_text(
                "include " + str(ROOT / "vendor_product.mk") + "\n"
                ".PHONY: all\nall:\n"
                "\t@echo USB_PKGS=$(PRODUCT_PACKAGES)\n"
                "\t@echo USB_PROPS=$(PRODUCT_PROPERTY_OVERRIDES)\n"
                "\t@echo USB_SYS_PROPS=$(PRODUCT_SYSTEM_PROPERTIES)\n"
                "\t@echo USB_NS=$(PRODUCT_SOONG_NAMESPACES)\n",
                encoding="utf-8",
            )
            run = subprocess.run(
                ["make", "--no-print-directory", "-f", str(mk), "all",
                 "TARGET_DEVICE=" + device,
                 "TARGET_BOARD_PLATFORM=" + platform,
                 "TARGET_KERNEL_VERSION=" + kernel,
                 "TARGET_BUILD_VARIANT=" + build_variant,
                 "PRODUCT_HAS_GADGET_HAL=" + gadget_hal,
                 "TARGET_USES_QMAA=false",
                 "TARGET_HAS_DIAG_ROUTER=true",
                 "TARGET_COPY_OUT_VENDOR=vendor"],
                cwd=ROOT, text=True, capture_output=True, check=False,
            )
            self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
            return run.stdout

    def test_mondrian_cannot_register_legacy_usb_hal_or_init_even_when_selected(self):
        for gadget_hal in ("true", "false"):
            for build_type in ("userdebug", "user"):
                with self.subTest(gadget=gadget_hal, build=build_type):
                    out = self.evaluate_makefile(
                        "mondrian", gadget_hal=gadget_hal, build_variant=build_type
                    )
                    self.assertIn("USB_PKGS=\n", out)
                    self.assertIn("USB_PROPS=\n", out)
                    self.assertIn("USB_NS=\n", out)
                    self.assertNotIn("android.hardware.usb@1.3-service-qti", out)
                    self.assertNotIn("android.hardware.usb.gadget@1.2-service-qti", out)
                    self.assertNotIn("init.qcom.usb", out)
                    self.assertNotIn("usb_compositions.conf", out)

    def test_historical_other_device_behavior_is_unchanged(self):
        on = self.evaluate_makefile("reference_target")
        self.assertIn("android.hardware.usb@1.3-service-qti", on)
        self.assertIn("android.hardware.usb.gadget@1.2-service-qti", on)
        self.assertIn("init.qcom.usb.rc", on)
        self.assertIn("init.qcom.usb.sh", on)
        self.assertIn("usb_compositions.conf", on)
        self.assertIn("vendor.usb.use_gadget_hal=1", on)
        off = self.evaluate_makefile("reference_target", gadget_hal="false")
        self.assertNotIn("android.hardware.usb.gadget@1.2-service-qti", off)
        self.assertIn("vendor.usb.use_gadget_hal=0", off)

    def test_archive_vintf_is_hidl_and_must_not_claim_aidl(self):
        for filename, interface, version in (
            ("android.hardware.usb@1.3-service-qti.xml", "android.hardware.usb", "1.3"),
            ("android.hardware.usb.gadget@1.2-service-qti.xml",
             "android.hardware.usb.gadget", "1.2"),
        ):
            with self.subTest(file=filename):
                fragment = ET.parse(ROOT / "hal" / filename).getroot()
                hal = fragment.find("hal")
                self.assertIsNotNone(hal)
                self.assertEqual(hal.get("format"), "hidl")
                self.assertEqual(hal.findtext("name"), interface)
                self.assertEqual(hal.findtext("version"), version)
        build = (ROOT / "hal/Android.bp").read_text(encoding="utf-8")
        self.assertIn('"android.hardware.usb@1.3"', build)
        self.assertIn('"android.hardware.usb.gadget@1.2"', build)
        self.assertNotIn('"android.hardware.usb-V4-ndk"', build)
        self.assertNotIn('"android.hardware.usb.gadget-V2-ndk"', build)

    def extract_serial_fragment(self):
        source = USB_INIT.read_text(encoding="utf-8")
        self.assertNotIn("serialno=1234567", source)
        self.assertIn("getprop ro.boot.serialno", source)
        self.assertIn("printf '%s' \"$serialno\"", source)
        marker = "\t# ADB needs a device-specific iSerialNumber"
        self.assertEqual(source.count(marker), 1)
        end = "\tsetprop vendor.usb.configfs 1"
        self.assertEqual(source.count(end), 1)
        # The marker begins a comment line; skip its remainder before execution.
        part = source.split(marker, 1)[1].split("\n", 1)[1].split(end, 1)[0]
        self.assertEqual(part.count("/config/usb_gadget/g1/strings/0x409/serialnumber"), 2)
        return part

    def run_serial_fragment(self, original, serial, boot_serial):
        with tempfile.TemporaryDirectory(prefix="pe-a17-usb-serial-") as td:
            path = Path(td) / "serialnumber"
            path.write_text(original, encoding="utf-8")
            fragment = self.extract_serial_fragment().replace(
                "/config/usb_gadget/g1/strings/0x409/serialnumber", str(path)
            )
            mock = """
getprop() {
  case "$1" in
    ro.serialno) printf '%s' "$TEST_SERIAL" ;;
    ro.boot.serialno) printf '%s' "$TEST_BOOT_SERIAL" ;;
  esac
}
"""
            env = {**os.environ, "TEST_SERIAL": serial,
                   "TEST_BOOT_SERIAL": boot_serial}
            run = subprocess.run(
                ["sh", "-eu", "-c", mock + fragment],
                env=env, cwd=td, capture_output=True, text=True, check=False,
            )
            self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
            return path.read_text(encoding="utf-8")

    def test_gadget_serial_identity_never_fabricated(self):
        cases = [
            ("FACTORYVALUE", "ANDROIDVAL", "BOOTVAL", "FACTORYVALUE"),
            ("", "ANDROIDVAL", "BOOTVAL", "ANDROIDVAL"),
            ("", "", "BOOTVAL", "BOOTVAL"),
            ("", "", "", ""),
            ("", "REAL-SERIAL-123", "", "REAL-SERIAL-123"),
        ]
        for initial, ro, boot, expected in cases:
            with self.subTest(initial=initial, ro=ro, boot=boot):
                self.assertEqual(self.run_serial_fragment(initial, ro, boot), expected)

    def test_original_script_is_shell_syntax_valid(self):
        run = subprocess.run(["sh", "-n", str(USB_INIT)],
                             capture_output=True, text=True, check=False)
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
