# Building DW3000 Kernel Modules from Source

How to cross-compile the full UWB kernel module chain for a LineageOS
Pixel 7 Pro running GKI kernel 6.1.

## Problem

The Pixel 7 Pro ships with vendor UWB modules signed for the stock Google kernel.
LineageOS replaces the kernel (different git commit hash), causing `MODULE_SIG_PROTECT`
to reject the vendor modules. We must build from source against the running kernel.

## Prerequisites

- Build server with aarch64 cross-compiler (tested on H1: x86_64, 16 cores)
- `aarch64-linux-gnu-gcc` installed
- `git`, `make`, `bc`, `bison`, `flex` installed
- Running kernel version from device: `adb shell uname -r`

## Step 1: Get kernel config from device

```bash
adb shell su -c 'zcat /proc/config.gz' > /tmp/kernel_config
```

## Step 2: Clone GKI common kernel

The running kernel `6.1.145-android14-11-gec45f20f38ea` is from the AOSP common kernel.

```bash
cd /tmp
git clone --depth 1 https://android.googlesource.com/kernel/common.git \
    -b android14-6.1 android14-kernel
```

## Step 3: Prepare kernel build environment

```bash
cd /tmp/android14-kernel
cp /tmp/kernel_config .config

# Create empty ABI symbol list (GKI build system requires it)
touch abi_symbollist.raw

# Configure and prepare
make ARCH=arm64 CROSS_COMPILE=aarch64-linux-gnu- olddefconfig
make ARCH=arm64 CROSS_COMPILE=aarch64-linux-gnu- modules_prepare -j$(nproc)

# Generate module.lds (required for linking .ko files)
# The kernel build might fail to auto-generate it due to BTF tools.
# If so, preprocess manually and fix PAGE_SIZE macros:
make ARCH=arm64 CROSS_COMPILE=aarch64-linux-gnu- scripts/module.lds 2>/dev/null || \
  aarch64-linux-gnu-gcc -E -Wp,-MD,scripts/.module.lds.d -DMODULE \
    -nostdinc -I./arch/arm64/include -I./arch/arm64/include/generated \
    -I./include -I./arch/arm64/include/uapi -I./include/uapi \
    -include ./include/linux/compiler-version.h -include ./include/linux/kconfig.h \
    -D__KERNEL__ -DCC_USING_PATCHABLE_FUNCTION_ENTRY \
    -P -Uarm64 -x c -o scripts/module.lds scripts/module.lds.S

# Fix PAGE_SIZE macros if not expanded
sed -i 's/((1UL) << 12)/4096/g' scripts/module.lds
```

## Step 4: Build ieee802154 and mac802154

```bash
cd /tmp/android14-kernel
make ARCH=arm64 CROSS_COMPILE=aarch64-linux-gnu- M=net/ieee802154 -j$(nproc)
make ARCH=arm64 CROSS_COMPILE=aarch64-linux-gnu- M=net/mac802154 -j$(nproc)

# Combine symbol exports for dependent modules
cat net/ieee802154/Module.symvers net/mac802154/Module.symvers > /tmp/ieee802154_symvers.txt
```

Output:

- `net/ieee802154/ieee802154.ko`
- `net/mac802154/mac802154.ko`

## Step 5: Clone and patch DW3000/mcps802154 source

```bash
cd /tmp
git clone --depth 1 \
    https://android.googlesource.com/kernel/google-modules/uwb/qorvo/dw3000 \
    -b android-gs-pantah-5.10-android14-qpr3 dw3000-src

# Apply patches for kernel 5.10 -> 6.1 API changes
cd dw3000-src
git apply /path/to/patches/0001-dw3000-spi-adapt-for-kernel-6.1.patch
```

### Patches required (kernel 5.10 -> 6.1)

1. **`spi->controller->kworker` is now a pointer** (was struct)
   - `kworker.task->pid` -> `kworker->task->pid`

2. **`spi_driver.remove` returns void** (was int)
   - Change `static int dw3000_spi_remove` to `static void dw3000_spi_remove`
   - Change `return 0;` to `return;`

3. **`spi->master->last_cs_enable` removed**
   - Guard the quirk code with `#if 0` (the CS line behavior changed in 6.1)

## Step 6: Build mcps802154 and dw3000

