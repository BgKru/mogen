"""Deterministic image-quality metrics implemented with NumPy and Pillow.

The worker images do not ship a Python OpenCV build: the scene image only has
the C++ COLMAP/OpenMVS OpenCV libraries and the object image has no OpenCV at
all. Adding ``opencv-python`` would introduce a second, differently pinned
NumPy/FFmpeg dependency into both ML images, so the metrics below are
implemented directly. Each algorithm is documented here and recorded by name in
the analysis report (``analyzer.metrics.ALGORITHMS``).

All functions accept arrays produced by :func:`luminance_array`,
:func:`bound_rgb` or :func:`normalized_gray`; none of them reads a file, writes
an image or mutates the caller's pixels. Values are expressed in 8-bit intensity
units (0-255) unless stated otherwise.
"""

from __future__ import annotations

import math

import numpy as np
from PIL import Image

# ITU-R BT.601 luma weights, the same conversion Pillow uses for ``mode="L"``.
_LUMA_RED = 0.299
_LUMA_GREEN = 0.587
_LUMA_BLUE = 0.114

_HASH_GRID = 8
_HASH_INPUT = 32
_SSIM_WINDOW = 8
_SSIM_C1 = (0.01 * 255.0) ** 2
_SSIM_C2 = (0.03 * 255.0) ** 2


def _dct_matrix(size: int) -> np.ndarray:
    """Return an orthonormal DCT-II matrix of ``size`` rows."""
    indices = np.arange(size, dtype=np.float64)
    frequencies = indices.reshape(-1, 1)
    matrix = np.cos(np.pi * (2.0 * indices + 1.0) * frequencies / (2.0 * size))
    matrix *= math.sqrt(2.0 / size)
    matrix[0, :] = math.sqrt(1.0 / size)
    return matrix


_DCT_32 = _dct_matrix(_HASH_INPUT)


def bound_rgb(image: Image.Image, max_dimension: int) -> Image.Image:
    """Return a bounded RGB analysis copy, never upscaling.

    The longest edge is limited to ``max_dimension`` so exposure and contrast
    analysis stay bounded for very large uploads. The returned image is an
    in-memory copy and is never saved as a replacement for the original.
    """
    if max_dimension < 1:
        message = "max_dimension must be positive"
        raise ValueError(message)
    rgb = image.convert("RGB")
    width, height = rgb.size
    longest = max(width, height)
    if longest <= max_dimension:
        return rgb
    scale = max_dimension / longest
    size = (max(1, round(width * scale)), max(1, round(height * scale)))
    return rgb.resize(size, Image.Resampling.LANCZOS)


def normalized_gray(image: Image.Image, long_edge: int) -> np.ndarray:
    """Return a grayscale array resized so its longest edge is ``long_edge``.

    Blur and noise depend on image scale, so both are measured on this
    normalized copy. Resizing (including small upscales) makes the thresholds
    comparable across image sizes and camera resolutions.
    """
    if long_edge < 2:
        message = "long_edge must be at least 2"
        raise ValueError(message)
    rgb = image.convert("RGB")
    width, height = rgb.size
    scale = long_edge / max(width, height)
    size = (max(1, round(width * scale)), max(1, round(height * scale)))
    resized = rgb.resize(size, Image.Resampling.LANCZOS)
    return luminance_array(resized)


def square_gray(image: Image.Image, edge: int) -> np.ndarray:
    """Return an exactly ``edge x edge`` grayscale array.

    Perceptual hashing and candidate SSIM compare the whole frame, so the
    aspect ratio is intentionally not preserved here (this is the standard
    pHash preprocessing step). Shape-only resizing keeps the comparison cheap
    and deterministic; it is not used for the technical metrics.
    """
    if edge < 2:
        message = "edge must be at least 2"
        raise ValueError(message)
    rgb = image.convert("RGB").resize((edge, edge), Image.Resampling.LANCZOS)
    return luminance_array(rgb)


