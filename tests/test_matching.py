from conftest import make_track

from relinkbox.matching import (
    Confidence,
    Method,
    build_folder_move_plan,
    build_plan,
    suggest_moved_prefix,
)
from relinkbox.scan import scan_folders

GONE = "Q:/Gone/Music"


def plan_for(tmp_path, tracks):
    return build_plan(tracks, scan_folders([str(tmp_path / "music")]))


def only_match(plan):
    assert len(plan.matches) == 1, plan
    return plan.matches[0]


def test_existing_tracks_are_never_touched(tmp_path, write_file):
    existing = write_file(tmp_path / "old" / "Artist - Song.mp3", 100)
    write_file(tmp_path / "music" / "Artist - Song.mp3", 100)
    plan = plan_for(tmp_path, [make_track(str(existing), 100)])
    assert plan.ok_tracks == 1
    assert plan.matches == [] and plan.missing == []


def test_same_name_and_size_is_high_confidence(tmp_path, write_file):
    target = write_file(tmp_path / "music" / "a" / "Artist - Song.mp3", 100)
    write_file(tmp_path / "music" / "b" / "Artist - Song.mp3", 999)
    match = only_match(plan_for(tmp_path, [make_track(f"{GONE}/Artist - Song.mp3", 100)]))
    assert match.method == Method.SAME_NAME_SIZE
    assert match.confidence == Confidence.HIGH
    assert match.new_path == str(target)
    assert match.selected_by_default


def test_duplicate_name_and_size_is_ambiguous(tmp_path, write_file):
    write_file(tmp_path / "music" / "a" / "Song.mp3", 100)
    write_file(tmp_path / "music" / "b" / "Song.mp3", 100)
    match = only_match(plan_for(tmp_path, [make_track(f"{GONE}/Song.mp3", 100)]))
    assert match.ambiguous
    assert match.new_path is None
    assert not match.selected_by_default


def test_parent_folder_breaks_ties(tmp_path, write_file):
    write_file(tmp_path / "music" / "House" / "Song.mp3", 100)
    techno = write_file(tmp_path / "music" / "Techno" / "Song.mp3", 100)
    match = only_match(plan_for(tmp_path, [make_track(f"{GONE}/Techno/Song.mp3", 100)]))
    assert not match.ambiguous
    assert match.new_path == str(techno)


def test_same_name_with_edited_tags_is_medium_without_note(tmp_path, write_file):
    write_file(tmp_path / "music" / "Song.mp3", 1010)
    match = only_match(plan_for(tmp_path, [make_track(f"{GONE}/Song.mp3", 1000)]))
    assert match.method == Method.SAME_NAME
    assert match.confidence == Confidence.MEDIUM
    assert not any("larger" in note for note in match.notes)


def test_same_name_much_larger_file_warns_about_cues(tmp_path, write_file):
    write_file(tmp_path / "music" / "Song.mp3", 2000)
    match = only_match(plan_for(tmp_path, [make_track(f"{GONE}/Song.mp3", 1000)]))
    assert match.method == Method.SAME_NAME
    assert any("100% larger" in note and "cue points" in note for note in match.notes)


def test_renamed_file_with_same_size(tmp_path, write_file):
    renamed = write_file(tmp_path / "music" / "01 Artist - Song.mp3", 4321)
    write_file(tmp_path / "music" / "Other.mp3", 1000)
    match = only_match(plan_for(tmp_path, [make_track(f"{GONE}/Artist - Song.mp3", 4321)]))
    assert match.method == Method.RENAMED_SAME_SIZE
    assert match.new_path == str(renamed)


def test_same_size_wav_with_unrelated_name_is_not_matched(tmp_path, write_file):
    write_file(tmp_path / "music" / "Kick 01.wav", 4321)
    plan = plan_for(tmp_path, [make_track(f"{GONE}/Vocal Chop.wav", 4321)])
    assert plan.matches == []


def test_leading_letter_rename_is_found(tmp_path, write_file):
    renamed = write_file(tmp_path / "music" / "Artist - The Song.mp3", 50)
    match = only_match(plan_for(tmp_path, [make_track(f"{GONE}/The Artist - The Song.mp3", 77)]))
    assert match.new_path == str(renamed)
    assert match.method == Method.SIMILAR_NAME


def test_small_rename_is_medium_even_when_library_size_is_stale(tmp_path, write_file):
    name = "A Place to Bury Strangers - Never Coming Back (Roly Porter remix)"
    renamed = write_file(tmp_path / "music" / f"{name}1.mp3", 2000)
    match = only_match(plan_for(tmp_path, [make_track(f"{GONE}/{name}.mp3", 1000)]))
    assert match.new_path == str(renamed)
    assert match.confidence == Confidence.MEDIUM
    assert match.selected_by_default


