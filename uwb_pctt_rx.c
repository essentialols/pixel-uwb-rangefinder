/*
 * uwb_pctt_rx.c -- Start PCTT PER_RX session on DW3000 via mcps802154 netlink
 *
 * Session 2, Experiment E009: Put DW3000 in continuous RX mode using the
 * PCTT (PHY Compliance Test Tool) region. This allows CIR capture without
 * a ranging partner.
 *
 * Protocol (from AOSP source analysis):
 *   1. Resolve "mcps802154" genl family
 *   2. CMD_SET_SCHEDULER: scheduler_name="on_demand"
 *   3. CMD_SET_SCHEDULER_REGIONS: region_name="pctt", region_id=0
 *   4. CMD_CALL_REGION: PCTT_CALL_SESSION_INIT
 *   5. CMD_CALL_REGION: PCTT_CALL_SESSION_SET_PARAMS (channel 5, etc.)
 *   6. CMD_CALL_REGION: PCTT_CALL_SESSION_CMD + PCTT_ID_ATTR_PER_RX
 *   7. Wait for PCTT_CALL_SESSION_NOTIFICATION with results
 *   8. CMD_CALL_REGION: PCTT_CALL_SESSION_DEINIT
 *   9. CMD_CLOSE_SCHEDULER
 *
 * Usage:
 *   uwb_pctt_rx              # start PER_RX on channel 5 for 1000 packets
 *   uwb_pctt_rx -c 9         # use channel 9
 *   uwb_pctt_rx -n 100       # expect 100 packets
 *   uwb_pctt_rx -t 5000      # 5 second RX window (T_WIN in us)
 *   uwb_pctt_rx --stop       # stop any running session
 *
 * Build:  make uwb_pctt_rx
 * Deploy: adb push uwb_pctt_rx /data/local/tmp/
 * Run:    adb shell su -c /data/local/tmp/uwb_pctt_rx
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

/* mcps802154 netlink (from kernel nl_mcps802154.h, verified against AOSP source) */
#define MCPS802154_GENL_NAME "mcps802154"

