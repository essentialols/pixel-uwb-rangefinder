/* Try to receive a raw 802.15.4 frame on wpan0 */
#include <stdio.h>
#include <string.h>
#include <unistd.h>
#include <sys/socket.h>
#include <linux/if_packet.h>
#include <net/if.h>
#include <errno.h>
#include <sys/ioctl.h>
#include <signal.h>

static volatile int running = 1;
static void sighandler(int s) { (void)s; running = 0; }

int main(void) {
    /* Open a raw 802.15.4 socket */
    int fd = socket(AF_PACKET, SOCK_RAW, 0);
    if (fd < 0) { 
        perror("socket(AF_PACKET)");
        /* Try AF_IEEE802154 */
        fd = socket(PF_IEEE802154, SOCK_DGRAM, 0);
        if (fd < 0) { perror("socket(PF_IEEE802154)"); return 1; }
        printf("Using PF_IEEE802154 socket\n");
    } else {
        printf("Using AF_PACKET raw socket\n");
    }
    
    /* Bind to wpan0 */
    struct ifreq ifr;
    memset(&ifr, 0, sizeof(ifr));
    strcpy(ifr.ifr_name, "wpan0");
    if (ioctl(fd, SIOCGIFINDEX, &ifr) < 0) {
        perror("ioctl(SIOCGIFINDEX)");
        close(fd);
        return 1;
    }
    printf("wpan0 ifindex: %d\n", ifr.ifr_ifindex);
    
    struct sockaddr_ll sll;
    memset(&sll, 0, sizeof(sll));
    sll.sll_family = AF_PACKET;
    sll.sll_ifindex = ifr.ifr_ifindex;
    sll.sll_protocol = 0; /* all protocols */
    if (bind(fd, (void*)&sll, sizeof(sll)) < 0) {
        perror("bind");
    }
    
    /* Set promiscuous mode */
    struct packet_mreq mreq;
    memset(&mreq, 0, sizeof(mreq));
    mreq.mr_ifindex = ifr.ifr_ifindex;
    mreq.mr_type = PACKET_MR_PROMISC;
    setsockopt(fd, SOL_PACKET, PACKET_ADD_MEMBERSHIP, &mreq, sizeof(mreq));
    
    signal(SIGALRM, sighandler);
    alarm(5); /* 5 second timeout */
    
    printf("Listening on wpan0 for 5 seconds...\n");
    char buf[256];
    while (running) {
        int n = recv(fd, buf, sizeof(buf), 0);
        if (n < 0) {
            if (errno == EINTR) break;
            perror("recv");
            break;
        }
        printf("Received %d bytes!\n", n);
        for (int i = 0; i < n && i < 64; i++)
            printf("%02x ", (unsigned char)buf[i]);
        printf("\n");
    }
    printf("Done. Checking trace for DW3000 activity...\n");
    
    close(fd);
    return 0;
}