def test_small_rename_with_same_size_is_high(tmp_path, write_file):
    name = "A Place to Bury Strangers - Never Coming Back (Roly Porter remix)"
    write_file(tmp_path / "music" / f"{name}1.mp3", 1000)
    write_file(tmp_path / "music" / "Unrelated.mp3", 1000)
    match = only_match(plan_for(tmp_path, [make_track(f"{GONE}/{name}.mp3", 1000)]))
    assert match.confidence == Confidence.HIGH


def test_changed_version_number_stays_low(tmp_path, write_file):
    write_file(tmp_path / "music" / "Artist - Long Track Name (Club Mix) v2.mp3", 2000)
    match = only_match(plan_for(tmp_path, [make_track(f"{GONE}/Artist - Long Track Name (Club Mix) v1.mp3", 1000)]))
    assert match.confidence == Confidence.LOW
    assert any("different version" in note for note in match.notes)


def test_type_change_is_low_confidence_and_warns(tmp_path, write_file):
    write_file(tmp_path / "music" / "Song.flac", 500)
    match = only_match(plan_for(tmp_path, [make_track(f"{GONE}/Song.mp3", 100)]))
    assert match.method == Method.TYPE_CHANGED
    assert match.confidence == Confidence.LOW
    assert not match.selected_by_default
    assert any("re-analyze" in note for note in match.notes)


def test_version_variants_are_not_silently_picked(tmp_path, write_file):
    write_file(tmp_path / "music" / "Artist - Song (Original Mix) v1.mp3", 10)
    write_file(tmp_path / "music" / "Artist - Song (Original Mix) v2.mp3", 11)
    match = only_match(plan_for(tmp_path, [make_track(f"{GONE}/Artist - Song (Original Mix) v3.mp3", 12)]))
    assert match.ambiguous
    assert match.new_path is None


def test_unrelated_file_is_not_matched(tmp_path, write_file):
    write_file(tmp_path / "music" / "Completely Different.mp3", 10)
    plan = plan_for(tmp_path, [make_track(f"{GONE}/Artist - Song.mp3", 99)])
    assert plan.matches == []
    assert len(plan.missing) == 1


def test_streaming_tracks_are_skipped(tmp_path):
    (tmp_path / "music").mkdir()
    plan = plan_for(tmp_path, [make_track("soundcloud:tracks:123"), make_track("")])
    assert plan.non_file_tracks == 2
    assert plan.missing_total == 0


def test_offline_drive_is_reported(tmp_path, write_file):
    write_file(tmp_path / "music" / "Song.mp3", 100)
    plan = plan_for(tmp_path, [make_track(f"{GONE}/Song.mp3", 100)])
    assert plan.offline_drives == ["Q:"]
    assert any("not connected" in note for note in plan.matches[0].notes)


def test_target_already_in_library_is_flagged(tmp_path, write_file):
    existing = write_file(tmp_path / "music" / "Song.mp3", 100)
    tracks = [
        make_track(f"{GONE}/Song.mp3", 100, track_id="1"),
        make_track(str(existing), 100, track_id="2"),
    ]
    match = only_match(plan_for(tmp_path, tracks))
    assert any("already in your library" in note for note in match.notes)


def test_folder_move_keeps_structure(tmp_path, write_file):
    new_root = tmp_path / "NewDrive" / "Music"
    moved = write_file(new_root / "House" / "Song.mp3", 100)
    tracks = [
        make_track(f"{GONE}/House/Song.mp3", 100, track_id="1"),
        make_track(f"{GONE}/House/Lost.mp3", 100, track_id="2"),
        make_track("Q:/Elsewhere/Other.mp3", 100, track_id="3"),
    ]
    plan = build_folder_move_plan(tracks, GONE, str(new_root))
    assert [m.new_path for m in plan.matches] == [str(moved)]
    assert plan.matches[0].confidence == Confidence.HIGH
    assert [t.id for t in plan.missing] == ["2"]


def test_folder_move_prefix_is_case_and_slash_insensitive(tmp_path, write_file):
    new_root = tmp_path / "Music"
    write_file(new_root / "Song.mp3", 100)
    plan = build_folder_move_plan([make_track(f"{GONE}/Song.mp3", 100)], "q:\\gone\\music\\", str(new_root))
    assert len(plan.matches) == 1


def test_suggest_moved_prefix():
    tracks = [
        make_track("E:/Music/House/a.mp3"),
        make_track("E:/Music/Techno/b.mp3"),
        make_track("E:/Music/Techno/c.mp3"),
        make_track("D:/Other/d.mp3"),
    ]
    assert suggest_moved_prefix(tracks) == ("E:/Music", 3)
    assert suggest_moved_prefix([make_track("E:/a.mp3"), make_track("E:/b.mp3")]) == ("E:/", 2)
    assert suggest_moved_prefix([]) is None
