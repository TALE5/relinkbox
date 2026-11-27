import numpy as np

from relinkbox.analysis import (
    BeatGrid,
    GridShiftError,
    Waveform,
    grid_shift_ok,
    onset_offset,
    read_beat_grid,
    shift_beat_grid,
    shifted_grid,
    snapped_ms,
)
from relinkbox.gui.waveform import cue_cell_span
from relinkbox.cues import (
    CueInfo,
    TrackCueReport,
    TrackEdit,
    Verdict,
    analyse,
    display_cues,
    draft_cues,
    frames,
    grid_delta_matching_cues,
    kept_overrides,
    mp3_offset_ms,
    snap_action,
    ticked_by_default,
)


def grid(bpm=128.0, beats=400, first=50.0):
    beat = 60000 / bpm
    return BeatGrid(times=[first + i * beat for i in range(beats)], bpms=[bpm] * beats, beats=[i % 4 + 1 for i in range(beats)])


def report(cue_times, path="D:/Music/track.mp3", sample_rate=44100):
    cues = [CueInfo(id=str(i), kind=i, in_ms=int(round(t))) for i, t in enumerate(cue_times)]
    return TrackCueReport(track_id="1", title="T", artist="A", path=path, sample_rate=sample_rate, cues=cues)


def on_beats(g, indexes, offset=0.0):
    return [g.times[i] + offset for i in indexes]


def hits(value):
    return lambda: value


def test_cues_on_grid():
    g = grid()
    r = analyse(report(on_beats(g, [0, 32, 64, 128])), g, hits(None))
    assert r.verdict == Verdict.ON_GRID
    assert not r.proposed


def test_mp3_encoder_offset_at_44_1_khz_snaps_cues_onto_beats():
    g = grid()
    shift = mp3_offset_ms(44100)
    r = analyse(report(on_beats(g, [1, 33, 65, 129, 200], shift)), g, hits(-2.0))
    assert r.verdict == Verdict.CUES_WRONG
    assert r.selected_by_default
    assert r.cause == "MP3 encoder offset"
    assert round(r.offset) == -51
    for cue in r.cues:
        new_in, _out = r.proposed[cue.id]
        assert abs(new_in - g.times[g.nearest(new_in)]) < 1


def test_mp3_encoder_offset_at_48_khz():
    g = grid()
    r = analyse(report(on_beats(g, [1, 33, 65, 129], mp3_offset_ms(48000)), sample_rate=48000), g, hits(-3.0))
    assert r.cause == "MP3 encoder offset"
    assert round(r.offset) == -47


def test_known_cause_is_accepted_at_fast_tempo():
    g = grid(bpm=177)
    r = analyse(report(on_beats(g, [1, 33, 65, 129], mp3_offset_ms(44100))), g, hits(-2.0))
    assert r.verdict == Verdict.CUES_WRONG


def test_unknown_shift_within_limit_is_fixed_when_audio_agrees_with_grid():
    g = grid(bpm=177)
    r = analyse(report(on_beats(g, [1, 33, 65, 129], -60)), g, hits(1.0))
    assert r.cause == ""
    assert r.verdict == Verdict.CUES_WRONG


def test_unknown_shift_too_large_for_the_tempo_is_flagged():
    g = grid(bpm=200)
    r = analyse(report(on_beats(g, [1, 33, 65, 129], -78)), g, hits(1.0))
    assert r.verdict == Verdict.UNCLEAR
    assert "too large" in r.reason


def test_audio_lining_up_with_cues_means_the_grid_is_off():
    g = grid()
    r = analyse(report(on_beats(g, [1, 33, 65, 129], -40)), g, hits(-41.0))
    assert r.verdict == Verdict.GRID_WRONG


def test_intentionally_off_grid_cue_is_left_alone():
    g = grid()
    times = on_beats(g, [1, 33, 65, 129], -40) + [g.times[50] + 180]
    r = analyse(report(times), g, hits(0.0))
    assert r.verdict == Verdict.CUES_WRONG
    assert "4" not in r.proposed
    assert "left alone" in r.reason


def test_too_few_cues_cannot_be_judged():
    g = grid()
    r = analyse(report(on_beats(g, [1, 33], -40)), g, hits(0.0))
    assert r.verdict == Verdict.UNCLEAR


def test_drifting_offset_means_a_different_bpm():
    g = grid()
    times = [g.times[1] - 40, g.times[60] - 40, g.times[200] - 30, g.times[380] - 20]
    r = analyse(report(times), g, hits(0.0))
    assert r.verdict == Verdict.UNCLEAR


def test_vbr_cues_are_never_proposed():
    g = grid()
    r = report(on_beats(g, [1, 33, 65, 129, 150], -40))
    r.cues[4].mpeg = True
    analyse(r, g, hits(0.0))
    assert r.verdict == Verdict.CUES_WRONG
    assert "4" not in r.proposed


def test_loops_move_by_the_same_amount():
    g = grid()
    r = report(on_beats(g, [1, 33, 65, 129], -40))
    r.cues[0].out_ms = r.cues[0].in_ms + 1875
    analyse(r, g, hits(0.0))
    new_in, new_out = r.proposed["0"]
    assert new_out - new_in == 1875


