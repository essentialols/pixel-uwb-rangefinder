/*
 * uwb_nl_probe.c -- Probe mcps802154 and nl802154 netlink families
 *
 * Session 2, Experiment E010: Verify netlink access to mcps802154 scheduler.
 * Resolves both generic netlink families, lists available multicast groups,
 * and optionally queries the current scheduler and region configuration.
 *
 * This is a lightweight prerequisite check before running uwb_pctt_rx.
 *
 * Build:  make uwb_nl_probe
 * Deploy: adb push uwb_nl_probe /data/local/tmp/
 * Run:    adb shell su -c /data/local/tmp/uwb_nl_probe
 */

#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <string.h>
#include <unistd.h>
#include <errno.h>
#include <sys/socket.h>
#include <linux/netlink.h>
#include <linux/genetlink.h>

/* mcps802154 commands from net/mcps802154/nl_mcps802154.h */
enum mcps802154_cmd {
    MCPS802154_CMD_GET_HW = 0,
    MCPS802154_CMD_SET_SCHEDULER = 1,
    MCPS802154_CMD_SET_SCHEDULER_REGIONS = 2,
    MCPS802154_CMD_SET_SCHEDULER_PARAMS = 3,
    MCPS802154_CMD_SET_REGIONS_PARAMS = 4,
    MCPS802154_CMD_CALL_SCHEDULER = 5,
    MCPS802154_CMD_CALL_REGION = 6,
    MCPS802154_CMD_TESTMODE = 7,
    MCPS802154_CMD_SET_CALIBRATIONS = 8,
    MCPS802154_CMD_GET_CALIBRATIONS = 9,
    MCPS802154_CMD_LIST_CALIBRATIONS = 10,
};

enum mcps802154_attr {
    MCPS802154_ATTR_HW = 1,
    MCPS802154_ATTR_WPAN_PHY_NAME,
    MCPS802154_ATTR_SCHEDULER_NAME,
    MCPS802154_ATTR_SCHEDULER_PARAMS,
    MCPS802154_ATTR_SCHEDULER_REGION_CALL_ID,
    MCPS802154_ATTR_SCHEDULER_REGION_ID,
    MCPS802154_ATTR_SCHEDULER_REGION_PARAMS,
    MCPS802154_ATTR_SCHEDULER_REGIONS,
    MCPS802154_ATTR_TESTMODE_DATA,
    MCPS802154_ATTR_CALIBRATIONS,
};

#ifndef NLA_HDRLEN
#define NLA_HDRLEN 4
#endif
#ifndef NLA_ALIGN
#define NLA_ALIGN(len) (((len) + 3) & ~3)
#endif

static int nl_sock = -1;
static uint32_t nl_seq = 0;
static uint32_t nl_pid = 0;

static int nl_open(void) {
    struct sockaddr_nl sa = { .nl_family = AF_NETLINK, .nl_pid = 0 };
    nl_sock = socket(AF_NETLINK, SOCK_RAW, NETLINK_GENERIC);
    if (nl_sock < 0) { perror("socket"); return -1; }
    if (bind(nl_sock, (struct sockaddr *)&sa, sizeof(sa)) < 0) {
        perror("bind"); close(nl_sock); return -1;
    }
    struct sockaddr_nl bound;
    socklen_t len = sizeof(bound);
    getsockname(nl_sock, (struct sockaddr *)&bound, &len);
    nl_pid = bound.nl_pid;
    return 0;
}

static int nl_send_recv(void *req, int req_len, void *resp, int resp_len) {
    struct sockaddr_nl sa = { .nl_family = AF_NETLINK };
    if (sendto(nl_sock, req, req_len, 0, (struct sockaddr *)&sa, sizeof(sa)) < 0) {
        perror("sendto"); return -1;
    }
    int n = recv(nl_sock, resp, resp_len, 0);
    if (n < 0) { perror("recv"); return -1; }
    return n;
}