enum mcps802154_commands {
    MCPS802154_CMD_UNSPEC,                 /* 0 */
    MCPS802154_CMD_GET_HW,                 /* 1 */
    MCPS802154_CMD_NEW_HW,                 /* 2 */
    MCPS802154_CMD_SET_SCHEDULER,          /* 3 */
    MCPS802154_CMD_SET_SCHEDULER_PARAMS,   /* 4 */
    MCPS802154_CMD_CALL_SCHEDULER,         /* 5 */
    MCPS802154_CMD_SET_SCHEDULER_REGIONS,  /* 6 */
    MCPS802154_CMD_SET_REGIONS_PARAMS,     /* 7 */
    MCPS802154_CMD_CALL_REGION,            /* 8 */
    MCPS802154_CMD_SET_CALIBRATIONS,       /* 9 */
    MCPS802154_CMD_GET_CALIBRATIONS,       /* 10 */
    MCPS802154_CMD_LIST_CALIBRATIONS,      /* 11 */
    MCPS802154_CMD_TESTMODE,               /* 12 */
    MCPS802154_CMD_CLOSE_SCHEDULER,        /* 13 */
    MCPS802154_CMD_GET_PWR_STATS,          /* 14 */
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

/* PCTT region (from pctt_region_nl.h) */
enum pctt_call {
    PCTT_CALL_SESSION_INIT,
    PCTT_CALL_SESSION_CMD,
    PCTT_CALL_SESSION_DEINIT,
    PCTT_CALL_SESSION_GET_STATE,
    PCTT_CALL_SESSION_GET_PARAMS,
    PCTT_CALL_SESSION_SET_PARAMS,
    PCTT_CALL_SESSION_NOTIFICATION,
};

enum pctt_call_attrs {
    PCTT_CALL_ATTR_UNSPEC,
    PCTT_CALL_ATTR_CMD_ID,
    PCTT_CALL_ATTR_RESULT_DATA,
    PCTT_CALL_ATTR_SESSION_ID,
    PCTT_CALL_ATTR_SESSION_STATE,
    PCTT_CALL_ATTR_SESSION_PARAMS,
};

enum pctt_id_attrs {
    PCTT_ID_ATTR_UNSPEC,
    PCTT_ID_ATTR_PERIODIC_TX,
    PCTT_ID_ATTR_PER_RX,
    PCTT_ID_ATTR_RX,
    PCTT_ID_ATTR_LOOPBACK,
    PCTT_ID_ATTR_SS_TWR,
    PCTT_ID_ATTR_STOP_TEST,
};

enum pctt_session_param_attrs {
    PCTT_SESSION_PARAM_ATTR_UNSPEC,
    PCTT_SESSION_PARAM_ATTR_DEVICE_ROLE,
    PCTT_SESSION_PARAM_ATTR_SHORT_ADDR,
    PCTT_SESSION_PARAM_ATTR_DESTINATION_SHORT_ADDR,
    PCTT_SESSION_PARAM_ATTR_RX_ANTENNA_SELECTION,
    PCTT_SESSION_PARAM_ATTR_TX_ANTENNA_SELECTION,
    PCTT_SESSION_PARAM_ATTR_SLOT_DURATION_RSTU,
    PCTT_SESSION_PARAM_ATTR_CHANNEL_NUMBER,
    PCTT_SESSION_PARAM_ATTR_PREAMBLE_CODE_INDEX,
    PCTT_SESSION_PARAM_ATTR_RFRAME_CONFIG,
    PCTT_SESSION_PARAM_ATTR_PRF_MODE,
    PCTT_SESSION_PARAM_ATTR_PREAMBLE_DURATION,
    PCTT_SESSION_PARAM_ATTR_SFD_ID,
    PCTT_SESSION_PARAM_ATTR_NUMBER_OF_STS_SEGMENTS,
    PCTT_SESSION_PARAM_ATTR_PSDU_DATA_RATE,
    PCTT_SESSION_PARAM_ATTR_BPRF_PHR_DATA_RATE,
    PCTT_SESSION_PARAM_ATTR_MAC_FCS_TYPE,
    PCTT_SESSION_PARAM_ATTR_TX_ADAPTIVE_PAYLOAD_POWER,
    PCTT_SESSION_PARAM_ATTR_STS_INDEX,
    PCTT_SESSION_PARAM_ATTR_STS_LENGTH,
    PCTT_SESSION_PARAM_ATTR_NUM_PACKETS,
    PCTT_SESSION_PARAM_ATTR_T_GAP,
    PCTT_SESSION_PARAM_ATTR_T_START,
    PCTT_SESSION_PARAM_ATTR_T_WIN,
    PCTT_SESSION_PARAM_ATTR_RANDOMIZE_PSDU,
    PCTT_SESSION_PARAM_ATTR_PHR_RANGING_BIT,
    PCTT_SESSION_PARAM_ATTR_RMARKER_TX_START,
    PCTT_SESSION_PARAM_ATTR_RMARKER_RX_START,
    PCTT_SESSION_PARAM_ATTR_STS_INDEX_AUTO_INCR,
    PCTT_SESSION_PARAM_ATTR_DATA_PAYLOAD,
};

/* NLA helpers - guard against kernel header conflicts */
#ifndef NLA_HDRLEN
#define NLA_HDRLEN 4
#endif
#ifndef NLA_ALIGN
#define NLA_ALIGN(len) (((len) + 3) & ~3)
#endif
#ifndef NLA_F_NESTED
#define NLA_F_NESTED 0x8000
#endif

static int nl_sock = -1;
static uint16_t mcps_family = 0;
static uint32_t nl_seq = 0;
static uint32_t nl_pid = 0;

static char *nla_buf;
static int nla_off;

static void nla_init(char *buf) { nla_buf = buf; nla_off = 0; }

static void nla_put(uint16_t type, const void *data, int len) {
    struct nlattr *a = (void *)(nla_buf + nla_off);
    a->nla_len = NLA_HDRLEN + len;
    a->nla_type = type;
    memcpy(nla_buf + nla_off + NLA_HDRLEN, data, len);
    nla_off += NLA_ALIGN(a->nla_len);
}

static void nla_put_u8(uint16_t type, uint8_t val) { nla_put(type, &val, 1); }
static void nla_put_u16(uint16_t type, uint16_t val) __attribute__((unused));
static void nla_put_u16(uint16_t type, uint16_t val) { nla_put(type, &val, 2); }
static void nla_put_u32(uint16_t type, uint32_t val) { nla_put(type, &val, 4); }
static void nla_put_string(uint16_t type, const char *s) { nla_put(type, s, strlen(s) + 1); }

static int nla_nest_start(uint16_t type) {
    int start = nla_off;
    struct nlattr *a = (void *)(nla_buf + nla_off);
    a->nla_type = type | NLA_F_NESTED;
    a->nla_len = NLA_HDRLEN; /* will be updated by nest_end */
    nla_off += NLA_HDRLEN;
    return start;
}

static void nla_nest_end(int start) {
    struct nlattr *a = (void *)(nla_buf + start);
    a->nla_len = nla_off - start;
}

static int send_cmd(uint8_t cmd) {
    char buf[4096];
    memset(buf, 0, sizeof(buf));

    struct nlmsghdr *nlh = (void *)buf;
    struct genlmsghdr *gh = NLMSG_DATA(nlh);

    gh->cmd = cmd;
    gh->version = 1;

    int attr_start = NLMSG_HDRLEN + GENL_HDRLEN;
    memcpy(buf + attr_start, nla_buf, nla_off);

    nlh->nlmsg_len = attr_start + nla_off;
    nlh->nlmsg_type = mcps_family;
    nlh->nlmsg_flags = NLM_F_REQUEST | NLM_F_ACK;
    nlh->nlmsg_seq = ++nl_seq;
    nlh->nlmsg_pid = nl_pid;

    struct sockaddr_nl dst = { .nl_family = AF_NETLINK };
    if (sendto(nl_sock, buf, nlh->nlmsg_len, 0, (void *)&dst, sizeof(dst)) < 0) {
        perror("sendto");
        return -1;
    }

    char resp[4096];
    int rlen = recv(nl_sock, resp, sizeof(resp), 0);
    if (rlen < 0) { perror("recv"); return -1; }

    struct nlmsghdr *rh = (void *)resp;
    fprintf(stderr, "  [dbg] recv %d bytes, type=%d seq=%d flags=0x%x\n",
            rlen, rh->nlmsg_type, rh->nlmsg_seq, rh->nlmsg_flags);
    if (rlen >= 20) {
        fprintf(stderr, "  [dbg] hex[16..35]:");
        for (int i = 16; i < (rlen < 36 ? rlen : 36); i++)
            fprintf(stderr, " %02x", (unsigned char)resp[i]);
        fprintf(stderr, "\n");
    }
    if (rh->nlmsg_type == NLMSG_ERROR) {
        int err = *(int *)(resp + NLMSG_HDRLEN);
        fprintf(stderr, "  [dbg] raw error field: %d (0x%08x)\n", err, (unsigned)err);
        if (err != 0) {
            fprintf(stderr, "  Error: %d (%s)\n", -err, strerror(-err));
            return err;
        }
        return 0; /* ACK */
    }

    /* Parse response attributes */
    printf("  Response: type=%d len=%d\n", rh->nlmsg_type, rh->nlmsg_len);
    return 0;
}

static int resolve_family(const char *name) {
    char buf[256];
    memset(buf, 0, sizeof(buf));
    struct nlmsghdr *nlh = (void *)buf;
    struct genlmsghdr *gh = NLMSG_DATA(nlh);

    int nlen = strlen(name) + 1;
    int alen = NLA_ALIGN(NLA_HDRLEN + nlen);

    nlh->nlmsg_len = NLMSG_HDRLEN + GENL_HDRLEN + alen;
    nlh->nlmsg_type = GENL_ID_CTRL;
    nlh->nlmsg_flags = NLM_F_REQUEST;
    nlh->nlmsg_seq = ++nl_seq;
    nlh->nlmsg_pid = nl_pid;
    gh->cmd = 3; /* CTRL_CMD_GETFAMILY */
    gh->version = 1;

    struct nlattr *a = (void *)(buf + NLMSG_HDRLEN + GENL_HDRLEN);
    a->nla_len = NLA_HDRLEN + nlen;
    a->nla_type = 2; /* CTRL_ATTR_FAMILY_NAME */
    memcpy((char *)a + NLA_HDRLEN, name, nlen);

    struct sockaddr_nl dst = { .nl_family = AF_NETLINK };
    sendto(nl_sock, buf, nlh->nlmsg_len, 0, (void *)&dst, sizeof(dst));

    char resp[4096];
    int rlen = recv(nl_sock, resp, sizeof(resp), 0);
    if (rlen < 0) return -1;

    struct nlmsghdr *rh = (void *)resp;
    if (rh->nlmsg_type == NLMSG_ERROR) return -1;

    int off = NLMSG_HDRLEN + GENL_HDRLEN;
    while (off < rlen) {
        struct nlattr *at = (void *)(resp + off);
        if (at->nla_type == 1) return *(uint16_t *)(resp + off + NLA_HDRLEN);
        off += NLA_ALIGN(at->nla_len);
    }
    return -1;
}

static void usage(const char *prog) {
    fprintf(stderr, "Usage: %s [options]\n", prog);
    fprintf(stderr, "  -c CHAN    UWB channel (5 or 9, default 5)\n");
    fprintf(stderr, "  -n NUM    number of packets (default 1000)\n");
    fprintf(stderr, "  -t USEC   RX window T_WIN in microseconds (default 5000000 = 5s)\n");
    fprintf(stderr, "  --stop    stop any running PCTT session\n");
    fprintf(stderr, "  -h        help\n");
}

int main(int argc, char *argv[]) {
    int channel = 5;
    int num_packets = 1000;
    int t_win = 5000000; /* 5 seconds in microseconds */
    int do_stop = 0;
    char attr_buf[4096];

    static struct option long_opts[] = {
        {"stop", no_argument, 0, 'S'},
        {0, 0, 0, 0}
    };

    int opt;
    while ((opt = getopt_long(argc, argv, "c:n:t:h", long_opts, NULL)) != -1) {
        switch (opt) {
        case 'c': channel = atoi(optarg); break;
        case 'n': num_packets = atoi(optarg); break;
        case 't': t_win = atoi(optarg); break;
        case 'S': do_stop = 1; break;
        default: usage(argv[0]); return 1;
        }
    }

    /* Open netlink socket */
    nl_sock = socket(AF_NETLINK, SOCK_RAW, NETLINK_GENERIC);
    if (nl_sock < 0) { perror("socket"); return 1; }

    struct sockaddr_nl sa = { .nl_family = AF_NETLINK, .nl_pid = 0 };
    bind(nl_sock, (void *)&sa, sizeof(sa));
    {
        struct sockaddr_nl bound;
        socklen_t blen = sizeof(bound);
        getsockname(nl_sock, (void *)&bound, &blen);
        nl_pid = bound.nl_pid;
    }

    int fid = resolve_family(MCPS802154_GENL_NAME);
    if (fid < 0) {
        fprintf(stderr, "Cannot resolve '%s' family\n", MCPS802154_GENL_NAME);
        return 1;
    }
    mcps_family = fid;
    printf("mcps802154 family ID: %d\n", fid);

    if (do_stop) {
        printf("Closing scheduler...\n");
        nla_init(attr_buf);
        nla_put_u32(MCPS802154_ATTR_HW, 0);
        int rc = send_cmd(MCPS802154_CMD_CLOSE_SCHEDULER);
        printf("Result: %d\n", rc);
        close(nl_sock);
        return rc != 0;
    }

    /* Step 1: Skip SET_SCHEDULER (keep HAL's scheduler to avoid killing active sessions) */
    printf("Step 1: (skipped, keeping existing scheduler)\n");
    int rc = 0;

    /* Step 2: Add pctt region alongside existing regions */
    printf("Step 2: SET_SCHEDULER_REGIONS fira+pctt\n");
    nla_init(attr_buf);
    nla_put_u32(MCPS802154_ATTR_HW, 0);
    nla_put_string(MCPS802154_ATTR_SCHEDULER_NAME, "on_demand");
    {
        int regions_nest = nla_nest_start(MCPS802154_ATTR_SCHEDULER_REGIONS);
        {
            int region_nest = nla_nest_start(1); /* fira region (preserve) */
            nla_put_string(MCPS802154_REGION_ATTR_NAME, "fira");
            nla_put_u32(MCPS802154_REGION_ATTR_ID, 0);
            nla_nest_end(region_nest);
        }
        {
            int region_nest = nla_nest_start(2); /* pctt region (add) */
            nla_put_string(MCPS802154_REGION_ATTR_NAME, "pctt");
            nla_put_u32(MCPS802154_REGION_ATTR_ID, 1);
            nla_nest_end(region_nest);
        }
        nla_nest_end(regions_nest);
    }
    rc = send_cmd(MCPS802154_CMD_SET_SCHEDULER_REGIONS);
    if (rc) { printf("Failed at step 2\n"); goto out; }

    /* Step 3: CALL_REGION SESSION_INIT */
    printf("Step 3: PCTT SESSION_INIT\n");
    nla_init(attr_buf);
    nla_put_u32(MCPS802154_ATTR_HW, 0);
    nla_put_string(MCPS802154_ATTR_SCHEDULER_NAME, "on_demand");
    {
        int call_nest = nla_nest_start(MCPS802154_ATTR_SCHEDULER_REGION_CALL);
        nla_put_string(MCPS802154_REGION_ATTR_NAME, "pctt");
        nla_put_u32(MCPS802154_REGION_ATTR_CALL, PCTT_CALL_SESSION_INIT);
        nla_put_u32(MCPS802154_REGION_ATTR_ID, 1);
        {
            int params_nest = nla_nest_start(MCPS802154_REGION_ATTR_CALL_PARAMS);
            nla_put_u32(PCTT_CALL_ATTR_SESSION_ID, 0);
            nla_nest_end(params_nest);
        }
        nla_nest_end(call_nest);
    }
    rc = send_cmd(MCPS802154_CMD_CALL_REGION);
    if (rc) { printf("Failed at step 3\n"); goto out; }

    /* Step 4: CALL_REGION SESSION_SET_PARAMS */
    printf("Step 4: PCTT SESSION_SET_PARAMS (channel=%d)\n", channel);
    nla_init(attr_buf);
    nla_put_u32(MCPS802154_ATTR_HW, 0);
    nla_put_string(MCPS802154_ATTR_SCHEDULER_NAME, "on_demand");
    {
        int call_nest = nla_nest_start(MCPS802154_ATTR_SCHEDULER_REGION_CALL);
        nla_put_string(MCPS802154_REGION_ATTR_NAME, "pctt");
        nla_put_u32(MCPS802154_REGION_ATTR_CALL, PCTT_CALL_SESSION_SET_PARAMS);
        nla_put_u32(MCPS802154_REGION_ATTR_ID, 0);
        {
            int params_nest = nla_nest_start(MCPS802154_REGION_ATTR_CALL_PARAMS);
            int sess_nest = nla_nest_start(PCTT_CALL_ATTR_SESSION_PARAMS);
            nla_put_u8(PCTT_SESSION_PARAM_ATTR_CHANNEL_NUMBER, channel);
            nla_put_u8(PCTT_SESSION_PARAM_ATTR_PREAMBLE_CODE_INDEX, 9);
            nla_put_u8(PCTT_SESSION_PARAM_ATTR_RFRAME_CONFIG, 0); /* SP0 */
            nla_put_u8(PCTT_SESSION_PARAM_ATTR_PRF_MODE, 0); /* BPRF */
            nla_put_u8(PCTT_SESSION_PARAM_ATTR_PREAMBLE_DURATION, 1); /* 64 symbols */
            nla_put_u8(PCTT_SESSION_PARAM_ATTR_SFD_ID, 2);
            nla_put_u8(PCTT_SESSION_PARAM_ATTR_NUMBER_OF_STS_SEGMENTS, 0);
            nla_put_u32(PCTT_SESSION_PARAM_ATTR_NUM_PACKETS, num_packets);
            nla_put_u32(PCTT_SESSION_PARAM_ATTR_T_WIN, t_win);
            nla_put_u32(PCTT_SESSION_PARAM_ATTR_T_GAP, 2000); /* 2ms gap */
            nla_nest_end(sess_nest);
            nla_nest_end(params_nest);
        }
        nla_nest_end(call_nest);
    }
    rc = send_cmd(MCPS802154_CMD_CALL_REGION);
    if (rc) { printf("Failed at step 4\n"); goto out; }

    /* Step 5: CALL_REGION SESSION_CMD with PER_RX */
    printf("Step 5: PCTT PER_RX (listening for %d us)\n", t_win);
    nla_init(attr_buf);
    nla_put_u32(MCPS802154_ATTR_HW, 0);
    nla_put_string(MCPS802154_ATTR_SCHEDULER_NAME, "on_demand");
    {
        int call_nest = nla_nest_start(MCPS802154_ATTR_SCHEDULER_REGION_CALL);
        nla_put_string(MCPS802154_REGION_ATTR_NAME, "pctt");
        nla_put_u32(MCPS802154_REGION_ATTR_CALL, PCTT_CALL_SESSION_CMD);
        nla_put_u32(MCPS802154_REGION_ATTR_ID, 0);
        {
            int params_nest = nla_nest_start(MCPS802154_REGION_ATTR_CALL_PARAMS);
            nla_put_u8(PCTT_CALL_ATTR_CMD_ID, PCTT_ID_ATTR_PER_RX);
            nla_nest_end(params_nest);
        }
        nla_nest_end(call_nest);
    }
    rc = send_cmd(MCPS802154_CMD_CALL_REGION);
    if (rc) { printf("Failed at step 5\n"); goto out; }

    printf("\nPCTT PER_RX started! DW3000 is now in continuous RX mode.\n");
    printf("Check ftrace and debugfs cir_data for CIR captures.\n");
    printf("Press Ctrl+C to stop, or run: %s --stop\n", argv[0]);

    /* Wait for notification (blocking recv) */
    printf("\nWaiting for session notification...\n");
    char resp[4096];
    int rlen = recv(nl_sock, resp, sizeof(resp), 0);
    if (rlen > 0) {
        struct nlmsghdr *rh = (void *)resp;
        printf("Notification received: type=%d len=%d\n", rh->nlmsg_type, rh->nlmsg_len);
        /* TODO: parse PCTT result data (PER statistics, CIR info) */
    }

out:
    close(nl_sock);
    return rc != 0;
}
