# HANDOFF: project history and pending work

This file holds the story, the open work, and the debugging history that
explains why things are the way they are. Read together with CLAUDE.md,
which holds the compact always-true facts. Last updated 2026-07-21
(warm-up discard, check_sync.py, proposed final geometry).

## Where the project stands

Working and proven on hardware:
- Single-mic pipeline end to end: button press records to RAM, dumps over
  ST-LINK VCP, Python saves a playable WAV. Tagged v0.1-single-mic.
- Localization simulation (mic_sims_files/localization_sim.py) verified:
  isolated delay estimator worst error 0.0007 samples, full-sweep angle
  error under 0.1 degrees at 2 m and 20 m, graceful degradation to ~0.4
  deg at 0 dB SNR. Note this was all for the default 10 cm SQUARE
  geometry, which is not the array actually being built (see below).
  It is the reference the firmware port will be validated against.
- GitHub repo with README and .gitignore.

Written, committed, builds clean, NEVER RUN ON HARDWARE:
- CubeMX four-mic configuration (channels 0,1,3 added, filters 1-3, three
  new DMA requests), plus commit 9f179e1 fixing channel 3 RightBitShift
  to 0x07.
- The four-mic user code is in mic_test/Core/Src/main.c as of commit
  b21479e. Sync-order filter start, per-mic circular DMA drain via a
  filter->mic map, "WAV4" UART dump. RECORD_SECS dropped 4 -> 1 for the
  RAM budget. 0 errors, 0 warnings, bss 164040 bytes.
- mic_sims_files/catch_audio4.py as of commit e6058c1. Syncs on "WAV4",
  reads the per-channel length, saves mic0.wav..mic3.wav plus capture.npy
  shaped (4, nsamples) to match what localization_sim.py expects.

- mic_sims_files/check_sync.py, the bring-up analysis for a capture.
  Smoke tested against a synthetic capture with a deliberate
  1-sample-per-channel stagger; it recovered +0.000, +1.000, +2.000,
  +3.000 exactly. Never yet run on real data.

Cleared:
- All four mics are now wired on the temporary in-line fixture (was the
  blocker). Nothing downstream of that has been exercised yet.

Not started:
- Clap sync verification on real data, offline localization, CMSIS-DSP
  port.

## Current bench array is a temporary in-line fixture

The four mics are currently in a straight line on the small breadboard,
packed about as close as the parts allow. This is a BRING-UP FIXTURE for
proving all four channels work, not the final array. A larger breadboard
is coming so the mics can be spaced out properly; the final geometry is
still to be decided.

What this means for now:

- Do NOT touch MIC_POS or estimate_direction() yet. Geometry is
  irrelevant to the only test this fixture is for (the clap sync check),
  and any values entered now would just have to be redone.
- The tight spacing is an advantage for sync checking. At roughly 2 cm
  pitch the true acoustic delay between adjacent mics is about 58 us, or
  under one sample at 16 kHz, and under about 3 samples end to end.
  So all four clap onsets should land essentially on top of each other.
  Any channel sitting several samples off is a filter sync bug, not
  geometry, which makes this fixture a cleaner test than a spread out
  array would be.
- This fixture cannot do localization. Sub-sample delays across the whole
  aperture means there is no real angular resolution to extract. Do not
  read anything into direction estimates from it.

When the real array is built, before analyzing any capture:

1. Replace MIC_POS with the measured port-to-port positions.
2. If the final array is also collinear, estimate_direction() will
   silently return garbage: every baseline vector is parallel, so the
   least squares matrix is rank 1, the across-axis component of u is
   unconstrained and comes back near zero, and arctan2 collapses the
   answer to 0 or 180 deg. A linear array needs the reduced solve
   (recover the along-axis direction cosine, then arccos) and can only
   ever give a bearing in a half plane, since sources mirrored across the
   mic line produce identical delays. A non-collinear layout (the square
   the sim already assumes, or any triangle plus centre) avoids both
   problems and is worth preferring if the mounting allows it. Worth
   raising with Ben before committing to a final geometry.

## Proposed final geometry: 10 cm square (not yet agreed with Ben)

Recommendation is a 10 cm square, side measured port to port. Spacing is a
straight trade: wider gives better angular resolution, narrower avoids
spatial aliasing. Assuming GCC-PHAT with parabolic interpolation resolves
about 0.2 samples on a real clap:

| Side  | Delay across one side | Angle error at broadside | Aliasing above |
|-------|-----------------------|--------------------------|----------------|
| 5 cm  | 2.3 samples           | about 4.9 deg            | 3.4 kHz        |
| 10 cm | 4.7 samples           | about 2.5 deg            | 1.7 kHz        |
| 15 cm | 7.0 samples           | about 1.6 deg            | 1.1 kHz        |
| 20 cm | 9.3 samples           | about 1.2 deg            | 860 Hz         |

