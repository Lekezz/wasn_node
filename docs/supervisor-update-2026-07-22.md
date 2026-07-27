# WASN Node: progress update

**To:** Ben **[FILL IN: last name or preferred salutation]**
**From:** Leke
**Date:** 22 July 2026
**Period covered:** **[FILL IN: date of last update]** to 22 July 2026

---

## Summary

All four microphones are now recording simultaneously and in sync. This was
the main blocker from last time, and it is cleared. The four channel
firmware had been written but never run on hardware; it now runs, and the
captures it produces pass the timing checks I set up to validate it.

The one thing I would like your input on is array geometry. I only have a
single breadboard to build on, which rules out the 10 cm square the
simulation was originally validated against. I have picked a layout that
fits and characterised what it costs. Details in the geometry section
below.

---

## What is working now

| Stage | Status | Evidence |
|-------|--------|----------|
| Single mic record and dump | Working since **[FILL IN: date]** | Playable WAV over serial |
| Four channel firmware | Working as of 22 July | Builds clean, runs, dumps four channels |
| Four mic simultaneous capture | Working as of 22 July | See timing results below |
| Channel sync verification | Passing | Worst offset 1.80 samples |
| Offline direction estimation | Code written and validated in simulation | Not yet run on a real array |

### The sync result

The concern with four microphones is whether the four digital filters
inside the microcontroller actually start at the same instant. If they do
not, every channel is offset by an unknown amount and no timing based
localization is possible. The hardware has a synchronised start mode for
this, and the firmware starts the three follower filters first and the
trigger filter last.

To test it, all four mics were packed close together in a straight line,
about 2 cm apart. At that spacing the real acoustic delay across the whole
array is under 3 samples at 16 kHz, so if the filters are synchronised, a
single clap should arrive at all four channels at essentially the same
moment. Any channel sitting far off would be a synchronisation fault
rather than real physics.

Measured delays relative to microphone 0, from a single clap:

| Microphone | Delay (samples) | Delay (microseconds) |
|------------|-----------------|----------------------|
| 0 | 0.000 | 0.0 |
| 1 | -0.481 | -30.1 |
| 2 | -1.354 | -84.7 |
| 3 | -1.801 | -112.6 |

Worst offset is 1.80 samples against a physical aperture of about 3
samples, so the channels are aligned.

The result I am more pleased with is that these delays are not just small,
they are physically consistent. Four microphones in a straight line
hearing one distant clap must produce delays that increase linearly with
position. Fitting a straight line through the four values gives a maximum
residual of 0.131 samples, about 8 microseconds. Nothing in the firmware
forces that linearity, so getting it out means the synchronised start, the
data transfer, the channel to microphone mapping, and the serial protocol
are all correct at the same time. A fault in any one of them would have
broken either the ordering or the spacing.

End to end the delay is 1.80 samples, which corresponds to 3.9 cm of extra
path length across a roughly 6 cm array. That puts the clap about 50
degrees off the array axis, which matches where I was standing.

**[PHOTO 1: the bring-up fixture. Four mics in a line on the small
breadboard, with the Nucleo board visible. Take it from above so the
in-line arrangement and the shared wiring are both clear.]**

![Bring-up fixture](images/bringup-fixture.jpg)

**[PHOTO 2: close up of the microphone wiring, showing the shared data
lines and the SEL pins tied high or low. This is the part that is hardest
to describe in text.]**

![Mic wiring detail](images/mic-wiring.jpg)

---

## Geometry: the constraint and what I chose

### The problem

The simulation was validated on a 10 cm square array. I cannot build that.
I have one full-size breadboard, which is about 16.5 cm long but only
about 2.8 cm across the usable rows, so a 10 cm square does not fit in the
short direction.

### What I evaluated

Rather than guess, I extended the simulation to score the layouts that
actually fit, using the same estimator that will run on the real data. All
figures below are simulation only, with no room echo and no measurement
error, so they should be read as a ranking rather than a prediction of
real accuracy.

| Layout | Aperture | Mean error | Median | 90th percentile | Fits one breadboard? |
|--------|----------|-----------|--------|-----------------|----------------------|
| 10 cm square (original) | 14.1 cm | 1.12 deg | 1.01 deg | 2.32 deg | No |
| 10 cm L-shape | 14.1 cm | 1.41 deg | 1.07 deg | 3.03 deg | No |
| **2.8 x 10 cm rectangle** | **10.4 cm** | **1.87 deg** | **1.06 deg** | **7.87 deg** | **Yes** |
| 5 cm square | 7.1 cm | 2.21 deg | 1.81 deg | 4.72 deg | No, needs two boards |
| 2.8 x 15 cm rectangle | 15.3 cm | 2.48 deg | 1.11 deg | 7.96 deg | Yes |
| 2.5 cm square | 3.5 cm | 6.33 deg | 7.72 deg | 8.60 deg | Yes, very tight |

### What I chose and why

