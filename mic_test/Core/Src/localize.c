/* localize.c - capture in, bearing out. Port of localize_capture.py.
 *
 * Three stages, in order:
 *
 *   1. find_clap  - locate the transient and cut an analysis window around it
 *   2. pair loop  - GCC-PHAT on all six mic pairs
 *   3. fit        - least squares fuse of the six delays into one direction
 *
 * Stage 3 is worth understanding. In the far field, let u be the unit vector
 * pointing from the array toward the source. A mic further along u is closer
 * to the source and hears the clap earlier, so
 *
 *     t_j - t_i = ((pos_i - pos_j) . u) / c
 *
 * Each pair gives one linear equation in u = (ux, uy). Six pairs give an
 * overdetermined 6x2 system, and that redundancy is the whole point: any one
 * pair corrupted by a reflection gets outvoted by the other five. The bearing
 * is then atan2(uy, ux).
 *
 * numpy solves the 6x2 system with lstsq. Here it is solved through the
 * normal equations: (A'A) u = A'b, where A'A is 2x2 and inverts by hand. For
 * a well-conditioned array (condition number near 1, which Geom_Describe
 * checks) the two agree to well under the float32 noise floor.
 */
#include "localize.h"

#include "array_geometry.h"
#include "gcc_phat.h"

#include <math.h>
#include <stdio.h>

static int s_ready = 0;


/*
 * Format a float without needing newlib's floating-point printf.
 *
 * The project links --specs=nano.specs, whose printf omits float support
 * unless the link also pulls in -u _printf_float. Without it every %f in a
 * report prints as nothing at all: the first hardware run came back with
 * "BEARING  deg" and six blank pair delays while every integer field printed
 * correctly. That is a silent, total loss of the numbers the port exists to
 * produce.
 *
 * Turning the flag on would work, but it is an IDE linker setting, which is
 * precisely the kind of state a CubeMX regeneration resets, and it costs
 * roughly 10 KB of flash. Doing the conversion here with integer arithmetic
 * keeps the output working no matter how the project is rebuilt, and keeps
 * this file honest about depending only on integer printf.
 *
 * dp must be 2 or 3, the only precisions this file prints. Returns buf so it
 * can be used directly as a printf argument.
 */
static const char *f2s(char *buf, int n, float v, int dp)
{
    if (isnan(v))  { snprintf(buf, n, "nan");  return buf; }
    if (isinf(v))  { snprintf(buf, n, "%sinf", (v < 0.0f) ? "-" : ""); return buf; }

    const char *sign = "";
    if (v < 0.0f) { sign = "-"; v = -v; }

    const long scale = (dp == 3) ? 1000L : 100L;
    /* +0.5 rounds to nearest rather than truncating, matching how the Python
       side's formatted output rounds. */
    const long total = (long)(v * (float)scale + 0.5f);
    const long ip = total / scale;
    const long fp = total % scale;

    if (dp == 3) snprintf(buf, n, "%s%ld.%03ld", sign, ip, fp);
    else         snprintf(buf, n, "%s%ld.%02ld", sign, ip, fp);
    return buf;
}


int Localize_Init(void)
{
    s_ready = GccPhat_Init();
    return s_ready;
}


const char *Localize_StatusText(loc_status_t status)
{
    switch (status) {
        case LOC_OK:                 return "ok";
        case LOC_ERR_NOT_INIT:       return "localizer not initialised";
        case LOC_ERR_COLLINEAR:      return "array is collinear (rank 1)";
        case LOC_ERR_SHORT_CAPTURE:  return "capture shorter than the window";
        case LOC_ERR_SINGULAR:       return "least squares matrix is singular";
        default:                     return "unknown";
    }
}


/*
 * Envelope of the capture at one sample: the summed absolute value across all
 * four channels, with each channel's DC removed.
 *
 * Summing across mics means one weak channel cannot drag the window off the
 * event. Removing DC matters more than it looks: the DFSDM output carries an
 * offset of several hundred counts that decays for the whole second after a
 * clap, and the median below would otherwise measure that offset rather than
 * the room. On the first ground-truthed capture the offsets summed to 3633
 * against a measured floor of 3268, so the reported SNR was essentially a
 * measure of DC and called a good clap weak. Same fix as the Python.
 */
static inline float envelope_at(const int16_t *const channels[LOC_NUM_MICS],
                                const float dc[LOC_NUM_MICS], uint32_t n)
{
    float sum = 0.0f;
    for (int m = 0; m < LOC_NUM_MICS; m++) {
        sum += fabsf((float)channels[m][n] - dc[m]);
    }
    return sum;
}


