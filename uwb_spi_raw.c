/*
 * uwb_spi_raw.c -- Direct SPI register access to DW3000
 *
 * Session 2, Experiment E008: Raw SPI communication with DW3000 via spidev.
 *
 * This tool bypasses the full ieee802154/mcps/dw3000 kernel driver stack
 * and talks directly to the DW3000 UWB chip via /dev/spidevN.N.
 *
 * Requires: CONFIG_SPI_SPIDEV=y in kernel, and spidev bound to spi16.0
 *
 * To bind spidev to the DW3000 SPI device:
 *   echo spidev > /sys/bus/spi/devices/spi16.0/driver_override
 *   echo spi16.0 > /sys/bus/spi/drivers/spidev/bind
 *
 * DW3000 SPI protocol:
 *   - 1-byte header for short addresses (< 0x80): [0:RW][6:0 addr]
 *   - 2-byte header for full addresses: [1:0x80|addr_hi][7:0 addr_lo]
 *   - 6-byte header for sub-addresses: complex encoding
 *   - SPI mode 0, MSB first, max 38.4 MHz
 *
 * Key registers:
 *   0x00:00  DEV_ID (4 bytes) - should read 0xDECA0302 for DW3000
 *   0x0F:00  SYS_CFG (4 bytes) - system configuration
 *   0x15:00  CIR_RAM - channel impulse response memory
 *   0x18:00  DB_DIAG - diagnostic data
 *
 * Usage:
 *   uwb_spi_raw                      # read DEV_ID (chip identification)
 *   uwb_spi_raw -r 0x00              # read register at file_id 0x00
 *   uwb_spi_raw -r 0x15 -l 128      # read 128 bytes from CIR_RAM
 *   uwb_spi_raw -d /dev/spidev16.0   # explicit device path
 *   uwb_spi_raw --scan               # scan all register file IDs
 *
 * Build:  make uwb_spi_raw
 * Deploy: adb push uwb_spi_raw /data/local/tmp/
 * Run:    adb shell su -c /data/local/tmp/uwb_spi_raw
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <fcntl.h>
#include <unistd.h>
#include <errno.h>
#include <getopt.h>
#include <stdint.h>
#include <sys/ioctl.h>
#include <linux/spi/spidev.h>

/* DW3000 SPI header encoding
 * Short header (1 byte): for file IDs 0x00-0x7F, offset 0
 *   bit 7: 0=read, 1=write
 *   bits 6:0: file_id
 *
 * Full header (2 bytes): for file IDs with sub-address
 *   byte 0: 0x80 | (file_id >> 1)
 *   byte 1: (file_id << 7) | (sub_addr >> 2) | mode_bits
 *   (more complex for extended addresses)
 */

/* DW3000 known device IDs */
#define DW3000_DEV_ID_EXPECTED 0x00030000  /* RIDTAG for DW3000 */
#define DW3000_CHIP_C0  0xDECA0302
#define DW3000_CHIP_D0  0xDECA0312
#define DW3000_CHIP_E0  0xDECA0322

/* SPI configuration for DW3000 */
#define DW3000_SPI_MODE     SPI_MODE_0
#define DW3000_SPI_BITS     8
#define DW3000_SPI_SPEED    7000000  /* 7 MHz (safe default, max is 38.4 MHz) */

static int spi_fd = -1;

static int spi_open(const char *dev) {
    spi_fd = open(dev, O_RDWR);
    if (spi_fd < 0) {
        fprintf(stderr, "Cannot open %s: %s\n", dev, strerror(errno));
        return -1;
    }

    uint8_t mode = DW3000_SPI_MODE;
    uint8_t bits = DW3000_SPI_BITS;
    uint32_t speed = DW3000_SPI_SPEED;

    ioctl(spi_fd, SPI_IOC_WR_MODE, &mode);
    ioctl(spi_fd, SPI_IOC_WR_BITS_PER_WORD, &bits);
    ioctl(spi_fd, SPI_IOC_WR_MAX_SPEED_HZ, &speed);

    return 0;
}

/* DW3000 fast read: file_id (short header, offset 0, read mode)
 * For simple register reads at offset 0:
 *   TX: [file_id & 0x3F] [dummy bytes...]
 *   RX: [ignored]         [data bytes...]
 */
