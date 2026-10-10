import csv

from conftest import make_track

from relinkbox.matching import build_plan
from relinkbox.reports import write_m3u8, write_plan_csv
from relinkbox.scan import scan_folders


def test_scan_finds_common_dj_formats_and_skips_others(tmp_path, write_file):
    for name in ("a.mp3", "b.AIF", "c.aiff", "d.flac", "e.wav", "f.m4a", "notes.txt", "cover.jpg"):
        write_file(tmp_path / "music" / "sub" / name, 10)
    index = scan_folders([str(tmp_path / "music")])
    assert sorted(e.name for e in index.files) == ["a.mp3", "b.aif", "c.aiff", "d.flac", "e.wav", "f.m4a"]


def test_overlapping_folders_are_not_counted_twice(tmp_path, write_file):
    write_file(tmp_path / "music" / "sub" / "a.mp3", 10)
    index = scan_folders([str(tmp_path / "music"), str(tmp_path / "music" / "sub")])
    assert len(index.files) == 1


def test_m3u8_lists_every_file(tmp_path):
    path = tmp_path / "list.m3u8"
    write_m3u8(path, ["C:\\Music\\Ärtist - Song.mp3"])
    lines = path.read_text(encoding="utf-8").splitlines()
    assert lines == ["#EXTM3U", "#EXTINF:-1,Ärtist - Song", "C:\\Music\\Ärtist - Song.mp3"]


def test_plan_csv_has_matches_and_missing(tmp_path, write_file):
    write_file(tmp_path / "music" / "Song.mp3", 100)
    tracks = [
        make_track("Q:/Gone/Song.mp3", 100, track_id="1", title="Song", artist="Artist"),
        make_track("Q:/Gone/Lost.mp3", 555, track_id="2", title="Lost"),
    ]
    plan = build_plan(tracks, scan_folders([str(tmp_path / "music")]))
    out = tmp_path / "report.csv"
    write_plan_csv(out, plan)
    with open(out, encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert [r["Status"] for r in rows] == ["Match found", "Still missing"]
    assert rows[0]["Confidence"] == "High"