I am going with the **2.8 x 10 cm rectangle**. The reasoning:

1. It fits the board I have, using the full row A to row J span across the
   centre channel for the short side and 40 hole pitches for the long side.
2. Its median accuracy (1.06 deg) matches the original 10 cm square, so
   for most source directions there is no penalty at all.
3. It is not collinear, which matters more than the exact dimensions. A
   straight line array cannot tell front from back, and it breaks the
   direction solver outright, because all the baselines become parallel
   and the maths becomes unsolvable in one axis. The rectangle keeps the
   solver well posed. I checked this numerically: rank 2 of 2 required,
   condition number 3.6.
4. Shrinking to a square that fits (2.5 cm) costs far more than making the
   array rectangular. 6.33 deg average versus 1.87 deg.

### The catch, stated honestly

The rectangle's weakness is that its accuracy depends on direction. The
90th percentile error is 7.87 deg against the square's 2.32 deg. I mapped
where the error actually lives:

| Source direction | Mean error |
|------------------|-----------|
| Along the long axis (0, 180 deg) | 0.08 deg |
| Perpendicular to it (90, 270 deg) | 0.02 deg |
| 60 to 120 deg off axis | 0.5 to 1.0 deg |
| **About 30 deg off the long axis (30, 150, 210, 330)** | **8.2 deg** |

So it is not uniformly worse. It is excellent almost everywhere, with four
narrow blind cones roughly 30 degrees off the long axis. I plan to work
around this by aiming the validation claps away from those four bands, and
the analysis script now warns automatically when an estimated bearing
lands in one.

**Question for you:** is that acceptable for what we want to demonstrate,
or is uniform accuracy important enough that I should find a way to mount
the mics off the breadboard on a separate flat surface? Mounting them on
foam board with jumper wires back to the breadboard would restore the full
10 cm square, at the cost of longer wires on the 2.4 MHz clock line, which
brings its own signal quality risk. I did not want to make that call
alone.

---

## Software written this period

| File | Purpose |
|------|---------|
| `check_sync.py` | Verifies the four channels are time aligned. Reports per channel levels, finds the clap, and measures each channel's delay against microphone 0. |
| `compare_geometries.py` | Scores candidate array layouts using the existing estimator, which produced the table above. |
| `localize_capture.py` | Turns a real four channel capture into a direction estimate. Validated against synthetic sources at known angles: mean error 1.42 deg, worst 3.04 deg. |

One firmware change: the recording now discards the first 0.25 seconds
before it starts storing, because the microphones and the digital filters
both need a moment to settle after starting. All four channels discard the
same amount, so their alignment is unaffected.

I also found and fixed a measurement error in my own analysis script that
had briefly convinced me two microphones had double the gain of the other
two. The script was measuring signal strength without removing the slow
DC drift that follows a loud clap, and that drift is larger on whichever
mics heard the clap loudest. Once measured correctly, all four channels
match within about 1.4x, which is just the clap being closer to one end.

---

## Next steps

1. Build the 2.8 x 10 cm rectangular array on the full-size breadboard.
   Position by counting holes, since the 0.1 inch grid is more accurate
   than anything I can measure by hand.
2. Measure the actual microphone port positions with calipers and put the
   real numbers into the code. The port is offset from the header pins on
   the breakout boards, so pin spacing is not port spacing.
3. Re-run the sync check on the spaced array to confirm nothing broke with
   the longer wiring.
4. Validation experiment: claps from known angles, measured with a
   protractor and tape measure, at **[FILL IN: distance you plan to use,
   suggest 1 to 2 m]** and away from walls. Compare estimated against true
   angle. Deliverable is an estimated versus true angle plot.
5. Port the direction estimation to run on the microcontroller itself
   using the CMSIS-DSP library, validated by feeding it the same recorded
   data and checking it agrees with the Python version.

**[PHOTO 3: the finished rectangular array, once built. Include a ruler or
calipers in the shot so the scale is visible.]**

![Final array](images/final-array.jpg)

**[PHOTO 4: the validation setup, showing the array, the marked angles on
the floor, and the clap position. Take this during the experiment.]**

![Validation setup](images/validation-setup.jpg)

---

## Open questions

1. **Geometry.** Rectangle on the breadboard with four blind cones, or
   off-board mounting to keep the uniform square? See the geometry section.
2. **Validation scope.** How many angles should I test, and over what
   range? A full 360 degree sweep is more work but shows the blind cones
   clearly, which might be worth documenting rather than hiding.
3. **[FILL IN: anything you want to raise about timeline or deliverables]**
4. **[FILL IN: do you want the raw capture files, or just the plots?]**

---

## Things I am not sure about

- **[FILL IN: is there a deadline or milestone date I should be working
  toward?]**
- **[FILL IN: next meeting date, if we have one scheduled]**
- Whether the final demonstration needs to run in real time on the board,
  or whether offline analysis of recorded captures is enough. This changes
  how much effort the CMSIS-DSP port is worth.
