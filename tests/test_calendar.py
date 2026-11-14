import json
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient
from icalendar import Calendar

from main import app


@pytest.fixture
def source(tmp_path, monkeypatch):
    path = tmp_path / "agenda.org"
    monkeypatch.setenv("ORG_FILES", json.dumps([str(path)]))
    return path


@pytest.fixture
def client():
    return TestClient(app)


def events(response):
    return Calendar.from_ical(response.content).walk("VEVENT")


def test_page_and_local_assets(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "Org calendar" in response.text
    for asset in ["calendar.js", "style.css"]:
        assert client.get(f"/static/{asset}").status_code == 200


def test_types_and_filtered_feeds(client, source):
    source.write_text("""* Meeting
<2026-11-16 Mon 09:00-10:00>
* Work
SCHEDULED: <2026-11-17 Tue>
* Due
DEADLINE: <2026-11-18 Wed>
""", encoding="utf-8")
    response = client.get("/calendar.ics")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/calendar")
    assert response.headers["cache-control"] == "no-store"
    assert len(events(response)) == 3
    for category in ("TIMESTAMP", "SCHEDULED", "DEADLINE"):
        filtered = events(client.get("/calendar.ics", params={"event_type": category}))
        assert len(filtered) == 1
        assert filtered[0]["CATEGORIES"].to_ical().decode() == category
    assert client.get("/calendar.ics?event_type=invalid").status_code == 422


def test_all_day_and_inclusive_org_range(client, source):
    source.write_text("* Day\n<2026-11-16 Mon>\n* Trip\n<2026-11-18 Wed>--<2026-11-20 Fri>\n")
    response = client.get("/calendar.ics")
    day, trip = events(response)
    assert day.decoded("DTSTART") == date(2026, 11, 16)
    assert day.decoded("DTEND") == date(2026, 11, 17)
    assert trip.decoded("DTEND") == date(2026, 11, 21)
    assert b"DTSTART;VALUE=DATE:20261116" in response.content


def test_floating_local_time_ranges_and_recurrence(client, source):
    source.write_text("""* Across DST
<2026-10-26 Mon 09:00-10:30 +1w>
* Point
SCHEDULED: <2026-11-16 Mon 12:00>
""")
    response = client.get("/calendar.ics")
    recurring, point = events(response)
    assert recurring.decoded("DTSTART").tzinfo is None
    assert recurring.decoded("DTEND") - recurring.decoded("DTSTART") == timedelta(minutes=90)
    assert recurring["RRULE"]["FREQ"] == ["WEEKLY"]
    assert recurring["RRULE"]["INTERVAL"] == [1]
    assert "DTEND" not in point
    assert b"DTSTART:20261026T090000\r\n" in response.content


def test_refresh_rereads_files_and_uids_are_stable(client, source):
    source.write_text("* First\n<2026-11-16 Mon>\n")
    first = events(client.get("/calendar.ics"))[0]
    assert first["UID"] == events(client.get("/calendar.ics"))[0]["UID"]
    source.write_text("* Changed\n<2026-11-17 Tue>\n")
    changed = events(client.get("/calendar.ics"))[0]
    assert str(changed["SUMMARY"]) == "Changed"
    assert changed.decoded("DTSTART") == date(2026, 11, 17)


def test_multiple_files_and_deduplication(client, source, tmp_path, monkeypatch):
    other = tmp_path / "other agenda.org"
    for path in (source, other):
        path.write_text("* Same\n<2026-11-16 Mon>\n")
    monkeypatch.setenv("ORG_FILES", json.dumps([str(source), str(other), str(source)]))
    result = events(client.get("/calendar.ics"))
    assert len(result) == 2
    assert result[0]["UID"] != result[1]["UID"]


def test_missing_file_returns_valid_ics_and_error(client, source):
    response = client.get("/calendar.ics")
    assert response.status_code == 503
    assert events(response) == []
    assert "could not read or parse" in response.headers["x-calendar-warnings"]


def test_bad_file_does_not_hide_good_files(client, source, tmp_path, monkeypatch):
    source.write_text("* Good\n<2026-11-16 Mon>\n")
    broken = tmp_path / "broken.org"
    broken.write_bytes(b"\xff\xfe")
    monkeypatch.setenv("ORG_FILES", json.dumps([str(source), str(broken)]))
    response = client.get("/calendar.ics")
    assert response.status_code == 200
    assert len(events(response)) == 1
    assert "broken.org" in response.headers["x-calendar-warnings"]


@pytest.mark.parametrize("value", ["not json", "[]", '"file.org"', "null", '[""]', "[12]"])
def test_invalid_configuration(client, monkeypatch, value):
    monkeypatch.setenv("ORG_FILES", value)
    response = client.get("/calendar.ics")
    assert response.status_code == 503
    assert "Invalid ORG_FILES" in response.headers["x-calendar-warnings"]


def test_parser_warning_and_recovery(client, source):
    source.write_text("* Missing date\nSCHEDULED: someday\n")
    response = client.get("/calendar.ics")
    assert response.status_code == 200
    assert "parsing warning" in response.headers["x-calendar-warnings"]
    source.write_text("* Repaired\nSCHEDULED: <2026-11-16 Mon>\n")
    response = client.get("/calendar.ics")
    assert len(events(response)) == 1
    assert json.loads(response.headers["x-calendar-warnings"]) == []


def test_text_escaping_unicode_and_line_folding(client, source):
    title = r"C:\new, notes; café " + "長" * 40
    description = r"Keep C:\notes\file, commas; and semicolons."
    source.write_text(f"* {title}\n<2026-11-16 Mon 10:00>\n{description}\n", encoding="utf-8")
    event = events(client.get("/calendar.ics"))[0]
    assert str(event["SUMMARY"]) == title
    assert description in str(event["DESCRIPTION"])


def test_inactive_done_and_archived_entries_are_ignored(client, source):
    source.write_text("""* Hidden date
[2026-11-16 Mon]
* DONE Finished
<2026-11-16 Mon>
* Archived :ARCHIVE:
<2026-11-16 Mon>
""")
    assert events(client.get("/calendar.ics")) == []


def test_read_only(client, source):
    original = "* Keep\n<2026-11-16 Mon>\n"
    source.write_text(original)
    assert client.post("/calendar.ics", json={"title": "Edit"}).status_code == 405
    client.get("/calendar.ics")
    assert source.read_text() == original
