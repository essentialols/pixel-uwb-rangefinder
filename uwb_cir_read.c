/*
 * uwb_cir_read.c -- Read CIR (Channel Impulse Response) data from DW3000
 *
 * Session 1, Experiment E003: Read raw CIR data through debugfs.
 *
 * The DW3000 driver exposes CIR data via:
 *   /sys/kernel/debug/dw3000/<spidev>/cir_data    (binary, read-only)
 *   /sys/kernel/debug/dw3000/<spidev>/cir_config   (text, read/write)
 *
 * CIR data format (from dw3000_cir.h):
 *   Header: count(4) + filter(4) + ts(8) + utime(8) + fp_power1(4) +
 *           fp_power2(4) + fp_power3(4) + offset(4) + fp_index(2) +
 *           pdoa(2) + acc(2) + type(1) + dummy(1)
 *   Records: N x { real[3], imag[3] } -- 6.18 fixed-point
 *
 * Usage:
 *   uwb_cir_read                         # auto-detect debugfs path
 *   uwb_cir_read -p /sys/kernel/debug/dw3000/spi0.0  # explicit path
 *   uwb_cir_read -c 64                   # read 64 CIR records (default 20)
 *   uwb_cir_read -n 10                   # capture 10 CIR snapshots
 *   uwb_cir_read -j                      # JSON output
 *   uwb_cir_read -q                      # quiet: CSV only, no header
 *
 * Build:  make uwb_cir_read
 * Deploy: adb push uwb_cir_read /data/local/tmp/
 * Run:    adb shell su -c /data/local/tmp/uwb_cir_read
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <fcntl.h>
#include <unistd.h>
#include <dirent.h>
#include <math.h>
#include <errno.h>
#include <getopt.h>
#include <stdint.h>

/* CIR record: 6 bytes per sample (3 real + 3 imag), 6.18 fixed-point */
struct cir_record {
    uint8_t real[3];
    uint8_t imag[3];
} __attribute__((packed));

/* CIR data header as read from debugfs (matches kernel struct after 'count') */
struct cir_header {
    uint32_t count;
    uint32_t filter;
    uint64_t ts;
    uint64_t utime;
    uint32_t fp_power1;
    uint32_t fp_power2;
    uint32_t fp_power3;
    int32_t  offset;
    uint16_t fp_index;
    uint16_t pdoa;
    uint16_t acc;
    uint8_t  type;
    uint8_t  dummy;
} __attribute__((packed));

/* Convert 3-byte 6.18 fixed-point to double */
static double fixed_to_double(const uint8_t bytes[3]) {
    /* Reconstruct 24-bit signed value (6.18 format) */
    int32_t val = (int32_t)((uint32_t)bytes[0] |
                            ((uint32_t)bytes[1] << 8) |
                            ((uint32_t)bytes[2] << 16));
    /* Sign-extend from 24 bits */
    if (val & 0x800000)
        val |= 0xFF000000;
    /* Convert from 6.18 fixed-point */
    return (double)val / (double)(1 << 18);
}

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

static void usage(const char *prog) {
    fprintf(stderr, "Usage: %s [options]\n", prog);
    fprintf(stderr, "  -p PATH   debugfs device path\n");
    fprintf(stderr, "  -c COUNT  CIR record count (default 20)\n");
    fprintf(stderr, "  -n NUM    number of CIR snapshots to capture\n");
    fprintf(stderr, "  -j        JSON output\n");
    fprintf(stderr, "  -q        quiet (CSV only, no header)\n");
    fprintf(stderr, "  -h        this help\n");
}

