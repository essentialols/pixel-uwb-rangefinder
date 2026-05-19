/*
 * uwb_probe.c -- UWB subsystem reconnaissance for Pixel 7 Pro
 *
 * Session 1, Experiment E001: Enumerate UWB device nodes, sysfs interfaces,
 * netlink families, loaded modules, debugfs CIR interface, and dmesg references.
 *
 * Based on AOSP source analysis:
 *   - DW3000 driver creates debugfs at /sys/kernel/debug/dw3000/<spidev>/
 *   - CIR data accessible via debugfs: cir_data, cir_config, power
 *   - Testmode netlink via ieee802154: RX_DIAG, CW tone, continuous TX
 *   - AOC only controls reset GPIO -- not a data mediator
 *   - CIR RAM at register 0x150000, DB_DIAG at 0x180000
 *
 * This tool only reads, never writes. Safe to run.
 *
 * Build:  make uwb_probe
 * Deploy: adb push uwb_probe /data/local/tmp/
 * Run:    adb shell su -c /data/local/tmp/uwb_probe
 */

#define _GNU_SOURCE
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <dirent.h>
#include <fcntl.h>
#include <unistd.h>
#include <sys/stat.h>
#include <strings.h>

static void section(const char *title) {
    printf("\n=== %s ===\n", title);
}

static void run_cmd(const char *cmd) {
    FILE *fp = popen(cmd, "r");
    if (!fp) {
        printf("  (failed to run: %s)\n", cmd);
        return;
    }
    char buf[1024];
    int found = 0;
    while (fgets(buf, sizeof(buf), fp)) {
        printf("  %s", buf);
        found = 1;
    }
    if (!found)
        printf("  (no output)\n");
    pclose(fp);
}

static int check_file(const char *path) {
    struct stat st;
    if (stat(path, &st) == 0) {
        printf("  FOUND: %s (mode=%o, %s)\n", path, st.st_mode & 0777,
               S_ISDIR(st.st_mode) ? "dir" :
               S_ISCHR(st.st_mode) ? "char" :
               S_ISREG(st.st_mode) ? "file" : "other");
        return 1;
    }
    return 0;
}

static void scan_dev(const char *keyword) {
    DIR *d = opendir("/dev");
    if (!d) return;
    struct dirent *ent;
    int found = 0;
    while ((ent = readdir(d))) {
        if (strcasestr(ent->d_name, keyword)) {
            char path[256];
            snprintf(path, sizeof(path), "/dev/%s", ent->d_name);
            struct stat st;
            stat(path, &st);
            printf("  /dev/%s  (type=%s, mode=%o)\n", ent->d_name,
                   S_ISCHR(st.st_mode) ? "char" :
                   S_ISBLK(st.st_mode) ? "block" : "other",
                   st.st_mode & 0777);
            found = 1;
        }
    }
    if (!found)
        printf("  (none found matching '%s')\n", keyword);
    closedir(d);
}

/* Recursively list a directory up to given depth */
static void list_dir_recursive(const char *path, int depth, int maxdepth) {
    if (depth > maxdepth) return;
    DIR *d = opendir(path);
    if (!d) return;
    struct dirent *ent;
    while ((ent = readdir(d))) {
        if (ent->d_name[0] == '.') continue;
        char full[512];
        snprintf(full, sizeof(full), "%s/%s", path, ent->d_name);
        struct stat st;
        if (stat(full, &st) != 0) continue;
        for (int i = 0; i < depth; i++) printf("  ");
        if (S_ISDIR(st.st_mode)) {
            printf("  %s/\n", ent->d_name);
            list_dir_recursive(full, depth + 1, maxdepth);
        } else {
            /* Try to read small files to show their content */
            if (st.st_size > 0 && st.st_size < 256) {
                int fd = open(full, O_RDONLY);
                if (fd >= 0) {
                    char buf[256] = {0};
                    int n = read(fd, buf, sizeof(buf) - 1);
                    close(fd);
                    if (n > 0) {
                        /* Remove trailing newline */
                        while (n > 0 && (buf[n-1] == '\n' || buf[n-1] == '\r'))
                            buf[--n] = 0;
                        printf("  %s = %s\n", ent->d_name, buf);
                        continue;
                    }
                }
            }
            printf("  %s (%ld bytes)\n", ent->d_name, (long)st.st_size);
        }
    }
    closedir(d);
}

