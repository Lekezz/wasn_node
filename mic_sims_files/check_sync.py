"""
check_sync.py

Bring-up check for the four mic capture. Run it on capture.npy right after
catch_audio4.py saves one.

It answers three questions, in order:

  1. Is every channel alive? A dead or badly wired mic shows up as near
     zero RMS, or as a rail-to-rail constant, long before any delay math
     matters.
  2. Where is the clap? It finds the loudest transient and cuts a short
     window around it, so the delay math only sees the event and not a
     second of room noise.
  3. Are the four channels sample aligned? On the temporary in-line
     fixture the mics sit roughly 2 cm apart, so the true acoustic delay
     across the whole array is under about 3 samples at 16 kHz. Every
     channel should therefore land within a couple of samples of mic0.
     A channel sitting far off is a filter sync bug, not geometry.

This script is deliberately geometry free. It does not touch MIC_POS and
does not try to estimate a direction, because the bring-up fixture has no
usable angular resolution.

Run:  python check_sync.py [capture.npy]
"""

import sys

import numpy as np

from localization_sim import gcc_phat

FS = 16000

# How far the correlation search is allowed to look, in samples. Much wider
# than any real delay on this fixture (about 3 samples end to end), so a
# broken channel can show its true offset instead of being clipped to the
# edge of a tight window.
MAX_LAG_SEARCH = 32

# Pass/fail line for the sync check, in samples. 3 samples is the physical
# aperture of the in-line fixture, and 2 more samples of slack covers
# correlation noise on a single clap.
SYNC_TOLERANCE = 5.0

# Window cut around the clap for the delay math, in samples.
WINDOW_BEFORE = 256
WINDOW_AFTER = 1792


def load_capture(path):
    cap = np.load(path)
    if cap.ndim != 2 or cap.shape[0] != 4:
        raise SystemExit(f"expected a (4, nsamples) array, got {cap.shape}")
    return cap.astype(np.float64)


def channel_health(cap):
    """Print per channel level stats and flag anything obviously wrong."""
    print("channel health")
    print("  mic    rms     peak     mean(DC)   clipped")
    problems = []
    for m, sig in enumerate(cap):
        rms = float(np.sqrt(np.mean(sig ** 2)))
        peak = float(np.max(np.abs(sig)))
        dc = float(np.mean(sig))
        clipped = int(np.sum(np.abs(sig) >= 32700))
        print(f"  {m}   {rms:8.1f} {peak:8.0f} {dc:10.1f} {clipped:9d}")

        if rms < 5.0:
            problems.append(f"mic{m} is essentially silent (rms {rms:.1f}). "
                            f"Check DOUT wiring, SEL level, and that this "
                            f"filter's channel edge matches the SEL level.")
        if clipped > 0:
            problems.append(f"mic{m} clipped on {clipped} samples. Clap from "
                            f"further away or the peak position is unreliable.")
        if abs(dc) > 2000:
            problems.append(f"mic{m} has a large DC offset ({dc:.0f}). Usually "
                            f"filter settling; if it persists, check the "
                            f"right bit shift for that channel.")
    print()
    return problems


def find_clap(cap):
    """
    Locate the transient. Uses the summed absolute value across all four
    channels so one weak mic cannot drag the window off the event, then
    walks back to where the energy first rises above the noise floor.
    """
    env = np.sum(np.abs(cap), axis=0)
    peak = int(np.argmax(env))

    noise = np.median(env)
    threshold = noise + 0.2 * (env[peak] - noise)

    onset = peak
    while onset > 0 and env[onset] > threshold:
        onset -= 1

    print(f"loudest transient at sample {peak} ({peak / FS:.3f} s), "
          f"onset near {onset} ({onset / FS:.3f} s)")
    print(f"  peak envelope {env[peak]:.0f} vs noise floor {noise:.0f} "
          f"(ratio {env[peak] / max(noise, 1e-9):.1f})")
    if env[peak] < 10 * max(noise, 1e-9):
        print("  WARNING: that is a weak transient. Clap louder or closer; "
              "delay estimates from this capture will be noisy.")
    print()
    return onset


