"""
wav4_stream.py

The board's "WAV4" serial protocol, in one place.

Why this file exists: catch_audio4.py used to own the only copy of the
protocol reader, and it owns it as top-level script code, so nothing else
could import it. run_session.py needs the exact same reader, and a second
hand-written copy of a wire format is how two tools quietly stop agreeing
about the same bytes. So the reader moved here and catch_audio4.py now
imports it. Its command line and its behaviour are unchanged.

The wire format, which the firmware in mic_test/Core/Src/capture.c defines
and which is NOT changing:

    b"WAV4"                 magic, so we can resynchronise mid-stream
    4 bytes little-endian   number of BYTES in ONE channel
    channel 0 payload       that many bytes of raw int16, little-endian
    channel 1 payload       ...
    channel 2 payload
    channel 3 payload
    text report             the on-board localizer's answer, ending in
                            "--- end ---"

We sync on the magic instead of reading a fixed byte count, so boot text or
a half-finished dump left in the buffer is skipped instead of being parsed
as audio.
"""

import time
import wave

import numpy as np

MAGIC = b"WAV4"
BAUD = 115200
SAMPLE_RATE = 16000
NUM_MICS = 4

# One second of four channels is 128000 bytes, which takes about 11 s to
# send at 115200 baud. The rest of the timeout is there so you have time to
# walk to the array and press the button after the script starts.
PORT_TIMEOUT = 90


def open_port(port_name, timeout=PORT_TIMEOUT):
    """
    Open the board's virtual COM port.

    Imported lazily so that replay runs, the session summary, and the tests
    all work on a machine where pyserial is not installed or no board is
    plugged in. Nothing except a real capture needs the serial library.
    """
    import serial
    return serial.Serial(port_name, BAUD, timeout=timeout)


def read_exact(port, n):
    """Read exactly n bytes or return whatever arrived before the timeout."""
    buf = bytearray()
    while len(buf) < n:
        chunk = port.read(n - len(buf))
        if not chunk:            # timeout, give up with a short buffer
            break
        buf.extend(chunk)
    return bytes(buf)


def sync_to_magic(port, magic=MAGIC):
    """Slide a window over the stream until the magic bytes appear."""
    window = bytearray()
    while True:
        b = port.read(1)
        if not b:                # timed out before we ever saw the magic
            return False
        window.extend(b)
        if len(window) > len(magic):
            del window[0]        # keep only the last len(magic) bytes
        if window == magic:
            return True


def read_report(port, overall_timeout=8.0):
    """
    Read the localizer's text report the board prints after the raw dump.

    The firmware sends the WAV4 payload first and only then the report, so by
    the time this is called the audio is already safely read and nothing here
    can corrupt it. Reading it matters because only one process can hold the
    COM port: without this you would have to choose between capturing the data
    and seeing the board's own answer.

    Stops at the report's "--- end ---" marker, or when the board goes quiet,
    or at overall_timeout. Returns a list of lines, empty if the firmware
    produced nothing (an older build, or Localize_Init having failed).
    """
    previous_timeout = port.timeout
    port.timeout = 0.5              # short, so silence is detected quickly
    lines = []
    deadline = time.time() + overall_timeout
    try:
        while time.time() < deadline:
            raw = port.readline()
            if not raw:
                if lines:
                    break           # it spoke, then stopped: report is done
                continue            # still thinking, keep waiting
            line = raw.decode("ascii", errors="replace").rstrip("\r\n")
            lines.append(line)
            if "--- end ---" in line:
                break
    finally:
        port.timeout = previous_timeout
    return lines


def read_capture(port, num_mics=NUM_MICS, log=print):
    """
    Wait for one dump and return it as a (num_mics, nsamples) int16 array,
    or None if the stream ended early.

    log is where progress text goes; pass a no-op to stay quiet.
    """
    if not sync_to_magic(port):
        log("Never saw the WAV4 header. Did the recording finish?")
        return None

    length_bytes = read_exact(port, 4)
    if len(length_bytes) < 4:
        log("Short read on the length field.")
        return None

    nbytes = int.from_bytes(length_bytes, "little")   # per-channel byte count
    nsamples = nbytes // 2
    log(f"Header OK. {num_mics} channels of {nbytes} bytes "
        f"({nsamples} samples each).")

    channels = []
    for m in range(num_mics):
        data = read_exact(port, nbytes)
        if len(data) < nbytes:
            log(f"Short read on mic{m}: got {len(data)} of {nbytes} bytes.")
            return None
        channels.append(np.frombuffer(data, dtype="<i2"))   # LE int16

    return np.stack(channels, axis=0)


def save_wavs(cap, wav_for, sample_rate=SAMPLE_RATE):
    """
    Write one mono WAV per channel. wav_for(m) gives the path for mic m.

    These are listening copies only. Nothing in the analysis reads them, but
    being able to play a trial back is the fastest way to tell a clean clap
    from a chair scrape.
    """
    for m in range(cap.shape[0]):
        with wave.open(wav_for(m), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(sample_rate)
            w.writeframes(cap[m].astype("<i2").tobytes())
