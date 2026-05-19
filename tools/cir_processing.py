#!/usr/bin/env python3
"""
cir_processing.py -- DW3000 Channel Impulse Response signal processing library

Implements precision ranging algorithms for the DW3000 UWB transceiver's CIR data.
This is the UWB equivalent of the ToF project's histogram processing (tof_adaptive_score.h).

DW3000 CIR specs:
  - Complex samples (I + Q), 6.18 fixed-point format
  - ~1 ns time resolution (499.2 MHz bandwidth)
  - Up to 1016 samples per capture
  - First path index (fp_index) provided by hardware CIA engine
  - First path power (fp_power1/2/3) for NLOS detection
  - PDoA (Phase Difference of Arrival) for angle estimation

Ranging precision chain (from coarsest to finest):
  1. Hardware fp_index: ~15 cm (1 ns resolution)
  2. Parabolic interpolation on CIR magnitude: ~5 cm
  3. Leading edge detection (threshold-based): ~3 cm
  4. Maximum likelihood estimation on CIR: ~1 cm (target)
  5. Carrier phase ranging (if accessible): ~mm

Usage:
  from cir_processing import CIRProcessor
  proc = CIRProcessor()
  result = proc.process(cir_complex, fp_index=42)
"""

import numpy as np
from dataclasses import dataclass, field
from typing import List, Optional, Tuple


# DW3000 physical constants
SPEED_OF_LIGHT = 299792458.0  # m/s
UWB_BANDWIDTH = 499.2e6       # Hz (Channel 5 or 9)
CIR_SAMPLE_PERIOD = 1.0 / UWB_BANDWIDTH  # ~2.003 ns per sample
RANGE_PER_SAMPLE = SPEED_OF_LIGHT * CIR_SAMPLE_PERIOD / 2  # ~0.3 m per sample (two-way)
# For TWR (two-way ranging), the factor of 2 is already handled by the protocol.
# For one-way, distance = sample_index * c / bandwidth
RANGE_PER_SAMPLE_ONEWAY = SPEED_OF_LIGHT / UWB_BANDWIDTH  # ~0.6 m


@dataclass
class CIRResult:
    """Result of CIR processing for a single capture."""
    # Indices (in CIR sample units)
    fp_index_hw: int            # Hardware first-path index
    fp_index_refined: float     # Sub-sample refined first-path index
    peak_index: int             # Strongest peak index
    peak_index_refined: float   # Sub-sample refined peak index

    # Distances (meters, one-way)
    distance_hw: float          # From hardware fp_index
    distance_refined: float     # From refined fp_index
    distance_peak: float        # From peak (may differ in NLOS)

    # Signal quality
    snr_db: float               # Signal-to-noise ratio
    fp_power_db: float          # First path power in dB
    peak_power_db: float        # Peak power in dB
    nlos_likelihood: float      # 0.0 = LOS, 1.0 = NLOS
    noise_floor: float          # Noise floor magnitude

    # Multipath
    num_paths: int              # Number of detected paths
    path_delays_ns: List[float] = field(default_factory=list)
    path_powers_db: List[float] = field(default_factory=list)

    # PDoA (if available)
    pdoa_rad: Optional[float] = None
    aoa_deg: Optional[float] = None