```bash
cd /tmp/dw3000-src/kernel
make -C /tmp/android14-kernel \
    ARCH=arm64 \
    CROSS_COMPILE=aarch64-linux-gnu- \
    M=/tmp/dw3000-src/kernel \
    KBUILD_EXTRA_SYMBOLS=/tmp/ieee802154_symvers.txt \
    CONFIG_MCPS802154_TESTMODE=y \
    -j$(nproc)
```

Output:

- `net/mcps802154/mcps802154.ko`
- `net/mcps802154/mcps802154_region_fira.ko`
- `net/mcps802154/mcps802154_region_nfcc_coex.ko`
- `net/mcps802154/mcps802154_region_pctt.ko`
- `drivers/net/ieee802154/dw3000.ko`

## Step 7: Deploy to device

The modules must be loaded by init (PID 1) due to `MODULE_SIG_PROTECT`.
Replace the vendor modules so init's `modules.load` picks up our builds:

```bash
# Remount vendor_dlkm as read-write (requires root)
adb shell su -c 'mount -o remount,rw /vendor_dlkm'

# Backup originals
adb shell su -c 'mkdir -p /data/local/tmp/vendor_modules_backup'
for mod in ieee802154.ko mac802154.ko mcps802154.ko \
    mcps802154_region_fira.ko mcps802154_region_nfcc_coex.ko \
    mcps802154_region_pctt.ko dw3000.ko; do
    adb shell su -c "cp /vendor/lib/modules/$mod /data/local/tmp/vendor_modules_backup/"
done

# Replace with our builds
adb push ieee802154.ko /data/local/tmp/
adb push mac802154.ko /data/local/tmp/
adb push mcps802154.ko /data/local/tmp/
adb push mcps802154_region_fira.ko /data/local/tmp/
adb push mcps802154_region_nfcc_coex.ko /data/local/tmp/
adb push mcps802154_region_pctt.ko /data/local/tmp/
adb push dw3000.ko /data/local/tmp/

for mod in ieee802154.ko mac802154.ko mcps802154.ko \
    mcps802154_region_fira.ko mcps802154_region_nfcc_coex.ko \
    mcps802154_region_pctt.ko dw3000.ko; do
    adb shell su -c "cp /data/local/tmp/$mod /vendor/lib/modules/$mod"
done

# Also copy to system_dlkm for ieee802154 and mac802154
adb shell su -c 'mount -o remount,rw /system_dlkm'
adb shell su -c 'cp /data/local/tmp/ieee802154.ko /system_dlkm/lib/modules/ieee802154.ko'
adb shell su -c 'cp /data/local/tmp/mac802154.ko /system_dlkm/lib/modules/mac802154.ko'

# Reboot - init will load our modules from modules.load
adb reboot
```

## Verification

After reboot:

```bash
adb shell su -c 'cat /proc/modules | grep -iE "dw3000|mcps|802154"'
# Should show: ieee802154, mac802154, mcps802154, mcps802154_region_fira, dw3000 etc.

adb shell su -c 'ls /sys/kernel/debug/dw3000/'
# Should show: spi16.0/

adb shell su -c 'cat /sys/kernel/debug/dw3000/spi16.0/power'
# Should show: 0 or 1

adb shell su -c '/data/local/tmp/uwb_probe'
# Should show debugfs entries and chip info
```

## Module dependency chain

```
ieee802154.ko          (no deps)
  mac802154.ko         (depends: ieee802154)
    mcps802154.ko      (depends: mac802154)
      dw3000.ko        (depends: mcps802154)
      mcps802154_region_fira.ko   (depends: mcps802154)
      mcps802154_region_pctt.ko   (depends: mcps802154)
      mcps802154_region_nfcc_coex.ko (depends: mcps802154)
```

## Build artifacts on H1

```
/tmp/android14-kernel/               # Kernel source tree
/tmp/android14-kernel/net/ieee802154/ieee802154.ko
/tmp/android14-kernel/net/mac802154/mac802154.ko
/tmp/dw3000-src/                     # DW3000 AOSP source (patched)
/tmp/dw3000-src/kernel/net/mcps802154/mcps802154.ko
/tmp/dw3000-src/kernel/net/mcps802154/mcps802154_region_fira.ko
/tmp/dw3000-src/kernel/net/mcps802154/mcps802154_region_nfcc_coex.ko
/tmp/dw3000-src/kernel/net/mcps802154/mcps802154_region_pctt.ko
/tmp/dw3000-src/kernel/drivers/net/ieee802154/dw3000.ko
```