/*
 * Median of the envelope, without ever storing it.
 *
 * numpy just calls np.median on a 16000-element array. That array would be
 * 64 KB of float here and there is nowhere to put it, so instead the envelope
 * is recomputed on the fly and binned into a histogram; the median is the bin
 * where the running count passes half the samples.
 *
 * The approximation is bounded by one bin width, peak/LOC_MEDIAN_BINS. On a
 * typical capture that is about 20 counts against a median near 1350, and it
 * only shifts the onset threshold by a fraction of a percent, which moves the
 * detected onset by at most a sample. The window is cut identically for all
 * four channels, so even that shift cancels out of the relative delays that
 * actually set the bearing.
 */
static float median_estimate(const int16_t *const channels[LOC_NUM_MICS],
                             const float dc[LOC_NUM_MICS],
                             uint32_t n_samples, float env_max)
{
    static uint16_t hist[LOC_MEDIAN_BINS];

    for (int b = 0; b < LOC_MEDIAN_BINS; b++) hist[b] = 0;

    if (env_max <= 0.0f) return 0.0f;
    const float scale = (float)(LOC_MEDIAN_BINS - 1) / env_max;

    for (uint32_t n = 0; n < n_samples; n++) {
        int b = (int)(envelope_at(channels, dc, n) * scale);
        if (b < 0) b = 0;
        if (b >= LOC_MEDIAN_BINS) b = LOC_MEDIAN_BINS - 1;
        hist[b]++;
    }

    const uint32_t half = n_samples / 2;
    uint32_t running = 0;
    for (int b = 0; b < LOC_MEDIAN_BINS; b++) {
        running += hist[b];
        if (running >= half) {
            /* Centre of the bin, which is the best single estimate of the
               values that fell into it. */
            return ((float)b + 0.5f) / scale;
        }
    }
    return env_max;
}


/*
 * Locate the clap: find the loudest point of the envelope, then walk back to
 * where the energy first rose above the noise floor. Mirrors find_clap() in
 * both Python scripts, which must stay in agreement with each other and now
 * with this.
 */
static void find_clap(const int16_t *const channels[LOC_NUM_MICS],
                      uint32_t n_samples, loc_result_t *out)
{
    float dc[LOC_NUM_MICS];
    for (int m = 0; m < LOC_NUM_MICS; m++) {
        float sum = 0.0f;
        for (uint32_t n = 0; n < n_samples; n++) sum += (float)channels[m][n];
        dc[m] = sum / (float)n_samples;
    }

    uint32_t peak = 0;
    float    env_peak = -1.0f;
    for (uint32_t n = 0; n < n_samples; n++) {
        const float e = envelope_at(channels, dc, n);
        if (e > env_peak) {
            env_peak = e;
            peak = n;
        }
    }

    const float noise = median_estimate(channels, dc, n_samples, env_peak);
    const float threshold = noise + LOC_ONSET_FRACTION * (env_peak - noise);

    uint32_t onset = peak;
    while (onset > 0 && envelope_at(channels, dc, onset) > threshold) {
        onset--;
    }

    out->onset     = onset;
    out->peak      = peak;
    out->snr_ratio = env_peak / fmaxf(noise, 1e-9f);
    out->weak_transient = (out->snr_ratio < LOC_WEAK_SNR) ? 1 : 0;
}


/*
 * Plane-wave consistency check.
 *
 * A single plane wave forces every triangle of delays to close:
 * d(i,j) + d(j,k) must equal d(i,k). Measured delays that violate this are
 * not describing one arrival direction, which in practice means a reflection
 * has pulled one pair's correlation peak onto the wrong lobe. Reporting the
 * worst residual gives a per-capture trust signal that costs almost nothing.
 *
 * On the first ground-truthed capture five pairs agreed to within 0.07
 * samples while the two triangles containing pair 1-2 were off by 0.88 and
 * 0.75, which is how the wall reflection was identified.
 */
