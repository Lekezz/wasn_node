"""
capture_paths.py

Single source of truth for where capture files live on disk, the same way
array_geometry.py is the single source of truth for geometry. Every script
that reads or writes a capture goes through here, so the layout can change
in one place instead of four.

Layout written by catch_audio4.py:

    mic_sims_files/captures/
        2026-07-24-wall-2m/            <- one session (one sitting at the bench)
            notes.txt                  <- date, port, geometry, your --notes text
            angle000/
                trial1.npy             <- the (4, N) array the analysis reads
                trial2.npy
                wav/                   <- listening copies, not used by analysis
                    trial1_mic0.wav
                    trial1_mic1.wav
                    ...
            angle045/
                ...

Why the split: the .npy is the data, the .wav files are only there so you can
listen to a trial and hear whether the clap was clean. Keeping the wavs in
their own subfolder means an angle directory shows you the trials at a glance
instead of burying four wavs per trial in the same listing.

A session groups everything recorded in one sitting under one room setup. That
matters because room geometry, especially distance to the nearest wall, sets
how late the first echo arrives and therefore how trustworthy the trial is.
notes.txt is where that gets written down.

Legacy flat files (angle000_trial1_capture.npy sitting directly in
mic_sims_files) are still found by discovery below, so old data and the
archived milestone captures keep working.
"""

import glob
import os
import re

# Anchor everything to this file's directory so the scripts work no matter
# which directory you run them from.
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CAPTURES_DIR = os.path.join(BASE_DIR, "captures")


def session_dir(session):
    """Absolute path to one session folder. Does not create it."""
    return os.path.join(CAPTURES_DIR, session)


def angle_dir(session, tag):
    """Absolute path to one angle folder inside a session."""
    return os.path.join(session_dir(session), tag)


def wav_dir(session, tag):
    """Absolute path to the listening-copy folder for one angle."""
    return os.path.join(angle_dir(session, tag), "wav")


def ensure_dirs(session, tag):
    """Create the angle folder and its wav subfolder. Returns both paths."""
    a = angle_dir(session, tag)
    w = wav_dir(session, tag)
    os.makedirs(w, exist_ok=True)      # makes the parent angle dir too
    return a, w


def trial_npy(session, tag, k):
    """Path of trial k's data file."""
    return os.path.join(angle_dir(session, tag), f"trial{k}.npy")


def trial_wav(session, tag, k, mic):
    """Path of trial k's listening copy for one mic."""
    return os.path.join(wav_dir(session, tag), f"trial{k}_mic{mic}.wav")


def trial_report(session, tag, k):
    """
    Path of trial k's on-board bearing report.

    The board prints this after the raw dump. It is saved next to the data so
    a trial carries the firmware's own answer alongside the samples that
    produced it, which is what makes embedded-versus-Python comparison
    possible after the fact instead of only while watching the terminal.
    """
    return os.path.join(angle_dir(session, tag), f"trial{k}_bearing.txt")


def next_trial_number(session, tag):
    """
    First unused trial index for this angle, so rerunning the command adds
    trials instead of overwriting them.
    """
    highest = 0
    for path in glob.glob(os.path.join(angle_dir(session, tag), "trial*.npy")):
        m = re.search(r"trial(\d+)\.npy$", os.path.basename(path))
        if m:
            highest = max(highest, int(m.group(1)))
    return highest + 1


def _angle_from(text):
    """Pull the angle out of 'angle045' or 'angle045_trial2_capture.npy'."""
    m = re.search(r"angle(\d+)", text)
    return float(m.group(1)) if m else None


def find_captures(session=None):
    """
    Every capture on disk that carries a known true angle, newest layout
    first then the legacy flat form.

    Returns a list of dicts sorted by angle then path:
        {"path", "angle", "session", "tag", "trial"}

    session filters to one session folder; None means every session. Files
    without a parseable angle (the archived milestone captures, which are
    named for the event rather than the angle) are skipped here on purpose:
    those get passed to plot_validation.py explicitly as PATH:ANGLE.
    """
    out = {}

    # New nested layout: captures/<session>/angle<NNN>/trial<K>.npy
    root = session_dir(session) if session else CAPTURES_DIR
    for path in glob.glob(os.path.join(root, "**", "trial*.npy"),
                          recursive=True):
        tag = os.path.basename(os.path.dirname(path))
        ang = _angle_from(tag)
        if ang is None:
            continue
        m = re.search(r"trial(\d+)\.npy$", os.path.basename(path))
        out[os.path.abspath(path)] = {
            "path": os.path.abspath(path),
            "angle": ang,
            "session": os.path.basename(
                os.path.dirname(os.path.dirname(path))),
            "tag": tag,
            "trial": int(m.group(1)) if m else 0,
        }

    # Legacy flat layout sitting directly in mic_sims_files.
    if session is None:
        for pat in ("angle*_trial*_capture.npy", "angle*_capture.npy"):
            for path in glob.glob(os.path.join(BASE_DIR, pat)):
                name = os.path.basename(path)
                ang = _angle_from(name)
                if ang is None:
                    continue
                m = re.search(r"trial(\d+)", name)
                out[os.path.abspath(path)] = {
                    "path": os.path.abspath(path),
                    "angle": ang,
                    "session": "(loose files, pre-session layout)",
                    "tag": f"angle{int(ang):03d}",
                    "trial": int(m.group(1)) if m else 0,
                }

    return sorted(out.values(), key=lambda d: (d["angle"], d["path"]))


def newest_capture():
    """
    Most recently written capture, so check_sync.py and localize_capture.py
    can be run with no argument straight after a recording. Returns None if
    there is nothing to find.
    """
    cands = [d["path"] for d in find_captures()]
    cands += glob.glob(os.path.join(BASE_DIR, "capture.npy"))
    cands = [p for p in cands if os.path.exists(p)]
    if not cands:
        return None
    return max(cands, key=os.path.getmtime)


def describe(path):
    """Short human label for a capture path, relative to mic_sims_files."""
    try:
        return os.path.relpath(path, BASE_DIR)
    except ValueError:
        return path
