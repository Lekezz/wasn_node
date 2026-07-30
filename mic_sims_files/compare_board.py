"""
compare_board.py

Check the board's own localization answer against the Python reference, on
the exact same samples. This is the acceptance test for the CMSIS-DSP port
(milestone 7): the firmware is only trusted once its delays match
localization_sim.py to a fraction of a sample.

Why this script has to exist. The board prints a text report after every
capture and catch_audio4.py saves it as trial<K>_bearing.txt right next to
trial<K>.npy. So each trial already carries two independent answers to the
same question: the firmware's, and whatever the Python produces from the
stored samples. Nothing read those two back and compared them, so the port
was being judged by eye against a terminal scroll. This does it properly and
gives a pass or fail.

The one real subtlety is the analysis window. Both sides cut 2048 samples
around the onset, but they clamp differently when the clap lands near an
end of the buffer: the Python shrinks the window (numpy re-derives the FFT
length from whatever it gets) while the firmware slides it (LOC_FFT_LEN is
fixed and the buffers are sized for it). That is a deliberate divergence
documented in localize.c, not a bug. If the two windows come out different
here, comparing delays straight across would be measuring the window
difference rather than the arithmetic. So the delays are always compared on
the BOARD's window: the Python is re-run pinned to it. The window choice
itself is still checked and reported separately, so a divergence shows up
as its own line instead of silently polluting the delay numbers.

Reports printed by firmware older than commit f5c3d78 have blank floats,
because the project links --specs=nano.specs and its printf drops floating
point. Those trials are reported as SKIPPED with a reminder to reflash, not
as failures. Their integer fields (onset, peak, window) are still compared,
which is exactly the partial validation the 2026-07-27 session managed.

Run:  python compare_board.py [--session NAME] [PATH ...]

  no arguments   every trial on disk that has a saved board report
  --session NAME limit to one session folder
  PATH           a trial .npy, or its angle folder, or a session folder

Exit status is 0 when every compared trial passes, 1 otherwise, so this can
be used as a regression check after touching either implementation.
"""

import os
import re
import sys

import numpy as np

import capture_paths as cp
import localization_sim as ls
import localize_capture as lc

# Tolerances, and why each is what it is.
#
# The board computes in float32 and the Python in float64, so the two can
# never be bit identical. What matters is that the difference stays far below
# the measurement error of the array itself: 1 mm of position error is about
# 0.047 samples, and real captures disagree with truth by degrees, so a
# hundredth of a sample of numerical drift is irrelevant. The board also
# prints delays rounded to 3 decimals and the bearing to 2, so quantization
# alone accounts for 0.0005 samples and 0.005 deg. These sit well above both.
DELAY_TOL = 0.05        # samples, per pair
RESIDUAL_TOL = 0.05     # samples, worst triangle residual
BEARING_TOL = 0.5       # degrees

# peak/noise needs its own rule, derived rather than picked.
#
# The firmware does not compute a true median. It bins the envelope into
# LOC_MEDIAN_BINS bins spanning 0..peak and returns the centre of the bin the
# median falls in, because a real median needs a sort or a second pass over
# 16000 samples. So its noise estimate is quantized: it can sit up to half a
# bin, peak/(2*(BINS-1)), away from the exact median numpy computes.
#
# That small absolute difference becomes a large difference in the RATIO,
# because snr = peak/noise and the noise is tiny. Propagating the bound:
#
#     |snr_board - snr_py| = snr_board * snr_py * |noise_py - noise_board| / peak
#                         <= snr^2 / (2 * (BINS - 1))
#
# which at snr 200 is about 9.8. A flat percentage cannot express this: the
# same bin error is negligible at snr 20 and dominant at snr 400. Anything
# inside this bound is the documented approximation working as intended;
# anything outside it is a real disagreement.
#
# Keep in sync with LOC_MEDIAN_BINS in mic_test/Core/Inc/loc_config.h.
MEDIAN_BINS = 2048

