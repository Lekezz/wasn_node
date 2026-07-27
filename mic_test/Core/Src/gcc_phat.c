/* gcc_phat.c - GCC-PHAT delay estimation, ported from localization_sim.py.
 *
 * The algorithm, and why each step is there:
 *
 *   1. Copy each window to float and subtract its mean. DC is a huge spike in
 *      the zero-frequency bin; PHAT would normalise it to the same weight as
 *      everything else and let it dominate.
 *   2. Zero-pad to twice the window length. Correlation via FFT is circular,
 *      so without padding a peak near the edge wraps around and reappears at
 *      the wrong lag.
 *   3. Cross spectrum R = A * conj(B).
 *   4. PHAT weighting: divide every bin by its own magnitude, keeping only
 *      phase. Phase is "when", magnitude is "what", and only "when" carries
 *      direction information. This is what keeps the peak sharp in a room
 *      with echoes.
 *   5. Inverse FFT to get the correlation curve; its peak is the delay.
 *   6. Parabolic interpolation through the peak and its two neighbours, which
 *      is what buys sub-sample resolution. One sample at 16 kHz is 2.1 cm of
 *      path difference, so without this step the angular resolution would be
 *      far too coarse.
 *
 * MEMORY. The three working buffers are 16 KB each and live in RAM2, the
 * 64 KB bank at 0x20030000 that nothing else uses. The main 192 KB bank is
 * almost full: capture.c's `recording` (125 KB) and `dma_buf` (32 KB) leave
 * only about 32 KB, which is not enough. See the .ram2 section added to
 * STM32L552ZETXQ_FLASH.ld. They are marked NOLOAD there, so startup does not
 * spend time zeroing 48 KB that gets overwritten immediately anyway.
 */
#include "gcc_phat.h"

#include "loc_config.h"
#include "fft_backend.h"

#include <math.h>

/* Placed in RAM2 by the linker (see the .ram2 section in the .ld). Marked
   volatile-free and static: nothing outside this file touches them. */
#define IN_RAM2   __attribute__((section(".ram2"), aligned(4)))

static IN_RAM2 float s_scratch[LOC_FFT_LEN];   /* windowed input, then IFFT out */
static IN_RAM2 float s_spec_a[LOC_FFT_LEN];    /* spectrum of channel a */
static IN_RAM2 float s_spec_b[LOC_FFT_LEN];    /* spectrum of channel b */

static int s_ready = 0;


int GccPhat_Init(void)
{
    s_ready = Fft_Init(LOC_FFT_LEN);
    return s_ready;
}


/*
 * Copy one int16 window into s_scratch as floats, remove its mean, and zero
 * the padding. Mirrors `win = win - win.mean(...)` followed by numpy's
 * implicit zero-padding in rfft(x, n=...).
 */
static void load_window(const int16_t *src)
{
    float sum = 0.0f;
    for (int n = 0; n < LOC_WINDOW_LEN; n++) {
        sum += (float)src[n];
    }
    const float mean = sum / (float)LOC_WINDOW_LEN;

    for (int n = 0; n < LOC_WINDOW_LEN; n++) {
        s_scratch[n] = (float)src[n] - mean;
    }
    for (int n = LOC_WINDOW_LEN; n < LOC_FFT_LEN; n++) {
        s_scratch[n] = 0.0f;
    }
}


/*
 * Cross spectrum with PHAT weighting, computed in place into spec_a.
 *
 * For each bin: R = A * conj(B), then R /= (|R| + 1e-12). The epsilon is the
 * same guard the Python uses; it keeps a silent bin (magnitude zero) from
 * producing a division by zero, at the cost of leaving it near zero, which is
 * the right behaviour since a bin with no energy carries no timing.
 *
 * Bins 0 and N/2 are purely real and share a slot in CMSIS's packed layout
 * (see fft_backend.h). Their product is real, so PHAT reduces to taking the
 * sign, which is exactly what the general formula gives for a real number.
 */
static void cross_spectrum_phat(float *spec_a, const float *spec_b)
{
    /* DC and Nyquist, the two folded real bins. */
    for (int k = 0; k < 2; k++) {
        const float r = spec_a[k] * spec_b[k];
        spec_a[k] = r / (fabsf(r) + 1e-12f);
    }

    for (int k = 1; k < LOC_FFT_LEN / 2; k++) {
        const float ar = spec_a[2 * k];
        const float ai = spec_a[2 * k + 1];
        const float br = spec_b[2 * k];
        const float bi = spec_b[2 * k + 1];

        /* (ar + i·ai) * conj(br + i·bi) */
        const float rr = ar * br + ai * bi;
        const float ri = ai * br - ar * bi;

        const float mag = sqrtf(rr * rr + ri * ri) + 1e-12f;
        spec_a[2 * k]     = rr / mag;
        spec_a[2 * k + 1] = ri / mag;
    }
}


float GccPhat_Estimate(const int16_t *a, const int16_t *b,
                       float max_tau_samples)
{
    if (!s_ready) return 0.0f;

    load_window(a);
    Fft_RealForward(s_scratch, s_spec_a);

    load_window(b);
    Fft_RealForward(s_scratch, s_spec_b);

    cross_spectrum_phat(s_spec_a, s_spec_b);

    /* Correlation curve lands in s_scratch. Any global scale factor the
       inverse transform does or does not apply is irrelevant: everything
       below is either an argmax or a ratio of three neighbouring samples,
       and both are invariant under positive scaling. */
    Fft_RealInverse(s_spec_a, s_scratch);

    /*
     * Search only inside the physically possible lag range. The Python
     * rebuilds the correlation into a centred array and takes an argmax over
     * it; doing the same indexing directly is equivalent and avoids a copy.
     *
     * Lag L maps to correlation sample (L + N) % N, because a negative lag is
     * stored at the far end of a circular correlation. Python's
     *     cc = concat(cc[-max_shift:], cc[:max_shift+1])
     * is that same mapping written as a concatenation.
     */
    int max_shift = (int)ceilf(max_tau_samples) + 1;
    if (max_shift < 1) max_shift = 1;
    if (max_shift > LOC_FFT_LEN / 2 - 1) max_shift = LOC_FFT_LEN / 2 - 1;

    int   best_lag = 0;
    float best_mag = -1.0f;
    for (int lag = -max_shift; lag <= max_shift; lag++) {
        const int   idx = (lag + LOC_FFT_LEN) % LOC_FFT_LEN;
        const float mag = fabsf(s_scratch[idx]);
        if (mag > best_mag) {
            best_mag = mag;
            best_lag = lag;
        }
    }

    /*
     * Parabolic interpolation. Fit a parabola through the peak and its two
     * neighbours and take its vertex. Python guards with
     * `if 0 < peak < len(cc) - 1`, i.e. it skips interpolation when the peak
     * sits on either end of the searched range; the same guard is here.
     */
    float offset = 0.0f;
    if (best_lag > -max_shift && best_lag < max_shift) {
        const float y0 = fabsf(s_scratch[(best_lag - 1 + LOC_FFT_LEN) % LOC_FFT_LEN]);
        const float y1 = best_mag;
        const float y2 = fabsf(s_scratch[(best_lag + 1 + LOC_FFT_LEN) % LOC_FFT_LEN]);

        const float denom = y0 - 2.0f * y1 + y2;
        if (fabsf(denom) > 1e-12f) {
            offset = 0.5f * (y0 - y2) / denom;
        }
    }

    return (float)best_lag + offset;
}
