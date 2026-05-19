CC = $(shell which aarch64-linux-gnu-gcc 2>/dev/null || echo aarch64-unknown-linux-musl-gcc)
CFLAGS = -static -Wall -Wextra -O2
TARGETS = uwb_probe
PHONE_DIR = /data/local/tmp

all: $(TARGETS)

uwb_probe: uwb_probe.c
	$(CC) $(CFLAGS) -o $@ $<

# Pattern rule for tools that need -lm
# (add targets here as they are created)

deploy: all
	@for t in $(TARGETS); do \
		[ -f $$t ] && adb push $$t $(PHONE_DIR)/ ; \
	done

clean:
	rm -f $(TARGETS)

.PHONY: all deploy clean