static float worst_triangle_residual(const float d[LOC_NUM_PAIRS])
{
    /* Delay from mic i to mic j, using antisymmetry d(j,i) = -d(i,j). */
    float table[LOC_NUM_MICS][LOC_NUM_MICS] = { { 0.0f } };
    for (int p = 0; p < LOC_NUM_PAIRS; p++) {
        int i, j;
        Geom_Pair(p, &i, &j);
        table[i][j] =  d[p];
        table[j][i] = -d[p];
    }

    float worst = 0.0f;
    for (int i = 0; i < LOC_NUM_MICS; i++) {
        for (int j = i + 1; j < LOC_NUM_MICS; j++) {
            for (int k = j + 1; k < LOC_NUM_MICS; k++) {
                const float r = fabsf(table[i][j] + table[j][k] - table[i][k]);
                if (r > worst) worst = r;
            }
        }
    }
    return worst;
}


loc_status_t Localize_Run(const int16_t *const channels[LOC_NUM_MICS],
                          uint32_t n_samples, loc_result_t *out)
{
    for (int p = 0; p < LOC_NUM_PAIRS; p++) {
        out->pair_delay[p] = 0.0f;
        out->pair_max_tau[p] = 0.0f;
        out->pair_exceeds_physics[p] = 0;
    }
    out->bearing_deg = 0.0f;
    out->worst_triangle_residual = 0.0f;

    if (!s_ready) {
        out->status = LOC_ERR_NOT_INIT;
        return out->status;
    }
    if (n_samples < LOC_WINDOW_LEN) {
        out->status = LOC_ERR_SHORT_CAPTURE;
        return out->status;
    }

    const array_layout_t *layout = Geom_Active();

    /* Refuse to produce a confident-looking number from a hopeless array. A
       collinear layout is rank 1: the across-axis component of u is
       unconstrained and the answer collapses to 0 or 180 regardless of truth.
       Better to say so than to print something plausible. */
    geom_info_t info;
    Geom_Describe(layout, &info);
    if (info.rank < 2) {
        out->status = LOC_ERR_COLLINEAR;
        return out->status;
    }

    find_clap(channels, n_samples, out);

    /*
     * Cut the window around the onset, kept inside the capture.
     *
     * This is a deliberate, small divergence from the Python. Both scripts
     * clamp with max(0, onset - WINDOW_BEFORE) and min(n, onset +
     * WINDOW_AFTER), so a clap near either end simply yields a SHORTER window
     * and numpy re-derives the FFT length from it. Here the FFT length is
     * fixed at LOC_FFT_LEN and the buffers are sized for it, so a short window
     * is not an option; the window slides instead of shrinking.
     *
     * This is a live case, not a corner case: capture is clap-triggered, so
     * the onset is always inside the first frame and lands below sample 256
     * whenever the clap trips the threshold early in that frame. When it does,
     * the board analyses samples 0..2047 while the Python would analyse
     * 0..onset+1792. Both see the whole transient, so the delays agree closely,
     * but they are not bit-identical in that case. window_start/window_end in
     * the result report exactly what was used, so a comparison run can tell.
     */
    uint32_t start;
    if (out->onset >= (uint32_t)LOC_WINDOW_BEFORE) {
        start = out->onset - LOC_WINDOW_BEFORE;
    } else {
        start = 0;
    }
    if (start + LOC_WINDOW_LEN > n_samples) {
        start = n_samples - LOC_WINDOW_LEN;
    }
    out->window_start = start;
    out->window_end   = start + LOC_WINDOW_LEN;

    /*
     * Six pair delays, and the least squares system built as we go.
     *
     * GccPhat_Estimate returns (t_a - t_b). Everything downstream, and the
     * Python, stores delays as (t_j - t_i), hence the negation. Get this sign
     * wrong and the bearing comes out 180 degrees off, which is exactly the
     * kind of error that looks like a wiring mistake.
     */
    float ata_xx = 0.0f, ata_xy = 0.0f, ata_yy = 0.0f;   /* A'A */
    float atb_x  = 0.0f, atb_y  = 0.0f;                  /* A'b */

    for (int p = 0; p < LOC_NUM_PAIRS; p++) {
        int i, j;
        Geom_Pair(p, &i, &j);

        const float max_tau = Geom_MaxTauSamples(layout, i, j);
        const float tau = -GccPhat_Estimate(&channels[i][start],
                                            &channels[j][start],
                                            max_tau);

        out->pair_delay[p]   = tau;
        out->pair_max_tau[p] = max_tau;
        /* Small tolerance so a delay sitting exactly at the physical limit,
           which a source directly on that baseline legitimately produces,
           is not flagged by float rounding alone. */
        out->pair_exceeds_physics[p] = (fabsf(tau) > max_tau + 0.5f) ? 1 : 0;

        /* Row of A is (pos_i - pos_j); note the order, it matches the model
           above and the Python's estimate_direction(). Right-hand side is the
           delay converted from samples to metres of path difference. */
        const float bx = layout->pos[i][0] - layout->pos[j][0];
        const float by = layout->pos[i][1] - layout->pos[j][1];
        const float rhs = tau * LOC_METRES_PER_SAMPLE;

        ata_xx += bx * bx;
        ata_xy += bx * by;
        ata_yy += by * by;
        atb_x  += bx * rhs;
        atb_y  += by * rhs;
    }

    out->worst_triangle_residual = worst_triangle_residual(out->pair_delay);

    /* Solve the 2x2 normal equations by hand. */
    const float det = ata_xx * ata_yy - ata_xy * ata_xy;
    if (fabsf(det) < 1e-20f) {
        out->status = LOC_ERR_SINGULAR;
        return out->status;
    }
    const float ux = ( ata_yy * atb_x - ata_xy * atb_y) / det;
    const float uy = (-ata_xy * atb_x + ata_xx * atb_y) / det;

    /* u should come out unit length but noise makes it drift, and only its
       direction carries information, so take the angle and discard the
       magnitude. Wrapped to 0..360 to match how the Python reports. */
    float deg = atan2f(uy, ux) * (180.0f / (float)M_PI);
    if (deg < 0.0f) deg += 360.0f;
    out->bearing_deg = deg;

    out->status = LOC_OK;
    return out->status;
}


