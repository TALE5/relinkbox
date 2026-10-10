from types import SimpleNamespace

from relinkbox.rekordbox import file_type_for, lost_tag_types, raw_tag_types


def _tag(fourcc, body=b""):
    return fourcc.encode("ascii") + (12).to_bytes(4, "big") + (12 + len(body)).to_bytes(4, "big") + body


def _anlz_file(path, *tags):
    body = b"".join(tags)
    header_len = 28
    header = b"PMAI" + header_len.to_bytes(4, "big") + (header_len + len(body)).to_bytes(4, "big")
    path.write_bytes(header + b"\0" * (header_len - len(header)) + body)
    return path


def test_raw_tag_types_lists_every_section(tmp_path):
    path = _anlz_file(tmp_path / "ANLZ0000.EXT", _tag("PPTH", b"\0" * 8), _tag("PVB2", b"\0" * 20), _tag("PCO2"))
    assert raw_tag_types(path) == ["PPTH", "PVB2", "PCO2"]


def test_raw_tag_types_ignores_non_analysis_files(tmp_path):
    path = tmp_path / "other.bin"
    path.write_bytes(b"not an analysis file")
    assert raw_tag_types(path) == []


def test_lost_tag_types_reports_sections_pyrekordbox_dropped(tmp_path):
    path = _anlz_file(tmp_path / "ANLZ0000.EXT", _tag("PPTH"), _tag("PVB2"), _tag("PCO2"), _tag("PCO2"))
    parsed = SimpleNamespace(tag_types=["PPTH", "PCO2", "PCO2"])
    assert lost_tag_types(path, parsed) == ["PVB2"]
    assert lost_tag_types(path, SimpleNamespace(tag_types=["PPTH", "PVB2", "PCO2", "PCO2"])) == []


def test_file_type_codes():
    assert file_type_for("D:/Music/a.MP3") == 1
    assert file_type_for("a.flac") == 5
    assert file_type_for("a.wav") == 11
    assert file_type_for("a.aif") == 12
    assert file_type_for("a.ogg") is None