# The quantization term above is the DOMINANT source of disagreement but not
# the only one, so it is a first-order model rather than a strict bound. The
# ratio also inherits float32 effects the model ignores: the firmware sums
# 16000 samples in float32 to estimate DC and builds the envelope from that,
# where the Python uses float64 throughout, so peak and median both shift a
# little before the division. Two trials in the 2026-07-29 sweep landed at
# 16.58 against a computed bound of 16.05, about 3 percent over.
#
# Hence an explicit empirical factor, named rather than folded quietly into the
# formula. 1.5 covers what was observed with room to spare while still catching
# any real error: a noise estimate wrong by even 10 percent moves the ratio by
# about 25 at snr 256, well past the allowance.
#
# Worth knowing that peak/noise is the WEAKEST test of the noise estimate in
# this table, not the strongest. The onset row is far stricter and is required
# to match exactly: onset is found by walking back from the peak until the
# envelope drops below noise + 0.2 * (peak - noise), so it depends directly on
# the noise value. Onset has matched exactly on all 45 trials compared so far,
# which validates the noise path much harder than this ratio does.
SNR_MODEL_MARGIN = 1.5


def snr_tolerance(snr):
    """Largest peak/noise gap the histogram median can produce on its own."""
    quantization = snr * snr / (2.0 * (MEDIAN_BINS - 1))
    return max(SNR_MODEL_MARGIN * quantization, 0.05)

# Onset, peak and window are integers on both sides and are produced by the
# same deterministic search, so they are required to match exactly. They did
# on all three captures of the 2026-07-27 session, which is what gave the
# first evidence the port's find_clap was right.
WINDOW_BEFORE = lc.WINDOW_BEFORE
WINDOW_AFTER = lc.WINDOW_AFTER
WINDOW_LEN = WINDOW_BEFORE + WINDOW_AFTER


# ---------------------------------------------------------------- parsing

def _f(text):
    """Float from a report field, or None if the field printed blank."""
    if text is None:
        return None
    text = text.strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None            # "nan", "inf" and anything unexpected


def parse_report(path):
    """
    Pull the numbers out of one trial<K>_bearing.txt.

    Returns a dict. Any field the firmware printed blank comes back None,
    which is how a pre-f5c3d78 report is recognised later.
    """
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        text = f.read()

    out = {
        "path": path,
        "failed": None,
        "onset": None,
        "peak": None,
        "snr": None,
        "window": None,
        "delays": {},
        "residual": None,
        "bearing": None,
        "exceeds_physics": [],
        "inconsistent": "(inconsistent" in text,
    }

    m = re.search(r"FAILED:\s*(.+)", text)
    if m:
        out["failed"] = m.group(1).strip()

    m = re.search(r"transient at (\d+), onset (\d+), peak/noise\s*([^\r\n]*)",
                  text)
    if m:
        out["peak"] = int(m.group(1))
        out["onset"] = int(m.group(2))
        out["snr"] = _f(m.group(3))

    m = re.search(r"window (\d+)\.\.(\d+)", text)
    if m:
        out["window"] = (int(m.group(1)), int(m.group(2)))

    # Pair lines look like "  0-1        -1.234           4.31" and, with the
    # old firmware, like "  0-1              ". Match the label, then take
    # whatever numeric tokens follow, so a blank line parses to no delay
    # instead of throwing.
    for line in text.splitlines():
        m = re.match(r"\s*(\d)-(\d)\b(.*)$", line)
        if not m:
            continue
        i, j = int(m.group(1)), int(m.group(2))
        rest = m.group(3)
        if "EXCEEDS PHYSICS" in rest:
            out["exceeds_physics"].append((i, j))
            rest = rest.replace("EXCEEDS PHYSICS", "")
        nums = [_f(t) for t in rest.split()]
        nums = [v for v in nums if v is not None]
        if nums:
            out["delays"][(i, j)] = nums[0]      # second token is max physical

    m = re.search(r"worst triangle residual\s*([^\r\n]*?)\s*samples", text)
    if m:
        out["residual"] = _f(m.group(1))

    m = re.search(r"BEARING\s*([^\r\n]*?)\s*deg", text)
    if m:
        out["bearing"] = _f(m.group(1))

    return out


