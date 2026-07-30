"""
nearfield_analysis.py

How close can the source be before the plane wave assumption starts to
cost accuracy, and is that ever the thing that actually limits us?

The estimator in localization_sim.estimate_direction() assumes a PLANE
wave: every mic sees the same arrival direction, so the delay between two
mics is just the projection of their baseline onto that direction. A real
source radiates a SPHERICAL wave, and the two only agree when the source
is far away compared with the array. Close in, the model is wrong, and the
usual rule of thumb for how close is too close is

    r_farfield = 2 * D^2 / lambda

with D the array aperture and lambda the shortest wavelength of interest.

This script does four things, in order:

  1. Derives the error properly instead of quoting the rule. It computes
     the exact spherical-wave delays for a source at range r and bearing
     theta, feeds them to the real estimator, and reads off the bearing it
     returns. The difference from theta is the curvature error, with no
     noise, no room and no measurement error in it. Only geometry.

  2. Separates curvature error (a physics floor you cannot remove at a
     given range) from PLACEMENT error (you put the source where you
     thought, plus or minus a few centimetres). Curvature falls off as
     1/r^2 for this array, placement falls off as 1/r, so there is a range
     where they swap places. Finding it says which one to spend effort on.

  3. Tests both against the real 40 cm captures from 2026-07-27, which
     gave 2.12 and 6.38 degrees of error at a true 315, and against the
     later 1.1 m and 1.5 m captures at the same angle.

  4. States a minimum working range for this array, and how that number
     moves if the aperture changes.

Everything geometric comes from array_geometry.py (positions, C_SOUND, FS)
and the estimator comes from localization_sim.py, so nothing here can
drift away from what the rest of the project uses. The ACTIVE layout is
never changed: where a different aperture is needed it is passed in as an
argument, the same way compare_geometries.py scores layouts it is not
using.

Run:  python nearfield_analysis.py

Writes docs/images/fig_nearfield.png. Add --no-figure to skip the drawing
and just print the numbers.
"""

import os
import sys

import numpy as np

import array_geometry as geom
import localization_sim as ls

# These two come from array_geometry so there is one definition of each.
C_SOUND = geom.C_SOUND
FS = geom.FS

# Highest frequency we claim to use. The mics run at 16 kHz, so Nyquist is
# 8 kHz and that is the shortest wavelength any of this has to survive.
# The 2*D^2/lambda bound is quoted at this frequency everywhere else in the
# project, so it is quoted at this frequency here too.
F_MAX = FS / 2.0

# Range grid for the sweep. 0.2 m is closer than anyone would clap and 5 m
# is past the far end of the room, so the interesting part is inside.
R_MIN, R_MAX, R_POINTS = 0.2, 5.0, 220

# Bearings to test at each range. The curvature error is direction
# dependent, so a single bearing would either flatter or libel the array
# depending on which one got picked. 0.5 degree steps resolve the peaks.
BEARING_STEP = 0.5

# Hand placement offsets to compare against, in metres. 5 cm is the figure
# the project already uses for a clap placed by eye against a floor mark;
# 1 cm is a careful taped mark; 1 mm is about the best you could do with a
# tape measure and is included to show where the crossover would have to
# move to before curvature mattered.
PLACEMENT_OFFSETS = [0.05, 0.01, 0.001]
PLACEMENT_MAIN = 0.05

# The real captures, as (label, range in metres, session, angle folder,
# true bearing). Ranges are what each session's own notes.txt records.
#
# One inconsistency worth knowing about before reading the output: the
# 2026-07-29-sweep notes.txt says "clap 1.1 m" while CLAUDE.md, the README
# and the writeup all describe that sweep as 1.5 m. The dedicated
# 2026-07-29-angle315 session says 1.5 m and is not ambiguous. Both values
# are far outside the near field, so nothing below changes either way, but
# the sweep is listed at the distance its own notes give rather than the
# one the summaries repeat.
REAL_GROUPS = [
    ("2026-07-27-wall-2m", 0.40, "captures/2026-07-27-wall-2m/angle315", 315.0),
    ("2026-07-29-sweep", 1.10, "captures/2026-07-29-sweep/angle315", 315.0),
    ("2026-07-29-angle315", 1.50,
     "captures/2026-07-29-angle315/angle315", 315.0),
]

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FIG_PATH = os.path.join(os.path.dirname(BASE_DIR), "docs", "images",
                        "fig_nearfield.png")

# Palette lifted from docs/make_presentation.py so this figure sits next to
# the others without looking like it came from somewhere else.
INK = "#0b0b0b"
INK2 = "#52514e"
MUTED = "#a8a7a1"
ACCENT = "#2a78d6"
STATUS_BAD = "#e34948"
SURFACE = "#fcfcfb"
GRID = "#e3e2dd"


