/* array_geometry.c - the layout table and geometric health checks.
 *
 * Firmware mirror of mic_sims_files/array_geometry.py. If you edit the
 * dimensions here, edit them there too (and vice versa), or the board and the
 * offline analysis will disagree about where the mics are while both look
 * perfectly self-consistent.
 */
#include "array_geometry.h"

#include <math.h>

/* Measured dimensions of the built array, metres. Left-to-right span and
   top-to-bottom span. These two numbers are the ones to change if you
   re-measure or re-space the current build; everything downstream follows.
   Same values as BUILT_WIDTH_X / BUILT_HEIGHT_Y in array_geometry.py. */
#define BUILT_WIDTH_X    0.0925f   /* 9.25 cm, mic0<->mic1, ruler */
#define BUILT_HEIGHT_Y   0.0990f   /* 9.90 cm, mic0<->mic2, ruler */

/* Corner positions of a rectangle centred on the origin, in the physical
   labelling mic0 top-left, mic1 top-right, mic2 bottom-left, mic3
   bottom-right. Written out rather than computed so the table stays a plain
   initialiser you can read at a glance. RECT_* mirrors rect() in the Python. */
#define RECT(w, h)  { { -(w) / 2.0f,  (h) / 2.0f },   /* mic0 top-left     */ \
                      {  (w) / 2.0f,  (h) / 2.0f },   /* mic1 top-right    */ \
                      { -(w) / 2.0f, -(h) / 2.0f },   /* mic2 bottom-left  */ \
                      {  (w) / 2.0f, -(h) / 2.0f } }  /* mic3 bottom-right */

/* Named layouts. Order MUST match the enum in array_geometry.h.
   The superseded 2.8x10 single-board rectangle from the Python registry is
   deliberately not carried over: it has four blind cones and there is no
   reason to be able to select it by accident on hardware. */
static const array_layout_t kLayouts[GEOM_LAYOUT_COUNT] = {
    [GEOM_9_25X9_9_MEASURED] = {
        .name     = "9.25x9.9-measured",
        .pos      = RECT(BUILT_WIDTH_X, BUILT_HEIGHT_Y),
        .measured = 1,
        .note     = "THE BUILT ARRAY, calipered port to port. Near-square, "
                    "no blind directions.",
    },
    [GEOM_9_25X10_NOMINAL] = {
        .name     = "9.25x10-nominal",
        .pos      = RECT(0.100f, 0.0925f),
        .measured = 0,
        .note     = "Build target, nominal numbers. Most uniform option.",
    },
    [GEOM_9_25X12_NOMINAL] = {
        .name     = "9.25x12-nominal",
        .pos      = RECT(0.120f, 0.0925f),
        .measured = 0,
        .note     = "Stretch goal. Longer aperture, still no blind cones.",
    },
    [GEOM_9_25X16_NOMINAL] = {
        .name     = "9.25x16-nominal",
        .pos      = RECT(0.160f, 0.0925f),
        .measured = 0,
        .note     = "Full board length. Best simulated accuracy, most "
                    "spatial aliasing risk in a real room.",
    },
    [GEOM_10CM_SQUARE_REFERENCE] = {
        .name     = "10cm-square-reference",
        .pos      = RECT(0.100f, 0.100f),
        .measured = 0,
        .note     = "The geometry localization_sim.py is validated against. "
                    "Select this to compare the port against the reference.",
    },
};

/* The six unique pairs, in the same order as the Python PAIRS list. */
static const int kPairs[LOC_NUM_PAIRS][2] = {
    { 0, 1 }, { 0, 2 }, { 0, 3 }, { 1, 2 }, { 1, 3 }, { 2, 3 },
};


const array_layout_t *Geom_Active(void)
{
    return &kLayouts[GEOM_ACTIVE];
}


const array_layout_t *Geom_Get(int index)
{
    if (index < 0 || index >= GEOM_LAYOUT_COUNT) return 0;
    return &kLayouts[index];
}


void Geom_Pair(int pair_index, int *mic_i, int *mic_j)
{
    if (pair_index < 0 || pair_index >= LOC_NUM_PAIRS) {
        *mic_i = 0;
        *mic_j = 0;
        return;
    }
    *mic_i = kPairs[pair_index][0];
    *mic_j = kPairs[pair_index][1];
}