The aliasing column is the strict half wavelength bound and is pessimistic
in practice, since broadband claps plus the max_tau search window keep the
peak unambiguous well past it. It is still the reason not to go as wide as
the breadboard allows.

10 cm wins for a reason beyond the table: localization_sim.py is already
validated at exactly that geometry, so the first real capture can be
compared against a known good simulation result. If it disagrees, that is
hardware and not math. 15 cm buys under a degree and costs that reference.
Widening later is a one-line MIC_POS change plus a re-measure.

Far field holds comfortably: a 10 cm aperture with sources at 1 m or more
is well inside the assumption the model makes.

Is a square optimal? It is a good choice and clearly right over a line,
but not uniquely optimal. What matters most is that it is non-collinear,
which fixes both the rank deficiency in estimate_direction() and the front
to back ambiguity. The square is also symmetric, so accuracy is uniform in
angle, and it is the easiest shape to build accurately by counting holes.
The main alternative is an equilateral triangle with a mic at the centre:
for the same aperture it gives slightly more uniform coverage and better
conditioning, because the centre mic forms three baselines from one point
rather than the square's two redundant parallel pairs. The gain is a few
tenths of a degree, and it costs the validated reference and is harder to
lay out on a grid (the triangle height is an irrational multiple of the
pitch). The square's real limitation, shared with the triangle, is that it
is planar: bearing in the plane only, and a source above the plane is
indistinguishable from its mirror below. Elevation would need a
non-planar layout such as a tetrahedron. That planar limitation is the one
choice that is expensive to undo later, so raise it with Ben first.

Building it accurately without a PCB: use perfboard as the jig. The 0.1
inch (2.54 mm) grid is a precision etched fixture, more trustworthy than
any ruler. 40 holes is 101.6 mm, so a 40 by 40 hole square is 10.16 cm a
side, repeatable to the board's own etch tolerance. Count holes, do not
measure. Solder the mics down so they cannot shift, keep all four ports
coplanar and facing the same way, and label them 0 to 3 physically. Then
measure port to port with calipers and put the measured numbers in
MIC_POS. For scale, 1 mm of position error is about 0.047 samples of
delay error, well under a degree, so 1 mm accuracy is plenty.

Two wiring notes for the spread out version. The CLK net will fan 2.4 MHz
out to four mics over maybe 40 cm of jumper wire, long enough to ring: put
33 to 100 ohms in series at the MCU end and run a ground wire alongside
the clock. And mics 0 and 1 share PE7 while mics 2 and 3 share PB1, so
place each sharing pair on adjacent corners rather than diagonal ones to
keep those shared DOUT stubs short.

## Reference: the 4-mic user code, as landed in main.c

DONE, committed in b21479e. This listing is kept as a backup because
CubeMX regeneration wipes anything outside the USER CODE fences, and this
is the fastest way to restore it. If main.c and this listing ever
disagree, main.c wins. All of it lives inside USER CODE fences in
mic_test/Core/Src/main.c.

USER CODE BEGIN PD:

    #define SAMPLE_RATE   16000
    #define RECORD_SECS   1
    #define NUM_MICS      4
    #define TOTAL_SAMPLES (SAMPLE_RATE * RECORD_SECS)
    #define DMA_BUF_LEN   2048
    #define WARMUP_SAMPLES 4000

USER CODE BEGIN PV (replaces the single-mic buffers):

    int32_t dma_buf[NUM_MICS][DMA_BUF_LEN];
    int16_t recording[NUM_MICS][TOTAL_SAMPLES];
    volatile uint32_t rec_index[NUM_MICS];
    volatile uint32_t warmup_left[NUM_MICS];
    volatile uint8_t half_flag[NUM_MICS], full_flag[NUM_MICS];
    volatile uint8_t recording_active = 0;
    extern UART_HandleTypeDef hcom_uart[];

USER CODE BEGIN 0 (replaces store_samples):

    /* filter0=ch2 PE7 rising -> mic0, filter1=ch1 PE7 falling -> mic1,
       filter2=ch0 PB1 rising -> mic2, filter3=ch3 PB1 falling -> mic3 */
    static int filter_to_mic(DFSDM_Filter_HandleTypeDef *f)
    {
        if (f == &hdfsdm1_filter0) return 0;
        if (f == &hdfsdm1_filter1) return 1;
        if (f == &hdfsdm1_filter2) return 2;
        return 3;
    }

    static void store_samples(int mic, int32_t *src, uint32_t count)
    {
        uint32_t i = 0;
        while (i < count && warmup_left[mic] > 0) {   /* burn off warm-up */
            warmup_left[mic]--;
            i++;
        }
        for (; i < count && rec_index[mic] < TOTAL_SAMPLES; i++) {
            recording[mic][rec_index[mic]++] = (int16_t)(src[i] >> 8);
        }
    }