void Localize_Report(const loc_result_t *result)
{
    const array_layout_t *layout = Geom_Active();
    geom_info_t info;
    Geom_Describe(layout, &info);

    /* Separate buffers per call site: several values share one printf. */
    char a[24], b[24], c[24], d[24];

    printf("\r\n--- localization ---\r\n");
    printf("array %s  span %s x %s cm  aperture %s cm (%s samples)\r\n",
           layout->name,
           f2s(a, sizeof a, info.span_x * 100.0f, 2),
           f2s(b, sizeof b, info.span_y * 100.0f, 2),
           f2s(c, sizeof c, info.aperture_m * 100.0f, 2),
           f2s(d, sizeof d, info.aperture_samples, 2));
    printf("  rank %d of 2, condition number %s\r\n",
           info.rank, f2s(a, sizeof a, info.cond, 2));

    if (!layout->measured) {
        printf("  NOTE: this layout is nominal, not calipered. Bearings carry "
               "the dimension error.\r\n");
    }
    if (info.cond > LOC_POOR_COND) {
        printf("  WARNING: condition number above %s, so some bearings are "
               "much less accurate than others.\r\n",
               f2s(a, sizeof a, LOC_POOR_COND, 2));
    }

    if (result->status != LOC_OK) {
        printf("FAILED: %s\r\n", Localize_StatusText(result->status));
        return;
    }

    printf("transient at %lu, onset %lu, peak/noise %s\r\n",
           (unsigned long)result->peak, (unsigned long)result->onset,
           f2s(a, sizeof a, result->snr_ratio, 2));
    if (result->weak_transient) {
        printf("  WARNING: weak transient (below %s). Clap harder or "
               "closer; delays from this capture will be noisy.\r\n",
               f2s(a, sizeof a, LOC_WEAK_SNR, 2));
    }

    printf("window %lu..%lu (%d samples)\r\n",
           (unsigned long)result->window_start,
           (unsigned long)result->window_end, LOC_WINDOW_LEN);

    printf("  pair   delay (samples)   max physical\r\n");
    for (int p = 0; p < LOC_NUM_PAIRS; p++) {
        int i, j;
        Geom_Pair(p, &i, &j);
        printf("  %d-%d      %9s        %7s%s\r\n",
               i, j,
               f2s(a, sizeof a, result->pair_delay[p], 3),
               f2s(b, sizeof b, result->pair_max_tau[p], 2),
               result->pair_exceeds_physics[p] ? "   EXCEEDS PHYSICS" : "");
    }

    printf("worst triangle residual %s samples%s\r\n",
           f2s(a, sizeof a, result->worst_triangle_residual, 3),
           (result->worst_triangle_residual > 0.3f)
               ? "   (inconsistent: suspect a reflection)" : "");

    printf("BEARING %s deg\r\n", f2s(a, sizeof a, result->bearing_deg, 2));
    printf("  (counterclockwise from +x, which points toward the mic1/mic3\r\n"
           "   edge; 90 deg is off the mic0/mic1 edge)\r\n");
    printf("--- end ---\r\n");
}
