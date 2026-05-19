/*
 * uwb_testmode.c -- DW3000 testmode via ieee802154 netlink
 *
 * Session 1, Experiment E007: Access DW3000 testmode commands via
 * the ieee802154 generic netlink interface.
 *
 * The DW3000 driver registers testmode commands through the ieee802154
 * subsystem's netlink interface. This tool sends testmode commands to:
 *   - Start/stop RX diagnostics (RSSI collection)
 *   - Get RX diagnostic data (good/bad counts + RSSI array)
 *   - Configure channel and HRP parameters
 *   - Control CW tone and continuous TX
 *
 * From source analysis:
 *   - do_tm_cmd_start_rx_diag(): enables promiscuous RX + stats collection
 *   - do_tm_cmd_get_rx_diag(): returns good/bad counters + RSSI data
 *   - RSSI struct: cir_pwr(17), pacc_cnt(11), prf_64mhz(1), dgc_dec(3)
 *
 * Usage:
 *   uwb_testmode -l              # list ieee802154 PHY devices
 *   uwb_testmode -s              # start RX diagnostics
 *   uwb_testmode -g              # get RX diagnostic results
 *   uwb_testmode -x              # stop RX diagnostics
 *   uwb_testmode -c              # clear RX diagnostic counters
 *   uwb_testmode -i              # get PHY info
 *
 * Build:  make uwb_testmode
 * Deploy: adb push uwb_testmode /data/local/tmp/
 * Run:    adb shell su -c /data/local/tmp/uwb_testmode -l
 *
 * NOTE: This requires the ieee802154 netlink interface to be available.
 * If the Android UWB HAL is running, it may hold the device. Try stopping
 * the HAL first: "stop vendor.uwb_hal"
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <errno.h>
#include <getopt.h>
#include <sys/socket.h>
#include <linux/netlink.h>
#include <linux/genetlink.h>
#include <stdint.h>

/* ieee802154 netlink constants (from nl802154.h) */
#define NL802154_GENL_NAME "nl802154"

/* nl802154 commands (subset) */
enum nl802154_commands {
    NL802154_CMD_GET_WPAN_PHY = 1,
    NL802154_CMD_SET_WPAN_PHY = 2,
    NL802154_CMD_NEW_WPAN_PHY = 3,
    NL802154_CMD_DEL_WPAN_PHY = 4,
    NL802154_CMD_GET_INTERFACE = 5,
    NL802154_CMD_TESTMODE = 26,
};

/* nl802154 attributes (subset) */
enum nl802154_attrs {
    NL802154_ATTR_WPAN_PHY = 1,
    NL802154_ATTR_WPAN_PHY_NAME = 2,
    NL802154_ATTR_IFINDEX = 3,
    NL802154_ATTR_IFNAME = 4,
    NL802154_ATTR_TESTDATA = 55,
};

/* DW3000 testmode commands (from dw3000_testmode_nl.h) */
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
    DW3000_TM_CMD_SET_HRP_PARAMS = 23,
    DW3000_TM_CMD_SET_CHANNEL = 24,
};

/* DW3000 testmode attributes */
enum dw3000_tm_attr {
    DW3000_TM_ATTR_CMD = 1,
    DW3000_TM_ATTR_RX_GOOD_CNT = 2,
    DW3000_TM_ATTR_RX_BAD_CNT = 3,
    DW3000_TM_ATTR_RSSI_DATA = 4,
};

/* RSSI data structure */
struct dw3000_rssi {
    uint32_t cir_pwr : 17;
    uint16_t pacc_cnt : 11;
    uint8_t prf_64mhz : 1;
    uint8_t dgc_dec : 3;
} __attribute__((__packed__));

/* Netlink message helpers */
struct nl_msg {
    struct nlmsghdr nlh;
    struct genlmsghdr genlh;
    char attrs[4096];
};

static int nl_sock = -1;
static uint16_t nl802154_family_id = 0;

static int nl_open(void) {
    nl_sock = socket(AF_NETLINK, SOCK_RAW, NETLINK_GENERIC);
    if (nl_sock < 0) {
        perror("socket(NETLINK_GENERIC)");
        return -1;
    }

    struct sockaddr_nl addr = {
        .nl_family = AF_NETLINK,
        .nl_pid = getpid(),
    };
    if (bind(nl_sock, (struct sockaddr *)&addr, sizeof(addr)) < 0) {
        perror("bind");
        close(nl_sock);
        return -1;
    }
    return 0;
}