static uint16_t resolve_family(const char *name) {
    char buf[1024];
    memset(buf, 0, sizeof(buf));
    struct nlmsghdr *nlh = (void *)buf;
    struct genlmsghdr *genl = (void *)(buf + sizeof(*nlh));

    nlh->nlmsg_len = sizeof(*nlh) + sizeof(*genl) + NLA_ALIGN(NLA_HDRLEN + strlen(name) + 1);
    nlh->nlmsg_type = GENL_ID_CTRL;
    nlh->nlmsg_flags = NLM_F_REQUEST;
    nlh->nlmsg_seq = ++nl_seq;
    nlh->nlmsg_pid = nl_pid;
    genl->cmd = CTRL_CMD_GETFAMILY;
    genl->version = 1;

    struct nlattr *nla = (void *)(buf + sizeof(*nlh) + sizeof(*genl));
    nla->nla_len = NLA_HDRLEN + strlen(name) + 1;
    nla->nla_type = CTRL_ATTR_FAMILY_NAME;
    memcpy((char *)nla + NLA_HDRLEN, name, strlen(name) + 1);

    char resp[4096];
    int n = nl_send_recv(buf, nlh->nlmsg_len, resp, sizeof(resp));
    if (n < 0) return 0;

    struct nlmsghdr *rnlh = (void *)resp;
    if (rnlh->nlmsg_type == NLMSG_ERROR) {
        struct nlmsgerr *err = (void *)((char *)rnlh + sizeof(*rnlh));
        fprintf(stderr, "  resolve %s: error %d (%s)\n", name, -err->error, strerror(-err->error));
        return 0;
    }

    /* Parse CTRL_ATTR_FAMILY_ID from response */
    int off = sizeof(struct nlmsghdr) + sizeof(struct genlmsghdr);
    while (off + NLA_HDRLEN <= n) {
        struct nlattr *a = (void *)(resp + off);
        if (a->nla_len < NLA_HDRLEN) break;
        if (a->nla_type == CTRL_ATTR_FAMILY_ID) {
            uint16_t id;
            memcpy(&id, (char *)a + NLA_HDRLEN, 2);
            return id;
        }
        /* Print multicast groups */
        if (a->nla_type == CTRL_ATTR_MCAST_GROUPS) {
            printf("  multicast groups present\n");
        }
        off += NLA_ALIGN(a->nla_len);
    }
    return 0;
}

/* Send GET_HW to mcps802154 to query PHY info */
static int query_hw(uint16_t family_id) {
    char buf[512];
    memset(buf, 0, sizeof(buf));
    struct nlmsghdr *nlh = (void *)buf;
    struct genlmsghdr *genl = (void *)(buf + sizeof(*nlh));

    /* Add MCPS802154_ATTR_HW = 0 (first PHY) */
    int attr_off = sizeof(*nlh) + sizeof(*genl);
    struct nlattr *nla = (void *)(buf + attr_off);
    nla->nla_len = NLA_HDRLEN + 4;
    nla->nla_type = MCPS802154_ATTR_HW;
    uint32_t hw = 0;
    memcpy(buf + attr_off + NLA_HDRLEN, &hw, 4);
    int payload = NLA_ALIGN(nla->nla_len);

    nlh->nlmsg_len = attr_off + payload;
    nlh->nlmsg_type = family_id;
    nlh->nlmsg_flags = NLM_F_REQUEST;
    nlh->nlmsg_seq = ++nl_seq;
    nlh->nlmsg_pid = nl_pid;
    genl->cmd = MCPS802154_CMD_GET_HW;
    genl->version = 1;

    char resp[4096];
    int n = nl_send_recv(buf, nlh->nlmsg_len, resp, sizeof(resp));
    if (n < 0) return -1;

    struct nlmsghdr *rnlh = (void *)resp;
    if (rnlh->nlmsg_type == NLMSG_ERROR) {
        struct nlmsgerr *err = (void *)((char *)rnlh + sizeof(*rnlh));
        if (err->error == 0) {
            printf("  GET_HW: ACK (success)\n");
            return 0;
        }
        printf("  GET_HW: error %d (%s)\n", -err->error, strerror(-err->error));
        return err->error;
    }

    /* Parse response for PHY name */
    int off = sizeof(struct nlmsghdr) + sizeof(struct genlmsghdr);
    while (off + NLA_HDRLEN <= n) {
        struct nlattr *a = (void *)(resp + off);
        if (a->nla_len < NLA_HDRLEN) break;
        if (a->nla_type == MCPS802154_ATTR_WPAN_PHY_NAME) {
            char *phy_name = (char *)a + NLA_HDRLEN;
            printf("  PHY name: %s\n", phy_name);
        }
        off += NLA_ALIGN(a->nla_len);
    }
    return 0;
}

