/*
 * cir_stream.c -- Continuous CIR capture from DW3000 via debugfs
 *
 * Reads CIR data in a loop, outputting binary frames to stdout.
 * Each frame: 4-byte frame length (LE) + raw CIR data.
 * Use with cir_stream_decode.py for real-time analysis.
 *
 * Usage:
 *   cir_stream [max_frames]     # capture max_frames (0 = infinite)
 *   cir_stream 100 > capture.bin
 *   cir_stream 0 | python3 cir_stream_decode.py
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <fcntl.h>
#include <unistd.h>
#include <signal.h>
#include <errno.h>
#include <time.h>
#include <stdint.h>

#define CIR_PATH "/sys/kernel/debug/dw3000/cir_data"
#define BUF_SIZE 16384

static volatile int running = 1;

static void sighandler(int sig) {
    (void)sig;
    running = 0;
}

int main(int argc, char **argv) {
    int max_frames = argc > 1 ? atoi(argv[1]) : 0;
    char buf[BUF_SIZE];
    int frame_count = 0;
    struct timespec t0, t1;

    signal(SIGINT, sighandler);
    signal(SIGTERM, sighandler);

    clock_gettime(CLOCK_MONOTONIC, &t0);

    fprintf(stderr, "CIR stream: capturing %s frames\n",
            max_frames > 0 ? "" : "unlimited");

    while (running && (max_frames == 0 || frame_count < max_frames)) {
        int fd = open(CIR_PATH, O_RDONLY);
        if (fd < 0) {
            if (errno == EINTR) continue;
            perror("open");
            break;
        }

        ssize_t n = read(fd, buf, sizeof(buf));
        int err = errno;
        close(fd);

        if (n <= 0) {
            if (err == EINTR || err == EAGAIN) continue;
            fprintf(stderr, "Read error after %d frames: %s\n",
                    frame_count, strerror(err));
            usleep(100000);
            continue;
        }

        uint32_t len = (uint32_t)n;
        fwrite(&len, 4, 1, stdout);
        fwrite(buf, 1, n, stdout);
        fflush(stdout);

        frame_count++;
        if (frame_count % 10 == 0) {
            clock_gettime(CLOCK_MONOTONIC, &t1);
            double elapsed = (t1.tv_sec - t0.tv_sec) +
                           (t1.tv_nsec - t0.tv_nsec) / 1e9;
            fprintf(stderr, "  %d frames in %.1fs (%.1f fps)\n",
                    frame_count, elapsed, frame_count / elapsed);
        }
    }

    clock_gettime(CLOCK_MONOTONIC, &t1);
    double elapsed = (t1.tv_sec - t0.tv_sec) +
                   (t1.tv_nsec - t0.tv_nsec) / 1e9;
    fprintf(stderr, "Done: %d frames in %.1fs (%.1f fps)\n",
            frame_count, elapsed,
            elapsed > 0 ? frame_count / elapsed : 0);

    return 0;
}