static int dw3000_read_short(uint8_t file_id, uint8_t *buf, size_t len) {
    uint8_t tx[258] = {0};
    uint8_t rx[258] = {0};

    /* Short header: bit 7=0 (read), bits 6:1 = file_id, bit 0 = 0 */
    tx[0] = (file_id & 0x3F) << 1;

    struct spi_ioc_transfer xfer = {
        .tx_buf = (unsigned long)tx,
        .rx_buf = (unsigned long)rx,
        .len = 1 + len,  /* 1 header byte + data */
        .speed_hz = DW3000_SPI_SPEED,
        .bits_per_word = 8,
    };

    if (ioctl(spi_fd, SPI_IOC_MESSAGE(1), &xfer) < 0) {
        fprintf(stderr, "SPI transfer failed: %s\n", strerror(errno));
        return -1;
    }

    memcpy(buf, rx + 1, len);  /* Skip header byte in response */
    return 0;
}

/* DW3000 full address read: file_id + sub_address
 * 2-byte header for sub-addressed reads:
 *   byte 0: 0x40 | (file_id & 0x1F) << 1 | (sub_addr >> 6) & 1
 *   byte 1: (sub_addr & 0x3F) << 2 | mode
 * Wait 1 dummy byte before data
 */
static int dw3000_read_full(uint8_t file_id, uint16_t sub_addr,
                             uint8_t *buf, size_t len) {
    uint8_t tx[4 + 1024] = {0};
    uint8_t rx[4 + 1024] = {0};

    if (sub_addr == 0) {
        /* Short header when no sub-address needed */
        return dw3000_read_short(file_id, buf, len);
    }

    /* Extended address header (2 bytes + addr extension if needed) */
    tx[0] = 0x40 | ((file_id & 0x1F) << 1) | ((sub_addr >> 6) & 0x01);
    tx[1] = (sub_addr & 0x3F) << 2;  /* mode bits = 00 (read, no addr ext) */

    int hdr_len = 2;

    struct spi_ioc_transfer xfer = {
        .tx_buf = (unsigned long)tx,
        .rx_buf = (unsigned long)rx,
        .len = hdr_len + len,
        .speed_hz = DW3000_SPI_SPEED,
        .bits_per_word = 8,
    };

    if (ioctl(spi_fd, SPI_IOC_MESSAGE(1), &xfer) < 0) {
        fprintf(stderr, "SPI transfer failed: %s\n", strerror(errno));
        return -1;
    }

    memcpy(buf, rx + hdr_len, len);
    return 0;
}

static void print_hex(const uint8_t *buf, size_t len, const char *prefix) {
    printf("%s", prefix);
    for (size_t i = 0; i < len; i++) {
        printf("%02x", buf[i]);
        if ((i + 1) % 16 == 0 && i + 1 < len) printf("\n%s", prefix);
        else if ((i + 1) % 4 == 0 && i + 1 < len) printf(" ");
    }
    printf("\n");
}

static int read_dev_id(void) {
    uint8_t buf[4] = {0};
    if (dw3000_read_short(0x00, buf, 4) < 0)
        return -1;

    uint32_t dev_id = buf[0] | (buf[1] << 8) | (buf[2] << 16) | (buf[3] << 24);
    printf("DEV_ID: 0x%08X\n", dev_id);

    if (dev_id == DW3000_CHIP_C0) printf("  Chip: DW3000 C0\n");
    else if (dev_id == DW3000_CHIP_D0) printf("  Chip: DW3000 D0\n");
    else if (dev_id == DW3000_CHIP_E0) printf("  Chip: DW3000 E0\n");
    else if ((dev_id & 0xFFFF0000) == 0xDECA0000) printf("  Chip: Decawave (variant 0x%04X)\n", dev_id & 0xFFFF);
    else if (dev_id == 0x00000000) printf("  WARNING: All zeros -- chip may be powered off or SPI not working\n");
    else if (dev_id == 0xFFFFFFFF) printf("  WARNING: All ones -- chip may be powered off or SPI bus disconnected\n");
    else printf("  Unknown device ID\n");

    return 0;
}

