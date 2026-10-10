"""Read beat grids and waveforms straight from Rekordbox analysis (ANLZ) files.

Only the local files Rekordbox uses on this computer are read (share/PIONEER/USBANLZ),
never exports on USB drives. Nothing here writes to them.
"""

import bisect
from dataclasses import dataclass
from pathlib import Path

import numpy as np

WAVEFORM_POINTS_PER_SECOND = 150
ONSET_WINDOW_MS = 100
MIN_ONSET_BEATS = 16


def iter_sections(data):
    """Yield (fourcc, start, len_header, len_tag) for every section of an analysis file."""
    if data[:4] != b"PMAI":
        return
    end = min(int.from_bytes(data[8:12], "big"), len(data))
    i = int.from_bytes(data[4:8], "big")
    while i + 12 <= end:
        len_header = int.from_bytes(data[i + 4 : i + 8], "big")
        len_tag = int.from_bytes(data[i + 8 : i + 12], "big")
        if len_tag <= 0:
            return
        yield data[i : i + 4].decode("ascii", errors="replace"), i, len_header, len_tag
        i += len_tag


def _section(data, fourcc):
    for code, start, len_header, len_tag in iter_sections(data):
        if code == fourcc:
            return start, len_header, len_tag
    return None


def anlz_paths(share_dir, analysis_data_path):
    """Local .DAT, .EXT and .2EX paths for a track, or None where missing."""
    if not analysis_data_path:
        return None, None, None
    dat = Path(share_dir) / analysis_data_path.strip("\\/")
    ext = dat.with_suffix(".EXT")
    twoex = dat.with_suffix(".2EX")
    return (
        dat if dat.is_file() else None,
        ext if ext.is_file() else None,
        twoex if twoex.is_file() else None,
    )


@dataclass
class BeatGrid:
    times: list  # ms
    bpms: list
    beats: list  # position in the bar, 1-4

    def __len__(self):
        return len(self.times)

    def nearest(self, t):
        """Index of the beat closest to time t (ms)."""
        i = bisect.bisect_left(self.times, t)
        if i == 0:
            return 0
        if i >= len(self.times):
            return len(self.times) - 1
        return i if self.times[i] - t < t - self.times[i - 1] else i - 1

    def beat_length(self, t):
        """Length of one beat in ms around time t."""
        i = self.nearest(t)
        if 0 < i < len(self.times):
            return self.times[i] - self.times[i - 1]
        if len(self.times) > 1:
            return self.times[1] - self.times[0]
        bpm = self.bpms[0] if self.bpms else 120
        return 60000 / bpm


def read_beat_grid(dat_path):
    """The PQTZ beat grid from a .DAT file, or None."""
    data = Path(dat_path).read_bytes()
    found = _section(data, "PQTZ")
    if not found:
        return None
    start, _len_header, len_tag = found
    count = int.from_bytes(data[start + 20 : start + 24], "big")
    if count == 0 or 24 + count * 8 > len_tag:
        return None
    entries = np.frombuffer(
        data, dtype=[("beat", ">u2"), ("tempo", ">u2"), ("time", ">u4")], count=count, offset=start + 24
    )
    return BeatGrid(
        times=entries["time"].astype(float).tolist(),
        bpms=(entries["tempo"] / 100).tolist(),
        beats=entries["beat"].astype(int).tolist(),
    )


@dataclass
class Waveform:
    heights: np.ndarray  # 0-31, one point per 1/150 s
    colors: np.ndarray  # (n, 3) RGB, 0-255
    bands: np.ndarray = None  # PWV7 detail (n, 3) low/mid/high
    overview: np.ndarray = None  # PWV6 whole-track preview, usually 1200 columns

    def index(self, t):
        return int(t * WAVEFORM_POINTS_PER_SECOND / 1000)

    def time(self, i):
        return i * 1000 / WAVEFORM_POINTS_PER_SECOND


def _read_pwv5(path):
    data = Path(path).read_bytes()
    found = _section(data, "PWV5")
    if not found:
        return None
    start, len_header, len_tag = found
    count = int.from_bytes(data[start + 16 : start + 20], "big")
    count = min(count, (len_tag - len_header) // 2)
    raw = np.frombuffer(data, dtype=">u2", count=count, offset=start + len_header).astype(np.int32)
    heights = (raw >> 2) & 0x1F
    colors = np.stack([(raw >> 13) & 7, (raw >> 10) & 7, (raw >> 7) & 7], axis=1) * 36
    return heights, colors.astype(np.uint8)


def _read_band_tag(path, fourcc):
    """3-byte columns [low, mid, high] from a PWV6 or PWV7 tag."""
    data = Path(path).read_bytes()
    found = _section(data, fourcc)
    if not found:
        return None
    start, len_header, len_tag = found
    count = int.from_bytes(data[start + 16 : start + 20], "big")
    available = max(0, len_tag - len_header)
    count = min(count, available // 3) if count else available // 3
    if count < 1:
        return None
    raw = np.frombuffer(data, dtype=np.uint8, count=count * 3, offset=start + len_header)
    return raw.reshape(-1, 3).astype(np.int16)


def _read_three_band(path):
    """PWV7 detail: 150 columns/sec. Not the 1200-column PWV6 overview."""
    return _read_band_tag(path, "PWV7")


def read_waveform(ext_path, twoex_path=None):
    """Colour detail waveform, plus Rekordbox 3-band overview/detail when a .2EX exists."""
    color = _read_pwv5(ext_path) if ext_path else None
    bands = None
    overview = None
    if twoex_path:
        try:
            bands = _read_band_tag(twoex_path, "PWV7")
        except Exception:
            bands = None
        try:
            overview = _read_band_tag(twoex_path, "PWV6")
        except Exception:
            overview = None
    if color is None and bands is None and overview is None:
        return None
    if bands is not None:
        heights = bands.max(axis=1)
        colors = color[1] if color is not None and len(color[1]) == len(heights) else np.zeros((len(heights), 3), dtype=np.uint8)
        return Waveform(heights=heights, colors=colors, bands=bands, overview=overview)
    if color is not None:
        heights, colors = color
        return Waveform(heights=heights, colors=colors, overview=overview)
    heights = overview.max(axis=1)
    return Waveform(heights=heights, colors=np.zeros((len(heights), 3), dtype=np.uint8), overview=overview)


def onset_offset(grid, waveform):
    """Median distance (ms) from grid beats to the nearest sharp rise in the waveform.

    Positive means the hits come after the grid. None when there are too few clear hits.
    """
    if grid is None or waveform is None or len(grid) < MIN_ONSET_BEATS:
        return None
    h = waveform.heights.astype(float)
    rise = np.maximum(np.diff(h, prepend=h[0]), 0)
    window = int(ONSET_WINDOW_MS * WAVEFORM_POINTS_PER_SECOND / 1000)
    offsets = []
    for t in grid.times:
        center = waveform.index(t)
        lo, hi = max(center - window, 1), min(center + window + 1, len(rise))
        if hi - lo < window:
            continue
        segment = rise[lo:hi]
        peak = int(np.argmax(segment))
        if segment[peak] < 4:
            continue
        offsets.append(waveform.time(lo + peak) - t)
    if len(offsets) < MIN_ONSET_BEATS:
        return None
    return float(np.median(offsets))
