/*
 * uwb_regdump.c -- Dump full DW3000 register space via debugfs
 *
 * Session 1, Experiment E005: Complete register map dump.
 *
 * Reads all 0x* register files from debugfs, sorts by address, and outputs
 * a complete register map. Useful for understanding chip state and finding
 * undocumented registers.
 *
 * Usage:
 *   uwb_regdump                    # dump to stdout
 *   uwb_regdump -o regs.csv        # dump to CSV file
 *   uwb_regdump -d                 # diff mode: dump twice, show changes
 *
 * Build:  make uwb_regdump
 * Deploy: adb push uwb_regdump /data/local/tmp/
 * Run:    adb shell su -c /data/local/tmp/uwb_regdump
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <fcntl.h>
#include <unistd.h>
#include <dirent.h>
#include <errno.h>
#include <getopt.h>

#define MAX_REGS 2048

struct reg_entry {
    unsigned long addr;
    char name[32];
    char value[64];
};

static int reg_cmp(const void *a, const void *b) {
    const struct reg_entry *ra = a, *rb = b;
    if (ra->addr < rb->addr) return -1;
    if (ra->addr > rb->addr) return 1;
    return 0;
}

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

static int dump_registers(const char *basepath, struct reg_entry *regs) {
    DIR *d = opendir(basepath);
    if (!d) return -1;

    struct dirent *ent;
    int n = 0;
    while ((ent = readdir(d)) && n < MAX_REGS) {
        if (ent->d_name[0] != '0' || ent->d_name[1] != 'x')
            continue;
        char path[512];
        snprintf(path, sizeof(path), "%s/%s", basepath, ent->d_name);
        int fd = open(path, O_RDONLY);
        if (fd < 0) continue;
        char val[64] = {0};
        int len = read(fd, val, sizeof(val) - 1);
        close(fd);
        if (len <= 0) continue;
        while (len > 0 && (val[len-1] == '\n' || val[len-1] == '\r'))
            val[--len] = 0;

        regs[n].addr = strtoul(ent->d_name, NULL, 16);
        strncpy(regs[n].name, ent->d_name, sizeof(regs[n].name) - 1);
        strncpy(regs[n].value, val, sizeof(regs[n].value) - 1);
        n++;
    }
    closedir(d);

    qsort(regs, n, sizeof(struct reg_entry), reg_cmp);
    return n;
}

int main(int argc, char *argv[]) {
    char dbgfs_path[256] = {0};
    const char *outfile = NULL;
    int diff_mode = 0;
    int opt;

    while ((opt = getopt(argc, argv, "p:o:dh")) != -1) {
        switch (opt) {
        case 'p': strncpy(dbgfs_path, optarg, sizeof(dbgfs_path) - 1); break;
        case 'o': outfile = optarg; break;
        case 'd': diff_mode = 1; break;
        default:
            fprintf(stderr, "Usage: %s [-p path] [-o file.csv] [-d]\n", argv[0]);
            return 1;
        }
    }

    if (!dbgfs_path[0]) {
        if (find_debugfs_path(dbgfs_path, sizeof(dbgfs_path)) < 0) {
            fprintf(stderr, "Error: cannot find /sys/kernel/debug/dw3000/\n");
            return 1;
        }
    }

    fprintf(stderr, "DW3000 debugfs: %s\n", dbgfs_path);

    struct reg_entry *regs1 = calloc(MAX_REGS, sizeof(struct reg_entry));
    if (!regs1) { perror("malloc"); return 1; }

    int n1 = dump_registers(dbgfs_path, regs1);
    if (n1 <= 0) {
        fprintf(stderr, "No registers found\n");
        free(regs1);
        return 1;
    }

    FILE *out = stdout;
    if (outfile) {
        out = fopen(outfile, "w");
        if (!out) {
            perror(outfile);
            free(regs1);
            return 1;
        }
    }

    if (!diff_mode) {
        fprintf(out, "address,value\n");
        for (int i = 0; i < n1; i++)
            fprintf(out, "%s,%s\n", regs1[i].name, regs1[i].value);
        fprintf(stderr, "Dumped %d registers\n", n1);
    } else {
        fprintf(stderr, "First dump: %d registers. Waiting 2s for second dump...\n", n1);
        sleep(2);

        struct reg_entry *regs2 = calloc(MAX_REGS, sizeof(struct reg_entry));
        if (!regs2) { perror("malloc"); free(regs1); return 1; }
        int n2 = dump_registers(dbgfs_path, regs2);

        fprintf(out, "address,value1,value2,changed\n");
        int changes = 0;
        /* Simple merge by address */
        int i = 0, j = 0;
        while (i < n1 && j < n2) {
            if (regs1[i].addr == regs2[j].addr) {
                int changed = strcmp(regs1[i].value, regs2[j].value) != 0;
                if (changed) changes++;
                fprintf(out, "%s,%s,%s,%d\n",
                        regs1[i].name, regs1[i].value, regs2[j].value, changed);
                i++; j++;
            } else if (regs1[i].addr < regs2[j].addr) {
                fprintf(out, "%s,%s,,1\n", regs1[i].name, regs1[i].value);
                i++;
            } else {
                fprintf(out, "%s,,%s,1\n", regs2[j].name, regs2[j].value);
                j++;
            }
        }
        fprintf(stderr, "Diff: %d/%d registers changed\n", changes, n1);
        free(regs2);
    }

    if (outfile) fclose(out);
    free(regs1);
    return 0;
}