static void scan_registers(void) {
    printf("=== Register Scan ===\n");
    printf("FileID  Value (first 4 bytes)\n");
    for (int fid = 0; fid < 0x40; fid++) {
        uint8_t buf[4] = {0};
        if (dw3000_read_short(fid, buf, 4) == 0) {
            uint32_t val = buf[0] | (buf[1] << 8) | (buf[2] << 16) | (buf[3] << 24);
            if (val != 0x00000000 && val != 0xFFFFFFFF)
                printf("  0x%02X:  0x%08X\n", fid, val);
        }
    }
}

static const char *find_spidev(void) {
    /* Try common paths */
    static const char *paths[] = {
        "/dev/spidev16.0",
        "/dev/spidev0.0",
        "/dev/spidev1.0",
        NULL
    };
    for (int i = 0; paths[i]; i++) {
        if (access(paths[i], F_OK) == 0)
            return paths[i];
    }
    return NULL;
}

static void usage(const char *prog) {
    fprintf(stderr, "Usage: %s [options]\n", prog);
    fprintf(stderr, "  -d DEVICE  spidev device (default: auto-detect)\n");
    fprintf(stderr, "  -r FILE_ID read register at file_id (hex)\n");
    fprintf(stderr, "  -s SUB_ADDR sub-address within file (hex, default 0)\n");
    fprintf(stderr, "  -l LEN     bytes to read (default 4)\n");
    fprintf(stderr, "  --scan     scan all register file IDs\n");
    fprintf(stderr, "  --bind     bind spidev to spi16.0 first\n");
    fprintf(stderr, "  -h         help\n");
}

int main(int argc, char *argv[]) {
    const char *device = NULL;
    int file_id = -1;
    int sub_addr = 0;
    int read_len = 4;
    int do_scan = 0;
    int do_bind = 0;

    static struct option long_opts[] = {
        {"scan", no_argument, 0, 'S'},
        {"bind", no_argument, 0, 'B'},
        {0, 0, 0, 0}
    };

    int opt;
    while ((opt = getopt_long(argc, argv, "d:r:s:l:h", long_opts, NULL)) != -1) {
        switch (opt) {
        case 'd': device = optarg; break;
        case 'r': file_id = strtol(optarg, NULL, 16); break;
        case 's': sub_addr = strtol(optarg, NULL, 16); break;
        case 'l': read_len = atoi(optarg); break;
        case 'S': do_scan = 1; break;
        case 'B': do_bind = 1; break;
        default: usage(argv[0]); return 1;
        }
    }

    /* Auto-bind spidev to DW3000 SPI device */
    if (do_bind) {
        printf("Binding spidev to spi16.0...\n");
        FILE *f;
        f = fopen("/sys/bus/spi/devices/spi16.0/driver_override", "w");
        if (f) { fprintf(f, "spidev"); fclose(f); }
        else { fprintf(stderr, "Cannot write driver_override: %s\n", strerror(errno)); }

        f = fopen("/sys/bus/spi/drivers/spidev/bind", "w");
        if (f) { fprintf(f, "spi16.0"); fclose(f); }
        else { fprintf(stderr, "Cannot bind: %s\n", strerror(errno)); }

        /* Wait for device node to appear */
        usleep(100000);
    }

    if (!device) {
        device = find_spidev();
        if (!device) {
            fprintf(stderr, "No spidev device found.\n");
            fprintf(stderr, "Ensure CONFIG_SPI_SPIDEV=y and bind with --bind flag.\n");
            fprintf(stderr, "Or specify device: -d /dev/spidevN.N\n");
            return 1;
        }
    }

    printf("DW3000 SPI raw access via %s\n\n", device);

    if (spi_open(device) < 0)
        return 1;

    if (do_scan) {
        scan_registers();
    } else if (file_id >= 0) {
        uint8_t buf[1024] = {0};
        if (read_len > (int)sizeof(buf)) read_len = sizeof(buf);
        printf("Reading file_id=0x%02X sub=0x%04X len=%d:\n", file_id, sub_addr, read_len);
        if (dw3000_read_full(file_id, sub_addr, buf, read_len) == 0) {
            print_hex(buf, read_len, "  ");
        }
    } else {
        /* Default: read chip ID */
        read_dev_id();
    }

    close(spi_fd);
    return 0;
}