USER CODE BEGIN 2 (new, forces filter sync even if CubeMX did not):

    hdfsdm1_filter1.Init.RegularParam.Trigger = DFSDM_FILTER_SYNC_TRIGGER;
    hdfsdm1_filter2.Init.RegularParam.Trigger = DFSDM_FILTER_SYNC_TRIGGER;
    hdfsdm1_filter3.Init.RegularParam.Trigger = DFSDM_FILTER_SYNC_TRIGGER;
    if (HAL_DFSDM_FilterInit(&hdfsdm1_filter1) != HAL_OK) Error_Handler();
    if (HAL_DFSDM_FilterInit(&hdfsdm1_filter2) != HAL_OK) Error_Handler();
    if (HAL_DFSDM_FilterInit(&hdfsdm1_filter3) != HAL_OK) Error_Handler();

USER CODE BEGIN 4 (replaces the two callbacks):

    void HAL_DFSDM_FilterRegConvHalfCpltCallback(DFSDM_Filter_HandleTypeDef *f)
    {
        half_flag[filter_to_mic(f)] = 1;
    }

    void HAL_DFSDM_FilterRegConvCpltCallback(DFSDM_Filter_HandleTypeDef *f)
    {
        full_flag[filter_to_mic(f)] = 1;
    }

USER CODE BEGIN WHILE (replaces the whole single-mic state machine):

    if (!recording_active && BspButtonState == BUTTON_PRESSED)
    {
      BspButtonState = BUTTON_RELEASED;
      for (int m = 0; m < NUM_MICS; m++) {
        rec_index[m] = 0;
        warmup_left[m] = WARMUP_SAMPLES;
        half_flag[m] = 0;
        full_flag[m] = 0;
      }
      recording_active = 1;
      BSP_LED_On(LED_GREEN);
      /* sync-armed filters first, trigger filter LAST */
      if (HAL_DFSDM_FilterRegularStart_DMA(&hdfsdm1_filter1, dma_buf[1], DMA_BUF_LEN) != HAL_OK) Error_Handler();
      if (HAL_DFSDM_FilterRegularStart_DMA(&hdfsdm1_filter2, dma_buf[2], DMA_BUF_LEN) != HAL_OK) Error_Handler();
      if (HAL_DFSDM_FilterRegularStart_DMA(&hdfsdm1_filter3, dma_buf[3], DMA_BUF_LEN) != HAL_OK) Error_Handler();
      if (HAL_DFSDM_FilterRegularStart_DMA(&hdfsdm1_filter0, dma_buf[0], DMA_BUF_LEN) != HAL_OK) Error_Handler();
    }

    if (recording_active)
    {
      for (int m = 0; m < NUM_MICS; m++) {
        if (half_flag[m]) { half_flag[m] = 0; store_samples(m, &dma_buf[m][0], DMA_BUF_LEN / 2); }
        if (full_flag[m]) { full_flag[m] = 0; store_samples(m, &dma_buf[m][DMA_BUF_LEN / 2], DMA_BUF_LEN / 2); }
      }

      uint8_t all_done = 1;
      for (int m = 0; m < NUM_MICS; m++)
        if (rec_index[m] < TOTAL_SAMPLES) all_done = 0;

      if (all_done)
      {
        HAL_DFSDM_FilterRegularStop_DMA(&hdfsdm1_filter0);
        HAL_DFSDM_FilterRegularStop_DMA(&hdfsdm1_filter1);
        HAL_DFSDM_FilterRegularStop_DMA(&hdfsdm1_filter2);
        HAL_DFSDM_FilterRegularStop_DMA(&hdfsdm1_filter3);
        recording_active = 0;
        BSP_LED_Off(LED_GREEN);
        BSP_LED_On(LED_BLUE);

        uint32_t nbytes = TOTAL_SAMPLES * 2u;
        uint8_t header[8] = { 'W','A','V','4',
                              (uint8_t)nbytes, (uint8_t)(nbytes >> 8),
                              (uint8_t)(nbytes >> 16), (uint8_t)(nbytes >> 24) };
        HAL_UART_Transmit(&hcom_uart[COM1], header, 8, HAL_MAX_DELAY);
        for (int m = 0; m < NUM_MICS; m++)
          HAL_UART_Transmit(&hcom_uart[COM1], (uint8_t *)recording[m],
                            (uint16_t)nbytes, HAL_MAX_DELAY);

        BSP_LED_Off(LED_BLUE);
      }
    }

