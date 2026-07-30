# Bench checklist: 4-mic clap capture

Print this. Full reasoning is in `steps-forward.md`.

**Bearing convention:** counterclockwise from +x, where +x points toward the
mic1/mic3 edge (the right-hand side when mic0 is the top-left corner). 0 deg
is off that edge, 90 deg is off the mic0/mic1 top edge.

## Setup (do this before touching the board)

- [ ] Array at least **2 m** from the nearest wall or large flat object. A
      reflection off something closer arrives inside the analysis window and
      corrupts the delay of the microphone pair facing it. At 65 cm clearance
      that cost about 3.4 deg of bearing error, with no code change involved
      either way. Image source arithmetic tells you where to expect the echo: a
      surface d metres away adds 2d of path, which is `2d / 343 * 16000`
      samples, so 65 cm predicts a bump about 61 samples after the direct peak.
- [ ] Source **1.5 m or more** from the array, and **at array height**. Hand
      placement is what sets this, not physics: the angular error from placing
      the source by hand goes as 1/distance, so 5 cm of it is 7 deg at 40 cm but
      under 2 deg at 1.5 m. Under 2 deg needs 1.43 m or more.
- [ ] Mark the source position with tape. Protractor centred on the array,
      0 deg along +x, angles measured counterclockwise. Tape measure from the
      array centre to the source mark.
- [ ] All four mic ports coplanar, facing the same way, physically labelled
      0 to 3. **mic0 is the top-left corner** and is the one wired to PE7 with
      SEL to GND. A mislabelled corner reflects the bearing even when every
      delay is right.
- [ ] Write the room setup into `--notes`: wall distance and clap distance.
      They set when the first echo arrives, which decides whether a trial is
      trustworthy.

## Run order (script FIRST, then the button)

Only one process can hold the COM port, so the capture script must already be
running before you press the button.

1. `python run_session.py COM4 --session <name> --angles 0,45,90,135,180,225,270,315 --trials 5 --notes "wall 2.1 m, clap 1.5 m"`
   Manual fallback, one angle at a time, still works:
   `python catch_audio4.py COM4 --tag angle000 --session <name> --trials 5 --notes "wall 2.1 m, clap 1.5 m"`
2. The runner names the angle to set up. Move the source, then press Enter.
3. Wait for "Ready. Press the blue button on the board now..."
4. Press the blue user button. Green LED comes on.
5. Clap once, sharply, from the marked position.
6. Green out, blue on for about 11 s, board prints its report.
7. The runner checks the trial and prints PASS or FAIL on the spot. On a FAIL:
   **Enter** retakes, **k** keeps it anyway, **s** skips the angle, **q** ends
   the session. A retake renames the bad capture to `rejected<N>.npy`, which no
   analysis script reads, so nothing is lost and nothing bad enters the plot.
8. At the end the runner writes the validation plot and runs the board-vs-Python
   comparison itself. No separate step needed.

Useful any time, opens no COM port:
`python run_session.py --summary --session <name>` shows which angles are done.
Re-running the same record command resumes where you left off.

Checking one capture by hand: `python trial_quality.py <npy> --true-angle 315`

## LEDs

| LED | Meaning |
|---|---|
| Green on | Armed: discarding warm-up, listening, AND storing. It covers both, so there is **no visual cue for the exact trigger instant**. |
| Green off | The stored second is complete. |
| Blue on | Dumping over UART, about 11 s per trial at 115200. |

## Symptom table

| What you see | What it means |
|---|---|
| Green LED never goes out, script times out, no other symptom | Trigger never fired. Clap harder and closer, then check the board is running current firmware (TRIGGER_LEVEL 1000). |
| A channel near silent (rms under 5 in check_sync) | SEL wiring on that mic, or that channel's clock edge does not match its SEL level. |
| A channel alive but tens of samples off mic0 | Filter sync. Filters 1,2,3 armed with the sync trigger, filter 0 started LAST. |
| Plausible bearing but a high triangle residual | Reflection. Firmware flags it above 0.3 samples. Check clearance again, including furniture, not just walls. A high residual marks a suspect capture, it is not an error estimate. |
| "weak transient" warning | Clap harder or closer. Firmware warns below peak/noise 14.7, localize_capture.py below 20. |
| "very quiet, clap harder or closer" (peak under 2000) | Same fix. |
| "clipped" (peak 32700 or more) | Clap softer or further; the transient position is unreliable. |
| No report after the audio dump | Older firmware, or Localize_Init failed at boot. |
| `FAILED: array is collinear` or `singular` | Compiled-in geometry is wrong, not the room. |
| Bearing about 180 deg off, everything else clean | Corner labelling versus array_geometry.py. |

## Quick reference

Aperture 13.55 cm = 6.32 samples. Sync tolerance 8.32 samples. Condition number
1.07, no blind directions. 16 kHz, 1 sample = 62.5 us = about 2.1 cm.
compare_board.py tolerances: delays 0.05 samples, bearing 0.5 deg.
