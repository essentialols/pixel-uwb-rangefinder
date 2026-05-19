/* uwb_rx_start.c -- Start DW3000 RX diagnostics via nl802154 testmode */
#include <stdio.h>
#include <string.h>
#include <unistd.h>
#include <sys/socket.h>
#include <linux/netlink.h>
#include <linux/genetlink.h>
#include <stdint.h>
#include <errno.h>

#define NL802154_CMD_TESTMODE 26
#define NL802154_ATTR_WPAN_PHY 1
#define NL802154_ATTR_TESTDATA 55
#define DW3000_TM_ATTR_CMD 1

enum { START=1, STOP=2, GET=3, CLEAR=4 };

static int nl_sock;
static uint16_t family_id;

static int resolve_family(const char *name) {
    struct { struct nlmsghdr n; struct genlmsghdr g; char attrs[64]; } req;
    memset(&req, 0, sizeof(req));
    int nlen = strlen(name)+1;
    int alen = (4+nlen+3)&~3;
    req.n.nlmsg_len = NLMSG_LENGTH(GENL_HDRLEN) + alen;
    req.n.nlmsg_type = GENL_ID_CTRL;
    req.n.nlmsg_flags = NLM_F_REQUEST;
    req.n.nlmsg_seq = 1;
    req.g.cmd = 3; /* CTRL_CMD_GETFAMILY */
    req.g.version = 1;
    struct nlattr *a = (void*)req.attrs;
    a->nla_len = 4+nlen; a->nla_type = 2; /* CTRL_ATTR_FAMILY_NAME */
    memcpy((char*)a+4, name, nlen);
    send(nl_sock, &req, req.n.nlmsg_len, 0);
    char buf[4096]; int len = recv(nl_sock, buf, sizeof(buf), 0);
    if (len < 0) return -1;
    struct nlmsghdr *h = (void*)buf;
    if (h->nlmsg_type == NLMSG_ERROR) return -1;
    int off = NLMSG_HDRLEN + GENL_HDRLEN;
    while (off < len) {
        struct nlattr *at = (void*)(buf+off);
        if (at->nla_type == 1) return *(uint16_t*)(buf+off+4); /* FAMILY_ID */
        off += (at->nla_len+3)&~3;
    }
    return -1;
}

static int send_tm(int cmd) {
    char buf[256];
    memset(buf, 0, sizeof(buf));
    struct nlmsghdr *nlh = (void*)buf;
    struct genlmsghdr *gh = NLMSG_DATA(nlh);
    
    gh->cmd = NL802154_CMD_TESTMODE;
    gh->version = 1;
    
    int off = NLMSG_HDRLEN + GENL_HDRLEN;
    
    /* NL802154_ATTR_WPAN_PHY = 0 (phy0) */
    struct nlattr *a = (void*)(buf+off);
    a->nla_len = 4+4; a->nla_type = NL802154_ATTR_WPAN_PHY;
    *(uint32_t*)((char*)a+4) = 0;
    off += (a->nla_len+3)&~3;
    
    /* NL802154_ATTR_TESTDATA (nested) containing DW3000_TM_ATTR_CMD */
    struct nlattr *nest = (void*)(buf+off);
    int nest_start = off;
    off += 4; /* nla header for nested */
    
    struct nlattr *tc = (void*)(buf+off);
    tc->nla_len = 4+4; tc->nla_type = DW3000_TM_ATTR_CMD;
    *(uint32_t*)((char*)tc+4) = cmd;
    off += (tc->nla_len+3)&~3;
    
    nest->nla_len = off - nest_start;
    nest->nla_type = NL802154_ATTR_TESTDATA | 0x8000; /* NLA_F_NESTED */
    
    nlh->nlmsg_len = off;
    nlh->nlmsg_type = family_id;
    nlh->nlmsg_flags = NLM_F_REQUEST;
    nlh->nlmsg_seq = 2;
    
    if (send(nl_sock, buf, off, 0) < 0) { perror("send"); return -1; }
    
    char resp[4096];
    int rlen = recv(nl_sock, resp, sizeof(resp), 0);
    if (rlen < 0) { perror("recv"); return -1; }
    
    struct nlmsghdr *rh = (void*)resp;
    if (rh->nlmsg_type == NLMSG_ERROR) {
        int err = *(int*)(resp+NLMSG_HDRLEN);
        return err;
    }
    
    /* Parse GET_RX_DIAG response */
    if (cmd == GET) {
        int roff = NLMSG_HDRLEN + GENL_HDRLEN;
        while (roff < rlen) {
            struct nlattr *ra = (void*)(resp+roff);
            printf("  attr type=%d len=%d\n", ra->nla_type & 0x7FFF, ra->nla_len);
            if ((ra->nla_type & 0x7FFF) == NL802154_ATTR_TESTDATA) {
                /* Parse nested testdata */
                int ioff = roff + 4;
                int iend = roff + ra->nla_len;
                while (ioff < iend) {
                    struct nlattr *ia = (void*)(resp+ioff);
                    int t = ia->nla_type & 0x7FFF;
                    if (t == 2) printf("    RX_GOOD_CNT: %u\n", *(uint32_t*)(resp+ioff+4));
                    else if (t == 3) printf("    RX_BAD_CNT: %u\n", *(uint32_t*)(resp+ioff+4));
                    else if (t == 4) {
                        int dlen = ia->nla_len - 4;
                        printf("    RSSI_DATA: %d bytes\n", dlen);
                        /* Parse RSSI entries */
                        uint8_t *d = (uint8_t*)(resp+ioff+4);
                        int n = dlen / 4;
                        for (int i = 0; i < n && i < 10; i++) {
                            uint32_t v = *(uint32_t*)(d + i*4);
                            uint32_t cir_pwr = v & 0x1FFFF;
                            uint16_t pacc = (v >> 17) & 0x7FF;
                            printf("      [%d] cir_pwr=%u pacc=%u\n", i, cir_pwr, pacc);
                        }
                    }
                    ioff += (ia->nla_len+3)&~3;
                }
            }
            roff += (ra->nla_len+3)&~3;
        }
    }
    return 0;
}

int main(int argc, char **argv) {
    int cmd = START;
    if (argc > 1) {
        if (!strcmp(argv[1],"stop")) cmd = STOP;
        else if (!strcmp(argv[1],"get")) cmd = GET;
        else if (!strcmp(argv[1],"clear")) cmd = CLEAR;
    }
    
    nl_sock = socket(AF_NETLINK, SOCK_RAW, NETLINK_GENERIC);
    struct sockaddr_nl sa = {.nl_family=AF_NETLINK};
    bind(nl_sock, (void*)&sa, sizeof(sa));
    
    int fid = resolve_family("nl802154");
    if (fid < 0) { fprintf(stderr,"Cannot resolve nl802154\n"); return 1; }
    family_id = fid;
    printf("nl802154 family: %d\n", fid);
    
    const char *names[] = {"?","START_RX_DIAG","STOP_RX_DIAG","GET_RX_DIAG","CLEAR_RX_DIAG"};
    printf("Sending %s...\n", names[cmd]);
    int rc = send_tm(cmd);
    printf("Result: %d (%s)\n", rc, rc==0?"OK":strerror(-rc));
    
    close(nl_sock);
    return rc != 0;
}