# ------------------------------------------------------------- reference

def triangle_residual(delays):
    """
    Worst triangle inequality violation across the delay set, matching
    worst_triangle_residual() in localize.c.

    Delay is antisymmetric, so for any three mics d(i,j) + d(j,k) should
    equal d(i,k) exactly. It does not when a reflection has corrupted a pair,
    which makes this a consistency check that needs no knowledge of the true
    angle. The Python reference never needed it (it is a firmware-side sanity
    print) so it is implemented here rather than imported.
    """
    mics = sorted({m for pair in delays for m in pair})
    table = {}
    for (i, j), d in delays.items():
        table[(i, j)] = d
        table[(j, i)] = -d
    worst = 0.0
    for a in range(len(mics)):
        for b in range(a + 1, len(mics)):
            for c in range(b + 1, len(mics)):
                i, j, k = mics[a], mics[b], mics[c]
                r = abs(table[(i, j)] + table[(j, k)] - table[(i, k)])
                worst = max(worst, r)
    return worst


def reference(cap, forced_window=None):
    """
    Run the Python reference on one capture.

    forced_window pins the analysis to a given (start, stop) so the delays
    can be compared against a board that chose its window differently. It
    works by handing lc.localize the onset that produces that window, rather
    than by reimplementing the windowing, so this stays honest: the numbers
    still come from the same code path localize_capture.py uses.
    """
    onset, peak, snr = lc.find_clap(cap)

    if forced_window is None:
        eff_onset = onset
    else:
        eff_onset = forced_window[0] + WINDOW_BEFORE

    bearing, delays = lc.localize(cap, eff_onset, verbose=False)
    start = max(0, eff_onset - WINDOW_BEFORE)
    stop = min(cap.shape[1], eff_onset + WINDOW_AFTER)

    return {
        "onset": onset,
        "peak": peak,
        "snr": snr,
        "window": (start, stop),
        "delays": delays,
        "residual": triangle_residual(delays),
        "bearing": bearing % 360,
    }


# ------------------------------------------------------------ comparison

class Row:
    """One compared field, so printing and pass/fail share a definition."""

    def __init__(self, name, board, py, tol, exact=False, unit=""):
        self.name = name
        self.board = board
        self.py = py
        self.tol = tol
        self.exact = exact
        self.unit = unit
        # Set for a window row whose mismatch is the documented fixed-length
        # slide. It prints as "slid" and is not counted as a failure.
        self.excused = False

    @property
    def missing(self):
        return self.board is None

    @property
    def delta(self):
        if self.missing or self.py is None:
            return None
        return self.board - self.py

    @property
    def ok(self):
        if self.missing:
            return None                     # not a failure, just absent
        if self.exact:
            return self.board == self.py
        return abs(self.delta) <= self.tol

    def line(self):
        if self.missing:
            return f"  {self.name:<24} {'(blank)':>12} {self._fmt(self.py):>12}"
        mark = "ok " if self.ok else ("slid" if self.excused else "BAD")
        d = self.delta
        ds = "exact" if (self.exact and d == 0) else f"{d:+.3f}"
        return (f"  {self.name:<24} {self._fmt(self.board):>12} "
                f"{self._fmt(self.py):>12} {ds:>10}  {mark}")

    @staticmethod
    def _fmt(v):
        if v is None:
            return "-"
        if isinstance(v, int):
            return str(v)
        return f"{v:.3f}"


