"""
localization_sim.py

Offline simulation of the source localization algorithm (GCC-PHAT + least
squares direction fit) for a 4 microphone array.
This script:
  1. places 4 mics in a chosen geometry
  2. places a sound source at a known angle
  3. generates a random test signal and delays it to each mic exactly the
     way physics would (plus some noise)
  4. runs GCC-PHAT on each mic pair to estimate the delays back
  5. fuses the pair delays into a direction estimate
  6. prints estimated vs true angle so you can see how well it did

The same math will later run on the board (CMSIS-DSP), so this file doubles
as the reference implementation to compare the firmware against.

Only needs numpy. Run:  python localization_sim.py
"""

import numpy as np

# ---------------------------------------------------------------------------
# Constants and array geometry
# ---------------------------------------------------------------------------

C_SOUND = 343.0     # speed of sound in air, m/s (room temperature)
FS = 16000          # sample rate in Hz, same as the firmware

# Mic positions in meters, one (x, y) row per mic.
# Default: 10 cm square centered on the origin, which is roughly the scale
# of a wearable array. Editable the rest of the script adapts.
#
#   mic1 .        . mic0          y
#                                 ^
#   mic2 .        . mic3          +--> x
#
MIC_POS = np.array([
    [ 0.05,  0.05],   # mic 0: front right
    [-0.05,  0.05],   # mic 1: front left
    [-0.05, -0.05],   # mic 2: back left
    [ 0.05, -0.05],   # mic 3: back right
])

NUM_MICS = len(MIC_POS)

# All unique mic pairs, e.g. (0,1), (0,2) 6 pairs for 4 mics.
PAIRS = [(i, j) for i in range(NUM_MICS) for j in range(i + 1, NUM_MICS)]


# ---------------------------------------------------------------------------
# Signal simulation
# ---------------------------------------------------------------------------

def make_source_signal(n_samples, rng):
    """
    Make a random test signal that stands in for a clap or speech burst.

    White noise through a crude bandpass works well: it has energy spread
    over many frequencies, which is what gives cross correlation a sharp
    peak. A pure sine would be a bad test signal because its correlation
    is ambiguous (it matches itself every period).
    """
    sig = rng.standard_normal(n_samples)

    # Cheap bandpass by differencing (kills DC) then a short moving average
    sig = np.diff(sig, prepend=0.0)
    kernel = np.ones(4) / 4.0
    sig = np.convolve(sig, kernel, mode="same")

    # Fade in/out so the burst doesn't have hard edges
    env = np.hanning(n_samples)
    return sig * env


def fractional_delay(sig, delay_samples):
    """
    Delay a signal by a possibly non-integer number of samples.

    Real acoustic delays are almost never a whole number of samples, so the
    simulation has to support fractions or it would be unrealistically easy.
    The trick: a delay in time is a linear phase ramp in frequency, so we
    FFT, multiply by exp(-j*2*pi*f*delay), and inverse FFT. Exact for
    band limited signals.
    """
    n = len(sig)
    spectrum = np.fft.rfft(sig)
    freqs = np.fft.rfftfreq(n)                      # cycles per sample
    spectrum *= np.exp(-2j * np.pi * freqs * delay_samples)
    return np.fft.irfft(spectrum, n=n)


def simulate_capture(source_angle_deg, source_dist=2.0, n_samples=2048,
                     snr_db=20.0, seed=None):
    """
    Produce what the 4 mics 'would have recorded' for a source at the given
    angle (degrees, counterclockwise from the +x axis) and distance (m).

    Returns (mic_signals, true_delays) where mic_signals is a
    (NUM_MICS, n_samples) array and true_delays[i] is mic i's absolute
    arrival delay in samples (useful for checking the estimator).
    """
    rng = np.random.default_rng(seed)

    # Source position in the same coordinate frame as the mics
    theta = np.radians(source_angle_deg)
    src = source_dist * np.array([np.cos(theta), np.sin(theta)])

    # Distance from source to each mic -> arrival delay in samples.
    # We only care about relative delays, so subtract the minimum to keep
    # numbers small.
    dists = np.linalg.norm(MIC_POS - src, axis=1)
    delays = (dists / C_SOUND) * FS
    delays -= delays.min()

    dry = make_source_signal(n_samples, rng)

    mic_signals = np.zeros((NUM_MICS, n_samples))
    for m in range(NUM_MICS):
        clean = fractional_delay(dry, delays[m])
        # Add independent noise per mic at the requested SNR
        noise_power = np.var(clean) / (10 ** (snr_db / 10))
        noise = rng.standard_normal(n_samples) * np.sqrt(noise_power)
        mic_signals[m] = clean + noise

    return mic_signals, delays


# ---------------------------------------------------------------------------
# GCC-PHAT delay estimation (the part that will move to the board)
# ---------------------------------------------------------------------------

