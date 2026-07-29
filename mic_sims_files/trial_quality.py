"""
trial_quality.py

Judge one capture the moment it lands, while you are still standing at the
bench and can just clap again.

Why this exists: until now a bad clap was only discovered at analysis time,
hours later, when re-recording meant setting the whole angle up again. Every
check below was already somewhere in the project, but each lived at the end
of a different script. Collecting them into one pass over the samples turns
"we will find out later" into a pass or fail printed a second after the dump.

Nothing here invents a new number. Every threshold is one the project
already committed to somewhere else, and every measurement is imported from
the script that owns it, so the bench check and the analysis cannot drift
apart:

  clipping and channel level   check_sync.channel_stats, with check_sync's
                               own CLIP_LEVEL and SILENT_RMS
  transient strength           localize_capture.find_clap, threshold 20,
                               the number localize_capture already warns on
  pair delays and bearing      localize_capture.localize, which is the
                               localization_sim reference implementation
  triangle residual            compare_board.triangle_residual, threshold
                               0.3 samples, the same figure localize.c uses
                               to print "(inconsistent: suspect a
                               reflection)" on the board itself

Run:  python trial_quality.py [capture.npy] [--true-angle DEG]

which is useful on its own for judging a capture you already have.
"""

import sys

import numpy as np

import array_geometry as geom
import capture_paths as cp
import check_sync as cs
import compare_board as cb
import localize_capture as lc

FS = lc.FS
C_SOUND = lc.C_SOUND

# Peak-to-noise ratio below which the transient is too weak to trust. Taken
# straight from localize_capture.py, which has warned at 20 since the
# bring-up fixture showed a ratio of 14.7 producing physically inconsistent
# delays while 327 gave clean ones.
SNR_MIN = 20.0

# Worst triangle inequality violation allowed, in samples. Delay is
# antisymmetric, so d(i,j) + d(j,k) has to equal d(i,k) unless something
# corrupted a pair, which in this room means a reflection. 0.3 is what
# localize.c uses for its own "inconsistent" warning, so the bench check and
# the firmware agree about which captures are suspect. For scale: the good
# 0 deg capture measured 0.119 and the 6.4 deg error at 315 deg measured
# 0.499.
RESIDUAL_MAX = 0.3

# A channel this much quieter than the middle of the pack is not a level
# difference any more. Matched mics on one clap sit within about 2x of each
# other (check_sync warns above 2x on room noise), so a factor of 10 is a
# channel that is barely hearing the event rather than one placed further
# from it.
QUIET_FRACTION = 0.1


class Check:
    """One named pass or fail, with the number that decided it."""

    def __init__(self, name, ok, detail, advice=None):
        self.name = name
        self.ok = ok
        self.detail = detail
        self.advice = advice        # what to do about it, only shown on fail


class Quality:
    """Everything the bench check learned about one capture."""

    def __init__(self, checks, onset, peak, snr, bearing, residual, delays,
                 stats, true_angle=None):
        self.checks = checks
        self.onset = onset
        self.peak = peak
        self.snr = snr
        self.bearing = bearing
        self.residual = residual
        self.delays = delays
        self.stats = stats
        self.true_angle = true_angle
        self.error = None
        if true_angle is not None and bearing is not None:
            self.error = (bearing - true_angle + 180) % 360 - 180

    @property
    def ok(self):
        return all(c.ok for c in self.checks)

    @property
    def failed(self):
        return [c for c in self.checks if not c.ok]

    def reason(self):
        """One short line naming what failed, for the log and the summary."""
        if self.ok:
            return "all checks passed"
        return "; ".join(f"{c.name}: {c.detail}" for c in self.failed)

    def lines(self, indent="  "):
        """The block printed at the bench, verdict first."""
        out = [f"{indent}QUALITY: {'PASS' if self.ok else 'FAIL'}"]
        for c in self.checks:
            mark = "ok  " if c.ok else "FAIL"
            out.append(f"{indent}  {mark} {c.name:<10} {c.detail}")
        if self.bearing is not None:
            line = f"{indent}  bearing {self.bearing:6.1f} deg"
            if self.error is not None:
                line += (f"   true {self.true_angle:.0f} deg   "
                         f"error {self.error:+.1f} deg")
            out.append(line)
        for c in self.failed:
            if c.advice:
                out.append(f"{indent}  -> {c.advice}")
        return out