# --------------------------------------------------------------- geometry

def aperture(mic_pos):
    """Largest mic-to-mic distance, which is what D means in 2*D^2/lambda."""
    P = np.asarray(mic_pos)
    n = len(P)
    return max(np.linalg.norm(P[i] - P[j]) for (i, j) in geom.pairs(n))


def farfield_bound(mic_pos, f_max=F_MAX):
    """The textbook 2*D^2/lambda range, in metres."""
    return 2.0 * aperture(mic_pos) ** 2 / (C_SOUND / f_max)


def spherical_delays(mic_pos, r, bearing_deg):
    """
    Exact arrival times at each mic, in samples, for a point source at
    range r and bearing theta. No approximation: straight line distance
    from the source to each mic, divided by the speed of sound.

    Returned with the mean removed, because only differences matter.
    """
    th = np.radians(bearing_deg)
    src = r * np.array([np.cos(th), np.sin(th)])
    t = np.linalg.norm(np.asarray(mic_pos) - src, axis=1) / C_SOUND * FS
    return t - t.mean()


def plane_delays(mic_pos, bearing_deg):
    """
    What the estimator's model says those arrival times should be: a flat
    wavefront travelling in direction -u, so mic m's arrival is the
    projection of its position onto u, negated (further along u means
    closer to the source means earlier).
    """
    th = np.radians(bearing_deg)
    u = np.array([np.cos(th), np.sin(th)])
    t = -(np.asarray(mic_pos) @ u) / C_SOUND * FS
    return t - t.mean()


def pair_delays_from(times, n):
    """Per-mic arrival times to the {(i, j): t_j - t_i} form the fuser wants."""
    return {(i, j): times[j] - times[i] for (i, j) in geom.pairs(n)}


def estimate_with(mic_pos, pair_delays):
    """
    Run the project's own direction fuser against an arbitrary layout.

    localization_sim keeps module level geometry, so it gets swapped in and
    restored, exactly the way localize_capture.localize() and
    compare_geometries.py already do it. Nothing about ACTIVE changes.
    """
    saved = (ls.MIC_POS, ls.NUM_MICS, ls.PAIRS)
    try:
        ls.MIC_POS = np.asarray(mic_pos)
        ls.NUM_MICS = len(ls.MIC_POS)
        ls.PAIRS = geom.pairs(ls.NUM_MICS)
        return ls.estimate_direction(pair_delays)
    finally:
        ls.MIC_POS, ls.NUM_MICS, ls.PAIRS = saved


# ------------------------------------------------------- curvature error

def curvature_error_deg(mic_pos, r, bearings):
    """
    Bearing error, in degrees, caused ONLY by the source being at a finite
    range. For each bearing: build the exact spherical delays, hand them to
    the plane wave estimator, and see how far its answer lands from the
    truth.

    Since the delays are exact, whatever comes back is pure model error.
    Positive and negative are kept, so the shape over bearing is visible.
    """
    P = np.asarray(mic_pos)
    out = np.empty(len(bearings))
    for k, th in enumerate(bearings):
        est = estimate_with(P, pair_delays_from(spherical_delays(P, r, th),
                                                len(P)))
        out[k] = (est - th + 180.0) % 360.0 - 180.0
    return out


def curvature_curve(mic_pos, ranges, bearings):
    """Worst case and RMS curvature error over bearing, one row per range."""
    worst = np.empty(len(ranges))
    rms = np.empty(len(ranges))
    for k, r in enumerate(ranges):
        e = curvature_error_deg(mic_pos, r, bearings)
        worst[k] = np.max(np.abs(e))
        rms[k] = np.sqrt(np.mean(e ** 2))
    return worst, rms


def path_error_samples(mic_pos, r):
    """
    How far the spherical wavefront departs from a flat one across the
    array, in samples, from the sagitta of a circle of radius r over a
    chord D:

        sag = r - sqrt(r^2 - (D/2)^2)  ~=  D^2 / (8 r)

    This is the quantity 2*D^2/lambda is really about. Setting r to that
    bound makes the sagitta lambda/16, which at 16 kHz is 0.125 samples.
    Note this is a DELAY error, not a bearing error. The two are not the
    same thing and the whole point of the section below is how differently
    they behave.
    """
    D = aperture(mic_pos)
    return D * D / (8.0 * r) / C_SOUND * FS


def fit_inverse_square(ranges, errors):
    """
    Least squares fit of err = K / r^2, returning K in degree metre^2.

    Fitting rather than asserting, so the printed exponent check below is
    an actual measurement of how the curve falls off and not a claim.
    """
    x = 1.0 / np.asarray(ranges) ** 2
    y = np.asarray(errors)
    K = float(np.sum(x * y) / np.sum(x * x))
    return K


