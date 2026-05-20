/*
 * pctt_inject.c -- Inject PCTT continuous RX into running FiRa scheduler
 *
 * Different approach from uwb_pctt_rx.c: instead of replacing the scheduler,
 * this tool tries to ADD the PCTT region alongside the existing FiRa region
 * within the running "on_demand" scheduler.
 *
 * Strategy:
 *   1. DO NOT call CMD_SET_SCHEDULER (keeps FiRa's scheduler alive)
 *   2. Call CMD_SET_SCHEDULER_REGIONS with BOTH fira and pctt regions
 *   3. Call CMD_CALL_REGION for PCTT session init + PER_RX
 *
 * This avoids the chip power-down caused by scheduler replacement.
 * If SET_SCHEDULER_REGIONS crashes (as in E018), try:
 *   - Adding only pctt region (not replacing fira)
 *   - Using region_id=1 instead of 0 (separate slot)
 *
 * Alternative strategy (--testmode):
 *   Use MCPS802154_CMD_TESTMODE (cmd 12) instead of PCTT region.
 *   This sends DW3000 testmode commands via the mcps802154 netlink
 *   interface, which might work even when CONFIG_MCPS802154_TESTMODE
 *   is disabled (the dw3000 driver may still handle the command).
 *
 * Usage:
 *   pctt_inject                # try PCTT region injection
 *   pctt_inject --testmode     # try mcps802154 testmode path
 *   pctt_inject --rx-diag      # testmode: start RX diagnostics
 *   pctt_inject --cw           # testmode: start CW tone (TX)
 *
 * Build: aarch64-linux-gnu-gcc -static -o pctt_inject tools/pctt_inject.c
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <errno.h>
#include <getopt.h>
#include <stdint.h>
#include <sys/socket.h>
#include <linux/netlink.h>
#include <linux/genetlink.h>

#define MCPS802154_GENL_NAME "mcps802154"

enum mcps802154_commands {
    MCPS802154_CMD_UNSPEC,
    MCPS802154_CMD_GET_HW,
    MCPS802154_CMD_NEW_HW,
    MCPS802154_CMD_SET_SCHEDULER,
    MCPS802154_CMD_SET_SCHEDULER_PARAMS,
    MCPS802154_CMD_CALL_SCHEDULER,
    MCPS802154_CMD_SET_SCHEDULER_REGIONS,
    MCPS802154_CMD_SET_REGIONS_PARAMS,
    MCPS802154_CMD_CALL_REGION,
    MCPS802154_CMD_SET_CALIBRATIONS,
    MCPS802154_CMD_GET_CALIBRATIONS,
    MCPS802154_CMD_LIST_CALIBRATIONS,
    MCPS802154_CMD_TESTMODE,
    MCPS802154_CMD_CLOSE_SCHEDULER,
    MCPS802154_CMD_GET_PWR_STATS,
};

enum mcps802154_attrs {
    MCPS802154_ATTR_UNSPEC,
    MCPS802154_ATTR_HW,
    MCPS802154_ATTR_WPAN_PHY_NAME,
    MCPS802154_ATTR_SCHEDULER_NAME,
    MCPS802154_ATTR_SCHEDULER_PARAMS,
    MCPS802154_ATTR_SCHEDULER_REGIONS,
    MCPS802154_ATTR_SCHEDULER_CALL,
    MCPS802154_ATTR_SCHEDULER_CALL_PARAMS,
    MCPS802154_ATTR_SCHEDULER_REGION_CALL,
    MCPS802154_ATTR_TESTDATA,
    MCPS802154_ATTR_CALIBRATIONS,
    MCPS802154_ATTR_PWR_STATS,
};

enum mcps802154_region_attrs {
    MCPS802154_REGION_UNSPEC,
    MCPS802154_REGION_ATTR_ID,
    MCPS802154_REGION_ATTR_NAME,
    MCPS802154_REGION_ATTR_PARAMS,
    MCPS802154_REGION_ATTR_CALL,
    MCPS802154_REGION_ATTR_CALL_PARAMS,
};

/* DW3000 testmode commands (from uwb_testmode.c) */
enum dw3000_tm_cmd {
    DW3000_TM_CMD_START_RX_DIAG = 1,
    DW3000_TM_CMD_STOP_RX_DIAG = 2,
    DW3000_TM_CMD_GET_RX_DIAG = 3,
    DW3000_TM_CMD_CLEAR_RX_DIAG = 4,
    DW3000_TM_CMD_OTP_READ = 5,
    DW3000_TM_CMD_OTP_WRITE = 6,
    DW3000_TM_CMD_START_TX_CWTONE = 7,
    DW3000_TM_CMD_STOP_TX_CWTONE = 8,
    DW3000_TM_CMD_START_CONTINUOUS_TX = 9,
    DW3000_TM_CMD_STOP_CONTINUOUS_TX = 10,
};