def assess(cap, true_angle=None):
    """
    Run every bench check on one (4, N) capture and return a Quality.

    The bearing is computed too, not because it decides pass or fail (the
    whole point is a check that works without knowing the true angle) but
    because printing it costs nothing once the delays exist, and seeing a
    sensible bearing at the bench catches a mislabelled angle immediately.
    """
    cap = np.asarray(cap, dtype=np.float64)
    checks = []

    # 1. Clipping. Uses check_sync's per channel stats so the rail level is
    #    defined in exactly one place.
    stats = cs.channel_stats(cap)
    clipped = sum(s["clipped"] for s in stats)
    checks.append(Check(
        "clipping", clipped == 0,
        f"{clipped} samples at or past {cs.CLIP_LEVEL} of 32767",
        "clap from further away: a flattened peak moves the onset and the "
        "delay with it"))

    # 2. Channel health. A dead channel and a channel that is merely quiet
    #    fail for different physical reasons, so they are reported apart.
    rmss = [s["rms"] for s in stats]
    median_rms = float(np.median(rmss))
    dead = [m for m, r in enumerate(rmss) if r < cs.SILENT_RMS]
    quiet = [m for m, r in enumerate(rmss)
             if r >= cs.SILENT_RMS and r < QUIET_FRACTION * median_rms]
    rms_text = "rms " + "/".join(f"{r:.0f}" for r in rmss)
    if dead:
        checks.append(Check(
            "channels", False,
            f"{rms_text}, mic{'/'.join(str(m) for m in dead)} silent "
            f"(under {cs.SILENT_RMS:.0f})",
            "that mic is not streaming. Check its DOUT wire, its SEL level, "
            "and that the filter's clock edge matches that SEL level"))
    elif quiet:
        checks.append(Check(
            "channels", False,
            f"{rms_text}, mic{'/'.join(str(m) for m in quiet)} under "
            f"{QUIET_FRACTION:.0%} of the median",
            "one mic is barely hearing the clap. Check its wiring and that "
            "nothing is resting against the port"))
    else:
        checks.append(Check("channels", True,
                            f"{rms_text}, all alive and within range"))

    # 3. Transient strength, from the same locator the analysis uses.
    onset, peak, snr = lc.find_clap(cap)
    checks.append(Check(
        "transient", snr >= SNR_MIN,
        f"peak/noise {snr:.1f} (need {SNR_MIN:.0f}), onset {onset}",
        "clap harder or closer. A weak transient gives noisy delays even "
        "when nothing is wrong with the array"))

    # 4. and 5. Delays. Both remaining checks need them, so localize once.
    bearing, delays = lc.localize(cap, onset, verbose=False)
    bearing = bearing % 360

    over = []
    for (i, j), tau in delays.items():
        spacing = np.linalg.norm(lc.MIC_POS[j] - lc.MIC_POS[i])
        max_tau = spacing / C_SOUND * FS
        if abs(tau) > max_tau + 0.5:
            over.append(f"{i}-{j}")
    checks.append(Check(
        "physics", not over,
        ("every pair delay inside its spacing limit" if not over
         else f"pair(s) {', '.join(over)} exceed what the spacing allows"),
        "a delay larger than the mic spacing allows is not a direction, it "
        "is a correlation lock onto an echo or the wrong mic order"))

    residual = cb.triangle_residual(delays)
    checks.append(Check(
        "residual", residual <= RESIDUAL_MAX,
        f"worst triangle {residual:.3f} samples (need {RESIDUAL_MAX:.2f})",
        "the pairs disagree with each other, which usually means a "
        "reflection landed inside the analysis window. Move further from "
        "the nearest wall or clap again"))

    return Quality(checks, onset, peak, snr, bearing, residual, delays,
                   stats, true_angle)


USAGE = """\
trial_quality.py: is this capture good enough to keep?

  python trial_quality.py [capture.npy] [--true-angle DEG]

  capture.npy    a trial to check. Defaults to the most recent capture.
  --true-angle   the angle you actually clapped from, so the error is
                 printed alongside the bearing.

Exits 0 if the capture passes every check, 1 if any check fails. Checks
clipping, channel health, weak transient, pair delays past what the mic
spacing allows, and the worst triangle residual.
"""

if __name__ == "__main__":
    args = list(sys.argv[1:])
    if "-h" in args or "--help" in args:
        print(USAGE)
        raise SystemExit(0)
    true_angle = None
    if "--true-angle" in args:
        k = args.index("--true-angle")
        true_angle = float(args[k + 1])
        del args[k:k + 2]

    path = args[0] if args else cp.newest_capture()
    if path is None:
        raise SystemExit("no captures found. Record one first:\n"
                         "  python run_session.py COM4 --angles 0")

    cap = np.load(path)
    if cap.ndim != 2 or cap.shape[0] != 4:
        raise SystemExit(f"expected a (4, nsamples) array, got {cap.shape}")

    print(f"{cp.describe(path)}   geometry {geom.ACTIVE}")
    q = assess(cap, true_angle)
    for line in q.lines():
        print(line)
    raise SystemExit(0 if q.ok else 1)