def falloff_exponent(ranges, errors):
    """Slope of log(error) against log(range). Minus 2 means 1/r^2."""
    m = np.asarray(errors) > 0
    return float(np.polyfit(np.log(np.asarray(ranges)[m]),
                            np.log(np.asarray(errors)[m]), 1)[0])


# -------------------------------------------------------- placement error

def placement_error_deg(offset_m, r):
    """
    Bearing error from putting the source in the wrong place. An offset of
    e metres sideways at range r moves the true bearing by arctan(e / r).
    Falls off as 1/r, so it is the slower of the two to go away.
    """
    return np.degrees(np.arctan2(offset_m, np.asarray(r, dtype=float)))


def crossover_range(K, offset_m):
    """
    Range where the two error sources are equal in size.

    Curvature is K / r^2 and placement is about (180/pi) * e / r for small
    angles, so setting them equal gives

        r* = K / ((180/pi) * e)

    Closer than r* curvature is the bigger term, further out placement is.
    Solved numerically rather than with that formula so the arctan is kept
    exact, but the formula is what it is doing.
    """
    lo, hi = 1e-4, 1e4
    for _ in range(200):
        mid = np.sqrt(lo * hi)
        if K / mid ** 2 > placement_error_deg(offset_m, mid):
            lo = mid
        else:
            hi = mid
    return float(np.sqrt(lo * hi))


def range_for_curvature_budget(K, budget_deg):
    """Closest range at which curvature error stays under a budget."""
    return float(np.sqrt(K / budget_deg))


def range_for_placement_budget(offset_m, budget_deg):
    """Range at which a given placement offset stops costing more than the budget."""
    return float(offset_m / np.tan(np.radians(budget_deg)))


# ------------------------------------------------------------- real data

def load_real_groups():
    """
    Re-measure the real captures with the reference pipeline rather than
    reading the numbers out of a quality log, so the comparison below is
    against samples and not against a summary of them.

    Returns a list of dicts, one per session group, each with the per trial
    bearing, error, and pair 1-2 delay.
    """
    import glob

    import localize_capture as lc

    P = geom.active_positions()
    groups = []
    for label, r, rel, true_deg in REAL_GROUPS:
        d = os.path.join(BASE_DIR, rel)
        trials = []
        for path in sorted(glob.glob(os.path.join(d, "trial*.npy"))):
            cap = np.load(path).astype(np.float64)
            onset, _, _ = lc.find_clap(cap)
            bearing, pair = lc.localize(cap, onset, verbose=False)
            trials.append({
                "file": os.path.basename(path),
                "bearing": bearing % 360.0,
                "error": (bearing - true_deg + 180.0) % 360.0 - 180.0,
                "tau12": float(pair[(1, 2)]),
            })
        if trials:
            groups.append({"label": label, "range": r, "true": true_deg,
                           "trials": trials, "dir": d})
    return groups, P


def pair12_null_deg(mic_pos):
    """
    Bearings where the mic1 to mic2 delay passes through zero.

    A pair reads zero delay when the source is broadside to its baseline,
    so the nulls sit 90 degrees either side of the baseline direction. For
    the built array that is 136.94 and 316.94 degrees, which is why 315 is
    such a good angle to test with: the source sits almost exactly on a
    null, where that one delay is at its most sensitive to bearing.
    """
    P = np.asarray(mic_pos)
    b = P[1] - P[2]
    d = np.degrees(np.arctan2(b[1], b[0]))
    return (d + 90.0) % 360.0, (d + 270.0) % 360.0


def bearing_from_pair12(mic_pos, tau_samples, near_deg):
    """
    Bearing implied by the mic1 to mic2 delay ALONE, picking whichever of
    the two solutions is nearer to near_deg.

    One pair cannot give a full answer, but near its null it is a very
    sharp one dimensional measurement, and it does not go through the six
    pair least squares fit at all. That makes it a useful second opinion on
    where the source actually was.
    """
    P = np.asarray(mic_pos)
    b = P[1] - P[2]
    nb = np.linalg.norm(b)
    bdir = np.degrees(np.arctan2(b[1], b[0]))
    cosphi = np.clip(tau_samples * C_SOUND / FS / nb, -1.0, 1.0)
    phi = np.degrees(np.arccos(cosphi))
    cands = [(bdir + phi) % 360.0, (bdir - phi) % 360.0]
    return min(cands, key=lambda c: abs((c - near_deg + 180.0) % 360.0 - 180.0))


def implied_offset_m(error_deg, r):
    """Sideways placement offset that would produce a given bearing error."""
    return r * np.tan(np.radians(abs(error_deg)))


# ---------------------------------------------------------------- report

