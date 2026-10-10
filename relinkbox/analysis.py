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
    """Paths of the .DAT and .EXT files for a track's AnalysisDataPath, or None where missing."""
    if not analysis_data_path:
        return None, None
    dat = Path(share_dir) / analysis_data_path.strip("\\/")
    ext = dat.with_suffix(".EXT")
    return (dat if dat.is_file() else None), (ext if ext.is_file() else None)


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

    def index(self, t):
        return int(t * WAVEFORM_POINTS_PER_SECOND / 1000)

    def time(self, i):
        return i * 1000 / WAVEFORM_POINTS_PER_SECOND


def read_waveform(ext_path):
    """The PWV5 colour detail waveform from an .EXT file, or None."""
    data = Path(ext_path).read_bytes()
    found = _section(data, "PWV5")
    if not found:
        return None
    start, len_header, len_tag = found
    count = int.from_bytes(data[start + 16 : start + 20], "big")
    count = min(count, (len_tag - len_header) // 2)
    raw = np.frombuffer(data, dtype=">u2", count=count, offset=start + len_header).astype(np.int32)
    heights = (raw >> 2) & 0x1F
    colors = np.stack([(raw >> 13) & 7, (raw >> 10) & 7, (raw >> 7) & 7], axis=1) * 36
    return Waveform(heights=heights, colors=colors.astype(np.uint8))


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
