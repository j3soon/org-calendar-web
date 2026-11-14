import json

import pytest
from fastapi.testclient import TestClient
from icalendar import Calendar

import main


@pytest.fixture
def client():
    return TestClient(main.app)


def test_example_is_default(client, monkeypatch):
    monkeypatch.delenv("ORG_FILES", raising=False)
    response = client.get("/calendar.ics")
    assert response.status_code == 200
    titles = {str(event["SUMMARY"]) for event in Calendar.from_ical(response.content).walk("VEVENT")}
    assert "Morning focus" in titles


def test_upload_converts_all_types_without_replacing_default(client, tmp_path, monkeypatch):
    source = tmp_path / "default.org"
    original = "* Original\n<2026-11-16 Mon>\n"
    source.write_text(original)
    monkeypatch.setenv("ORG_FILES", json.dumps([str(source)]))
    content = """* café
<2026-11-16 Mon 09:00-10:00 +1w>
* Scheduled
SCHEDULED: <2026-11-17 Tue>
* Deadline
DEADLINE: <2026-11-18 Wed>
"""
    response = client.post("/upload?filename=agenda.ORG", content=content.encode("utf-8-sig"))
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["content-type"].startswith("text/calendar")
    events = Calendar.from_ical(response.content).walk("VEVENT")
    assert len(events) == 3
    assert {event["CATEGORIES"].to_ical().decode() for event in events} == {"TIMESTAMP", "SCHEDULED", "DEADLINE"}
    assert str(events[0]["SUMMARY"]) == "café"
    assert events[0].decoded("DTSTART").tzinfo is None
    assert events[0]["RRULE"]["FREQ"] == ["WEEKLY"]
    default = Calendar.from_ical(client.get("/calendar.ics").content).walk("VEVENT")
    assert [str(event["SUMMARY"]) for event in default] == ["Original"]
    assert source.read_text() == original
    assert list(tmp_path.iterdir()) == [source]


@pytest.mark.parametrize("content, filename, message", [
    (b"", "empty.org", "empty"),
    (b"\xff\xfe", "encoding.org", "UTF-8"),
    (b"* Other\n", "agenda.txt", ".org"),
    (b"* Other\n", "agenda.org.txt", ".org"),
    (b"* Other\n", "agenda.org~", ".org"),
    (b"* Other\n", "agenda", ".org"),
    (b"* Invalid\n<2026-13-99 Mon>\n", "broken.org", "Could not parse"),
])
def test_upload_rejects_invalid_files(client, content, filename, message):
    response = client.post("/upload", params={"filename": filename}, content=content)
    assert response.status_code == 400
    assert message in response.json()["detail"]


def test_upload_over_five_megabytes(client):
    padding = b"# " + b"x" * (5 * 1024 * 1024) + b"\n"
    response = client.post(
        "/upload?filename=large.org",
        content=iter([padding, b"* Large upload\n<2026-11-17 Tue>\n"]),
    )
    assert response.status_code == 200
    events = Calendar.from_ical(response.content).walk("VEVENT")
    assert [str(event["SUMMARY"]) for event in events] == ["Large upload"]


def test_upload_returns_parser_warnings(client):
    response = client.post("/upload", content=b"* Missing date\nSCHEDULED: someday\n")
    assert response.status_code == 200
    assert "no timestamp" in response.headers["x-calendar-warnings"]


def test_upload_with_no_events_is_valid(client):
    response = client.post("/upload", content=b"* Notes\nNo dates here.\n")
    assert response.status_code == 200
    assert Calendar.from_ical(response.content).walk("VEVENT") == []