def test_no_grid():
    r = analyse(report([100, 200, 300]), None, hits(None))
    assert r.verdict == Verdict.NO_GRID


def test_frames_are_rounded_down():
    assert frames(1000) == 150
    assert frames(1006) == 150
    assert frames(1007) == 151


def test_cue_letter_is_badge_text():
    from relinkbox.gui.waveform import cue_letter

    assert cue_letter(CueInfo(id="1", kind=0, in_ms=0)) == "M"
    assert cue_letter(CueInfo(id="2", kind=1, in_ms=0)) == "A"


def test_bake_waveform_makes_a_picture():
    from relinkbox.gui.waveform import bake_waveform

    bands = np.zeros((1200, 3), dtype=np.int16)
    bands[100:180, 0] = 24
    bands[100:180, 1] = 16
    picture = bake_waveform(bands, 180000, 400, 80)
    assert picture is not None
    assert picture.image.width() == 400
    assert picture.image.height() == 80
    assert picture.duration_ms == 180000


def test_cue_colors_follow_rekordbox_tables():
    from relinkbox.gui.waveform import cue_color

    memory = CueInfo(id="1", kind=0, in_ms=0, color=1)
    hot = CueInfo(id="2", kind=1, in_ms=0, color_index=43)
    assert cue_color(memory).getRgb()[:3] == (222, 68, 207)
    assert cue_color(hot).getRgb()[:3] == (0xFF, 0x37, 0x6F)


def test_display_cues_collapses_duplicate_memory_cues():
    cues = [
        CueInfo(id="1", kind=0, in_ms=1000),
        CueInfo(id="2", kind=0, in_ms=1000),
        CueInfo(id="3", kind=1, in_ms=1000),
        CueInfo(id="4", kind=0, in_ms=2000),
    ]
    shown = display_cues(cues)
    assert [c.id for c in shown] == ["1", "3", "4"]
    assert shown[0].label == "Memory ×2"


def _anlz(path, *tags):
    body = b"".join(tags)
    header_len = 28
    header = b"PMAI" + header_len.to_bytes(4, "big") + (header_len + len(body)).to_bytes(4, "big")
    path.write_bytes(header + b"\0" * (header_len - len(header)) + body)
    return path


def _pqtz(times):
    body = b"\0" * 4 + (0x80000).to_bytes(4, "big") + len(times).to_bytes(4, "big")
    for i, time in enumerate(times):
        body += ((i % 4) + 1).to_bytes(2, "big") + (12800).to_bytes(2, "big") + int(time).to_bytes(4, "big")
    return b"PQTZ" + (24).to_bytes(4, "big") + (12 + len(body)).to_bytes(4, "big") + body


def _pqt2(first, second):
    body = bytearray(28)
    if first:
        body[16:20] = int(first).to_bytes(4, "big")
    if second:
        body[24:28] = int(second).to_bytes(4, "big")
    return b"PQT2" + (56).to_bytes(4, "big") + (12 + len(body)).to_bytes(4, "big") + bytes(body)


def test_shift_beat_grid_moves_every_beat_and_leaves_other_sections(tmp_path):
    path = _anlz(tmp_path / "ANLZ0000.DAT", _pqtz([50, 519, 988]), _pqt2(50, 988), b"ZZZZ" + (12).to_bytes(4, "big") + (16).to_bytes(4, "big") + b"KEEP")
    assert shift_beat_grid(path, 12) == 12
    moved = read_beat_grid(path)
    assert moved.times == [62, 531, 1000]
    assert moved.bpms == [128, 128, 128]
    assert moved.beats == [1, 2, 3]
    raw = path.read_bytes()
    assert b"KEEP" in raw
    assert int.from_bytes(raw[raw.index(b"PQT2") + 28 : raw.index(b"PQT2") + 32], "big") == 62
    assert int.from_bytes(raw[raw.index(b"PQT2") + 36 : raw.index(b"PQT2") + 40], "big") == 1000


def test_shift_beat_grid_skips_an_unused_extended_time(tmp_path):
    path = _anlz(tmp_path / "ANLZ0000.DAT", _pqtz([50, 519]), _pqt2(0, 519))
    shift_beat_grid(path, -10)
    raw = path.read_bytes()
    start = raw.index(b"PQT2")
    assert int.from_bytes(raw[start + 28 : start + 32], "big") == 0
    assert int.from_bytes(raw[start + 36 : start + 40], "big") == 509


def test_shift_past_zero_drops_beats_that_leave_the_track(tmp_path):
    path = _anlz(
        tmp_path / "ANLZ0000.DAT",
        _pqtz([5, 474, 943]),
        b"ZZZZ" + (12).to_bytes(4, "big") + (16).to_bytes(4, "big") + b"KEEP",
    )
    shift_beat_grid(path, -10)
    moved = read_beat_grid(path)
    assert moved.times == [464, 933]
    assert moved.beats == [2, 3]
    assert b"KEEP" in path.read_bytes()