int main(int argc, char *argv[]) {
    char dbgfs_path[256] = {0};
    int cir_count = 20;
    int num_captures = 1;
    int json_out = 0;
    int quiet = 0;
    int opt;

    while ((opt = getopt(argc, argv, "p:c:n:jqh")) != -1) {
        switch (opt) {
        case 'p': strncpy(dbgfs_path, optarg, sizeof(dbgfs_path) - 1); break;
        case 'c': cir_count = atoi(optarg); break;
        case 'n': num_captures = atoi(optarg); break;
        case 'j': json_out = 1; break;
        case 'q': quiet = 1; break;
        default: usage(argv[0]); return 1;
        }
    }

    /* Auto-detect path if not specified */
    if (!dbgfs_path[0]) {
        if (find_debugfs_path(dbgfs_path, sizeof(dbgfs_path)) < 0) {
            fprintf(stderr, "Error: cannot find /sys/kernel/debug/dw3000/\n");
            fprintf(stderr, "Is the dw3000 module loaded? Is debugfs mounted?\n");
            fprintf(stderr, "Try: mount -t debugfs none /sys/kernel/debug\n");
            return 1;
        }
    }

    if (!quiet)
        fprintf(stderr, "DW3000 debugfs: %s\n", dbgfs_path);

    /* Configure CIR */
    char config_path[512];
    snprintf(config_path, sizeof(config_path), "%s/cir_config", dbgfs_path);
    int cfd = open(config_path, O_WRONLY);
    if (cfd >= 0) {
        char config_str[64];
        int n = snprintf(config_str, sizeof(config_str),
                         "count %d filter 0x0 offset 0\n", cir_count);
        write(cfd, config_str, n);
        close(cfd);
        if (!quiet)
            fprintf(stderr, "CIR config: count=%d filter=0x0 offset=0\n", cir_count);
    } else {
        fprintf(stderr, "Warning: cannot write CIR config at %s: %s\n",
                config_path, strerror(errno));
    }

    /* Read CIR config back */
    cfd = open(config_path, O_RDONLY);
    if (cfd >= 0) {
        char buf[128] = {0};
        read(cfd, buf, sizeof(buf) - 1);
        close(cfd);
        if (!quiet)
            fprintf(stderr, "CIR config readback: %s", buf);
    }

    /* Allocate read buffer */
    size_t bufsz = sizeof(struct cir_header) +
                   sizeof(struct cir_record) * cir_count;
    uint8_t *buf = malloc(bufsz + 64); /* extra padding */
    if (!buf) {
        perror("malloc");
        return 1;
    }

    char data_path[512];
    snprintf(data_path, sizeof(data_path), "%s/cir_data", dbgfs_path);

    /* Print CSV header */
    if (!json_out && !quiet)
        printf("capture,index,real,imag,magnitude,phase_rad,"
               "fp_index,fp_power1,fp_power2,fp_power3,pdoa,acc,ts\n");

    for (int cap = 0; cap < num_captures; cap++) {
        int fd = open(data_path, O_RDONLY);
        if (fd < 0) {
            fprintf(stderr, "Error: cannot open %s: %s\n",
                    data_path, strerror(errno));
            fprintf(stderr, "CIR data may not be available (need active ranging?)\n");
            free(buf);
            return 1;
        }

        /* Read blocks until we get the full CIR data or EOF */
        memset(buf, 0, bufsz);
        ssize_t total = 0;
        ssize_t n;
        while (total < (ssize_t)bufsz) {
            n = read(fd, buf + total, bufsz - total);
            if (n <= 0) break;
            total += n;
        }
        close(fd);

        if (total < (ssize_t)sizeof(struct cir_header)) {
            fprintf(stderr, "Warning: only read %zd bytes (need %zu header)\n",
                    total, sizeof(struct cir_header));
            if (total == 0) {
                fprintf(stderr, "No CIR data available. Is UWB ranging active?\n");
                free(buf);
                return 1;
            }
            continue;
        }

        struct cir_header *hdr = (struct cir_header *)buf;
        struct cir_record *records = (struct cir_record *)(buf + sizeof(struct cir_header));
        int nrec = hdr->count;
        if (nrec > cir_count) nrec = cir_count;

        if (!quiet && !json_out) {
            fprintf(stderr, "Capture %d: count=%u fp_index=%u pdoa=%u acc=%u "
                    "ts=%llu fp_pwr=(%u,%u,%u)\n",
                    cap, hdr->count, hdr->fp_index, hdr->pdoa, hdr->acc,
                    (unsigned long long)hdr->ts,
                    hdr->fp_power1, hdr->fp_power2, hdr->fp_power3);
        }

        if (json_out) {
            printf("{\"capture\":%d,\"count\":%u,\"fp_index\":%u,"
                   "\"pdoa\":%u,\"acc\":%u,\"ts\":%llu,"
                   "\"fp_power\":[%u,%u,%u],\"offset\":%d,"
                   "\"records\":[",
                   cap, hdr->count, hdr->fp_index, hdr->pdoa,
                   hdr->acc, (unsigned long long)hdr->ts,
                   hdr->fp_power1, hdr->fp_power2, hdr->fp_power3,
                   hdr->offset);
        }

        for (int i = 0; i < nrec; i++) {
            double re = fixed_to_double(records[i].real);
            double im = fixed_to_double(records[i].imag);
            double mag = sqrt(re * re + im * im);
            double phase = atan2(im, re);

            if (json_out) {
                if (i > 0) printf(",");
                printf("{\"i\":%d,\"re\":%.6f,\"im\":%.6f,"
                       "\"mag\":%.6f,\"phase\":%.4f}", i, re, im, mag, phase);
            } else {
                printf("%d,%d,%.6f,%.6f,%.6f,%.4f,%u,%u,%u,%u,%u,%u,%llu\n",
                       cap, i, re, im, mag, phase,
                       hdr->fp_index, hdr->fp_power1, hdr->fp_power2,
                       hdr->fp_power3, hdr->pdoa, hdr->acc,
                       (unsigned long long)hdr->ts);
            }
        }

        if (json_out) printf("]}\n");
    }

    free(buf);
    return 0;
}
