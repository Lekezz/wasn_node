"""
replay_source.py

A stand-in for the board, so the capture tools can be run and tested with
nothing plugged in.

Why this exists: the bench session runner talks to a serial port, and the
port only exists when the hardware is on the desk. That would make every
change to the runner untestable until the next session, which is exactly
the kind of code that breaks in front of you at the bench. FakeSerial
implements the handful of pyserial methods the reader actually uses
(read, readline, timeout, reset_input_buffer, close) and plays back real
captures from captures/ as if the board had just dumped them. The runner
cannot tell the difference, so the whole path gets exercised: magic sync,
length field, four channel blocks, report, save, quality check, retake.

It also injects faults on purpose. The quality check is only worth having
if it fires, and the only honest way to know that is to hand it a capture
that is genuinely clipped, or genuinely missing a channel, and watch it
fail. FAULTS below does that to real samples.

Run:  python replay_source.py

which prints the quality verdict for a clean capture and for each injected
fault, side by side. No board and no serial port needed.
"""

import os

import numpy as np

import capture_paths as cp
import trial_quality as tq
import wav4_stream as ws

# Boot chatter put in front of the first frame. The board prints something
# like this on reset, and the reader is supposed to skip it by syncing on the
# magic instead of trusting the stream to start clean. Replaying it means
# that skip is exercised every test run rather than assumed.
BOOT_NOISE = b"\r\nSTM32L552 ready. DFSDM started, press the blue button.\r\n"


class FakeSerial:
    """
    Enough of a pyserial Serial to satisfy wav4_stream.

    Frames are handed out one per capture, the same way the board only dumps
    when you press the button. reset_input_buffer() drops what is left of the
    current frame but never the frames still queued, which mirrors the real
    thing: it throws away stale bytes, it does not stop the board from
    replying to the next press.
    """

    def __init__(self, frames, timeout=90):
        self._frames = list(frames)
        self._buf = b""
        self.timeout = timeout
        self.closed = False

    def _fill(self):
        if not self._buf and self._frames:
            self._buf = self._frames.pop(0)

    def read(self, n=1):
        self._fill()
        if not self._buf:
            return b""              # nothing queued: looks like a timeout
        out, self._buf = self._buf[:n], self._buf[n:]
        return out

    def readline(self):
        self._fill()
        if not self._buf:
            return b""
        idx = self._buf.find(b"\n")
        if idx < 0:
            out, self._buf = self._buf, b""
            return out
        out, self._buf = self._buf[:idx + 1], self._buf[idx + 1:]
        return out

    def reset_input_buffer(self):
        self._buf = b""

    def close(self):
        self.closed = True

    @property
    def frames_left(self):
        return len(self._frames)


def frame_bytes(cap, report_lines, prefix=b""):
    """
    Serialize one capture exactly the way the firmware does: magic, the
    per-channel byte count, four channel blocks, then the text report.
    """
    cap = np.asarray(cap).astype("<i2")
    per_channel = cap.shape[1] * 2
    out = bytearray(prefix)
    out += ws.MAGIC
    out += per_channel.to_bytes(4, "little")
    for m in range(cap.shape[0]):
        out += cap[m].tobytes()
    out += ("\r\n".join(report_lines) + "\r\n").encode("ascii")
    return bytes(out)


# ------------------------------------------------------------------ faults
#
# Each one takes a good capture and breaks it in a way that has actually
# happened, or is one loose wire away from happening, on this bench.

def fault_clip(cap):
    """
    Clap far too close. Scale until the transient slams into the int16 rail,
    which is what a clap next to the array does.
    """
    cap = cap.astype(np.float64)
    cap *= 40000.0 / np.abs(cap).max()
    return np.clip(cap, -32767, 32767).astype(np.int16)


def fault_dead_channel(cap):
    """A DOUT wire off, or a SEL pin floating: mic2 stops streaming."""
    cap = cap.copy()
    cap[2] = 0
    return cap


