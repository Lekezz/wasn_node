/* localize.h - turn a finished four-mic capture into a bearing.
 *
 * Firmware port of mic_sims_files/localize_capture.py, built on gcc_phat.c
 * and array_geometry.c. Given the four stored channels it finds the clap,
 * measures the six pair delays, and fits a single arrival direction.
 *
 * Usage:
 *   Localize_Init();                       once at startup
 *   Localize_Run(channels, n, &result);    after a capture completes
 *   Localize_Report(&result);              print it over UART
 *
 * To try a different array orientation, edit GEOM_ACTIVE in array_geometry.h.
 * Nothing in this file needs to change.
 */
#ifndef LOCALIZE_H
#define LOCALIZE_H

#include <stdint.h>

#include "loc_config.h"

/* Why a run produced no usable bearing. */
typedef enum {
    LOC_OK = 0,
    LOC_ERR_NOT_INIT,        /* Localize_Init not called, or FFT unavailable */
    LOC_ERR_COLLINEAR,       /* array is rank 1: no bearing is recoverable   */
    LOC_ERR_SHORT_CAPTURE,   /* fewer samples than the analysis window needs */
    LOC_ERR_SINGULAR         /* least squares matrix not invertible          */
} loc_status_t;

/* Stages timed by the DWT cycle counter when LOC_PROFILE_ENABLE is 1. TOTAL
   is measured around the whole of Localize_Run, so it is slightly more than
   the three parts summed: the difference is the geometry check and the
   window arithmetic, both of which are too small to be worth their own
   timer. Keep this in step with kStageName[] in localize.c. */
typedef enum {
    LOC_STAGE_FIND_CLAP = 0,
    LOC_STAGE_GCC_PHAT,
    LOC_STAGE_FIT,
    LOC_STAGE_TOTAL,
    LOC_STAGE_COUNT
} loc_stage_t;

typedef struct {
    loc_status_t status;

    float bearing_deg;                    /* 0..360, ccw from +x */

    /* Per-pair delays in samples, as (t_j - t_i), pair order matching
       Geom_Pair(): (0,1)(0,2)(0,3)(1,2)(1,3)(2,3). */
    float pair_delay[LOC_NUM_PAIRS];
    /* Largest delay physics allows for that pair. A measured delay above this
       means the estimate found a spurious peak, usually a reflection. */
    float pair_max_tau[LOC_NUM_PAIRS];
    int   pair_exceeds_physics[LOC_NUM_PAIRS];

    /* Where the clap was found, and how strong it was. */
    uint32_t onset;
    uint32_t peak;
    float    snr_ratio;                   /* envelope peak / envelope median */
    int      weak_transient;              /* snr_ratio < LOC_WEAK_SNR */

    /* Window actually analysed, after clamping to the capture bounds. */
    uint32_t window_start;
    uint32_t window_end;

    /* Largest residual of the plane-wave consistency check, in samples. Every
       triangle of delays must close: d(i,j) + d(j,k) should equal d(i,k). A
       large value means one pair disagrees with the other five, which is the
       signature of a reflection corrupting that pair. */
    float worst_triangle_residual;
} loc_result_t;

/* Prepare the FFT and validate the active geometry. Returns 1 on success.
   On failure Localize_Run will return the matching error status. */
int Localize_Init(void);

/*
 * Estimate the bearing of the clap in a finished capture.
 *
 * channels[m] points at n_samples int16 samples for mic m, in mic order,
 * exactly as capture.c stores them. The data is read, not modified.
 * Fills *out. Returns out->status for convenience.
 */
loc_status_t Localize_Run(const int16_t *const channels[LOC_NUM_MICS],
                          uint32_t n_samples, loc_result_t *out);

/* Print a human-readable report over the BSP UART, in roughly the same shape
   localize_capture.py prints, so the two are easy to compare side by side. */
void Localize_Report(const loc_result_t *result);

/* One-line description of a status code. */
const char *Localize_StatusText(loc_status_t status);

#endif /* LOCALIZE_H */
