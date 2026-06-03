/**
 * Deterministic ray definitions for the Apex OS login animation.
 *
 * Each entry only carries its angle (degrees clockwise from +X axis) plus
 * visual + timing variation. Geometry/positioning is handled in CSS using
 * `transform: rotate(--angle) scaleX(...)` so the animation stays on the
 * GPU compositor and never triggers paint/layout.
 *
 * Angles are biased toward the X axis (left/right of the "x" wordmark)
 * with a few outliers reaching the corners, mirroring the reference image.
 */

const RAY_ANGLES = [
  -52, -44, -36, -29, -22, -16, -11, -7, -3,
  3, 7, 11, 16, 22, 29, 36, 44, 52,
  128, 136, 144, 151, 158, 164, 169, 173, 177,
  183, 187, 191, 196, 202, 209, 216, 224, 232,
  240, 248, 256, 264, 272, 280, 288, 296, 304,
  312, 320, 328, 336, 344, 352, 360, 368, 376,
  384, 392, 400, 408, 416, 424, 432, 440, 448,
  456, 464, 472, 480, 488, 496, 504, 512, 520,
  528, 536, 544, 552, 560, 568, 576, 584, 592,
  600, 608, 616, 624, 632, 640, 648, 656, 664,
  672, 680, 688, 696, 704, 712, 720, 728, 736,
  744, 752, 760, 768, 776, 784, 792, 800, 808,
  816, 824, 832, 840, 848, 856, 864, 872, 880,
  888, 896, 904, 912, 920, 928, 936, 944, 952,
  960, 968, 976, 984, 992, 1000, 1008, 1016, 1024,
  1032, 1040, 1048, 1056, 1064, 1072, 1080, 1088, 1096,
  1104, 1112, 1120, 1128, 1136, 1144, 1152, 1160, 1168,
];

const STROKE_VARIANTS = [
  { width: 1.4, opacity: 0.55 },
  { width: 1.8, opacity: 0.7 },
  { width: 2.4, opacity: 0.85 },
  { width: 3.2, opacity: 1.0 },
  { width: 1.6, opacity: 0.6 },
  { width: 2.0, opacity: 0.75 },
  { width: 2.8, opacity: 0.9 },
];

export const LOGIN_RAYS = RAY_ANGLES.map((angle, i) => {
  const variant = STROKE_VARIANTS[i % STROKE_VARIANTS.length];
  return {
    id: `ray-${i}`,
    angle,
    width: variant.width,
    opacity: variant.opacity,
    delay: (i * 0.17) % 2.4,
    duration: 2.6 + ((i * 0.13) % 1.4),
  };
});
