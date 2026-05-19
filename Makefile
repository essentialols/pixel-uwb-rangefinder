CC = $(shell which aarch64-linux-gnu-gcc 2>/dev/null || echo aarch64-unknown-linux-musl-gcc)
CFLAGS = -static -Wall -Wextra -O2
TARGETS = uwb_probe uwb_cir_read uwb_diag uwb_regdump uwb_testmode
PHONE_DIR = /data/local/tmp

all: $(TARGETS)

uwb_probe: uwb_probe.c
	$(CC) $(CFLAGS) -o $@ $<

uwb_cir_read: uwb_cir_read.c
	$(CC) $(CFLAGS) -o $@ $< -lm

uwb_diag: uwb_diag.c
	$(CC) $(CFLAGS) -o $@ $<

uwb_regdump: uwb_regdump.c
	$(CC) $(CFLAGS) -o $@ $<

uwb_testmode: uwb_testmode.c
	$(CC) $(CFLAGS) -o $@ $<

deploy: all
	@for t in $(TARGETS); do \
		[ -f $$t ] && adb push $$t $(PHONE_DIR)/ ; \
	done
	adb push uwb_recon.sh $(PHONE_DIR)/
	adb shell su -c "chmod 755 $(PHONE_DIR)/uwb_recon.sh"

clean:
	rm -f $(TARGETS)

.PHONY: all deploy clean