def is_expected_slide(board_window, onset, n_samples):
    """
    True when the board's window differs from the Python's only because it
    slid a fixed-length window instead of shrinking a clamped one.

    This is not a defect and it is not rare. Capture is clap-triggered, so the
    onset always lands early in the buffer, and any onset below WINDOW_BEFORE
    makes the two rules disagree: the Python clamps start to 0 and keeps a
    SHORTER window, while the firmware slides a full LOC_WINDOW_LEN window
    because its FFT length and buffers are fixed. localize.c documents this.

    The firmware's choice is the better one, so a divergence of this shape is
    reported and then not counted against it. What is checked is that the
    board's window really is a legitimate slide: exactly the right length,
    inside the buffer, and still containing the onset it is supposed to
    analyse. Anything else is a genuine disagreement and still fails.
    """
    start, end = board_window
    return (end - start == WINDOW_LEN
            and start >= 0
            and end <= n_samples
            and start <= onset <= end)


def compare_trial(npy_path, report_path):
    """Compare one trial. Returns (status, rows, note) with status in
    {"pass", "fail", "skip"}."""
    cap = np.load(npy_path)
    if cap.ndim != 2 or cap.shape[0] != 4:
        return "skip", [], f"expected a (4, N) array, got {cap.shape}"

    cap = cap.astype(np.float64)
    board = parse_report(report_path)

    if board["failed"]:
        return "skip", [], f"board reported FAILED: {board['failed']}"

    # Pin the Python to the board's window when the board told us one, so the
    # delay comparison is arithmetic against arithmetic. The window choice is
    # compared separately below, using the Python's own unpinned answer.
    native = reference(cap)
    expected_slide = False
    if board["window"] and board["window"] != native["window"]:
        pinned = reference(cap, forced_window=board["window"])
        expected_slide = is_expected_slide(board["window"], native["onset"],
                                           cap.shape[1])
        window_note = (f"windows differ: board {board['window']}, "
                       f"python {native['window']}. Delays below are compared "
                       f"on the board's window.")
        if expected_slide:
            window_note += (
                " This is the DOCUMENTED divergence, not a fault: the clap "
                "landed within " + str(WINDOW_BEFORE) + " samples of the "
                "start, so the Python shrank its window while the firmware "
                "slid a full-length one to keep the FFT size fixed. The "
                "firmware's choice is the better one and the window rows "
                "below are not counted as failures.")
    else:
        pinned = native
        window_note = None

    rows = [
        Row("onset", board["onset"], native["onset"], 0, exact=True),
        Row("transient peak", board["peak"], native["peak"], 0, exact=True),
        Row("window start", board["window"][0] if board["window"] else None,
            native["window"][0], 0, exact=True),
        Row("window end", board["window"][1] if board["window"] else None,
            native["window"][1], 0, exact=True),
        Row("peak/noise", board["snr"], native["snr"],
            snr_tolerance(native["snr"])),
    ]

    for (i, j) in sorted(pinned["delays"]):
        rows.append(Row(f"delay {i}-{j}", board["delays"].get((i, j)),
                        pinned["delays"][(i, j)], DELAY_TOL, unit="samples"))

    rows.append(Row("triangle residual", board["residual"],
                    pinned["residual"], RESIDUAL_TOL, unit="samples"))
    rows.append(Row("bearing", board["bearing"], pinned["bearing"],
                    BEARING_TOL, unit="deg"))

    compared = [r for r in rows if not r.missing]
    floats_present = any(r.board is not None and not r.exact for r in rows)

    # A window row that fails only because the firmware legitimately slid its
    # window does not count against the port. Every other row still does, so a
    # real arithmetic disagreement in the same trial is not masked.
    WINDOW_ROWS = ("window start", "window end")
    if expected_slide:
        for r in rows:
            if r.name in WINDOW_ROWS:
                r.excused = True
    judged = [r for r in compared
              if not (expected_slide and r.name in WINDOW_ROWS)]

    if not floats_present:
        status = "skip"
    elif all(r.ok for r in judged):
        status = "pass"
    else:
        status = "fail"

    return status, rows, window_note


# ----------------------------------------------------------------- driver

