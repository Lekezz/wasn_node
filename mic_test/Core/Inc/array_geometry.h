/* array_geometry.h - where the microphones physically are.
 *
 * Firmware mirror of mic_sims_files/array_geometry.py. Same idea: one place
 * defines the layout, everything else asks this module, so trying a new
 * orientation is a one-line edit rather than a hunt through the codebase.
 *
 * TO CHANGE ORIENTATION: edit GEOM_ACTIVE below to another entry in the
 * table in array_geometry.c. To add a layout, add a row to that table. You
 * should not need to touch any other file.
 *
 * Coordinates are metres, (x, y) per mic, in mic order 0..3, matching the
 * physical build:
 *
 *     +y
 *      ^   mic0 .          . mic1     (top)
 *      |
 *      +---> +x
 *          mic2 .          . mic3     (bottom)
 *
 * Bearings are degrees counterclockwise from +x, so 0 deg is off the right
 * edge (toward mic1/mic3) and 90 deg is off the top edge (toward mic0/mic1).
 *
 * The row order is not cosmetic. capture.c always emits channels in the order
 * mic0..mic3, and this module assigns position[m] to channel m, so the mic
 * physically at top-left MUST be the one wired as channel 0 (PE7, SEL=GND,
 * per the mic map in CLAUDE.md). Get it wrong and every bearing comes out
 * reflected even though all six delays are correct.
 */
#ifndef ARRAY_GEOMETRY_H
#define ARRAY_GEOMETRY_H

#include "loc_config.h"

typedef struct {
    const char *name;                        /* matches the Python key */
    float       pos[LOC_NUM_MICS][2];        /* metres, (x, y) per mic */
    int         measured;                    /* 1 if really measured */
    const char *note;
} array_layout_t;

/* Geometric health of a layout, the C counterpart of describe() in
   array_geometry.py. */
typedef struct {
    int   rank;               /* of the 6x2 baseline matrix; must be 2 */
    float cond;               /* condition number; near 1 is uniform accuracy */
    float aperture_m;         /* widest mic-to-mic distance */
    float aperture_samples;   /* the same, expressed as delay at LOC_FS */
    float span_x;
    float span_y;
} geom_info_t;

/* Index into the layout table in array_geometry.c. THIS IS THE ONE LINE TO
   EDIT when you re-orient or rebuild the array. */
#define GEOM_ACTIVE   GEOM_9_25X9_9_MEASURED

/* Table indices. Keep in sync with kLayouts[] in array_geometry.c. */
enum {
    GEOM_9_25X9_9_MEASURED = 0,
    GEOM_9_25X10_NOMINAL,
    GEOM_9_25X12_NOMINAL,
    GEOM_9_25X16_NOMINAL,
    GEOM_10CM_SQUARE_REFERENCE,
    GEOM_LAYOUT_COUNT
};

/* The layout currently selected by GEOM_ACTIVE. */
const array_layout_t *Geom_Active(void);

/* Any layout by index, for reporting or comparison. NULL if out of range. */
const array_layout_t *Geom_Get(int index);

/* Fill out with the geometric health of a layout. */
void Geom_Describe(const array_layout_t *layout, geom_info_t *out);

/* The six unique mic pairs, in the same order the Python PAIRS list uses:
   (0,1)(0,2)(0,3)(1,2)(1,3)(2,3). Index 0..LOC_NUM_PAIRS-1. */
void Geom_Pair(int pair_index, int *mic_i, int *mic_j);

/* Straight-line distance between two mics, metres. */
float Geom_Spacing(const array_layout_t *layout, int mic_i, int mic_j);

/* Largest delay physics permits for a pair, in samples: spacing / c * FS.
   GCC-PHAT searches only inside this, which kills most spurious peaks. */
float Geom_MaxTauSamples(const array_layout_t *layout, int mic_i, int mic_j);

#endif /* ARRAY_GEOMETRY_H */
