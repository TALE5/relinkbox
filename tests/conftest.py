import pytest

from relinkbox.rekordbox import TrackInfo


def make_track(path, size=0, track_id="1", title="", artist="", display_name=None):
    return TrackInfo(
        id=track_id,
        path=path,
        display_name=display_name if display_name is not None else path.replace("\\", "/").rsplit("/", 1)[-1],
        size=size,
        title=title,
        artist=artist,
    )


@pytest.fixture
def write_file():
    def _write(path, size):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"\0" * size)
        return path

    return _write
