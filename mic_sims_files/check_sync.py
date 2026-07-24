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
  3. Are the four channels sample aligned? The true acoustic delay
     between any two mics cannot exceed the array aperture divided by the
     speed of sound, whatever direction the clap came from. Every channel
     should therefore land within that bound of mic0, plus a little slack.
     A channel sitting far outside it is a filter sync bug, not geometry.

This script does not estimate a direction, and it does not care where the
clap came from. It reads the ACTIVE layout for one number only, the
aperture, to know what delay physics permits before calling a channel
broken. Sizing that bound by hand is how the old 5.0 sample constant
ended up too tight for the built array (see SYNC_TOLERANCE below).

Run:  python check_sync.py [capture.npy]
"""

import sys

import numpy as np

import array_geometry as geom
from localization_sim import gcc_phat

FS = 16000

# How far the correlation search is allowed to look, in samples. Much wider
# than any real delay on the array, so a broken channel can show its true
# offset instead of being clipped to the edge of a tight window.
MAX_LAG_SEARCH = 32

# Pass/fail line for the sync check, in samples.
#
# The largest delay physics allows between any two mics is the array aperture
# (the widest mic-to-mic distance) divided by the speed of sound. A source on
# that axis produces exactly that delay with the channels perfectly synced, so
# the tolerance has to clear it or the check fails correct hardware.
#
# This used to be hardcoded at 5.0, sized for the retired in-line fixture whose
# aperture was about 3 samples. On the built 9.25 x 9.9 cm array the diagonal
# is about 6.3 samples, so a clap near a diagonal would have tripped a FAIL on
# a perfectly synced array. Deriving it from the ACTIVE layout keeps the check
# honest when the geometry changes, the same way localize_capture.py derives
# POOR_CONES from the condition number.
#
# SYNC_SLACK covers correlation noise on a single clap, and reverberation
# pulling the peak slightly off the direct path.
SYNC_SLACK = 2.0
APERTURE_SAMPLES = geom.describe(geom.active_positions())["aperture_samples"]
SYNC_TOLERANCE = APERTURE_SAMPLES + SYNC_SLACK

# Window cut around the clap for the delay math, in samples.
WINDOW_BEFORE = 256
WINDOW_AFTER = 1792


def load_capture(path):
    cap = np.load(path)
    if cap.ndim != 2 or cap.shape[0] != 4:
        raise SystemExit(f"expected a (4, nsamples) array, got {cap.shape}")
    return cap.astype(np.float64)


def channel_health(cap):
    """
    Print per channel level stats and flag anything obviously wrong.

    Everything here is computed with DC removed first. That is not a
    detail: a loud clap leaves a DC excursion that decays over several
    hundred ms, and it is larger on whichever mics got the louder clap.
    Raw RMS therefore mostly measures that tail and makes matched
    channels look like they have a 2x gain mismatch. Measure AC or the
    numbers lie.
    """
    print("channel health (DC removed before rms and peak)")
    print("  mic    rms     peak     mean(DC)   clipped")
    problems = []
    for m, sig in enumerate(cap):
        dc = float(np.mean(sig))
        ac = sig - dc
        rms = float(np.sqrt(np.mean(ac ** 2)))
        peak = float(np.max(np.abs(ac)))
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
            problems.append(f"mic{m} has a large mean DC ({dc:.0f}). Expected "
                            f"after a loud clap: the excursion decays over a "
                            f"few hundred ms and there is no DC blocking in "
                            f"the sinc path. Only worrying if it is also "
                            f"large BEFORE the transient (see the DC drift "
                            f"table), which would point at that channel's "
                            f"right bit shift or offset.")
    print()
    return problems


def find_clap(cap):
    """
    Locate the transient. Uses the summed absolute value across all four
    channels so one weak mic cannot drag the window off the event, then
    walks back to where the energy first rises above the noise floor.

    DC is removed per channel first, for the reason documented at the top of
    localize_capture.find_clap: the DFSDM offset is large and slowly decaying,
    and the median below would otherwise measure that offset rather than room
    noise, understating SNR badly enough to warn on a perfectly good clap.
    Both copies of this locator must stay identical so the two scripts agree.
    """
    cap = cap - cap.mean(axis=1, keepdims=True)
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


def dc_drift(cap, onset):
    """
    Show DC before the transient and in blocks after it.

    This is the table that separates the two very different things a big
    DC number can mean. Small before and large after means the clap
    kicked the front end and it is recovering, which is normal and
    harmless for TDOA. Large before as well means a real per-channel
    offset problem (right bit shift, Offset field, or a mic that is not
    actually streaming), which is worth fixing.
    """
    print("DC drift (mean per 2000-sample block)")
    print("  block    " + "".join(f"  mic{m}  " for m in range(cap.shape[0])))
    for b in range(0, cap.shape[1], 2000):
        seg = cap[:, b:b + 2000]
        mark = " <- clap" if b <= onset < b + 2000 else ""
        vals = "".join(f"{seg[m].mean():7.0f} " for m in range(cap.shape[0]))
        print(f"  {b:5d}   {vals}{mark}")

    pre = cap[:, :max(onset - 200, 1)]
    pre_dc = [float(pre[m].mean()) for m in range(cap.shape[0])]
    print(f"  pre-clap DC: " +
          "  ".join(f"mic{m} {pre_dc[m]:.0f}" for m in range(cap.shape[0])))

    # The honest channel-matching metric. The whole-capture rms above still
    # contains the decay tail (a single mean cannot remove a time-varying
    # offset), so quiet room noise before the event is what to compare.
    pre_ac = pre - pre.mean(axis=1, keepdims=True)
    pre_rms = np.sqrt((pre_ac ** 2).mean(axis=1))
    print(f"  pre-clap rms: " +
          "  ".join(f"mic{m} {pre_rms[m]:.1f}" for m in range(cap.shape[0])) +
          f"   (spread {pre_rms.max() / max(pre_rms.min(), 1e-9):.2f}x)")
    if pre_rms.max() / max(pre_rms.min(), 1e-9) > 2.0:
        print("  WARNING: channels differ by more than 2x on room noise. "
              "That is a real gain or wiring difference, not clap position.")
    if max(abs(d) for d in pre_dc) > 500:
        print("  WARNING: DC is already large before the transient, so this "
              "is not clap recovery. Check right bit shift and Offset.")
    print()


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
    print("  (a louder channel trips a fixed-fraction threshold earlier, so a")
    print("   spread here with matched GCC-PHAT lags means level, not sync)")
    ref = None
    for m, sig in enumerate(cap):
        seg = sig[start:stop]
        seg = np.abs(seg - seg.mean())          # DC would bias the threshold
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
    print(f"  tolerance {SYNC_TOLERANCE:.2f} samples "
          f"= {APERTURE_SAMPLES:.2f} aperture ({geom.ACTIVE}) "
          f"+ {SYNC_SLACK:.1f} slack")
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
        print(f"PASS: all four channels within {SYNC_TOLERANCE:.2f} samples "
              f"(worst {worst:.2f}). Filter sync looks correct.")
    else:
        print(f"FAIL: worst offset {worst:.2f} samples, over the "
              f"{SYNC_TOLERANCE:.2f} sample tolerance.")
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
    dc_drift(cap, onset)
    start, stop = sync_check(cap, onset)
    print()
    per_channel_onset(cap, start, stop)

    if problems:
        print("issues worth fixing before trusting the numbers above:")
        for p in problems:
            print(f"  - {p}")
        print()

    maybe_plot(cap, start, stop)
