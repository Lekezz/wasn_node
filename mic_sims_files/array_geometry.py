"""
array_geometry.py

One place to define where the microphones physically are.

Every script that needs geometry imports it from here, so trying a new
array layout means editing ACTIVE below (or adding a LAYOUTS entry), not
hunting through several files. localization_sim.py deliberately keeps its
own 10 cm square MIC_POS and is NOT driven by this file: that square is
the validated reference the firmware port gets compared against, and it
should stay fixed.

Coordinates are metres, (x, y) per mic, in mic order 0..3.

    +y
     ^   mic1 .          . mic0
     |
     +---> +x   (long axis of the breadboard pair)
         mic2 .          . mic3

Bearings reported elsewhere are degrees counterclockwise from +x.

BUILD NOTE, and this one matters: along the LONG axis you can count holes,
because the 0.1 inch (2.54 mm) column pitch is exact and uninterrupted.
Across the WIDTH you cannot. The centre channel of each board, the power
rails, and the glue seam between the two boards all break the grid, so the
width is whatever your boards happen to give. MEASURE the width, do not
count it.

Either way the final numbers must come from calipers on the mic PORTS, not
the header pins: the port is offset from the pins on a breakout board. For
scale, 1 mm of position error is about 0.047 samples of delay, well under
a degree, so +/- 1 mm is good enough.
"""

import numpy as np

C_SOUND = 343.0
FS = 16000


def rect(width_x, height_y):
    """Four mics at the corners of a rectangle centred on the origin."""
    w, h = width_x / 2.0, height_y / 2.0
    return np.array([
        [ w,  h],   # mic0
        [-w,  h],   # mic1
        [-w, -h],   # mic2
        [ w, -h],   # mic3
    ])


# Named layouts. Add entries here when trying something new; the scoring
# script picks them all up automatically.
#
#   positions : metres
#   measured  : True only once the numbers came off calipers
#   note      : what it needs and what it is for
LAYOUTS = {
    "9.25x10-nominal": {
        "positions": rect(0.100, 0.0925),
        "measured": False,
        "note": "Build target. Two full-size breadboards glued. 10 cm along "
                "the long axis is 39-40 hole pitches; 9.25 cm width is the "
                "full span across both boards including rails. Most uniform "
                "option (condition number 1.08), no blind directions.",
    },
    "9.25x12-nominal": {
        "positions": rect(0.120, 0.0925),
        "measured": False,
        "note": "Stretch goal. Slightly better accuracy from the longer "
                "aperture, still no blind directions.",
    },
    "9.25x16-nominal": {
        "positions": rect(0.160, 0.0925),
        "measured": False,
        "note": "Full board length. Best simulated accuracy, but the widest "
                "aperture also carries the most spatial aliasing risk in a "
                "reverberant room, which the simulation does not model. Try "
                "it after the 10 cm build works.",
    },
    "2.8x10-single-board": {
        "positions": rect(0.100, 0.028),
        "measured": False,
        "note": "Superseded. What one breadboard alone allowed. Kept for "
                "comparison: four blind cones about 30 deg off the long "
                "axis where error reaches 8 deg.",
    },
    "10cm-square-reference": {
        "positions": rect(0.100, 0.100),
        "measured": False,
        "note": "The geometry localization_sim.py is validated against. "
                "Does not fit the boards; here for scoring comparison only.",
    },
}

# Which layout the analysis scripts should use.
ACTIVE = "9.25x10-nominal"


def active_positions():
    return LAYOUTS[ACTIVE]["positions"]


def is_measured():
    return LAYOUTS[ACTIVE]["measured"]


def pairs(n=4):
    return [(i, j) for i in range(n) for j in range(i + 1, n)]


def describe(positions):
    """
    Geometric health of a layout.

    rank < 2 means the array is collinear and direction estimation cannot
    work: all baselines are parallel, so the across-axis component is
    unconstrained and the answer collapses to 0 or 180 regardless of
    truth. Condition number near 1 means accuracy is uniform in all
    directions; large means strongly direction dependent.
    """
    P = np.asarray(positions)
    A = np.array([P[i] - P[j] for (i, j) in pairs(len(P))])
    rank = int(np.linalg.matrix_rank(A))
    s = np.linalg.svd(A, compute_uv=False)
    cond = float(s[0] / s[1]) if len(s) > 1 and s[1] > 1e-12 else float("inf")
    ap = max(np.linalg.norm(P[i] - P[j]) for (i, j) in pairs(len(P)))
    return {
        "rank": rank,
        "cond": cond,
        "aperture_m": ap,
        "aperture_samples": ap / C_SOUND * FS,
        "span_x": float(P[:, 0].max() - P[:, 0].min()),
        "span_y": float(P[:, 1].max() - P[:, 1].min()),
    }


if __name__ == "__main__":
    print(f"ACTIVE layout: {ACTIVE}")
    print(f"  measured: {is_measured()}")
    print(f"  {LAYOUTS[ACTIVE]['note']}\n")
    for name, spec in LAYOUTS.items():
        d = describe(spec["positions"])
        mark = " <- ACTIVE" if name == ACTIVE else ""
        print(f"{name:<24} {d['span_x']*100:5.1f} x {d['span_y']*100:5.1f} cm  "
              f"aperture {d['aperture_m']*100:5.1f} cm "
              f"({d['aperture_samples']:4.1f} samples)  "
              f"rank {d['rank']}  cond {d['cond']:5.2f}{mark}")