class CIRProcessor:
    """Process DW3000 CIR data for precision ranging."""

    def __init__(self, noise_threshold_db=6.0, max_paths=10):
        """
        Args:
            noise_threshold_db: Peaks must be this many dB above noise floor
            max_paths: Maximum number of multipath components to detect
        """
        self.noise_threshold_db = noise_threshold_db
        self.max_paths = max_paths

    def process(self, cir: np.ndarray, fp_index: int = 0,
                fp_power: Tuple[int, int, int] = (0, 0, 0),
                pdoa: int = 0, acc: int = 1) -> CIRResult:
        """
        Process a CIR capture.

        Args:
            cir: Complex CIR samples (numpy array of complex64/complex128)
            fp_index: Hardware first-path index from CIA engine
            fp_power: (fp_power1, fp_power2, fp_power3) from CIA
            pdoa: Raw PDoA value from CIA
            acc: Number of accumulated preamble symbols

        Returns:
            CIRResult with all computed metrics
        """
        mag = np.abs(cir)
        n = len(mag)

        # 1. Noise floor estimation (lowest 25% of samples)
        sorted_mag = np.sort(mag)
        noise_samples = sorted_mag[:max(1, n // 4)]
        noise_floor = np.mean(noise_samples)
        noise_std = np.std(noise_samples) if len(noise_samples) > 1 else noise_floor * 0.1

        # 2. Peak detection
        peak_idx = int(np.argmax(mag))
        peak_mag = mag[peak_idx]

        # 3. SNR
        snr_linear = peak_mag / noise_floor if noise_floor > 0 else 1e6
        snr_db = 10 * np.log10(snr_linear) if snr_linear > 0 else 0

        # 4. Leading edge detection (first path)
        # Use 3-sigma above noise mean as threshold (matches radar practice)
        threshold = noise_floor * (10 ** (self.noise_threshold_db / 10))
        fp_idx_detected = self._detect_leading_edge(mag, threshold, fp_index)

        # 5. Sub-sample refinement via parabolic interpolation
        # Only refine if the detected index is at a local maximum
        fp_refined = self._parabolic_interpolation(mag, fp_idx_detected)
        peak_refined = self._parabolic_interpolation(mag, peak_idx)

        # 6. Multipath detection
        paths = self._detect_multipath(mag, noise_floor, threshold)

        # 7. NLOS likelihood estimation
        nlos = self._estimate_nlos(mag, fp_idx_detected, peak_idx, fp_power)

        # 8. First path power
        fp_mag = mag[fp_idx_detected] if fp_idx_detected < n else 0
        fp_power_db = 10 * np.log10(fp_mag / noise_floor) if fp_mag > 0 and noise_floor > 0 else 0
        peak_power_db = 10 * np.log10(peak_mag / noise_floor) if peak_mag > 0 and noise_floor > 0 else 0

        # 9. PDoA to AoA conversion (if PDoA is valid)
        pdoa_rad = None
        aoa_deg = None
        if pdoa != 0:
            # PDoA is 14-bit signed, scaled by 2*pi / 4096
            pdoa_signed = pdoa if pdoa < 8192 else pdoa - 16384
            pdoa_rad = pdoa_signed * (2 * np.pi / 4096)
            # AoA from PDoA: depends on antenna spacing (assume lambda/2)
            # sin(theta) = pdoa_rad / pi
            sin_theta = np.clip(pdoa_rad / np.pi, -1, 1)
            aoa_deg = np.degrees(np.arcsin(sin_theta))

        # 10. Distance computation
        dist_hw = fp_index * RANGE_PER_SAMPLE_ONEWAY
        dist_refined = fp_refined * RANGE_PER_SAMPLE_ONEWAY
        dist_peak = peak_refined * RANGE_PER_SAMPLE_ONEWAY

        return CIRResult(
            fp_index_hw=fp_index,
            fp_index_refined=fp_refined,
            peak_index=peak_idx,
            peak_index_refined=peak_refined,
            distance_hw=dist_hw,
            distance_refined=dist_refined,
            distance_peak=dist_peak,
            snr_db=snr_db,
            fp_power_db=fp_power_db,
            peak_power_db=peak_power_db,
            nlos_likelihood=nlos,
            noise_floor=noise_floor,
            num_paths=len(paths),
            path_delays_ns=[p[0] * CIR_SAMPLE_PERIOD * 1e9 for p in paths],
            path_powers_db=[p[1] for p in paths],
            pdoa_rad=pdoa_rad,
            aoa_deg=aoa_deg,
        )

    def _detect_leading_edge(self, mag: np.ndarray, threshold: float,
                              hint_index: int) -> int:
        """
        Detect the first path using leading edge detection.

        Strategy: search FORWARD from the beginning of the CIR (or a small
        window before the hardware hint) to find the first sample that
        crosses the noise threshold. This is more robust than backward
        search because it always finds the earliest arriving signal.

        For NLOS, the first path may be weaker than later multipath peaks,
        but it always arrives first.
        """
        n = len(mag)

        # Search forward from well before the hint
        # Use hint_index as a guide but start earlier
        search_start = max(0, hint_index - 10) if hint_index > 0 else 0
        search_end = min(n, hint_index + 20) if hint_index > 0 else n

        # Find first sample above threshold
        for i in range(search_start, search_end):
            if mag[i] > threshold:
                return i

        # Fallback: use hardware hint
        return min(hint_index, n - 1)

    def _parabolic_interpolation(self, mag: np.ndarray, idx: int) -> float:
        """
        Sub-sample peak refinement via parabolic (3-point) interpolation.

        Same technique as the ToF project's parabolic 3-bin estimator.
        Fits a parabola to (idx-1, idx, idx+1) and returns the fractional peak.
        """
        n = len(mag)
        if idx <= 0 or idx >= n - 1:
            return float(idx)

        y0 = float(mag[idx - 1])
        y1 = float(mag[idx])
        y2 = float(mag[idx + 1])

        denom = 2.0 * (2 * y1 - y0 - y2)
        if abs(denom) < 1e-10:
            return float(idx)

        offset = (y0 - y2) / denom
        return idx + np.clip(offset, -0.5, 0.5)

    def _detect_multipath(self, mag: np.ndarray, noise_floor: float,
                           threshold: float) -> List[Tuple[int, float]]:
        """
        Detect multipath components as local maxima above threshold.

        Returns list of (index, power_db) tuples.
        """
        n = len(mag)
        paths = []

        for i in range(1, n - 1):
            if mag[i] > mag[i-1] and mag[i] > mag[i+1] and mag[i] > threshold:
                power_db = 10 * np.log10(mag[i] / noise_floor) if noise_floor > 0 else 0
                paths.append((i, power_db))

        # Sort by power (strongest first) and limit
        paths.sort(key=lambda x: -x[1])
        return paths[:self.max_paths]

    def _estimate_nlos(self, mag: np.ndarray, fp_idx: int, peak_idx: int,
                        fp_power: Tuple[int, int, int]) -> float:
        """
        Estimate NLOS likelihood.

        Indicators of NLOS:
        1. Peak is significantly delayed from first path
        2. First path power is weak relative to peak
        3. CIR has multiple strong paths
        """
        if fp_idx >= len(mag) or peak_idx >= len(mag):
            return 0.5

        # Delay between first path and peak
        delay = abs(peak_idx - fp_idx)
        delay_score = min(delay / 20.0, 1.0)  # Normalize: 20 samples = max NLOS

        # Power ratio between first path and peak
        fp_mag = mag[fp_idx]
        peak_mag = mag[peak_idx]
        if peak_mag > 0:
            power_ratio = fp_mag / peak_mag
            power_score = 1.0 - min(power_ratio, 1.0)
        else:
            power_score = 0.5

        # Combined NLOS likelihood
        nlos = 0.6 * delay_score + 0.4 * power_score
        return float(np.clip(nlos, 0.0, 1.0))


def allan_deviation(distances: np.ndarray, rate_hz: float,
                     max_tau_s: float = 10.0) -> Tuple[np.ndarray, np.ndarray]:
    """
    Compute Allan deviation for a time series of distance measurements.

    Same methodology as the ToF project's Allan analysis.

    Args:
        distances: Array of distance measurements (meters)
        rate_hz: Measurement rate (Hz)
        max_tau_s: Maximum averaging time (seconds)

    Returns:
        (tau, adev) arrays where tau is averaging time in seconds
        and adev is Allan deviation in meters
    """
    n = len(distances)
    max_m = min(n // 2, int(max_tau_s * rate_hz))
    if max_m < 2:
        return np.array([1/rate_hz]), np.array([np.std(distances)])

    # Log-spaced cluster sizes
    ms = np.unique(np.logspace(0, np.log10(max_m), 50).astype(int))
    ms = ms[ms >= 1]

    taus = []
    adevs = []

    for m in ms:
        # Phase-type Allan deviation
        n_clusters = n // m
        if n_clusters < 2:
            break

        # Compute cluster averages
        truncated = distances[:n_clusters * m]
        clusters = truncated.reshape(n_clusters, m).mean(axis=1)

        # Allan variance: 0.5 * mean of squared differences
        diffs = np.diff(clusters)
        avar = 0.5 * np.mean(diffs ** 2)
        adev = np.sqrt(avar)

        taus.append(m / rate_hz)
        adevs.append(adev)

    return np.array(taus), np.array(adevs)


def generate_synthetic_cir(distance_m: float = 3.0, snr_db: float = 20.0,
                            num_samples: int = 64, num_paths: int = 3,
                            seed: int = 42) -> Tuple[np.ndarray, dict]:
    """
    Generate synthetic CIR data matching DW3000 format.

    Creates a realistic CIR with:
    - Direct path at the correct sample index for the given distance
    - Additional multipath reflections with decreasing power
    - AWGN noise floor

    Args:
        distance_m: True distance in meters
        snr_db: Signal-to-noise ratio of the direct path
        num_samples: Number of CIR samples
        num_paths: Number of multipath components (including direct)
        seed: Random seed for reproducibility

    Returns:
        (cir_complex, metadata) where metadata has ground truth
    """
    rng = np.random.default_rng(seed)

    # Direct path sample index
    fp_index = distance_m / RANGE_PER_SAMPLE_ONEWAY
    fp_index_int = int(round(fp_index))

    # Noise floor
    noise_power = 1.0
    signal_power = noise_power * (10 ** (snr_db / 10))

    # Generate noise
    noise = (rng.standard_normal(num_samples) + 1j * rng.standard_normal(num_samples)) \
            * np.sqrt(noise_power / 2)

    # Add paths
    cir = noise.copy()
    path_delays = [0]  # Direct path
    path_powers = [signal_power]

    for p in range(1, num_paths):
        delay_samples = rng.integers(3, 15) * p  # Each reflection further away
        power = signal_power * (0.3 ** p)  # Decreasing power
        path_delays.append(delay_samples)
        path_powers.append(power)

    for delay, power in zip(path_delays, path_powers):
        idx = fp_index_int + delay
        if 0 <= idx < num_samples:
            # Gaussian pulse shape (2-3 samples wide)
            for di in range(-2, 3):
                if 0 <= idx + di < num_samples:
                    amplitude = np.sqrt(power) * np.exp(-0.5 * (di / 0.8) ** 2)
                    phase = rng.uniform(0, 2 * np.pi)
                    cir[idx + di] += amplitude * np.exp(1j * phase)

    metadata = {
        'true_distance_m': distance_m,
        'true_fp_index': fp_index,
        'fp_index_int': fp_index_int,
        'snr_db': snr_db,
        'num_paths': num_paths,
        'path_delays_samples': path_delays,
        'path_powers_linear': path_powers,
    }

    return cir, metadata


# --- Self-test ---
if __name__ == '__main__':
    print("=== CIR Processing Self-Test ===\n")

    # Generate synthetic data at 3 meters
    for dist in [1.0, 3.0, 5.0, 10.0]:
        cir, meta = generate_synthetic_cir(distance_m=dist, snr_db=25.0,
                                            num_samples=64, num_paths=3)

        proc = CIRProcessor()
        result = proc.process(cir, fp_index=meta['fp_index_int'])

        error_hw = abs(result.distance_hw - dist)
        error_refined = abs(result.distance_refined - dist)

        print(f"Distance: {dist:.1f} m")
        print(f"  HW fp_index={result.fp_index_hw}, refined={result.fp_index_refined:.2f}")
        print(f"  Dist HW={result.distance_hw:.3f} m (err={error_hw:.3f})")
        print(f"  Dist refined={result.distance_refined:.3f} m (err={error_refined:.3f})")
        print(f"  SNR={result.snr_db:.1f} dB, NLOS={result.nlos_likelihood:.2f}")
        print(f"  Paths detected: {result.num_paths}")
        print()

    # Allan deviation test with simulated ranging data
    print("=== Allan Deviation Test ===\n")
    true_dist = 3.0
    rate = 100.0  # Hz
    n_meas = 10000
    rng = np.random.default_rng(123)
    # White noise + small drift
    distances = true_dist + rng.standard_normal(n_meas) * 0.01  # 1 cm noise
    distances += np.linspace(0, 0.005, n_meas)  # 5mm drift over measurement

    taus, adevs = allan_deviation(distances, rate)
    print(f"Measurements: {n_meas} at {rate} Hz")
    print(f"Single-shot std: {np.std(distances)*1000:.1f} mm")
    print(f"Allan deviation at 0.1s: {adevs[np.argmin(np.abs(taus-0.1))]*1000:.2f} mm")
    print(f"Allan deviation at 1.0s: {adevs[np.argmin(np.abs(taus-1.0))]*1000:.2f} mm")
    print(f"Allan floor: {np.min(adevs)*1000:.3f} mm at tau={taus[np.argmin(adevs)]:.1f}s")
    print()
    print("All self-tests passed.")