/* Resolve generic netlink family ID by name */
static int nl_resolve_family(const char *name) {
    struct {
        struct nlmsghdr nlh;
        struct genlmsghdr genlh;
        struct nlattr attr;
        char name[32];
    } __attribute__((packed)) req;

    memset(&req, 0, sizeof(req));
    int namelen = strlen(name) + 1;
    int attrlen = NLA_HDRLEN + namelen;
    int padded_attrlen = (attrlen + 3) & ~3;

    req.nlh.nlmsg_len = NLMSG_LENGTH(GENL_HDRLEN) + padded_attrlen;
    req.nlh.nlmsg_type = GENL_ID_CTRL;
    req.nlh.nlmsg_flags = NLM_F_REQUEST;
    req.nlh.nlmsg_seq = 1;
    req.nlh.nlmsg_pid = getpid();
    req.genlh.cmd = CTRL_CMD_GETFAMILY;
    req.genlh.version = 1;
    req.attr.nla_len = attrlen;
    req.attr.nla_type = CTRL_ATTR_FAMILY_NAME;
    strncpy(req.name, name, sizeof(req.name) - 1);

    if (send(nl_sock, &req, req.nlh.nlmsg_len, 0) < 0) {
        perror("send(GETFAMILY)");
        return -1;
    }

    char buf[4096];
    int len = recv(nl_sock, buf, sizeof(buf), 0);
    if (len < 0) {
        perror("recv(GETFAMILY)");
        return -1;
    }

    struct nlmsghdr *nlh = (struct nlmsghdr *)buf;
    if (nlh->nlmsg_type == NLMSG_ERROR) {
        struct nlmsgerr *err = NLMSG_DATA(nlh);
        fprintf(stderr, "GETFAMILY error: %d (%s)\n", -err->error, strerror(-err->error));
        return -1;
    }

    /* Parse response to find family ID */
    struct genlmsghdr *genlh = NLMSG_DATA(nlh);
    struct nlattr *attr = (struct nlattr *)((char *)genlh + GENL_HDRLEN);
    int remaining = len - NLMSG_HDRLEN - GENL_HDRLEN;

    while (remaining >= (int)NLA_HDRLEN) {
        if (attr->nla_type == CTRL_ATTR_FAMILY_ID) {
            uint16_t id = *(uint16_t *)((char *)attr + NLA_HDRLEN);
            return id;
        }
        int alen = (attr->nla_len + 3) & ~3;
        remaining -= alen;
        attr = (struct nlattr *)((char *)attr + alen);
    }

    fprintf(stderr, "Family ID not found in response\n");
    return -1;
}

/* List ieee802154 PHY devices */
static int list_phys(void) {
    struct nl_msg msg;
    memset(&msg, 0, sizeof(msg));
    msg.nlh.nlmsg_len = NLMSG_LENGTH(GENL_HDRLEN);
    msg.nlh.nlmsg_type = nl802154_family_id;
    msg.nlh.nlmsg_flags = NLM_F_REQUEST | NLM_F_DUMP;
    msg.nlh.nlmsg_seq = 2;
    msg.nlh.nlmsg_pid = getpid();
    msg.genlh.cmd = NL802154_CMD_GET_WPAN_PHY;
    msg.genlh.version = 1;

    if (send(nl_sock, &msg, msg.nlh.nlmsg_len, 0) < 0) {
        perror("send(GET_WPAN_PHY)");
        return -1;
    }

    printf("=== IEEE 802.15.4 PHY Devices ===\n");

    char buf[8192];
    while (1) {
        int len = recv(nl_sock, buf, sizeof(buf), 0);
        if (len < 0) { perror("recv"); return -1; }

        struct nlmsghdr *nlh = (struct nlmsghdr *)buf;
        for (; NLMSG_OK(nlh, (unsigned)len); nlh = NLMSG_NEXT(nlh, len)) {
            if (nlh->nlmsg_type == NLMSG_DONE) return 0;
            if (nlh->nlmsg_type == NLMSG_ERROR) {
                struct nlmsgerr *err = NLMSG_DATA(nlh);
                if (err->error == 0) return 0;
                fprintf(stderr, "Error: %d\n", -err->error);
                return -1;
            }

            struct genlmsghdr *genlh = NLMSG_DATA(nlh);
            struct nlattr *attr = (struct nlattr *)((char *)genlh + GENL_HDRLEN);
            int remaining = nlh->nlmsg_len - NLMSG_HDRLEN - GENL_HDRLEN;

            int phy_id = -1;
            const char *phy_name = "(unknown)";

            while (remaining >= (int)NLA_HDRLEN) {
                if (attr->nla_type == NL802154_ATTR_WPAN_PHY) {
                    phy_id = *(uint32_t *)((char *)attr + NLA_HDRLEN);
                } else if (attr->nla_type == NL802154_ATTR_WPAN_PHY_NAME) {
                    phy_name = (char *)attr + NLA_HDRLEN;
                }
                int alen = (attr->nla_len + 3) & ~3;
                remaining -= alen;
                attr = (struct nlattr *)((char *)attr + alen);
            }

            printf("  PHY %d: %s\n", phy_id, phy_name);
        }
    }
    return 0;
}