def report():
    P = geom.active_positions()
    n = len(P)
    D = aperture(P)
    lam = C_SOUND / F_MAX
    bound = farfield_bound(P)
    bearings = np.arange(0.0, 360.0, BEARING_STEP)
    ranges = np.geomspace(R_MIN, R_MAX, R_POINTS)

    print("=" * 72)
    print("NEAR FIELD vs FAR FIELD, array " + geom.ACTIVE)
    print("=" * 72)

    # ---- 1. the geometry and the textbook bound, checked not quoted
    print("\n1. THE ARRAY AND THE USUAL BOUND")
    d = geom.describe(P)
    print(f"   span            {d['span_x']*100:.2f} x {d['span_y']*100:.2f} cm")
    print(f"   aperture D      {D*100:.3f} cm  (diagonal, "
          f"{d['aperture_samples']:.2f} samples of delay)")
    print(f"   check: sqrt({geom.BUILT_WIDTH_X*100:.2f}^2 + "
          f"{geom.BUILT_HEIGHT_Y*100:.2f}^2) = "
          f"{np.hypot(geom.BUILT_WIDTH_X, geom.BUILT_HEIGHT_Y)*100:.3f} cm")
    print(f"   f_max           {F_MAX/1000:.1f} kHz, "
          f"lambda = {lam*1000:.2f} mm")
    print(f"   2*D^2/lambda    {bound:.3f} m")
    print(f"   at that range the wavefront departs from flat by "
          f"{path_error_samples(P, bound)*C_SOUND/FS*1000:.3f} mm")
    print(f"   which is lambda/16 = {lam/16*1000:.3f} mm, "
          f"or {path_error_samples(P, bound):.3f} samples")
    print("   So the 0.86 m figure the project quotes is right, and it is a")
    print("   statement about DELAY error, not about bearing error.")

    # ---- 2. what curvature actually costs in degrees
    print("\n2. WHAT THE CURVATURE ACTUALLY COSTS")
    print("   Exact spherical delays fed to the real estimator. No noise,")
    print("   no room, no measurement error: this is model error alone.")
    print()
    print("   range    wavefront sag   worst pair delay   bearing error (deg)")
    print("   (m)      (samples)       error (samples)    worst      rms")
    for r in [0.2, 0.3, 0.4, 0.6, bound, 1.1, 1.5, 2.0, 3.0, 5.0]:
        e = curvature_error_deg(P, r, bearings)
        # Worst per pair delay error at the worst bearing for it.
        worst_tau = 0.0
        for th in bearings[::8]:
            a = spherical_delays(P, r, th)
            b = plane_delays(P, th)
            for (i, j) in geom.pairs(n):
                worst_tau = max(worst_tau,
                                abs((a[j] - a[i]) - (b[j] - b[i])))
        print(f"   {r:5.2f}    {path_error_samples(P, r):9.4f}       "
              f"{worst_tau:9.4f}          {np.max(np.abs(e)):7.4f}  "
              f"{np.sqrt(np.mean(e**2)):7.4f}")

    worst, rms = curvature_curve(P, ranges, bearings)
    K = fit_inverse_square(ranges, worst)
    slope = falloff_exponent(ranges, worst)
    print()
    print(f"   Fit over the whole sweep:  worst error = {K:.5f} / r^2 degrees")
    print(f"   Measured falloff exponent: {slope:+.3f} "
          f"(minus 2 means 1/r^2)")
    print()
    print("   That exponent is the surprise. The wavefront error itself is")
    print("   1/r, so the naive expectation is a 1/r bearing error too. It")
    print("   comes out 1/r^2 because this array is symmetric about its")
    print("   centre: mic0 is opposite mic3 and mic1 is opposite mic2. The")
    print("   leading curvature term is the same at a mic and at its")
    print("   opposite, so when the least squares fit projects it onto the")
    print("   baselines the two cancel, and only the next term survives.")

    # Demonstrate that, rather than assert it, by breaking the symmetry.
    skew = np.array(P, dtype=float).copy()
    skew[3] = [0.020, -0.030]
    # Re-centre on the centroid before comparing. Bearings here are measured
    # from the origin, so a layout whose centroid has drifted off the origin
    # would show a parallax offset that has nothing to do with curvature.
    skew = skew - skew.mean(axis=0)
    print()
    print("   Proof by counterexample. Move mic3 so the array is no longer")
    print("   symmetric about its centre and the cancellation stops:")
    print()
    print("   range    symmetric rectangle   mic3 moved")
    for r in [0.4, 0.8, 1.6, 3.2]:
        a = np.max(np.abs(curvature_error_deg(P, r, bearings)))
        b = np.max(np.abs(curvature_error_deg(skew, r, bearings)))
        print(f"   {r:5.2f}    {a:15.4f}       {b:9.4f}")
    print()
    print(f"   symmetric falls x4 per doubling (1/r^2), skewed falls x2 "
          f"(1/r).")
    print("   Do not carry this result over to an irregular array. It is a")
    print("   property of the rectangle, not of GCC-PHAT.")

    # Direction dependence.
    e40 = curvature_error_deg(P, 0.40, bearings)
    print()
    print("   Direction dependence at 0.40 m. The error is not the same in")
    print("   every direction, and it is exactly zero along the array axes:")
    print()
    print("   bearing   curvature error (deg)")
    for th in [0, 45, 90, 113, 135, 180, 225, 270, 315]:
        k = int(np.argmin(np.abs(bearings - th)))
        note = "   <- worst" if abs(e40[k]) > 0.9 * np.max(np.abs(e40)) else ""
        print(f"   {th:5d}     {e40[k]:+8.4f}{note}")
    print()
    print("   Every angle in the 2026-07-29 sweep is either an axis or a")
    print("   diagonal, so at 0.40 m the curvature error at the angles")
    print("   actually measured is at most "
          f"{max(abs(e40[int(np.argmin(np.abs(bearings - t)))]) for t in [0,45,90,135,180,225,270,315]):.4f} degrees.")

    # ---- 3. curvature versus placement
    print("\n3. CURVATURE (PHYSICS) vs PLACEMENT (MEASUREMENT)")
    print("   Curvature is K/r^2 and cannot be reduced at a given range.")
    print("   Placement is arctan(e/r) and is a matter of how carefully the")
    print("   source is put where the notes say it is. Both shrink with")
    print("   range, placement more slowly, so placement eventually wins.")
    print()
    print("   range    curvature   placement error for an offset of")
    print("   (m)      (deg)       5 cm       1 cm       1 mm")
    for r in [0.2, 0.4, 0.6, bound, 1.1, 1.5, 3.0, 5.0]:
        c = np.max(np.abs(curvature_error_deg(P, r, bearings)))
        cols = "  ".join(f"{placement_error_deg(e, r):8.4f}"
                         for e in PLACEMENT_OFFSETS)
        print(f"   {r:5.2f}    {c:8.4f}    {cols}")
    print()
    print("   Crossover, where the two are the same size:")
    for e in PLACEMENT_OFFSETS:
        rx = crossover_range(K, e)
        print(f"     offset {e*1000:6.1f} mm  ->  r* = {rx*100:8.2f} cm")
    print()
    print("   Read that carefully. With 5 cm of hand placement error the")
    print(f"   crossover is {crossover_range(K, PLACEMENT_MAIN)*100:.1f} cm,")
    print("   which is inside the array itself. In other words, for every")
    print("   range you could physically use, placement is the larger error")
    print("   by a wide margin. Curvature would only become the limiting")
    print("   term if the source could be placed to better than about a")
    print("   millimetre, and even then only past a metre or so.")

    # ---- 4. the real captures
    print("\n4. THE REAL 40 cm CAPTURES")
    groups, _ = load_real_groups()
    if not groups:
        print("   No captures found on disk. Skipping.")
    else:
        print("   NOTE ON DISTANCES. Each group is listed at the range its")
        print("   own notes.txt records. captures/2026-07-29-sweep/notes.txt")
        print("   says 1.1 m, while CLAUDE.md, the README and the writeup all")
        print("   describe that sweep as 1.5 m. The dedicated angle315 session")
        print("   is unambiguous at 1.5 m. Both are far outside the near field")
        print("   so no conclusion here depends on which is right, but the")
        print("   sweep distance is worth settling in the notes.")
        print()
        null_a, null_b = pair12_null_deg(P)
        print(f"   Pair 1-2 nulls at {null_a:.2f} and {null_b:.2f} degrees,")
        print("   so a source at a true 315 sits almost on a null and that")
        print("   one delay reads near zero if the source is where we think.")
        print()
        for g in groups:
            print(f"   {g['label']}, source {g['range']:.2f} m, "
                  f"true {g['true']:.0f} deg")
            pred = np.max(np.abs(curvature_error_deg(P, g["range"], bearings)))
            th_true = g["true"]
            tau_exact = spherical_delays(P, g["range"], th_true)
            tau_exact = tau_exact[2] - tau_exact[1]
            print(f"     curvature error predicted here: {pred:.4f} deg "
                  f"(worst over all bearings)")
            print(f"     exact spherical pair 1-2 delay at a true "
                  f"{th_true:.0f}: {tau_exact:+.4f} samples")
            print("     trial      bearing    error    tau12    pair 1-2 says"
                  "   offset that")
            print("                (deg)      (deg)   (samples)  (deg)"
                  "          explains it")
            for t in g["trials"]:
                b12 = bearing_from_pair12(P, t["tau12"], th_true)
                off = implied_offset_m(t["error"], g["range"])
                print(f"     {t['file']:<10} {t['bearing']:8.2f} "
                      f"{t['error']:+8.2f}  {t['tau12']:+8.3f}   "
                      f"{b12:8.2f}       {off*100:6.1f} cm")
            errs = np.array([abs(t["error"]) for t in g["trials"]])
            print(f"     mean |error| {errs.mean():.2f} deg over "
                  f"{len(errs)} trials")
            print()

        g40 = groups[0]
        worst40 = max(g40["trials"], key=lambda t: abs(t["error"]))
        pred40 = np.max(np.abs(curvature_error_deg(P, 0.40, bearings)))
        print("   VERDICT")
        print(f"   Curvature at 0.40 m is at most {pred40:.3f} deg anywhere,")
        print("   and at a true 315 it is "
              f"{abs(curvature_error_deg(P, 0.40, np.array([315.0]))[0]):.4f} deg.")
        print(f"   The observed errors were up to "
              f"{abs(worst40['error']):.2f} deg, which is "
              f"{abs(worst40['error'])/max(pred40, 1e-9):.0f} times the worst")
        print("   curvature can produce at that range. Curvature does not")
        print("   explain these captures. It is not close.")
        print()
        print("   Placement does. The offsets in the table above are a few")
        print("   centimetres, which is what putting a clap somewhere by eye")
        print("   actually costs.")
        print()
        print("   The pair 1-2 column is the part that settles it. Curvature")
        print(f"   changes that delay by only "
              f"{abs(pair_curvature_tau12(P, 0.40, 315.0)):.4f} samples at "
              f"0.40 m, so if the")
        print("   source really had been at 315 the delay would have read "
              f"{tau_exact_at(P, 0.40, 315.0):+.3f}")
        print("   whatever the range. It did not. Pair 1-2 on its own puts")
        print("   the two 40 cm claps where the whole array puts them, and")
        print("   both of those are several degrees off 315. Two independent")
        print("   routes agreeing that the source was not at 315 is much")
        print("   stronger than either alone.")
        print()
        print("   HONEST LIMIT ON THIS. There are only two captures at")
        print("   0.40 m. The 1.5 m group contains a trial "
              f"{max(abs(t['error']) for t in groups[-1]['trials']):.2f} deg out,")
        print("   so the two distances overlap and a two point sample cannot")
        print("   separate them statistically. What rules curvature out is")
        print("   not the size of the errors, it is the model: the physics")
        print("   caps curvature at a quarter of a degree at 0.40 m, and")
        print("   nothing in the data can push it above that.")

    # ---- 5. recommendation
    print("\n5. RECOMMENDATION")
    print(f"   Curvature under 0.10 deg (a tenth of the "
          f"{1.11:.2f} deg system error):")
    print(f"     r >= {range_for_curvature_budget(K, 0.10):.2f} m")
    print(f"   Curvature under 0.01 deg, effectively zero:")
    print(f"     r >= {range_for_curvature_budget(K, 0.01):.2f} m")
    print(f"   Textbook 2*D^2/lambda bound: r >= {bound:.2f} m")
    print()
    print("   Placement under 2.00 deg with 5 cm of hand error:")
    print(f"     r >= {range_for_placement_budget(0.05, 2.0):.2f} m")
    print("   Placement under 1.00 deg with 5 cm of hand error:")
    print(f"     r >= {range_for_placement_budget(0.05, 1.0):.2f} m")
    print("   Placement under 1.00 deg with 1 cm of taped mark error:")
    print(f"     r >= {range_for_placement_budget(0.01, 1.0):.2f} m")
    print()
    print("   So: keep 1.5 m as the working minimum, which is what the")
    print("   project already does, but the reason is ground truth and not")
    print("   physics. On curvature alone this array is fine from about")
    print(f"   {range_for_curvature_budget(K, 0.10):.1f} m, and the 0.86 m "
          f"bound is already conservative.")
    print()
    print("   OTHER APERTURES. Worst curvature error goes as (D/r)^2 for a")
    print("   centre symmetric array, so the range needed for a fixed")
    print("   bearing budget scales with D, NOT with D^2 the way the")
    print("   2*D^2/lambda bound does. The two criteria therefore cross:")
    print()
    print("   aperture   2*D^2/lambda   range for 0.10 deg of curvature")
    for scale in [0.5, 1.0, 2.0, 4.0]:
        Q = np.asarray(P) * scale
        wq, _ = curvature_curve(Q, np.geomspace(0.5, 4.0, 12), bearings[::4])
        Kq = fit_inverse_square(np.geomspace(0.5, 4.0, 12), wq)
        print(f"   {aperture(Q)*100:6.1f} cm   {farfield_bound(Q):9.2f} m   "
              f"{range_for_curvature_budget(Kq, 0.10):19.2f} m")
    print()
    print("   Below about 20 cm of aperture the bearing criterion is the")
    print("   stricter of the two; above it the textbook bound is. Either")
    print("   way, on this array neither one is what limits the result.")

    return {"P": P, "D": D, "bound": bound, "K": K, "ranges": ranges,
            "bearings": bearings, "worst": worst, "rms": rms,
            "groups": groups}


