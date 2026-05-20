/*
 * cir_reader.c -- Read CIR data from debugfs with proper blocking
 *
 * Opens /sys/kernel/debug/dw3000/cir_data and reads in blocking mode.
 * The read blocks until CIR data is available (signaled by the driver
 * via complete()). Prints raw hex data when received.
 *
 * Usage: cir_reader [timeout_secs]
 *   Default timeout: 10 seconds (uses alarm(), not killing the read)
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <fcntl.h>
#include <unistd.h>
#include <signal.h>
#include <errno.h>

#define CIR_PATH "/sys/kernel/debug/dw3000/cir_data"
#define BUF_SIZE 4096

static volatile int timed_out = 0;

static void alarm_handler(int sig) {
    (void)sig;
    timed_out = 1;
}

int main(int argc, char **argv) {
    int timeout = argc > 1 ? atoi(argv[1]) : 10;
    char buf[BUF_SIZE];

    printf("Opening %s (timeout %ds)...\n", CIR_PATH, timeout);

    int fd = open(CIR_PATH, O_RDONLY);
    if (fd < 0) {
        perror("open");
        return 1;
    }
    printf("File opened (fd=%d). Waiting for CIR data...\n", fd);

    signal(SIGALRM, alarm_handler);
    alarm(timeout);

    ssize_t n = read(fd, buf, sizeof(buf));
    int err = errno;

    alarm(0);

    if (n < 0) {
        if (timed_out || err == EINTR) {
            printf("Timeout: no CIR data received in %ds\n", timeout);
        } else {
            printf("Read error: %d (%s)\n", err, strerror(err));
        }
        close(fd);
        return 1;
    }

    if (n == 0) {
        printf("Read returned 0 bytes (EOF)\n");
        close(fd);
        return 1;
    }

    printf("CIR DATA RECEIVED: %zd bytes!\n", n);
    for (ssize_t i = 0; i < n && i < 512; i++) {
        printf("%02x", (unsigned char)buf[i]);
        if ((i + 1) % 32 == 0) printf("\n");
        else if ((i + 1) % 4 == 0) printf(" ");
    }
    if (n > 512) printf("\n... (%zd more bytes)", n - 512);
    printf("\n");

    close(fd);
    return 0;
}