static void usage(const char *prog) {
    fprintf(stderr, "Usage: %s [options]\n", prog);
    fprintf(stderr, "  -l        list ieee802154 PHY devices\n");
    fprintf(stderr, "  -s        start RX diagnostics\n");
    fprintf(stderr, "  -g        get RX diagnostic results\n");
    fprintf(stderr, "  -x        stop RX diagnostics\n");
    fprintf(stderr, "  -c        clear RX diagnostic counters\n");
    fprintf(stderr, "  -h        this help\n");
    fprintf(stderr, "\nRequires ieee802154 (nl802154) netlink family.\n");
    fprintf(stderr, "If UWB HAL is running, stop it: 'stop vendor.uwb_hal'\n");
}

int main(int argc, char *argv[]) {
    int do_list = 0, do_start = 0, do_get = 0, do_stop = 0, do_clear = 0;
    int opt;

    while ((opt = getopt(argc, argv, "lsgxch")) != -1) {
        switch (opt) {
        case 'l': do_list = 1; break;
        case 's': do_start = 1; break;
        case 'g': do_get = 1; break;
        case 'x': do_stop = 1; break;
        case 'c': do_clear = 1; break;
        default: usage(argv[0]); return 1;
        }
    }

    if (!do_list && !do_start && !do_get && !do_stop && !do_clear) {
        /* Default: list PHYs */
        do_list = 1;
    }

    if (nl_open() < 0) return 1;

    /* Resolve nl802154 family */
    int fid = nl_resolve_family(NL802154_GENL_NAME);
    if (fid < 0) {
        fprintf(stderr, "Cannot resolve '%s' netlink family.\n", NL802154_GENL_NAME);
        fprintf(stderr, "Is the ieee802154/mcps802154 module loaded?\n");
        close(nl_sock);
        return 1;
    }
    nl802154_family_id = fid;
    fprintf(stderr, "nl802154 family ID: %d\n", nl802154_family_id);

    if (do_list) {
        list_phys();
    }

    /* For testmode commands, we would need to build nested NLA messages
     * with NL802154_ATTR_TESTDATA containing the DW3000_TM_ATTR_CMD.
     * This is complex netlink message construction. For now, just verify
     * the family exists and PHYs are enumerable. */

    if (do_start || do_get || do_stop || do_clear) {
        int cmd = do_start ? DW3000_TM_CMD_START_RX_DIAG :
                  do_get   ? DW3000_TM_CMD_GET_RX_DIAG :
                  do_stop  ? DW3000_TM_CMD_STOP_RX_DIAG :
                             DW3000_TM_CMD_CLEAR_RX_DIAG;

        printf("Testmode command %d: ", cmd);
        printf("(full netlink testmode implementation pending -- ");
        printf("need to verify PHY enumeration first)\n");
        printf("\nTo implement: build NL802154_CMD_TESTMODE message with:\n");
        printf("  NL802154_ATTR_WPAN_PHY = <phy_id from -l>\n");
        printf("  NL802154_ATTR_TESTDATA = nested {\n");
        printf("    DW3000_TM_ATTR_CMD = %d\n", cmd);
        printf("  }\n");
    }

    close(nl_sock);
    return 0;
}
