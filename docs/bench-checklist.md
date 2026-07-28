# Bench checklist: 4-mic clap capture

Print this. Full reasoning is in `steps-forward.md`.

**Bearing convention:** counterclockwise from +x, where +x points toward the
mic1/mic3 edge (the right-hand side when mic0 is the top-left corner). 0 deg
is off that edge, 90 deg is off the mic0/mic1 top edge.

## Setup (do this before touching the board)

- [ ] Array at least **2 m** from the nearest wall or large flat object. This
      was the single biggest error source: 65 cm gave -3.40 deg, 2.1 m gave
      +0.58 deg, with no code change.
- [ ] Source **1 m or more** from the array, and **at array height**.
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

1. `python run_session.py COM4 --session <name> --angles 0,45,90,135,180,225,270,315 --trials 5 --notes "wall 2.1 m, clap 1 m"`
   Manual fallback, one angle at a time, still works:
   `python catch_audio4.py COM4 --tag angle000 --session <name> --trials 5 --notes "wall 2.1 m, clap 1 m"`
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
| Green LED never goes out, script times out, no other symptom | Trigger never fired. Clap harder and closer, then check the board is running f5c3d78 or later (TRIGGER_LEVEL 1000, not 2500). |
| Every float in the report prints blank, integers fine | Old firmware. nano.specs printf fingerprint. Rebuild and reflash. |
| A channel near silent (rms under 5 in check_sync) | SEL wiring on that mic, or that channel's clock edge does not match its SEL level. |
| A channel alive but tens of samples off mic0 | Filter sync. Filters 1,2,3 armed with the sync trigger, filter 0 started LAST. |
| Plausible bearing but a high triangle residual | Reflection. Firmware flags it above 0.3 samples. Good is near 0.119; the 65 cm wall gave 0.875. Check clearance, including furniture. |
| "weak transient" warning | Clap harder or closer. Firmware warns below peak/noise 14.7, localize_capture.py below 20. |
| "very quiet, clap harder or closer" (peak under 2000) | Same fix. |
| "clipped" (peak 32700 or more) | Clap softer or further; the transient position is unreliable. |
| No report after the audio dump | Older firmware, or Localize_Init failed at boot. |
| `FAILED: array is collinear` or `singular` | Compiled-in geometry is wrong, not the room. |
| Bearing about 180 deg off, everything else clean | Corner labelling versus array_geometry.py. |

## Quick reference

Aperture 13.5 cm = 6.32 samples. Sync tolerance 8.32 samples. Condition number
1.07, no blind directions. 16 kHz, 1 sample = 62.5 us = about 2.1 cm.
compare_board.py tolerances: delays 0.05 samples, bearing 0.5 deg.