enum dw3000_tm_attr {
    DW3000_TM_ATTR_CMD = 1,
    DW3000_TM_ATTR_RX_GOOD_CNT = 2,
    DW3000_TM_ATTR_RX_BAD_CNT = 3,
    DW3000_TM_ATTR_RSSI_DATA = 4,
};

struct nl_msg {
    struct nlmsghdr nlh;
    struct genlmsghdr genlh;
    char attrs[4096];
};

static int nl_sock = -1;
static uint16_t family_id = 0;
static uint32_t hw_idx = 0;

static int nl_open(void) {
    nl_sock = socket(AF_NETLINK, SOCK_RAW, NETLINK_GENERIC);
    if (nl_sock < 0) { perror("socket"); return -1; }

    struct sockaddr_nl addr = { .nl_family = AF_NETLINK };
    if (bind(nl_sock, (struct sockaddr *)&addr, sizeof(addr)) < 0) {
        perror("bind"); close(nl_sock); return -1;
    }

    socklen_t addrlen = sizeof(addr);
    getsockname(nl_sock, (struct sockaddr *)&addr, &addrlen);

    return 0;
}

static void *nla_put(void *buf, int *pos, uint16_t type, const void *data, int len) {
    struct nlattr *nla = (struct nlattr *)((char *)buf + *pos);
    nla->nla_len = NLA_HDRLEN + len;
    nla->nla_type = type;
    memcpy((char *)nla + NLA_HDRLEN, data, len);
    *pos += NLA_ALIGN(nla->nla_len);
    return nla;
}

static int resolve_family(const char *name) {
    struct nl_msg msg = {0};
    msg.nlh.nlmsg_type = GENL_ID_CTRL;
    msg.nlh.nlmsg_flags = NLM_F_REQUEST | NLM_F_ACK;
    msg.genlh.cmd = CTRL_CMD_GETFAMILY;
    msg.genlh.version = 1;

    int pos = 0;
    uint16_t slen = strlen(name) + 1;
    nla_put(msg.attrs, &pos, CTRL_ATTR_FAMILY_NAME, name, slen);

    msg.nlh.nlmsg_len = NLMSG_LENGTH(GENL_HDRLEN + pos);

    struct sockaddr_nl dest = { .nl_family = AF_NETLINK };
    sendto(nl_sock, &msg, msg.nlh.nlmsg_len, 0,
           (struct sockaddr *)&dest, sizeof(dest));

    char buf[8192];
    int n = recv(nl_sock, buf, sizeof(buf), 0);
    if (n < 0) return -1;

    struct nlmsghdr *nlh = (struct nlmsghdr *)buf;
    if (nlh->nlmsg_type == GENL_ID_CTRL) {
        struct genlmsghdr *genlh = NLMSG_DATA(nlh);
        struct nlattr *nla = (struct nlattr *)((char *)genlh + GENL_HDRLEN);
        int remaining = nlh->nlmsg_len - NLMSG_HDRLEN - GENL_HDRLEN;
        while (remaining > 0 && nla->nla_len > 0) {
            if (nla->nla_type == CTRL_ATTR_FAMILY_ID) {
                family_id = *(uint16_t *)((char *)nla + NLA_HDRLEN);
                return 0;
            }
            int step = NLA_ALIGN(nla->nla_len);
            remaining -= step;
            nla = (struct nlattr *)((char *)nla + step);
        }
    }
    return -1;
}

