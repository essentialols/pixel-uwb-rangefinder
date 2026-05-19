/*
 * uwb_probe.c -- UWB subsystem reconnaissance for Pixel 7 Pro
 *
 * Session 1, Experiment E001: Enumerate UWB device nodes, sysfs interfaces,
 * netlink families, loaded modules, and dmesg references.
 *
 * This is the first tool -- it only reads, never writes. Safe to run.
 *
 * Build:  make uwb_probe
 * Deploy: adb push uwb_probe /data/local/tmp/
 * Run:    adb shell su -c /data/local/tmp/uwb_probe
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <dirent.h>
#include <fcntl.h>
#include <unistd.h>
#include <sys/stat.h>

static void section(const char *title) {
    printf("\n=== %s ===\n", title);
}

static void run_cmd(const char *cmd) {
    FILE *fp = popen(cmd, "r");
    if (!fp) {
        printf("  (failed to run: %s)\n", cmd);
        return;
    }
    char buf[512];
    int found = 0;
    while (fgets(buf, sizeof(buf), fp)) {
        printf("  %s", buf);
        found = 1;
    }
    if (!found)
        printf("  (no output)\n");
    pclose(fp);
}

static void check_file(const char *path) {
    struct stat st;
    if (stat(path, &st) == 0) {
        printf("  FOUND: %s (mode=%o)\n", path, st.st_mode & 0777);
    }
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

static void scan_sysfs_class(const char *keyword) {
    DIR *d = opendir("/sys/class");
    if (!d) return;
    struct dirent *ent;
    int found = 0;
    while ((ent = readdir(d))) {
        if (strcasestr(ent->d_name, keyword)) {
            printf("  /sys/class/%s\n", ent->d_name);
            found = 1;
        }
    }
    if (!found)
        printf("  (none found matching '%s')\n", keyword);
    closedir(d);
}

int main(void) {
    printf("pixel-uwb-rangefinder: UWB subsystem probe\n");
    printf("Device: Pixel 7 Pro (gs201/cheetah)\n");
    printf("Target: Qorvo DW3000 UWB transceiver\n");

    /* 1. Device nodes */
    section("Device nodes (/dev/*uwb* /dev/*dw* /dev/*mcps*)");
    scan_dev("uwb");
    scan_dev("dw3");
    scan_dev("mcps");
    scan_dev("aoc_uwb");

    /* 2. Known AOC device nodes */
    section("AOC device nodes");
    check_file("/dev/aoc_uwb_service");
    check_file("/dev/aoc_channel");
    check_file("/dev/aoc_control");

    /* 3. Sysfs classes */
    section("Sysfs classes matching uwb/ieee802154/wpan");
    scan_sysfs_class("uwb");
    scan_sysfs_class("ieee");
    scan_sysfs_class("wpan");
    scan_sysfs_class("mac");

    /* 4. IEEE 802.15.4 / UWB network interfaces */
    section("Network interfaces (wpan*, uwb*)");
    run_cmd("ls -la /sys/class/net/ 2>/dev/null | grep -iE 'uwb|wpan'");

    /* 5. Loaded modules */
    section("Loaded kernel modules (uwb/dw3000/mcps/aoc_uwb)");
    run_cmd("cat /proc/modules | grep -iE 'dw3000|mcps|uwb|aoc_uwb'");

    /* 6. Module info */
    section("Module details");
    run_cmd("modinfo dw3000 2>/dev/null | head -20");

    /* 7. SPI bus enumeration */
    section("SPI devices");
    run_cmd("ls -la /sys/bus/spi/devices/ 2>/dev/null");
    run_cmd("find /sys/bus/spi/devices/ -name 'modalias' -exec sh -c 'echo -n \"  {} -> \"; cat {}' \\; 2>/dev/null");

    /* 8. Netlink families */
    section("Netlink families (ieee802154/uwb/nl80215)");
    run_cmd("cat /proc/net/netlink 2>/dev/null | head -5");
    /* Generic netlink family discovery */
    run_cmd("ls /sys/kernel/debug/ieee80215* 2>/dev/null");

    /* 9. dmesg references */
    section("dmesg: UWB/DW3000/Qorvo references (last 50)");
    run_cmd("dmesg | grep -iE 'dw3000|uwb|qorvo|802\\.15\\.4' | tail -50");

    /* 10. dmesg: AOC UWB references */
    section("dmesg: AOC UWB references");
    run_cmd("dmesg | grep -i 'aoc.*uwb\\|uwb.*aoc' | tail -20");

    /* 11. UWB HAL service */
    section("Android UWB service process");
    run_cmd("ps -A 2>/dev/null | grep -iE 'uwb'");

    /* 12. SELinux context for UWB devices */
    section("SELinux contexts for UWB");
    run_cmd("ls -laZ /dev/ 2>/dev/null | grep -iE 'uwb|dw3|mcps'");

    /* 13. Debugfs */
    section("Debugfs UWB entries");
    run_cmd("find /sys/kernel/debug -maxdepth 3 -name '*uwb*' -o -name '*dw3000*' -o -name '*mcps*' 2>/dev/null");

    /* 14. procfs */
    section("Proc entries for IEEE 802.15.4");
    run_cmd("ls /proc/net/ 2>/dev/null | grep -iE 'ieee|wpan|uwb'");

    printf("\n=== PROBE COMPLETE ===\n");
    printf("Next: study DW3000 kernel source for register access paths\n");
    return 0;
}