/* Read and print a small file */
static int read_file(const char *path) {
    int fd = open(path, O_RDONLY);
    if (fd < 0) return 0;
    char buf[4096];
    int n = read(fd, buf, sizeof(buf) - 1);
    close(fd);
    if (n <= 0) return 0;
    buf[n] = 0;
    printf("  %s\n", buf);
    return 1;
}

int main(void) {
    printf("pixel-uwb-rangefinder: UWB subsystem probe v2\n");
    printf("Device: Pixel 7 Pro (gs201/cheetah)\n");
    printf("Target: Qorvo DW3000 UWB transceiver\n");
    printf("Key registers: CIR_RAM=0x150000, DB_DIAG=0x180000\n\n");

    /*=== 1. Loaded kernel modules ===*/
    section("1. Loaded kernel modules");
    run_cmd("cat /proc/modules 2>/dev/null | grep -iE 'dw3000|mcps|uwb|aoc_uwb'");

    /*=== 2. Device nodes ===*/
    section("2. Device nodes (/dev/)");
    scan_dev("uwb");
    scan_dev("dw3");
    scan_dev("mcps");
    scan_dev("wpan");
    scan_dev("ieee");

    /*=== 3. SPI bus -- DW3000 uses SPI ===*/
    section("3. SPI bus devices");
    run_cmd("ls -la /sys/bus/spi/devices/ 2>/dev/null");
    run_cmd("find /sys/bus/spi/devices/ -maxdepth 2 -name 'modalias' -exec sh -c 'echo \"  $(dirname {}) -> $(cat {})\"' \\; 2>/dev/null");
    run_cmd("find /sys/bus/spi/devices/ -maxdepth 2 -name 'driver' -exec sh -c 'echo \"  $(dirname {}) -> $(readlink -f {})\"' \\; 2>/dev/null");

    /*=== 4. Debugfs -- the PRIMARY interface for CIR data ===*/
    section("4. Debugfs DW3000 (CIR access path)");
    printf("  Looking for /sys/kernel/debug/dw3000/...\n");
    if (check_file("/sys/kernel/debug/dw3000")) {
        printf("  DW3000 debugfs found! Listing contents:\n");
        list_dir_recursive("/sys/kernel/debug/dw3000", 1, 3);
    } else {
        printf("  /sys/kernel/debug/dw3000 NOT FOUND\n");
        printf("  Trying broader search...\n");
        run_cmd("find /sys/kernel/debug -maxdepth 4 -name '*dw3*' -o -name '*uwb*' -o -name '*mcps*' -o -name '*ieee802154*' 2>/dev/null");
    }

    /*=== 5. CIR config check ===*/
    section("5. CIR configuration (debugfs)");
    /* Try common paths */
    const char *cir_paths[] = {
        "/sys/kernel/debug/dw3000/spi0.0/cir_config",
        "/sys/kernel/debug/dw3000/spi1.0/cir_config",
        "/sys/kernel/debug/dw3000/spi2.0/cir_config",
        NULL
    };
    int cir_found = 0;
    for (int i = 0; cir_paths[i]; i++) {
        if (read_file(cir_paths[i])) {
            printf("  -> CIR config at: %s\n", cir_paths[i]);
            cir_found = 1;
            break;
        }
    }
    if (!cir_found) {
        /* Find it dynamically */
        run_cmd("find /sys/kernel/debug -name 'cir_config' 2>/dev/null");
    }

    /*=== 6. Power state ===*/
    section("6. DW3000 power state (debugfs)");
    run_cmd("find /sys/kernel/debug -name 'power' -path '*dw3000*' -exec sh -c 'echo \"  {} = $(cat {})\"' \\; 2>/dev/null");

    /*=== 7. IEEE 802.15.4 network interfaces ===*/
    section("7. IEEE 802.15.4 / WPAN interfaces");
    run_cmd("ls -la /sys/class/ieee802154/ 2>/dev/null");
    run_cmd("ls -la /sys/class/net/ 2>/dev/null | grep -iE 'wpan|uwb'");
    run_cmd("ip link show 2>/dev/null | grep -iE 'wpan|uwb|ieee'");

    /*=== 8. Sysfs classes ===*/
    section("8. Sysfs classes");
    run_cmd("ls /sys/class/ 2>/dev/null | grep -iE 'uwb|ieee|wpan|mac'");

    /*=== 9. Generic netlink families ===*/
    section("9. Generic netlink families (nl80215/ieee802154)");
    /* The MAC layer registers a genl family */
    run_cmd("cat /proc/net/netlink 2>/dev/null | head -3");
    printf("  Scanning for ieee802154 genl families...\n");
    run_cmd("find /sys/kernel/debug -name '*nl*' -path '*802154*' 2>/dev/null");
    /* Try to list genl families if tool available */
    run_cmd("genl ctrl list 2>/dev/null | grep -A2 -iE 'ieee|802154|uwb|mcps' || echo '  (genl not available)'");

    /*=== 10. dmesg ===*/
    section("10. dmesg: DW3000/UWB boot messages");
    run_cmd("dmesg 2>/dev/null | grep -iE 'dw3000|uwb|qorvo|802\\.15\\.4|mcps' | tail -60");

    /*=== 11. dmesg: AOC UWB (reset GPIO only) ===*/
    section("11. dmesg: AOC UWB (GPIO control)");
    run_cmd("dmesg 2>/dev/null | grep -iE 'aoc.*uwb|uwb.*aoc|uwb.*gpio|uwb.*reset' | tail -20");

    /*=== 12. Android UWB service ===*/
    section("12. Android UWB HAL/service processes");
    run_cmd("ps -A 2>/dev/null | grep -iE 'uwb'");

    /*=== 13. SELinux ===*/
    section("13. SELinux context for UWB devices");
    run_cmd("ls -laZ /dev/ 2>/dev/null | grep -iE 'uwb|dw3|mcps|wpan|ieee802154'");
    run_cmd("ls -laZ /sys/kernel/debug/dw3000/ 2>/dev/null | head -10");

    /*=== 14. Hardware register file enumeration ===*/
    section("14. DW3000 hardware registers (debugfs)");
    printf("  Looking for register files in debugfs...\n");
    run_cmd("find /sys/kernel/debug -path '*dw3000*' -name '0x*' 2>/dev/null | head -20");
    /* Count total register files */
    run_cmd("find /sys/kernel/debug -path '*dw3000*' -name '0x*' 2>/dev/null | wc -l");

    /*=== 15. Chip identification ===*/
    section("15. DW3000 chip ID (register 0x0)");
    /* If debugfs register files exist, try to read chip ID */
    run_cmd("find /sys/kernel/debug -path '*dw3000*' -name '0x0' -exec sh -c 'echo \"  {} = $(cat {})\"' \\; 2>/dev/null");
    /* Alternative: look for dev_id in dmesg */
    run_cmd("dmesg 2>/dev/null | grep -iE 'dw3000.*dev.*id\\|dw3000.*chip\\|dw3000.*version\\|deca.*id' | tail -5");

    printf("\n=== PROBE COMPLETE ===\n");
    printf("\nSummary of access paths found:\n");
    printf("  - debugfs CIR: /sys/kernel/debug/dw3000/<dev>/cir_data\n");
    printf("  - debugfs CIR config: /sys/kernel/debug/dw3000/<dev>/cir_config\n");
    printf("  - debugfs power: /sys/kernel/debug/dw3000/<dev>/power\n");
    printf("  - debugfs registers: /sys/kernel/debug/dw3000/<dev>/0xNNNNNN\n");
    printf("  - testmode netlink: ieee802154 genl (START_RX_DIAG etc.)\n");
    printf("  - CIR RAM register: 0x150000\n");
    printf("  - Diagnostic set: 0x180000 (0xe8 bytes)\n");
    return 0;
}