def gcc_phat(sig_a, sig_b, max_tau_samples):
    """
    Estimate how many samples sig_b lags sig_a using GCC-PHAT.

    Steps:
      1. FFT both signals (zero padded so correlation doesn't wrap around)
      2. cross spectrum = A * conj(B)
      3. PHAT weighting: divide by magnitude, keeping only phase. Phase is
         'when', magnitude is 'what', and for localization only 'when'
         matters. This is what sharpens the peak in echoey rooms.
      4. inverse FFT -> correlation curve, peak location = delay
      5. parabolic interpolation around the peak for sub sample precision

    max_tau_samples: physics limit. Two mics can never disagree by more
    than spacing/c, so we only search inside that window. Kills most
    spurious peaks for free.
    """
    n = len(sig_a) + len(sig_b)         # zero pad to at least 2x
    A = np.fft.rfft(sig_a, n=n)
    B = np.fft.rfft(sig_b, n=n)

    R = A * np.conj(B)
    R /= (np.abs(R) + 1e-12)            # PHAT: normalize magnitude away

    cc = np.fft.irfft(R, n=n)

    # Rearrange so index 0 = most negative lag, center = zero lag
    max_shift = int(np.ceil(max_tau_samples)) + 1
    cc = np.concatenate((cc[-max_shift:], cc[:max_shift + 1]))

    peak = np.argmax(np.abs(cc))

    # Parabolic interpolation: fit a parabola through the peak and its two
    # neighbors, use the parabola's vertex as the refined peak position.
    # This is what buys sub sample (sub 2 cm) resolution.
    if 0 < peak < len(cc) - 1:
        y0, y1, y2 = np.abs(cc[peak - 1]), np.abs(cc[peak]), np.abs(cc[peak + 1])
        denom = (y0 - 2 * y1 + y2)
        offset = 0.5 * (y0 - y2) / denom if abs(denom) > 1e-12 else 0.0
    else:
        offset = 0.0

    delay = (peak + offset) - max_shift
    return delay          # in samples; equals (t_a - t_b), see run_trial


# ---------------------------------------------------------------------------
# Fusing pair delays into one direction (least squares)
# ---------------------------------------------------------------------------

def estimate_direction(pair_delays):
    """
    Turn the six pairwise delays into a single arrival direction.

    Far field model: let u be the unit vector pointing from the array
    toward the source. A mic further along u is closer to the source and
    hears the sound earlier, so arrival times satisfy
        t_j - t_i = ((pos_i - pos_j) . u) / c
    Each measured pair delay gives one linear equation in u = (ux, uy).
    Six pairs -> overdetermined system -> least squares. The redundancy is
    the point: any one noisy pair gets outvoted.

    pair_delays values must be (t_j - t_i) in samples.
    Returns the estimated angle in degrees.
    """
    rows = []
    rhs = []
    for (i, j), tau in pair_delays.items():
        baseline = MIC_POS[i] - MIC_POS[j]          # note the order, see model
        rows.append(baseline)
        rhs.append(tau / FS * C_SOUND)              # samples -> meters

    A = np.array(rows)
    b = np.array(rhs)
    u, *_ = np.linalg.lstsq(A, b, rcond=None)

    # u should be a unit vector but noise makes its length drift, and only
    # its direction carries information, so just take the angle.
    return np.degrees(np.arctan2(u[1], u[0]))


# ---------------------------------------------------------------------------
# Main experiment
# ---------------------------------------------------------------------------

def run_trial(true_angle, seed=None, verbose=True):
    """Simulate one sound event and localize it. Returns angle error in deg."""
    mic_sigs, true_delays = simulate_capture(true_angle, seed=seed)

    pair_delays = {}
    for (i, j) in PAIRS:
        spacing = np.linalg.norm(MIC_POS[j] - MIC_POS[i])
        max_tau = spacing / C_SOUND * FS            # physics search limit
        # gcc_phat(a, b) returns (t_a - t_b). We store delays as
        # (t_j - t_i) everywhere, matching the 'true' column below,
        # hence the minus sign.
        pair_delays[(i, j)] = -gcc_phat(mic_sigs[i], mic_sigs[j], max_tau)

    est_angle = estimate_direction(pair_delays)

    # Angle error wrapped to [-180, 180]
    err = (est_angle - true_angle + 180) % 360 - 180

    if verbose:
        print(f"\nSource at {true_angle:7.1f} deg -> estimated "
              f"{est_angle:7.1f} deg   (error {err:+6.2f} deg)")
        print("  pair   measured    true (samples)")
        for (i, j) in PAIRS:
            true_tau = true_delays[j] - true_delays[i]
            print(f"  {i}-{j}    {pair_delays[(i, j)]:+7.3f}    {true_tau:+7.3f}")
    return err


if __name__ == "__main__":
    print("4 mic GCC-PHAT localization simulation")
    print(f"Sample rate {FS} Hz, mic spacing "
          f"{np.linalg.norm(MIC_POS[0] - MIC_POS[1]) * 100:.0f} cm, "
          f"{len(PAIRS)} pairs")

    # Sweep a source around the array, one random signal per angle
    test_angles = np.arange(0, 360, 30)
    errors = []
    for k, ang in enumerate(test_angles):
        errors.append(run_trial(ang, seed=k))

    errors = np.array(errors)
    print("\nSummary over the sweep:")
    print(f"  mean absolute error: {np.mean(np.abs(errors)):.2f} deg")
    print(f"  worst case error:    {np.max(np.abs(errors)):.2f} deg")
    print("\nThings to try: shrink MIC_POS to see accuracy degrade, lower")
    print("snr_db in simulate_capture, or reduce FS to mimic a slower rate.")