Notes on this code (all already applied, kept as rationale):
- The warm-up discard exists because two notes in this file contradicted
  each other: trim the first second of settling, but RECORD_SECS is 1 so
  there is nothing left to trim. Dropping 0.25 s in firmware before
  storing starts resolves it. Sync is safe because every mic drops the
  same count from its own stream, so the channels shift together.
- 32000 bytes per channel fits a single HAL_UART_Transmit (uint16_t size
  limit is 65535), so no chunking loop needed at RECORD_SECS 1. If the
  duration ever grows, reintroduce chunking (this bug bit us once: the
  size arg silently truncated 128000 to 62464).
- Verify against the generated code that handle names match (hdfsdm1_filter0
  through hdfsdm1_filter3, hdfsdm1_channel0/1/2/3). Adjust if CubeMX named
  them differently.
- Before building, confirm in stm32l5xx_hal_msp.c: all four DMA inits say
  DMA_CIRCULAR and WORD alignment, and GPIO comments list PF10, PE7, PB1.

## Reference: 4-channel capture script

DONE, committed in e6058c1 as mic_sims_files/catch_audio4.py. Syncs on
magic "WAV4", reads the 4-byte little-endian per-channel length, then
reads four sequential channel blocks. Saves mic0.wav..mic3.wav plus
capture.npy, an int16 array shaped (4, nsamples) matching the mic_signals
layout localization_sim.py expects, so a capture feeds gcc_phat with no
reshaping. The single-mic "WAV0" version is still there as catch_audio.py.

## Milestones from here

1. DONE. Mics 1-3 wired on the temporary in-line breadboard.
2. First 4-mic run. This is the first time this firmware executes at all,
   so expect to debug the code as much as the wiring. Sequence:
     - flash the current main.c (the warm-up change needs a rebuild)
     - python catch_audio4.py COM4    (start it BEFORE the button press)
     - press the blue button, wait about half a second for the warm-up to
       pass, then one sharp clap 30 to 50 cm away, broadside to the line
     - blue LED means it is dumping, about 11 s at 115200
     - python check_sync.py
3. Clap sync check. check_sync.py prints per-channel RMS/peak/DC, finds
   the clap from the summed envelope, and reports each channel's GCC-PHAT
   lag against mic0 in samples. Because the mics are packed tight, true
   acoustic delay is under about 3 samples end to end, so a PASS means all
   four land within the 5 sample tolerance. A near-silent channel is
   almost always SEL wiring or a clock edge that does not match SEL on
   that channel. A channel that is alive but tens of samples off is filter
   sync. No offline trimming needed now that the firmware discards the
   warm-up.
4. Build the real spaced array on the larger breadboard (see the geometry
   decision below), discuss with Ben, then measure port-to-port and set
   MIC_POS from the measured numbers, not the nominal ones.
5. Offline validation: claps from known angles (protractor + tape measure,
   1 m or more away, source at array height, away from walls), run
   localization_sim.py's gcc_phat + estimate_direction on capture.npy.
   Deliverable: estimated vs true angle plot. Expect several degrees of
   error in the real world; the sim's sub-0.1 deg is the clean-room ceiling.
6. CMSIS-DSP port: reimplement gcc_phat (arm_rfft_fast_f32) and the least
   squares fusion in C. Validate by feeding identical capture.npy frames
   and comparing delays to Python within a fraction of a sample. Budget
   check from earlier analysis: ~10 ms of FFT work per 32 ms frame at
   96 MHz, roughly 3x headroom.

## Debugging history worth remembering

- CubeMX regeneration reverted DMA mode to Normal and later DMA width to
  Byte. Both fatal, both silent. Always diff generated files after regen.
- HAL_UART_Transmit uint16_t size truncation (128000 -> 62464 bytes,
  compiler warning was the only clue). Treat every warning as guilty.
- DFSDM is under Computing in this CubeMX version, not Analog.
- Original plan assumed 8 DFSDM channels; this chip has 4. The channel
  map in CLAUDE.md is the corrected version.
- First second of DFSDM output after start contains filter settling
  artifacts (pop or DC step). Normal; trim in analysis.
- Serial capture script must be started before pressing the button
  (reset_input_buffer eats boot text; script syncs on magic bytes).
- Mic orientation: MEMS mics are omnidirectional; all four flat on one
  plane, ports up, positions measured port-to-port. Direction info comes
  from timing only. Label mics physically 0-3.

## Context for tone and docs

Owner is an undergraduate; written deliverables should read like careful
undergrad work: plain sentences, no em dashes, explanations that show
reasoning rather than polish. Preference for tables in hardware
comparisons and staged step-by-step instructions.