def fault_weak(cap):
    """
    A clap too soft to stand out. Rather than scaling the whole capture
    down, which leaves the peak-to-noise ratio unchanged, this raises the
    noise floor around it, which is what a distant clap or a noisy room
    actually does to the ratio.
    """
    rng = np.random.default_rng(7)
    cap = cap.astype(np.float64)
    level = np.abs(cap).max() / 12.0
    cap = cap + rng.standard_normal(cap.shape) * level
    return np.clip(cap, -32767, 32767).astype(np.int16)


FAULTS = {
    "clip": ("clipped clap", fault_clip),
    "dead": ("mic2 not streaming", fault_dead_channel),
    "weak": ("weak transient", fault_weak),
}


def apply_fault(cap, name):
    """Break a capture on purpose. name None or 'none' leaves it alone."""
    if not name or name == "none":
        return cap
    if name not in FAULTS:
        raise SystemExit(f"unknown fault '{name}'. Known: "
                         f"{', '.join(FAULTS)}, none")
    return FAULTS[name][1](cap)


# ------------------------------------------------------------------ replay

def _report_for(npy_path, fault=None):
    """
    The report text to send after a replayed capture.

    A real trial usually has the board's own report saved beside it, so send
    that. When a fault has been injected the stored report no longer
    describes the samples, so say so in the report itself rather than
    silently passing off an old answer as a fresh one.
    """
    report = npy_path[:-4] + "_bearing.txt"
    if fault and fault != "none":
        return ["", "--- localization ---",
                f"(replayed capture with fault '{fault}' injected, so the "
                f"board's own numbers do not apply)", "--- end ---"]
    if os.path.exists(report):
        with open(report, "r", encoding="utf-8", errors="replace") as f:
            return f.read().splitlines()
    return ["", "--- localization ---", "(replay: no saved board report)",
            "--- end ---"]


def replay_paths(sources):
    """
    Turn what the user asked to replay into a list of .npy paths.

    A source is a session name, a folder, or a single .npy file, because at
    the point you want a replay you might have any of the three to hand.
    """
    out = []
    for src in sources:
        if os.path.isfile(src) and src.endswith(".npy"):
            out.append(os.path.abspath(src))
            continue
        folder = src if os.path.isdir(src) else cp.session_dir(src)
        if not os.path.isdir(folder):
            raise SystemExit(f"nothing to replay at '{src}'")
        found = [d["path"] for d in cp.find_captures()
                 if os.path.abspath(d["path"]).startswith(
                     os.path.abspath(folder))]
        out.extend(sorted(found))
    if not out:
        raise SystemExit("replay found no captures")
    return out


def fake_port(sources, count, faults=None):
    """
    A FakeSerial preloaded with count frames.

    sources cycle if there are fewer captures than frames asked for, because
    a replayed sweep of 8 angles times 5 trials needs 40 dumps and the disk
    only holds three real ones. faults is a list applied to the frames in
    order, so a test can say "third trial is clipped" and drive the retake
    path deliberately.
    """
    paths = replay_paths(sources)
    faults = list(faults or [])
    frames = []
    for i in range(count):
        path = paths[i % len(paths)]
        fault = faults[i] if i < len(faults) else None
        cap = apply_fault(np.load(path), fault)
        prefix = BOOT_NOISE if i == 0 else b""
        frames.append(frame_bytes(cap, _report_for(path, fault), prefix))
    return FakeSerial(frames)


if __name__ == "__main__":
    good = cp.trial_npy("2026-07-27-wall-2m", "angle000", 1)
    bad = cp.trial_npy("2026-07-27-wall-2m", "angle315", 2)
    base = np.load(good)

    print("Does the bench quality check actually fire? One real capture, "
          "broken four ways.\n")

    cases = [("clean (angle000/trial1 as recorded)", base, 0.0)]
    for name, (label, fn) in FAULTS.items():
        cases.append((f"{name}: {label}", fn(base), 0.0))
    cases.append(("residual: angle315/trial2 as recorded, no injection",
                  np.load(bad), 315.0))

    failures = 0
    for label, cap, true in cases:
        print(f"{label}")
        q = tq.assess(cap, true)
        for line in q.lines("    "):
            print(line)
        print()
        if not q.ok:
            failures += 1

    print(f"{len(cases)} cases, {failures} failed the check, "
          f"{len(cases) - failures} passed.")
    print("Expected: the clean one passes and every other case fails.")
