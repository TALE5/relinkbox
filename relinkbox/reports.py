import csv
import io
import os


def _csv_text(header, rows):
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(header)
    writer.writerows(rows)
    return buffer.getvalue()


def write_csv(path, header, rows):
    # utf-8-sig so Excel opens accented artist names correctly
    with open(path, "w", encoding="utf-8-sig", newline="") as handle:
        handle.write(_csv_text(header, rows))


def changes_csv_text(applied):
    rows = [(c.track.id, c.track.artist, c.track.title, c.old_path, c.new_path, c.method) for c in applied]
    return _csv_text(("Track ID", "Artist", "Title", "Old path", "New path", "How it was matched"), rows)


def write_plan_csv(path, plan):
    rows = []
    for match in plan.matches:
        status = "Ambiguous" if match.ambiguous and not match.new_path else "Match found"
        rows.append(
            (
                status,
                match.track.artist,
                match.track.title,
                match.track.path,
                match.new_path or " | ".join(c.path for c in match.candidates),
                match.method.value,
                match.confidence.value,
                " ".join(match.notes),
            )
        )
    for track in plan.missing:
        rows.append(("Still missing", track.artist, track.title, track.path, "", "", "", ""))
    write_csv(
        path,
        ("Status", "Artist", "Title", "Path in Rekordbox", "Proposed file", "How it was matched", "Confidence", "Notes"),
        rows,
    )


def write_missing_csv(path, tracks):
    write_csv(
        path,
        ("Artist", "Title", "Path in Rekordbox"),
        [(t.artist, t.title, t.path) for t in tracks],
    )


def write_m3u8(path, files):
    lines = ["#EXTM3U"]
    for file in files:
        lines.append(f"#EXTINF:-1,{os.path.splitext(os.path.basename(file))[0]}")
        lines.append(file)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")


def write_text_list(path, files):
    with open(path, "w", encoding="utf-8") as handle:
        handle.write("\n".join(files) + "\n")
