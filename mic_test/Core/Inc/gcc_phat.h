/* gcc_phat.h - GCC-PHAT delay estimation between two mic channels.
 *
 * Firmware port of gcc_phat() in mic_sims_files/localization_sim.py. That
 * Python function is the validated reference (delay bias under 0.001 samples,
 * angle error under 0.1 degrees in simulation), and this file is required to
 * reproduce its output on identical input. Any change here needs the same
 * change there.
 *
 * Call GccPhat_Init() once at startup, then GccPhat_Estimate() per pair.
 */
#ifndef GCC_PHAT_H
#define GCC_PHAT_H

#include <stdint.h>

/* Allocate and prepare the FFT. Call once before GccPhat_Estimate.
   Returns 1 on success, 0 if the FFT backend rejected the configured length
   (which would mean LOC_FFT_LEN is not a power of two the backend supports). */
int GccPhat_Init(void);

/*
 * Estimate how many samples channel b lags channel a.
 *
 * a and b point at LOC_WINDOW_LEN int16 samples each, already cut to the
 * analysis window. They are read, not modified. Their means are removed
 * internally, matching the Python, because a constant offset is a large
 * meaningless spike at zero frequency that PHAT would then normalise as if it
 * were signal.
 *
 * max_tau_samples bounds the search: two mics cannot disagree by more than
 * their spacing divided by the speed of sound, so looking outside that window
 * can only ever find a spurious peak. Use Geom_MaxTauSamples().
 *
 * Returns the delay in samples as (t_a - t_b), the same sign convention the
 * Python gcc_phat returns. Note that the callers in both languages negate it
 * to get (t_j - t_i); see localize.c.
 */
float GccPhat_Estimate(const int16_t *a, const int16_t *b,
                       float max_tau_samples);

#endif /* GCC_PHAT_H */