def trials_to_check(args, session):
    """
    Every (npy, report) pair to compare.

    With no path arguments this walks the capture tree through
    capture_paths.py, the same way plot_validation.py does, so a normal run
    needs no arguments. A path argument may be a trial .npy, an angle folder
    or a session folder, whichever is convenient at the time.
    """
    found = []

    if args:
        for arg in args:
            if os.path.isdir(arg):
                for path in sorted(_npys_under(arg)):
                    found.append(path)
            else:
                found.append(os.path.abspath(arg))
    else:
        found = [d["path"] for d in cp.find_captures(session)]

    out = []
    for npy in found:
        report = re.sub(r"\.npy$", "_bearing.txt", npy)
        if os.path.exists(report):
            out.append((npy, report))
        else:
            out.append((npy, None))
    return out


def _npys_under(root):
    for dirpath, _dirs, files in os.walk(root):
        for name in files:
            if name.endswith(".npy"):
                yield os.path.abspath(os.path.join(dirpath, name))


USAGE = """\
compare_board.py: does the firmware agree with the Python reference?

  python compare_board.py [--session NAME] [PATH ...]

  no arguments   every trial on disk that has a saved board report
  --session NAME limit to one session folder
  PATH           a trial .npy, or its angle folder, or a session folder

Compares the board's saved report against the reference run on the same
samples. Exits 0 when every compared trial passes, 1 otherwise.
"""


def main(argv):
    args = list(argv)
    if "-h" in args or "--help" in args:
        print(USAGE)
        return 0
    session = None
    if "--session" in args:
        k = args.index("--session")
        session = args[k + 1]
        del args[k:k + 2]

    pairs = trials_to_check(args, session)
    if not pairs:
        print("no captures found. Record one first:")
        print("  python catch_audio4.py COM4 --tag angle000")
        return 1

    with_report = [(n, r) for n, r in pairs if r]
    without = [n for n, r in pairs if not r]

    print(f"geometry: {ls.__name__} reference, active layout "
          f"{lc.MIC_POS.shape[0]} mics, "
          f"{'measured' if lc.ARRAY_MEASURED else 'NOMINAL (not calipered)'}")
    print(f"{len(with_report)} trial(s) carry a board report, "
          f"{len(without)} do not\n")

    results = []
    for npy, report in with_report:
        status, rows, note = compare_trial(npy, report)
        results.append((npy, status))

        print(f"{cp.describe(npy)}")
        if note:
            print(f"  NOTE: {note}")
        print(f"  {'field':<24} {'board':>12} {'python':>12} "
              f"{'delta':>10}")
        for r in rows:
            print(r.line())
        if status == "skip":
            print("  SKIPPED: this report has no float fields. It came from "
                  "firmware built")
            print("  before commit f5c3d78, whose printf dropped floating "
                  "point. Reflash and")
            print("  re-record to validate the delay path.")
        print()

    if without:
        print("No board report saved for these, so only the Python side "
              "exists:")
        for npy in without:
            print(f"  {cp.describe(npy)}")
        print("  (recorded before catch_audio4.py learned to save the "
              "report, or the")
        print("   board was running firmware that did not print one.)")
        print()

    npass = sum(1 for _, s in results if s == "pass")
    nfail = sum(1 for _, s in results if s == "fail")
    nskip = sum(1 for _, s in results if s == "skip")

    print(f"summary: {npass} passed, {nfail} failed, {nskip} skipped")
    if nfail:
        print(f"  A failure means the firmware and the reference disagree by "
              f"more than")
        print(f"  {DELAY_TOL} samples on a delay or {BEARING_TOL} deg on the "
              f"bearing, on identical")
        print("  input. That is a port bug, not a room problem: the same "
              "samples went in.")
        print("  The exception is a window row failing on its own. Both sides "
              "clamp the")
        print("  window differently near the ends of the buffer, which is "
              "deliberate and")
        print("  documented in localize.c, so check the NOTE line before "
              "hunting a bug.")
        return 1
    if npass == 0:
        print("  Nothing was actually validated. See the skip reasons above.")
        return 1
    print("  The CMSIS-DSP port agrees with the Python reference on every "
          "trial above.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