def tau_exact_at(mic_pos, r, bearing_deg):
    """Exact spherical pair 1-2 delay, in samples, at a given range and bearing."""
    t = spherical_delays(mic_pos, r, bearing_deg)
    return float(t[2] - t[1])


def pair_curvature_tau12(mic_pos, r, bearing_deg):
    """How much of that pair 1-2 delay is the curvature, versus a plane wave."""
    a = spherical_delays(mic_pos, r, bearing_deg)
    b = plane_delays(mic_pos, bearing_deg)
    return float((a[2] - a[1]) - (b[2] - b[1]))


# ---------------------------------------------------------------- figure

def _style_axes(ax):
    """Same recessive axes docs/make_presentation.py uses."""
    ax.set_facecolor(SURFACE)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(GRID)
    ax.tick_params(colors=INK2, labelsize=11, length=0)
    ax.set_axisbelow(True)


def make_figure(res):
    """
    Bearing error against source range, curvature and placement drawn
    separately, with the real captures on top.

    No title and no caption is drawn into the image on purpose: the
    presentation keeps that text in its own FIG_TEXT dict so it can be
    reworded without re-rendering. Only labels that point at something in
    the drawing belong inside the frame.
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    P, bound, K = res["P"], res["bound"], res["K"]
    ranges, bearings, worst = res["ranges"], res["bearings"], res["worst"]

    fig, (ax, ax2) = plt.subplots(1, 2, figsize=(10.6, 4.2),
                                  gridspec_kw={"width_ratios": [1.32, 1.0]})

    # ---------------- left: error against range
    _style_axes(ax)
    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.grid(which="major", color=GRID, linewidth=1)
    ax.grid(which="minor", color=GRID, linewidth=0.5, alpha=0.55)

    # Limits and ticks first, before anything is labelled, because the two
    # rotated labels below measure their angle off the drawn axes and that
    # angle changes if the limits move afterwards.
    ax.set_xlim(0.2, 5.4)
    ax.set_ylim(2e-3, 33)
    ax.set_xticks([0.2, 0.4, 1.1, 1.5, 3.0, 5.0])
    ax.set_xticklabels(["0.2", "0.4", "1.1", "1.5", "3", "5"])
    ax.set_yticks([0.01, 0.1, 1.0, 10.0])
    ax.set_yticklabels(["0.01", "0.1", "1", "10"])
    ax.minorticks_off()

    # The near field bound, as the one "do not go left of here" mark. The
    # label sits above the plotting area so it cannot land on a curve.
    ax.axvspan(ranges[0], bound, color=STATUS_BAD, alpha=0.06, zorder=0)
    ax.axvline(bound, color=STATUS_BAD, linewidth=1.8, zorder=2)
    ax.text(bound, 34.0, f"2D$^2$/$\\lambda$ = {bound:.2f} m",
            color=STATUS_BAD, fontsize=10.5, ha="center", va="bottom",
            fontweight="bold", zorder=6)

    # Placement error, one curve per offset, heaviest on the 5 cm case.
    for e in PLACEMENT_OFFSETS:
        main = abs(e - PLACEMENT_MAIN) < 1e-12
        ax.plot(ranges, placement_error_deg(e, ranges),
                color=INK if main else MUTED,
                linewidth=2.4 if main else 1.5,
                linestyle="-" if main else (0, (4, 3)), zorder=3)
        label = f"{e*100:.0f} cm" if e >= 0.01 else f"{e*1000:.0f} mm"
        ax.text(4.85, placement_error_deg(e, 4.85) * 1.13,
                f"placement, {label}", color=INK if main else MUTED,
                fontsize=10, ha="right", va="bottom",
                fontweight="bold" if main else "normal", zorder=6)

    # Curvature, the physics floor.
    ax.plot(ranges, worst, color=ACCENT, linewidth=2.6, zorder=4)
    # Both curvature curves fall as 1/r^2, which on log axes is a steep
    # straight line, so a horizontal label placed anywhere near one gets
    # crossed by it. Run the words along the curve instead, the way
    # make_presentation.fig_sync labels its fit. The angle has to be
    # measured in screen space after a draw, because the data slope and the
    # drawn slope are different numbers once the axes are scaled.
    fig.canvas.draw()
    p0 = ax.transData.transform((1.0, 0.100))
    p1 = ax.transData.transform((2.0, 0.025))       # a decade of slope -2
    slope_deg = float(np.degrees(np.arctan2(p1[1] - p0[1], p1[0] - p0[0])))

    def along_curve(r0, y0, text, **kw):
        """Put text just under a 1/r^2 curve, running parallel to it."""
        ax.text(r0, y0, text, color=ACCENT, ha="left", va="top", zorder=6,
                rotation=slope_deg, rotation_mode="anchor", **kw)

    along_curve(0.245, K / 0.245 ** 2 * 0.74, "curvature, worst bearing",
                fontsize=10.5, fontweight="bold")

    # Curvature at the eight angles the sweep actually used, which is much
    # smaller still because the axes of the array are exact nulls.
    sweep_ang = np.array([0, 45, 90, 135, 180, 225, 270, 315], dtype=float)
    at_sweep = np.array([np.max(np.abs(curvature_error_deg(P, r, sweep_ang)))
                         for r in ranges])
    ax.plot(ranges, at_sweep, color=ACCENT, linewidth=1.6,
            linestyle=(0, (4, 3)), alpha=0.85, zorder=4)
    k0 = int(np.argmin(np.abs(ranges - 0.245)))
    along_curve(0.245, at_sweep[k0] * 0.74, "curvature at the sweep angles",
                fontsize=10, alpha=0.85)

    # Real captures. One dot per clap, at its session's recorded range.
    # Errors are absolute, and a clap that landed on the true angle is
    # floored so it stays on a log axis instead of vanishing.
    for g in res["groups"]:
        xs = np.full(len(g["trials"]), g["range"])
        ys = np.array([max(abs(t["error"]), 0.02) for t in g["trials"]])
        # Jitter in x only, so overlapping trials stay readable.
        if len(xs) > 1:
            xs = xs * np.linspace(0.94, 1.06, len(xs))
        ax.scatter(xs, ys, s=64, color=INK, zorder=7,
                   edgecolor=SURFACE, linewidth=1.0)

    ax.set_xlabel("source range (m)", color=INK2, fontsize=11)
    ax.set_ylabel("bearing error (deg)", color=INK2, fontsize=11)

    # A label for the dots, placed once rather than in a legend box.
    ax.annotate("real claps, true 315 deg", (0.40, 6.38),
                textcoords="offset points", xytext=(16, 22), ha="left",
                va="bottom", color=INK, fontsize=10, zorder=8,
                arrowprops=dict(arrowstyle="-", color=INK2, linewidth=1.0))

    # ---------------- right: direction dependence
    _style_axes(ax2)
    ax2.grid(axis="y", color=GRID, linewidth=1)
    ax2.axhline(0.0, color=INK, linewidth=1.2, zorder=2)
    # Each curve is labelled at a DIFFERENT one of its four peaks, so three
    # curves of very different height do not stack their labels on top of
    # one another near zero.
    for r, alpha, lw, near in ((0.20, 1.0, 2.4, 23.0), (0.40, 0.6, 2.0, 113.0),
                               (bound, 0.4, 1.8, 293.0)):
        e = curvature_error_deg(P, r, bearings)
        ax2.plot(bearings, e, color=ACCENT, alpha=alpha, linewidth=lw,
                 zorder=3)
        band = np.abs(bearings - near) < 30.0
        k = int(np.argmax(np.where(band, e, -np.inf)))
        ax2.annotate(f"{r:.2f} m", (bearings[k], e[k]),
                     textcoords="offset points", xytext=(0, 7), ha="center",
                     color=ACCENT, alpha=max(alpha, 0.75), fontsize=10,
                     fontweight="bold", zorder=6)
    for th in (0, 90, 180, 270):
        ax2.scatter([th], [0.0], s=34, color=INK, zorder=5)
    ax2.annotate("zero along the array axes", (180.0, 0.0),
                 textcoords="offset points", xytext=(0, -66), ha="center",
                 va="top", color=INK, fontsize=10, zorder=6,
                 arrowprops=dict(arrowstyle="-", color=INK2, linewidth=1.0))

    ax2.set_xlabel("source bearing (deg)", color=INK2, fontsize=11)
    ax2.set_ylabel("curvature error (deg)", color=INK2, fontsize=11)
    ax2.set_xlim(-8, 368)
    ax2.set_xticks([0, 90, 180, 270, 360])

    os.makedirs(os.path.dirname(FIG_PATH), exist_ok=True)
    fig.savefig(FIG_PATH, dpi=200, facecolor=SURFACE, bbox_inches="tight",
                pad_inches=0.25)
    plt.close(fig)
    print(f"\nwrote {FIG_PATH}")
    return FIG_PATH


if __name__ == "__main__":
    res = report()
    if "--no-figure" not in sys.argv:
        try:
            make_figure(res)
        except ImportError:
            print("\nmatplotlib not installed, no PNG written "
                  "(pip install matplotlib).")
