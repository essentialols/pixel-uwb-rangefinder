#!/usr/bin/env python3
"""
uwb_link_budget.py -- UWB radar link budget for CIR reflection detection

Predicts whether a metal reflector at a given distance will produce a
detectable CIR peak above the measured noise floor.

Model:
  P_rx = P_tx * G_tx * G_rx * sigma * lambda^2 / ((4*pi)^3 * R^4)

  where:
  - P_tx: transmit power (-41.3 dBm/MHz per FCC, 500 MHz BW = -14.3 dBm total)
  - G_tx, G_rx: antenna gains (~0 dBi for chip antenna)
  - sigma: radar cross section of reflector
  - lambda: wavelength (46mm at 6.5 GHz ch5, 37mm at 8 GHz ch9)
  - R: one-way distance to reflector

  But this is for a CW radar. For pulsed UWB with correlator:
  - Correlator gain: N_acc * N_preamble symbols
  - The reflected preamble correlates with the RX template
  - Processing gain ~10*log10(N_symbols * N_chips_per_symbol)

  DW3000 channel 9 (8 GHz, 499.2 MHz BW):
  - Preamble: 64 symbols (STS_LENGTH default)
  - Chips per symbol: 496 (for 499.2 MHz)
  - Total processing gain: ~10*log10(64*496) = ~45 dB

Usage:
  python3 uwb_link_budget.py
  python3 uwb_link_budget.py --distance 0.5 --rcs 0.01
"""

import math
import argparse

C = 299792458.0
UWB_BW = 499.2e6

CHANNELS = {
    5: {'freq': 6.5e9, 'lambda': C / 6.5e9},
    9: {'freq': 8.0e9, 'lambda': C / 8.0e9},
}


def db(x):
    return 10 * math.log10(x) if x > 0 else -999


def from_db(x):
    return 10 ** (x / 10)


def radar_equation_dbm(p_tx_dbm, g_tx_dbi, g_rx_dbi, sigma_m2,
                        wavelength_m, distance_m):
    p_tx = from_db(p_tx_dbm)
    numerator = p_tx * from_db(g_tx_dbi) * from_db(g_rx_dbi) * sigma_m2 * wavelength_m**2
    denominator = (4 * math.pi)**3 * distance_m**4
    p_rx = numerator / denominator
    return db(p_rx)


def noise_floor_dbm(bw_hz, noise_figure_db=8.0, temp_k=300):
    ktb = 1.38e-23 * temp_k * bw_hz
    return db(ktb) + 30 + noise_figure_db


