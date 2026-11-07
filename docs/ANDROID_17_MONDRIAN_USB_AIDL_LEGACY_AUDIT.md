# Android 17 mondrian — Qualcomm USB HIDL audit, AIDL ownership, early-boot safety

**Target:** independent PixelExperience-Reborn based on official AOSP Android 17. Device POCO F5 Pro / Redmi K60 (`mondrian`, SM8475/taro family). This review does **not** import a different ROM's implementation or assume an existing PE-Reborn mondrian device tree.

## Verified historical baseline

- PE `seventeen` and `fourteen` both point to Qualcomm legacy source commit `10d0f08bb0be9e097b3c265a6549e956cb47f5f0`, tree `b41d03db96340a66fee48d24fb94f3139e18ebc9`, 2024-02-06, 20 entries.
- `hal/Android.bp` registers `android.hardware.usb@1.3-service-qti` with HIDL `android.hardware.usb@1.0`–`1.3`; VINTF `android.hardware.usb@1.3-service-qti.xml` declares **HIDL IUsb/default V1.3**.
- `hal/Android.bp` also has `android.hardware.usb.gadget@1.2-service-qti` with HIDL Gadget 1.0–1.2. Its VINTF also declares **HIDL 1.2**, not AIDL. The old `PRODUCT_HAS_GADGET_HAL` gate defaults to *off*, according to the historic final commit, precisely because of early-boot/ADB timing problems.
- `vendor_product.mk` nevertheless automatically selects **old HIDL USB port service** for newer kernels (including 5.10) and assigns vendor USB properties, controller name and assorted QTI diag/QDSS/rmnet functions. The generic `etc/init.qcom.usb.rc` contains very broad Qualcomm ConfigFS rules, not validated for mondrian's current kernel/controller or SELinux.
- When no preexisting gadget serial was available, historical `etc/init.qcom.usb.sh` wrote fixed **`1234567`** to `/config/usb_gadget/g1/strings/0x409/serialnumber`. A shared made-up serial is not a device identity and should not be used.

## Actual code changes in this isolated PE review

1. `vendor_product.mk` now excludes **the entire old Qualcomm USB recipe** when `TARGET_DEVICE=mondrian`. This prevents accidental HIDL USB/Gadget service installation, broad generic QTI init scripts, debug scripts, auto-selected vendor USB controller, persistent diag/QDSS properties and legacy Gadget HAL selection through this old makefile. Other historic device targets retain the original recipe. **This is a safety boundary, not a USB implementation for mondrian.**
2. `etc/init.qcom.usb.sh` no longer fabricates a serial. When the existing ConfigFS serial is empty, it uses `ro.serialno`, then `ro.boot.serialno`, only if nonempty; otherwise it leaves ConfigFS unchanged. An already present factory string is preserved. Script uses quoted `printf '%s'` to preserve the serial without an extra newline. This change is for the archived script and does **not** assume it is installed on mondrian.
3. `tests/check_aosp17_mondrian_usb.py` runs **GNU Make against the actual vendor_product.mk** in mondrian and non-mondrian scenarios (user/userdebug, gadget true/false, kernel 5.10), parses both legacy HIDL VINTF XMLs, runs shell syntax checking and **executes the extracted real serial assignment fragment** with only the ConfigFS path redirected to a temporary file. It verifies no shared dummy serial, original ID preserved, serial fallback, and absence of identity if none is supplied. GitHub Actions executes these source-level checks.

## Authoritative Android 17 interfaces, not auto-upgraded legacy modules

- PE-Reborn has pinned official AOSP17 `hardware/interfaces` commit `735e364cbdd00b0d6e4dc33ea0866dbb6d971a11`.
- The **frozen** AOSP17 `usb/aidl/Android.bp` defines `android.hardware.usb` AIDL V1, V2, V3, **V4**; `usb/gadget/aidl/Android.bp` defines `android.hardware.usb.gadget` AIDL V1, **V2**. A version's presence in AOSP does **not** prove it is mandatory for a device or that a vendor implementation satisfies VINTF/FCM at that version.
- LF52406 `sm8450-common/common.mk` (Lineage 24.0) selects `android.hardware.usb-service.qti`, `android.hardware.usb.gadget-service.qti`, `init.qcom.usb.rc`, `init.qcom.usb.sh`, and `usb_compositions.conf`. This is a *read-only hardware reference*. The modern Qualcomm example found in Lineage USB `lineage-24.0` has AIDL USB **V3 NDK** and Gadget **V1 NDK**, not an automatic upgrade to the AOSP17 highest versions. No LineageOS ROM/device code has been imported.
- USB `IUsb/default` (port roles, power, data signaling) and `IUsbGadget/default` (functions and ConfigFS) must have exactly one compatible service owner each. XML VINTF versions, HAL binder backend, init service and SELinux domain must agree. Do not register the old HIDL endpoints and new AIDL endpoints as a blind parallel stack.

## Mandatory mondrian bring-up tests before USB feature claims

- Independently establish stock Xiaomi SM8475 vendor USB binary ABI, Type-C TCPC/role switch, DWC3 UDC controller, device/host switching and PD negotiation; verify actual `/sys/class/typec` and `/sys/class/udc` nodes rather than assuming `a600000.dwc3`.
- Keep early boot and recovery `adbd`/FunctionFS behavior. Verify ADB before `boot_completed`, `adb sideload`, fastbootd, MTP/PTP, OTG host, USB tethering, charging-only, USB data-disable, role switching, attach/detach/reconnect, multiple reboot scenarios, permissions and SELinux, USB PD/charging/thermal safety.
- Independently review which ConfigFS init properties and `usb_compositions.conf` entries remain necessary and safe. In particular, do not default to vendor DIAG/RMNET/QDSS configurations or insecure fixed serials; avoid a generic supersized `init.qcom.usb.rc` import that can override security/performance or initialization behavior.
- Validate Soong full compilation, VINTF/FCM, CTS/VTS (USB + Gadget), and a real mondrian. Do not label the legacy HIDL implementation AIDL just by renaming binary or changing XML.
- Android 17 also has new userspace USB/AOA developments; any separate `system/usb` integration requires official pinned-source ownership and verification. No changes to that subsystem are made in this step.

**Status:** real archived-source packaging guard plus serial safety patch, source-only CI. Existing PE AOSP17 `default.xml` remains unchanged. **No independent modern USB HAL has been created or tested on hardware.**

Official references: https://source.android.com/docs/core/architecture/hal , https://source.android.com/docs/automotive/usb-reset and AOSP `hardware/interfaces/usb/aidl` and `usb/gadget/aidl` at pinned SHA above.