def luminance_array(rgb: Image.Image) -> np.ndarray:
    """Return a float64 luminance array (ITU-R BT.601) for an RGB image."""
    pixels = np.asarray(rgb.convert("RGB"), dtype=np.float64)
    return pixels[..., 0] * _LUMA_RED + pixels[..., 1] * _LUMA_GREEN + pixels[..., 2] * _LUMA_BLUE


def laplacian_variance(gray: np.ndarray) -> float:
    """Return the variance of the 4-neighbour Laplacian response.

    The metric is the classic focus measure: sharp edges produce a high
    response, while a blurred or out-of-focus photograph produces a low one.
    It is computed on the interior of the normalized grayscale copy, so the
    threshold is resolution-independent (11 Section 5.1).
    """
    if gray.ndim != 2 or min(gray.shape) < 3:
        message = "a Laplacian variance needs a grayscale image of at least 3x3"
        raise ValueError(message)
    response = (
        gray[:-2, 1:-1] + gray[2:, 1:-1] + gray[1:-1, :-2] + gray[1:-1, 2:] - 4.0 * gray[1:-1, 1:-1]
    )
    return float(np.var(response))


def immerkaer_noise(gray: np.ndarray) -> float:
    """Return the Immerkær fast noise estimate as an intensity standard deviation.

    The estimator convolves the image with
    ``[[1, -2, 1], [-2, 4, -2], [1, -2, 1]]`` and scales the mean absolute
    response by ``sqrt(pi / 2) / 6``. It is a documented high-frequency energy
    estimate, not a proof of sensor noise: genuine fine texture also raises it,
    which is why the default threshold is conservative and the finding is
    advisory (11 Section 5.1).
    """
    if gray.ndim != 2 or min(gray.shape) < 3:
        message = "a noise estimate needs a grayscale image of at least 3x3"
        raise ValueError(message)
    response = (
        4.0 * gray[1:-1, 1:-1]
        - 2.0 * gray[1:-1, :-2]
        - 2.0 * gray[1:-1, 2:]
        - 2.0 * gray[:-2, 1:-1]
        - 2.0 * gray[2:, 1:-1]
        + gray[:-2, :-2]
        + gray[:-2, 2:]
        + gray[2:, :-2]
        + gray[2:, 2:]
    )
    return math.sqrt(math.pi / 2.0) * float(np.mean(np.abs(response))) / 6.0


def luminance_stats(
    gray: np.ndarray,
    *,
    shadow_level: int,
    highlight_level: int,
) -> dict[str, float]:
    """Return mean, dispersion, percentile range and clipping ratios.

    Values are 0-255 intensities; ratios are fractions of all analysed pixels.
    The 5th/95th percentiles are used instead of min/max so a handful of
    extreme pixels does not hide an otherwise flat photograph.
    """
    if gray.size == 0:
        message = "luminance statistics need at least one pixel"
        raise ValueError(message)
    low_percentile, high_percentile = np.percentile(gray, (5.0, 95.0))
    return {
        "mean_luminance": float(gray.mean()),
        "luminance_std": float(gray.std()),
        "luminance_p05": float(low_percentile),
        "luminance_p95": float(high_percentile),
        "contrast_range": float(high_percentile - low_percentile),
        "shadow_clipped_ratio": float(np.count_nonzero(gray <= shadow_level)) / gray.size,
        "highlight_clipped_ratio": float(np.count_nonzero(gray >= highlight_level)) / gray.size,
    }


def perceptual_hash(gray: np.ndarray) -> int:
    """Return a 63-bit DCT perceptual hash for a 32x32 grayscale array.

    Coefficients are DCT-II transformed, the low-frequency 8x8 block (minus the
    DC term) is kept and each coefficient is compared with the block median.
    Resizing or recompressing a photograph changes the hash by only a few bits,
    which makes it a cheap candidate generator (11 Section 5.2).
    """
    if gray.ndim != 2 or gray.shape != (_HASH_INPUT, _HASH_INPUT):
        message = f"a perceptual hash needs a {_HASH_INPUT}x{_HASH_INPUT} grayscale image"
        raise ValueError(message)
    coefficients = _DCT_32 @ gray @ _DCT_32.T
    # A constant image produces numerically tiny non-DC coefficients
    # (~1e-13); rounding them keeps a flat frame's hash stable instead of
    # turning floating-point noise into bits.
    low = np.round(coefficients[:_HASH_GRID, :_HASH_GRID].ravel()[1:], 9)
    median = float(np.median(low))
    value = 0
    for coefficient in low:
        value = (value << 1) | int(coefficient > median)
    return value


