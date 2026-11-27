"""Read beat grids and waveforms straight from Rekordbox analysis (ANLZ) files.

Only the local files Rekordbox uses on this computer are used (share/PIONEER/USBANLZ),
never exports on USB drives. The beat grid can be shifted in place. Nothing else is written.
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


class GridShiftError(ValueError):
    """The beat grid cannot be moved by that amount."""


def snapped_ms(grid, ms):
    """The nearest beat to ms, in whole milliseconds. ms itself when there is no grid."""
    if grid is None or len(grid) == 0:
        return int(round(ms))
    return int(round(grid.times[grid.nearest(ms)]))


def shifted_grid(grid, delta_ms):
    """A copy of the grid with every beat moved by delta_ms. Beats that would pass 0 are left out."""
    if grid is None or not delta_ms:
        return grid
    delta = float(delta_ms)
    times, bpms, beats = [], [], []
    for time, bpm, beat in zip(grid.times, grid.bpms, grid.beats):
        moved = time + delta
        if moved < 0:
            continue
        if moved > 0xFFFFFFFF:
            return grid
        times.append(moved)
        bpms.append(bpm)
        beats.append(beat)
    if not times:
        return grid
    return BeatGrid(times=times, bpms=bpms, beats=beats)


def grid_shift_ok(grid, delta_ms):
    """True when the shift keeps at least one beat, and none run past the end of the time field."""
    if grid is None or len(grid) == 0 or not delta_ms:
        return False
    delta = int(round(delta_ms))
    kept = 0
    for time in grid.times:
        moved = time + delta
        if moved > 0xFFFFFFFF:
            return False
        if moved >= 0:
            kept += 1
    return kept > 0


def _add_u32(data, offset, delta, allow_zero=False, clamp_low=False):
    current = int.from_bytes(data[offset : offset + 4], "big")
    if allow_zero and current == 0:
        return
    updated = current + delta
    if updated < 0:
        if not clamp_low:
            raise GridShiftError(f"Moving the grid by {delta:+d} ms would put a beat outside the track.")
        updated = 0
    if updated > 0xFFFFFFFF:
        raise GridShiftError(f"Moving the grid by {delta:+d} ms would put a beat outside the track.")
    data[offset : offset + 4] = int(updated).to_bytes(4, "big")


def _rewrite_pqtz(data, start, len_tag, count, delta):
    """Shift PQTZ beat times. Beats that would pass 0 are removed and the file shrinks."""
    entries_at = start + 24
    kept = bytearray()
    for i in range(count):
        off = entries_at + i * 8
        moved = int.from_bytes(data[off + 4 : off + 8], "big") + delta
        if moved < 0:
            continue
        if moved > 0xFFFFFFFF:
            raise GridShiftError(f"Moving the grid by {delta:+d} ms would put a beat outside the track.")
        kept += data[off : off + 4] + int(moved).to_bytes(4, "big")
    if not kept:
        raise GridShiftError("Moving the grid that far would leave no beats.")
    new_count = len(kept) // 8
    if new_count == count:
        data[entries_at : entries_at + count * 8] = kept
        return data
    removed = (count - new_count) * 8
    extra = data[entries_at + count * 8 : start + len_tag]
    new_len = 24 + len(kept) + len(extra)
    head = bytearray(data[:start])
    prefix = bytearray(data[start:entries_at])
    prefix[8:12] = int(new_len).to_bytes(4, "big")
    prefix[20:24] = int(new_count).to_bytes(4, "big")
    body = head + prefix + kept + extra + data[start + len_tag :]
    total = int.from_bytes(body[8:12], "big") - removed
    body[8:12] = int(total).to_bytes(4, "big")
    return body


def shift_beat_grid(dat_path, delta_ms):
    """Add delta_ms to every beat time in a local .DAT. Tempo and bar positions stay put.

    A positive delta moves the grid later, which is what lines the beats up with late cues.
    Beats that would move before the start of the track are dropped.
    """
    delta = int(round(delta_ms))
    if delta == 0:
        return 0
    path = Path(dat_path)
    data = bytearray(path.read_bytes())
    found = _section(data, "PQTZ")
    if not found:
        raise GridShiftError("This track has no beat grid to move.")
    start, _len_header, len_tag = found
    count = int.from_bytes(data[start + 20 : start + 24], "big")
    if count == 0 or 24 + count * 8 > len_tag:
        raise GridShiftError("This track's beat grid could not be read.")
    extended = _section(data, "PQT2")
    if extended:
        pstart, _header, plen = extended
        if plen >= 40:
            for offset in (28, 36):
                _add_u32(data, pstart + offset, delta, allow_zero=True, clamp_low=True)
    data = _rewrite_pqtz(data, start, len_tag, count, delta)
    tmp = path.parent / (path.name + ".tmp")
    try:
        tmp.write_bytes(data)
        tmp.replace(path)
    except Exception:
        tmp.unlink(missing_ok=True)
        raise
    return delta


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