/* Send LIST_CALIBRATIONS to get available calibration keys */
static int list_calibrations(uint16_t family_id) {
    char buf[512];
    memset(buf, 0, sizeof(buf));
    struct nlmsghdr *nlh = (void *)buf;
    struct genlmsghdr *genl = (void *)(buf + sizeof(*nlh));

    int attr_off = sizeof(*nlh) + sizeof(*genl);
    struct nlattr *nla = (void *)(buf + attr_off);
    nla->nla_len = NLA_HDRLEN + 4;
    nla->nla_type = MCPS802154_ATTR_HW;
    uint32_t hw = 0;
    memcpy(buf + attr_off + NLA_HDRLEN, &hw, 4);
    int payload = NLA_ALIGN(nla->nla_len);

    nlh->nlmsg_len = attr_off + payload;
    nlh->nlmsg_type = family_id;
    nlh->nlmsg_flags = NLM_F_REQUEST | NLM_F_DUMP;
    nlh->nlmsg_seq = ++nl_seq;
    nlh->nlmsg_pid = nl_pid;
    genl->cmd = MCPS802154_CMD_LIST_CALIBRATIONS;
    genl->version = 1;

    char resp[8192];
    int n = nl_send_recv(buf, nlh->nlmsg_len, resp, sizeof(resp));
    if (n < 0) return -1;

    struct nlmsghdr *rnlh = (void *)resp;
    if (rnlh->nlmsg_type == NLMSG_ERROR) {
        struct nlmsgerr *err = (void *)((char *)rnlh + sizeof(*rnlh));
        if (err->error == 0) {
            printf("  LIST_CALIBRATIONS: ACK\n");
            return 0;
        }
        printf("  LIST_CALIBRATIONS: error %d (%s)\n", -err->error, strerror(-err->error));
        return err->error;
    }

    /* Parse calibration key list */
    printf("  LIST_CALIBRATIONS response (%d bytes):\n", n);
    int off = sizeof(struct nlmsghdr) + sizeof(struct genlmsghdr);
    while (off + NLA_HDRLEN <= n) {
        struct nlattr *a = (void *)(resp + off);
        if (a->nla_len < NLA_HDRLEN) break;
        if (a->nla_type == MCPS802154_ATTR_CALIBRATIONS) {
            /* Nested: iterate sub-attrs for key names */
            int inner_off = off + NLA_HDRLEN;
            int inner_end = off + a->nla_len;
            while (inner_off + NLA_HDRLEN <= inner_end) {
                struct nlattr *sub = (void *)(resp + inner_off);
                if (sub->nla_len < NLA_HDRLEN) break;
                /* Each sub-attr is a calibration key string */
                char key[128] = {0};
                int key_len = sub->nla_len - NLA_HDRLEN;
                if (key_len > 0 && key_len < (int)sizeof(key)) {
                    memcpy(key, resp + inner_off + NLA_HDRLEN, key_len);
                    printf("    key[%d]: %s\n", sub->nla_type, key);
                }
                inner_off += NLA_ALIGN(sub->nla_len);
            }
        }
        off += NLA_ALIGN(a->nla_len);
    }
    return 0;
}

int main(void) {
    printf("=== UWB Netlink Family Probe ===\n\n");

    if (nl_open() < 0) return 1;

    /* Resolve nl802154 */
    printf("[1] Resolving nl802154...\n");
    uint16_t nl802154_id = resolve_family("nl802154");
    if (nl802154_id) {
        printf("  nl802154 family ID: %u\n", nl802154_id);
    } else {
        printf("  nl802154: NOT FOUND\n");
    }

    /* Resolve mcps802154 */
    printf("\n[2] Resolving mcps802154...\n");
    uint16_t mcps_id = resolve_family("mcps802154");
    if (mcps_id) {
        printf("  mcps802154 family ID: %u\n", mcps_id);
    } else {
        printf("  mcps802154: NOT FOUND\n");
        goto done;
    }

    /* Query HW */
    printf("\n[3] Querying GET_HW...\n");
    query_hw(mcps_id);

    /* List calibrations */
    printf("\n[4] Listing calibrations...\n");
    list_calibrations(mcps_id);

done:
    close(nl_sock);
    printf("\n=== Probe complete ===\n");
    return 0;
}