def hamming_distance(left: int, right: int) -> int:
    """Return the number of differing bits between two perceptual hashes."""
    return int(left ^ right).bit_count()


def _box_mean(array: np.ndarray, window: int) -> np.ndarray:
    """Return the uniform-window mean of every position, using an integral image."""
    pad = window // 2
    padded = np.pad(array, ((pad, window - 1 - pad), (pad, window - 1 - pad)), mode="reflect")
    integral = padded.cumsum(axis=0).cumsum(axis=1)
    integral = np.pad(integral, ((1, 0), (1, 0)))
    total = (
        integral[window:, window:]
        - integral[:-window, window:]
        - integral[window:, :-window]
        + integral[:-window, :-window]
    )
    return total / float(window * window)


def structural_similarity(left: np.ndarray, right: np.ndarray) -> float:
    """Return the mean SSIM of two equally sized grayscale arrays.

    A uniform 8x8 window is used. The value is in ``[-1, 1]`` and is close to
    ``1`` for a resized or recompressed copy of the same photograph. It is only
    computed for perceptual-hash candidates, never for every pair
    (11 Section 5.2).
    """
    if left.shape != right.shape or left.ndim != 2 or min(left.shape) < _SSIM_WINDOW:
        message = "SSIM needs two equally sized grayscale images at least 8x8"
        raise ValueError(message)
    mu_left = _box_mean(left, _SSIM_WINDOW)
    mu_right = _box_mean(right, _SSIM_WINDOW)
    mu_left_sq = mu_left * mu_left
    mu_right_sq = mu_right * mu_right
    mu_product = mu_left * mu_right
    sigma_left = _box_mean(left * left, _SSIM_WINDOW) - mu_left_sq
    sigma_right = _box_mean(right * right, _SSIM_WINDOW) - mu_right_sq
    sigma_product = _box_mean(left * right, _SSIM_WINDOW) - mu_product
    numerator = (2.0 * mu_product + _SSIM_C1) * (2.0 * sigma_product + _SSIM_C2)
    denominator = (mu_left_sq + mu_right_sq + _SSIM_C1) * (sigma_left + sigma_right + _SSIM_C2)
    ssim_map = numerator / denominator
    border = _SSIM_WINDOW // 2
    if border:
        ssim_map = ssim_map[border:-border, border:-border]
    return float(np.mean(ssim_map))


def aspect_ratio(width: int, height: int) -> float:
    """Return ``width / height``, raising for invalid dimensions."""
    if width < 1 or height < 1:
        message = "aspect ratio needs positive dimensions"
        raise ValueError(message)
    return width / height


ALGORITHMS: dict[str, str] = {
    "blur": (
        "variance_of_laplacian(4-neighbour, grayscale ITU-R BT.601, "
        "long edge normalized with LANCZOS)"
    ),
    "exposure": "luminance_histogram(ITU-R BT.601, bounded analysis copy)",
    "contrast": "p95_minus_p5_luminance(ITU-R BT.601, bounded analysis copy)",
    "noise": "immerkaer_high_frequency_sigma(grayscale, normalized long edge)",
    "perceptual_hash": "dct_phash_63bit(low_frequency_8x8_median)",
    "near_duplicate_similarity": "ssim_uniform_8x8(grayscale, common square size)",
}


__all__ = [
    "ALGORITHMS",
    "aspect_ratio",
    "bound_rgb",
    "hamming_distance",
    "immerkaer_noise",
    "laplacian_variance",
    "luminance_array",
    "luminance_stats",
    "normalized_gray",
    "perceptual_hash",
    "square_gray",
    "structural_similarity",
]