def test_shifted_grid_does_not_change_the_original():
    g = grid()
    original = list(g.times)
    moved = shifted_grid(g, -8)
    assert g.times == original
    assert moved.times[0] == original[0] - 8
    assert shifted_grid(g, 0) is g
    assert grid_shift_ok(g, -8)
    earlier = shifted_grid(g, -(g.times[0] + 1))
    assert earlier.times[0] == g.times[1] - (g.times[0] + 1)
    assert not grid_shift_ok(g, -(g.times[-1] + 1))


def test_snap_action_follows_the_verdict_on_screen():
    g = grid()
    cues_wrong = analyse(report(on_beats(g, [1, 33, 65, 129], -40)), g, hits(0.0))
    cues_wrong.dat_path = "ANLZ0000.DAT"
    assert snap_action(cues_wrong, Verdict.CUES_WRONG) == "grid"
    assert ticked_by_default(cues_wrong, Verdict.CUES_WRONG)
    assert snap_action(cues_wrong, Verdict.GRID_WRONG) == "cues"
    assert ticked_by_default(cues_wrong, Verdict.GRID_WRONG)

    grid_wrong = analyse(report(on_beats(g, [1, 33, 65, 129], -40)), g, hits(-41.0))
    grid_wrong.dat_path = "ANLZ0000.DAT"
    assert snap_action(grid_wrong, grid_wrong.verdict) == "cues"
    assert snap_action(grid_wrong, Verdict.CUES_WRONG) == "grid"
    assert ticked_by_default(grid_wrong, Verdict.CUES_WRONG)

    fast = grid(bpm=200)
    large = analyse(report(on_beats(fast, [1, 33, 65, 129], -78)), fast, hits(1.0))
    large.dat_path = "ANLZ0000.DAT"
    assert large.verdict == Verdict.UNCLEAR
    assert snap_action(large, large.verdict) == "grid"
    assert not ticked_by_default(large, large.verdict)

    unclear = analyse(report(on_beats(g, [1, 33], -40)), g, hits(0.0))
    unclear.dat_path = "ANLZ0000.DAT"
    assert snap_action(unclear, unclear.verdict) is None
    assert not ticked_by_default(unclear, unclear.verdict)


def test_manual_verdicts_survive_a_new_scan_for_tracks_that_remain():
    first = report([1, 2, 3])
    second = report([4, 5, 6])
    second.track_id = "2"
    saved = {"1": Verdict.GRID_WRONG, "2": Verdict.CUES_WRONG, "9": Verdict.GRID_WRONG, "1": Verdict.GRID_WRONG}
    saved["nope"] = "not a verdict"
    assert kept_overrides(saved, [first, second]) == {"1": Verdict.GRID_WRONG, "2": Verdict.CUES_WRONG}
    assert kept_overrides(saved, [second]) == {"2": Verdict.CUES_WRONG}


def test_removing_a_track_counts_as_a_pending_edit():
    assert TrackEdit(track_id="1", remove=True).pending()
    assert not TrackEdit(track_id="1").pending()


def test_matching_the_grid_follows_cues_that_were_already_snapped():
    g = grid()
    original = analyse(report(on_beats(g, [1, 33, 65, 129], -40)), g, hits(0.0))
    before = grid_delta_matching_cues(original, original.cues)
    assert before == int(round(original.offset))
    assert before != 0
    snapped = draft_cues(original.cues, moved={cue_id: times for cue_id, times in original.proposed.items()})
    assert grid_delta_matching_cues(original, snapped) == 0


def test_draft_cues_applies_moves_deletes_and_adds():
    cues = [
        CueInfo(id="1", kind=1, in_ms=1000),
        CueInfo(id="2", kind=2, in_ms=2000),
    ]
    added = CueInfo(id="new:3", kind=3, in_ms=1500)
    got = draft_cues(cues, deleted=["2"], moved={"1": (1100, -1)}, added=[added])
    assert [(cue.id, cue.in_ms) for cue in got] == [("1", 1100), ("new:3", 1500)]
    assert cues[0].in_ms == 1000


def test_snapped_ms_lands_on_the_nearest_beat():
    g = grid()
    assert abs(snapped_ms(g, g.times[10] + 20) - g.times[10]) < 1
    assert snapped_ms(None, 40) == 40


def test_grid_markers_spread_out_as_the_bars_get_narrow():
    from relinkbox.gui.waveform import grid_detail

    assert grid_detail(20, 4) == (1, 1)
    assert grid_detail(10, 4)[1] == 1
    assert grid_detail(6, 4)[1] == 4
    assert grid_detail(2, 4)[1] == 16


def test_cue_cell_keeps_the_same_zoom_when_the_offset_changes():
    beat = 60000 / 128
    assert cue_cell_span(beat) == cue_cell_span(beat)
    assert cue_cell_span(beat) == max(beat * 2, 180)


def test_onset_offset_finds_hits_relative_to_grid():
    g = grid(beats=100)
    heights = np.zeros(int(g.times[-1] * 0.15) + 200, dtype=int)
    for t in g.times:
        i = int((t + 20) * 0.15)
        heights[i : i + 10] = 28
    assert abs(onset_offset(g, Waveform(heights=heights, colors=np.zeros((len(heights), 3)))) - 20) <= 7
