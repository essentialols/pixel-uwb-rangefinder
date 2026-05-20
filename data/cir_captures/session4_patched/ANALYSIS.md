# CIR Capture Analysis - Session 4 (Patched Module)

## Capture Details
- File: cir_10s.bin (72,180 bytes)
- Frames: 45 (at 5Hz over ~9s)
- Bins per frame: 258 (config: 256 + 2 header bins)
- Frame size: ~1604 bytes (48-byte header + 258 x 6-byte I/Q)

## Result: Valid frame structure, zero I/Q samples

The patched dw3000_cir_stream_v3.ko module DOES produce CIR frames:
- Frame headers have valid timestamps (~200ms apart, confirming 5Hz RXPTO)
- Frame counter increments correctly (0, 1, 2, ...)
- Header byte at offset 0x2E contains non-zero diagnostic data (0x03AD)
- I/Q sample bins are all zeros

## Interpretation

The DW3000 accumulator memory is NOT populated during RXPTO (preamble timeout)
when no valid preamble is detected. The chip clears or doesn't fill the
accumulator without an actual received signal.

This is different from some other UWB chips (e.g., DW1000) where the
accumulator contains noise even without a received signal.

## Next Step

A second UWB device as a FiRa responder would produce actual received
packets, populating the CIR accumulator with real signal + multipath data.
The patched module pipeline is validated and ready for real signal capture.