def per_channel_onset(cap, start, stop):
    """
    Crude independent onset per channel, as a sanity cross check on the
    correlation result. Threshold crossing only, so it is quantized to
    whole samples and will disagree with GCC-PHAT by a sample or so. It is
    here because it fails differently: if a channel is a copy of another
    channel rather than its own mic, correlation looks perfect while these
    do not.
    """
    print("independent threshold onsets (whole samples, rough)")
    ref = None
    for m, sig in enumerate(cap):
        seg = np.abs(sig[start:stop])
        floor = np.median(seg)
        thresh = floor + 0.25 * (seg.max() - floor)
        idx = int(np.argmax(seg > thresh)) + start
        if ref is None:
            ref = idx
        print(f"  mic{m}: sample {idx}   ({idx - ref:+d} vs mic0)")
    print()


def sync_check(cap, onset):
    start = max(0, onset - WINDOW_BEFORE)
    stop = min(cap.shape[1], onset + WINDOW_AFTER)
    win = cap[:, start:stop]

    # Remove DC inside the window. GCC-PHAT is a phase method and a constant
    # offset just adds a big meaningless bin at zero frequency.
    win = win - win.mean(axis=1, keepdims=True)

    print(f"GCC-PHAT lags over samples {start}..{stop}, reference mic0")
    print("  mic    lag (samples)   lag (us)   verdict")
    worst = 0.0
    for m in range(cap.shape[0]):
        # gcc_phat(a, b) returns (t_a - t_b), so this is (t_m - t_0):
        # positive means mic m heard the clap later than mic0.
        lag = -gcc_phat(win[0], win[m], MAX_LAG_SEARCH)
        ok = abs(lag) <= SYNC_TOLERANCE
        worst = max(worst, abs(lag))
        print(f"  {m}   {lag:+13.3f} {lag / FS * 1e6:+10.1f}   "
              f"{'ok' if ok else 'OUT OF RANGE'}")
    print()

    if worst <= SYNC_TOLERANCE:
        print(f"PASS: all four channels within {SYNC_TOLERANCE:.0f} samples "
              f"(worst {worst:.2f}). Filter sync looks correct.")
    else:
        print(f"FAIL: worst offset {worst:.2f} samples, over the "
              f"{SYNC_TOLERANCE:.0f} sample tolerance.")
        print("  Likely causes, in the order worth checking:")
        print("   - a filter did not start on the sync trigger (filter0 must")
        print("     be started LAST, filters 1-3 armed with SYNC_TRIGGER)")
        print("   - a channel's clock edge does not match its mic's SEL level")
        print("   - two mics swapped physically versus the mic map")
    return start, stop


def maybe_plot(cap, start, stop):
    try:
        import matplotlib.pyplot as plt
    except ImportError:
        print("\n(matplotlib not installed, skipping the plot: "
              "pip install matplotlib)")
        return

    t = np.arange(start, stop) / FS * 1000.0
    fig, axes = plt.subplots(4, 1, sharex=True, sharey=True, figsize=(9, 7))
    for m, ax in enumerate(axes):
        ax.plot(t, cap[m, start:stop], linewidth=0.8)
        ax.set_ylabel(f"mic{m}")
        ax.grid(alpha=0.3)
    axes[-1].set_xlabel("time (ms from start of capture)")
    fig.suptitle("clap window, all four channels")
    fig.tight_layout()
    plt.show()


if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else "capture.npy"
    cap = load_capture(path)
    print(f"loaded {path}: {cap.shape[0]} channels, {cap.shape[1]} samples "
          f"({cap.shape[1] / FS:.3f} s)\n")

    problems = channel_health(cap)
    onset = find_clap(cap)
    start, stop = sync_check(cap, onset)
    print()
    per_channel_onset(cap, start, stop)

    if problems:
        print("issues worth fixing before trusting the numbers above:")
        for p in problems:
            print(f"  - {p}")
        print()

    maybe_plot(cap, start, stop)
