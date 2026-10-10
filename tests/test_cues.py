import numpy as np

from relinkbox.analysis import BeatGrid, Waveform, onset_offset
from relinkbox.cues import CueInfo, TrackCueReport, Verdict, analyse, display_cues, frames, mp3_offset_ms


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


def test_onset_offset_finds_hits_relative_to_grid():
    g = grid(beats=100)
    heights = np.zeros(int(g.times[-1] * 0.15) + 200, dtype=int)
    for t in g.times:
        i = int((t + 20) * 0.15)
        heights[i : i + 10] = 28
    assert abs(onset_offset(g, Waveform(heights=heights, colors=np.zeros((len(heights), 3)))) - 20) <= 7
