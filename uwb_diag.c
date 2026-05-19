/*
 * uwb_diag.c -- Read DW3000 RX diagnostics via debugfs register access
 *
 * Session 1, Experiment E004: Read diagnostic registers directly.
 *
 * Reads DW3000 diagnostic data from debugfs register files:
 *   - Device ID (0x0)
 *   - System status
 *   - RX diagnostics (CIA registers)
 *   - DB_DIAG sets (0x180000 / 0x1800e8)
 *
 * Usage:
 *   uwb_diag                    # auto-detect, dump key registers
 *   uwb_diag -p /sys/kernel/debug/dw3000/spi0.0   # explicit path
 *   uwb_diag -a                 # dump ALL register files
 *   uwb_diag -r 0x150000        # read specific register
 *
 * Build:  make uwb_diag
 * Deploy: adb push uwb_diag /data/local/tmp/
 * Run:    adb shell su -c /data/local/tmp/uwb_diag
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <fcntl.h>
#include <unistd.h>
#include <dirent.h>
#include <errno.h>
#include <getopt.h>

/* Key DW3000 register addresses */
static const struct {
    const char *name;
    const char *file; /* debugfs filename (0xNNNNNN format) */
    const char *desc;
} key_registers[] = {
    { "DEV_ID",     "0x0",      "Device identifier" },
    { "SYS_CFG",    "0x10",     "System configuration (PDOA mode, CIA)" },
    { "SYS_TIME",   "0x1c",     "System time counter" },
    { "SYS_STATUS", "0x44",     "System event status (CIA_DONE, RX events)" },
    { "RX_FINFO",   "0x4c",     "RX frame information" },
    { "RX_TIME",    "0x64",     "RX timestamp" },
    { "CIA_DIAG0",  "0xc0020",  "CIA diagnostic 0 (clock offset PPM)" },
    { "CIA_DIAG1",  "0xc0024",  "CIA diagnostic 1" },
    { "CIA_TDOA",   "0xc0018",  "CIA TDoA result" },
    { "CIA_PDOA",   "0xc001c",  "CIA PDoA + first path agreement" },
    { "IP_DIAG0",   "0xc0028",  "IP diagnostic 0" },
    { "IP_DIAG1",   "0xc002c",  "IP diagnostic 1" },
    { "IP_DIAG2",   "0xc0030",  "IP diagnostic 2" },
    { "IP_DIAG8",   "0xc0048",  "IP diagnostic 8" },
    { "CLK_CTRL",   "0x70036",  "Clock control (ACC_MEM_CLK_ON at bit 15)" },
    { NULL, NULL, NULL }
};

/* Auto-detect DW3000 debugfs path */
static int find_debugfs_path(char *buf, size_t len) {
    DIR *d = opendir("/sys/kernel/debug/dw3000");
    if (!d) return -1;
    struct dirent *ent;
    while ((ent = readdir(d))) {
        if (ent->d_name[0] == '.') continue;
        snprintf(buf, len, "/sys/kernel/debug/dw3000/%s", ent->d_name);
        closedir(d);
        return 0;
    }
    closedir(d);
    return -1;
}

/* Read a debugfs register file, return content as string */
static int read_reg(const char *basepath, const char *regfile, char *out, size_t outlen) {
    char path[512];
    snprintf(path, sizeof(path), "%s/%s", basepath, regfile);
    int fd = open(path, O_RDONLY);
    if (fd < 0) return -1;
    int n = read(fd, out, outlen - 1);
    close(fd);
    if (n <= 0) return -1;
    out[n] = 0;
    /* Strip trailing whitespace */
    while (n > 0 && (out[n-1] == '\n' || out[n-1] == '\r' || out[n-1] == ' '))
        out[--n] = 0;
    return 0;
}

static void dump_key_registers(const char *basepath) {
    char val[256];
    printf("=== DW3000 Key Registers ===\n");
    printf("%-12s %-10s %-40s %s\n", "Name", "Address", "Description", "Value");
    printf("%-12s %-10s %-40s %s\n", "----", "-------", "-----------", "-----");
    for (int i = 0; key_registers[i].name; i++) {
        if (read_reg(basepath, key_registers[i].file, val, sizeof(val)) == 0) {
            printf("%-12s %-10s %-40s %s\n",
                   key_registers[i].name,
                   key_registers[i].file,
                   key_registers[i].desc,
                   val);
        } else {
            printf("%-12s %-10s %-40s (not readable)\n",
                   key_registers[i].name,
                   key_registers[i].file,
                   key_registers[i].desc);
        }
    }
}

static void dump_all_registers(const char *basepath) {
    DIR *d = opendir(basepath);
    if (!d) {
        fprintf(stderr, "Cannot open %s\n", basepath);
        return;
    }

    printf("=== ALL DW3000 Registers ===\n");
    printf("%-12s %s\n", "Register", "Value");

    struct dirent *ent;
    int count = 0;
    while ((ent = readdir(d))) {
        if (ent->d_name[0] != '0' || ent->d_name[1] != 'x')
            continue;
        char val[256];
        if (read_reg(basepath, ent->d_name, val, sizeof(val)) == 0) {
            printf("%-12s %s\n", ent->d_name, val);
            count++;
        }
    }
    closedir(d);
    printf("\nTotal: %d registers read\n", count);
}

static void read_specific_register(const char *basepath, const char *regaddr) {
    char val[256];
    if (read_reg(basepath, regaddr, val, sizeof(val)) == 0) {
        printf("%s = %s\n", regaddr, val);
    } else {
        fprintf(stderr, "Cannot read register %s/%s\n", basepath, regaddr);
    }
}

static void usage(const char *prog) {
    fprintf(stderr, "Usage: %s [options]\n", prog);
    fprintf(stderr, "  -p PATH   debugfs device path\n");
    fprintf(stderr, "  -a        dump ALL register files\n");
    fprintf(stderr, "  -r ADDR   read specific register (e.g. 0x150000)\n");
    fprintf(stderr, "  -h        this help\n");
}

int main(int argc, char *argv[]) {
    char dbgfs_path[256] = {0};
    int dump_all = 0;
    const char *specific_reg = NULL;
    int opt;

    while ((opt = getopt(argc, argv, "p:ar:h")) != -1) {
        switch (opt) {
        case 'p': strncpy(dbgfs_path, optarg, sizeof(dbgfs_path) - 1); break;
        case 'a': dump_all = 1; break;
        case 'r': specific_reg = optarg; break;
        default: usage(argv[0]); return 1;
        }
    }

    if (!dbgfs_path[0]) {
        if (find_debugfs_path(dbgfs_path, sizeof(dbgfs_path)) < 0) {
            fprintf(stderr, "Error: cannot find /sys/kernel/debug/dw3000/\n");
            return 1;
        }
    }

    fprintf(stderr, "DW3000 debugfs: %s\n", dbgfs_path);

    if (specific_reg) {
        read_specific_register(dbgfs_path, specific_reg);
    } else if (dump_all) {
        dump_all_registers(dbgfs_path);
    } else {
        dump_key_registers(dbgfs_path);
    }

    /* Also show power state and CIR config */
    char val[256];
    printf("\n=== Virtual Registers ===\n");
    if (read_reg(dbgfs_path, "power", val, sizeof(val)) == 0)
        printf("power    = %s\n", val);
    if (read_reg(dbgfs_path, "cir_config", val, sizeof(val)) == 0)
        printf("cir_cfg  = %s\n", val);

    return 0;
}