float Geom_Spacing(const array_layout_t *layout, int mic_i, int mic_j)
{
    const float dx = layout->pos[mic_i][0] - layout->pos[mic_j][0];
    const float dy = layout->pos[mic_i][1] - layout->pos[mic_j][1];
    return sqrtf(dx * dx + dy * dy);
}


float Geom_MaxTauSamples(const array_layout_t *layout, int mic_i, int mic_j)
{
    return Geom_Spacing(layout, mic_i, mic_j) / LOC_METRES_PER_SAMPLE;
}


/*
 * Geometric health, the C counterpart of describe() in array_geometry.py.
 *
 * Build the same 6x2 baseline matrix the least squares fit solves, where row
 * p is (pos_i - pos_j) for pair p, and ask two questions about it:
 *
 *   rank  - must be 2. A collinear array is rank 1: every baseline is
 *           parallel, the across-axis component of the direction vector is
 *           unconstrained, and the reported angle collapses to 0 or 180
 *           regardless of truth. Localize_Run refuses to answer in that case.
 *   cond  - ratio of the singular values. Near 1 means accuracy is uniform in
 *           every direction. Large means narrow bearings where error blows up.
 *
 * numpy gets the singular values from an SVD. Here the matrix is only 6x2, so
 * the singular values of A are the square roots of the eigenvalues of the 2x2
 * symmetric matrix A'A, which has a closed form. Same answer, no iteration,
 * about twenty lines.
 */
void Geom_Describe(const array_layout_t *layout, geom_info_t *out)
{
    float sxx = 0.0f, sxy = 0.0f, syy = 0.0f;   /* entries of A'A */

    for (int p = 0; p < LOC_NUM_PAIRS; p++) {
        const int i = kPairs[p][0];
        const int j = kPairs[p][1];
        const float bx = layout->pos[i][0] - layout->pos[j][0];
        const float by = layout->pos[i][1] - layout->pos[j][1];
        sxx += bx * bx;
        sxy += bx * by;
        syy += by * by;
    }

    /* Eigenvalues of [[sxx, sxy], [sxy, syy]]. Both are real and >= 0 because
       A'A is symmetric positive semi-definite. */
    const float trace = sxx + syy;
    const float diff  = sxx - syy;
    const float root  = sqrtf(diff * diff + 4.0f * sxy * sxy);
    float lam_hi = 0.5f * (trace + root);
    float lam_lo = 0.5f * (trace - root);
    if (lam_lo < 0.0f) lam_lo = 0.0f;           /* clamp rounding noise */

    const float s_hi = sqrtf(lam_hi);
    const float s_lo = sqrtf(lam_lo);

    /* Same relative tolerance idea numpy's matrix_rank uses: a singular value
       counts only if it is not negligible next to the largest one. */
    const float tol = 1e-6f * s_hi;
    out->rank = 0;
    if (s_hi > tol) out->rank++;
    if (s_lo > tol) out->rank++;

    out->cond = (s_lo > 1e-12f) ? (s_hi / s_lo) : INFINITY;

    /* Aperture: the widest mic-to-mic distance, and what that is worth in
       samples of delay. This is the largest lag any pair can legitimately
       produce, which is what bounds the GCC-PHAT search. */
    float widest = 0.0f;
    for (int p = 0; p < LOC_NUM_PAIRS; p++) {
        const float d = Geom_Spacing(layout, kPairs[p][0], kPairs[p][1]);
        if (d > widest) widest = d;
    }
    out->aperture_m       = widest;
    out->aperture_samples = widest / LOC_METRES_PER_SAMPLE;

    float xmin = layout->pos[0][0], xmax = layout->pos[0][0];
    float ymin = layout->pos[0][1], ymax = layout->pos[0][1];
    for (int m = 1; m < LOC_NUM_MICS; m++) {
        if (layout->pos[m][0] < xmin) xmin = layout->pos[m][0];
        if (layout->pos[m][0] > xmax) xmax = layout->pos[m][0];
        if (layout->pos[m][1] < ymin) ymin = layout->pos[m][1];
        if (layout->pos[m][1] > ymax) ymax = layout->pos[m][1];
    }
    out->span_x = xmax - xmin;
    out->span_y = ymax - ymin;
}