def main():
    parser = argparse.ArgumentParser(description="UWB radar link budget")
    parser.add_argument('--distance', type=float, default=0,
                        help='Specific distance to analyze (m)')
    parser.add_argument('--rcs', type=float, default=0.01,
                        help='Radar cross section (m^2), default 0.01 = ~10cm plate')
    parser.add_argument('--channel', type=int, default=9, choices=[5, 9])
    args = parser.parse_args()

    ch = CHANNELS[args.channel]
    freq = ch['freq']
    wavelength = ch['lambda']

    # DW3000 parameters
    p_tx_total_dbm = -14.3  # -41.3 dBm/MHz * 500 MHz = -14.3 dBm total
    g_tx = 0.0  # dBi (chip antenna)
    g_rx = 0.0
    nf = 8.0  # dB noise figure (typical for DW3000)

    # Correlator processing gain
    n_preamble_symbols = 64  # typical FiRa STS
    n_chips_per_symbol = int(UWB_BW / 1e6)
    processing_gain_db = db(n_preamble_symbols * n_chips_per_symbol)

    # Noise floor
    nf_dbm = noise_floor_dbm(UWB_BW, nf)
    nf_after_corr = nf_dbm - processing_gain_db

    # Measured noise floor from baseline capture (in CIR magnitude units)
    measured_noise_mag = 0.347
    measured_noise_3sigma = 0.760
    measured_noise_max = 0.696

    print(f"=== UWB Radar Link Budget (Channel {args.channel}) ===\n")
    print(f"Frequency: {freq/1e9:.1f} GHz, Wavelength: {wavelength*1e3:.1f} mm")
    print(f"Bandwidth: {UWB_BW/1e6:.0f} MHz")
    print(f"TX power: {p_tx_total_dbm:.1f} dBm total ({p_tx_total_dbm - db(UWB_BW/1e6):.1f} dBm/MHz)")
    print(f"Antenna gain: {g_tx:.0f} dBi TX, {g_rx:.0f} dBi RX")
    print(f"Noise figure: {nf:.0f} dB")
    print(f"Processing gain: {processing_gain_db:.1f} dB ({n_preamble_symbols} symbols x {n_chips_per_symbol} chips)")
    print(f"Noise floor: {nf_dbm:.1f} dBm (pre-correlator), {nf_after_corr:.1f} dBm (post-correlator)")
    print(f"RCS: {args.rcs:.4f} m^2")
    print()

    # Common RCS values
    print(f"--- Common Reflector RCS at {freq/1e9:.1f} GHz ---")
    rcs_table = [
        ('Aluminum foil 10x10cm', 0.01),
        ('Aluminum foil 20x20cm', 0.16),
        ('Metal plate 30x30cm', 0.81),
        ('Soda can', 0.005),
        ('Human body', 0.5),
        ('Corner reflector 5cm', 0.02),
    ]
    for name, rcs in rcs_table:
        print(f"  {name}: {rcs:.3f} m^2 ({db(rcs):.1f} dBsm)")

    # TX-to-RX turnaround limitation
    tx_to_rx_us = 2.0  # minimum DW3000 turnaround (hardware limit)
    min_detectable_m = C * tx_to_rx_us * 1e-6 / 2
    print(f"\n--- CRITICAL: TX-to-RX Turnaround Limitation ---")
    print(f"  Minimum turnaround time: {tx_to_rx_us:.0f} us (DW3000 hardware)")
    print(f"  Reflections from < {min_detectable_m:.0f}m arrive BEFORE RX window opens")
    print(f"  ALL indoor reflections are MISSED in monostatic mode")
    print(f"  FiRa TX_TO_RX_DELAY is typically 200-500us (even worse)")
    print(f"")
    print(f"  --> Monostatic UWB radar is NOT possible with DW3000 in FiRa mode")
    print(f"  --> A second UWB device is REQUIRED for actual CIR signal measurement")
    print(f"  --> The reflector experiment would produce NO detectable peaks")

    # Theoretical detection range (if monostatic WERE possible)
    print(f"\n--- Theoretical Detection (if monostatic were possible, RCS={args.rcs:.4f} m^2) ---")
    print(f"{'dist':>6s} {'P_rx':>8s} {'SNR':>7s} {'SNR_corr':>9s} {'CIR_bin':>8s} {'detectable':>10s}")
    print("-" * 55)

    distances = [0.1, 0.2, 0.3, 0.5, 0.7, 1.0, 1.5, 2.0, 3.0, 5.0, 7.0, 10.0]
    if args.distance > 0:
        distances = sorted(set(distances + [args.distance]))

    for d in distances:
        p_rx = radar_equation_dbm(p_tx_total_dbm, g_tx, g_rx, args.rcs, wavelength, d)
        snr_pre = p_rx - nf_dbm
        snr_post = snr_pre + processing_gain_db

        cir_bin = round(2 * d / (C / UWB_BW))

        # Will it be above 3-sigma threshold?
        # Map SNR to expected CIR magnitude: mag = noise_mean * 10^(SNR/20)
        expected_mag = measured_noise_mag * from_db(snr_post / 2)
        detectable = "YES" if expected_mag > measured_noise_3sigma else "no"
        if expected_mag > measured_noise_max * 2:
            detectable = "EASY"

        print(f"{d:6.2f}m {p_rx:+8.1f} {snr_pre:+7.1f} {snr_post:+9.1f} "
              f"{cir_bin:8d} {detectable:>10s}")

    # Specific analysis
    if args.distance > 0:
        d = args.distance
        p_rx = radar_equation_dbm(p_tx_total_dbm, g_tx, g_rx, args.rcs, wavelength, d)
        snr_post = (p_rx - nf_dbm) + processing_gain_db
        cir_bin = round(2 * d / (C / UWB_BW))
        print(f"\n--- Detailed Analysis for d={d:.2f}m ---")
        print(f"  Round-trip time: {2*d/C*1e9:.2f} ns")
        print(f"  CIR bin: {cir_bin}")
        print(f"  Received power: {p_rx:.1f} dBm")
        print(f"  Pre-correlator SNR: {p_rx - nf_dbm:.1f} dB")
        print(f"  Post-correlator SNR: {snr_post:.1f} dB")
        if snr_post > 10:
            print(f"  VERDICT: Strong detection expected")
        elif snr_post > 3:
            print(f"  VERDICT: Marginal detection, averaging may help")
        else:
            print(f"  VERDICT: Below noise floor, not detectable")


if __name__ == '__main__':
    main()