static int send_testmode_cmd(uint8_t tm_cmd) {
    struct nl_msg msg = {0};
    msg.nlh.nlmsg_type = family_id;
    msg.nlh.nlmsg_flags = NLM_F_REQUEST | NLM_F_ACK;
    msg.genlh.cmd = MCPS802154_CMD_TESTMODE;
    msg.genlh.version = 1;

    int pos = 0;

    /* ATTR_HW */
    nla_put(msg.attrs, &pos, MCPS802154_ATTR_HW, &hw_idx, 4);

    /* ATTR_TESTDATA: nested { TM_ATTR_CMD = tm_cmd } */
    int nest_start = pos;
    struct nlattr *nest = (struct nlattr *)(msg.attrs + pos);
    pos += NLA_HDRLEN;

    nla_put(msg.attrs, &pos, DW3000_TM_ATTR_CMD, &tm_cmd, 1);

    nest->nla_type = MCPS802154_ATTR_TESTDATA | NLA_F_NESTED;
    nest->nla_len = pos - nest_start;

    msg.nlh.nlmsg_len = NLMSG_LENGTH(GENL_HDRLEN + pos);

    struct sockaddr_nl dest = { .nl_family = AF_NETLINK };
    int ret = sendto(nl_sock, &msg, msg.nlh.nlmsg_len, 0,
                     (struct sockaddr *)&dest, sizeof(dest));

    if (ret < 0) {
        printf("  send error: %s\n", strerror(errno));
        return -1;
    }

    char buf[8192];
    int n = recv(nl_sock, buf, sizeof(buf), 0);
    if (n < 0) {
        printf("  recv error: %s\n", strerror(errno));
        return -1;
    }

    struct nlmsghdr *nlh = (struct nlmsghdr *)buf;
    if (nlh->nlmsg_type == NLMSG_ERROR) {
        int *err = NLMSG_DATA(nlh);
        printf("  result: error=%d (%s)\n", -*err, strerror(-*err));
        return *err;
    }

    printf("  result: OK (type=%d, len=%d)\n", nlh->nlmsg_type, n);

    /* Print response data */
    if (nlh->nlmsg_type == family_id) {
        printf("  response data (%d bytes):", n);
        for (int i = 0; i < n && i < 128; i++) {
            if (i % 16 == 0) printf("\n    ");
            printf("%02x ", (unsigned char)buf[i]);
        }
        printf("\n");
    }

    return 0;
}

int main(int argc, char **argv) {
    int mode_testmode = 0;
    int mode_rx_diag = 0;
    int mode_cw = 0;
    int mode_cont_tx = 0;

    static struct option opts[] = {
        {"testmode", no_argument, 0, 't'},
        {"rx-diag", no_argument, 0, 'r'},
        {"cw", no_argument, 0, 'w'},
        {"cont-tx", no_argument, 0, 'x'},
        {"stop", no_argument, 0, 's'},
        {"help", no_argument, 0, 'h'},
        {0, 0, 0, 0}
    };

    int c;
    int stop = 0;
    while ((c = getopt_long(argc, argv, "trwxsh", opts, NULL)) != -1) {
        switch (c) {
            case 't': mode_testmode = 1; break;
            case 'r': mode_rx_diag = 1; break;
            case 'w': mode_cw = 1; break;
            case 'x': mode_cont_tx = 1; break;
            case 's': stop = 1; break;
            case 'h':
            default:
                printf("Usage: %s [--testmode|--rx-diag|--cw|--cont-tx] [--stop]\n", argv[0]);
                return 1;
        }
    }

    if (!mode_testmode && !mode_rx_diag && !mode_cw && !mode_cont_tx) {
        mode_testmode = 1;
    }

    if (nl_open() < 0) return 1;

    printf("Resolving %s...\n", MCPS802154_GENL_NAME);
    if (resolve_family(MCPS802154_GENL_NAME) < 0) {
        printf("Failed to resolve %s\n", MCPS802154_GENL_NAME);
        return 1;
    }
    printf("  family_id = %d\n\n", family_id);

    if (mode_rx_diag || mode_testmode) {
        if (stop) {
            printf("Stopping RX diagnostics...\n");
            send_testmode_cmd(DW3000_TM_CMD_STOP_RX_DIAG);
        } else {
            printf("Starting RX diagnostics via MCPS802154_CMD_TESTMODE...\n");
            int ret = send_testmode_cmd(DW3000_TM_CMD_START_RX_DIAG);
            if (ret == 0) {
                printf("\nRX diagnostics started. Waiting 3s for data...\n");
                sleep(3);
                printf("\nGetting RX diagnostic results...\n");
                send_testmode_cmd(DW3000_TM_CMD_GET_RX_DIAG);
            }
        }
    }

    if (mode_cw) {
        if (stop) {
            printf("Stopping CW tone...\n");
            send_testmode_cmd(DW3000_TM_CMD_STOP_TX_CWTONE);
        } else {
            printf("Starting CW tone via MCPS802154_CMD_TESTMODE...\n");
            send_testmode_cmd(DW3000_TM_CMD_START_TX_CWTONE);
        }
    }

    if (mode_cont_tx) {
        if (stop) {
            printf("Stopping continuous TX...\n");
            send_testmode_cmd(DW3000_TM_CMD_STOP_CONTINUOUS_TX);
        } else {
            printf("Starting continuous TX via MCPS802154_CMD_TESTMODE...\n");
            send_testmode_cmd(DW3000_TM_CMD_START_CONTINUOUS_TX);
        }
    }

    close(nl_sock);
    return 0;
}
