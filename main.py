"""A read-only, local Org-mode calendar. Run with uvicorn main:app."""

import hashlib
import json
import logging
import os
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Literal

import org2ical
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from icalendar import Calendar
from starlette.concurrency import run_in_threadpool

BASE_DIR = Path(__file__).resolve().parent
logger = logging.getLogger("uvicorn.error")
EventType = Literal["TIMESTAMP", "SCHEDULED", "DEADLINE"]

app = FastAPI(title="Org calendar", docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")


def configured_files() -> list[Path]:
    """ORG_FILES is a JSON array, so paths may contain spaces or colons."""
    value = os.environ.get("ORG_FILES")
    if value is None:
        return [BASE_DIR / "example.org"]
    paths = json.loads(value)
    if not isinstance(paths, list) or not paths or not all(
        isinstance(path, str) and path.strip() for path in paths
    ):
        raise ValueError("ORG_FILES must be a non-empty JSON array of file paths.")
    return list(dict.fromkeys(Path(path).expanduser().resolve() for path in paths))


def convert_org(content: str, path: Path, event_type: EventType | None) -> tuple[Calendar, list[str]]:
    # org2ical escapes newlines but leaves other iCalendar TEXT escapes to us.
    escaped = content.replace("\\", "\\\\").replace(",", "\\,").replace(";", "\\;")
    ics, warnings = org2ical.loads(
        escaped,
        now=datetime.now(timezone.utc),
        include_types={event_type} if event_type else None,
    )
    # Org dates have no zone. Remove org2ical's default UTC suffix to preserve
    # local wall time, including repeats across daylight-saving boundaries.
    ics = re.sub(r"(?m)^(DTSTART|DTEND):(\d{8}T\d{6})Z$", r"\1:\2", ics)
    # org2ical omits VALUE=DATE; make all-day dates explicit for ICS readers.
    ics = re.sub(r"(?m)^(DTSTART|DTEND):(\d{8})$", r"\1;VALUE=DATE:\2", ics)
    calendar = Calendar.from_ical(ics)
    for index, event in enumerate(calendar.walk("VEVENT")):
        start = event.decoded("DTSTART")
        end = event.decoded("DTEND")
        if isinstance(start, datetime) and end == start:
            # Point timestamps have no duration. Let FullCalendar use its
            # default duration rather than sending a zero-length event.
            del event["DTEND"]
        elif isinstance(start, date) and not isinstance(start, datetime) and end <= start:
            del event["DTEND"]
            event.add("DTEND", start + timedelta(days=1))
        # Upstream UIDs include DTSTAMP. Keep IDs stable between refreshes and
        # distinct when two source files contain the same event.
        identity = f"{path}\0{index}\0{event.get('CATEGORIES')}\0{start}\0{event.get('SUMMARY')}"
        event["UID"] = hashlib.sha256(identity.encode()).hexdigest() + "@org-calendar"
    return calendar, warnings


@app.get("/")
def index() -> FileResponse:
    return FileResponse(BASE_DIR / "static" / "index.html")


@app.post("/upload")
async def upload(request: Request, filename: str = "agenda.org") -> Response:
    """Convert an uploaded snapshot without storing it or changing defaults."""
    if not filename.lower().endswith(".org"):
        raise HTTPException(400, "Choose an .org file.")
    content = await request.body()
    if not content:
        raise HTTPException(400, "The Org file is empty.")
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise HTTPException(400, "Save the Org file as UTF-8 and try again.") from error
    try:
        calendar, warnings = await run_in_threadpool(convert_org, text, Path(filename), None)
    except Exception as error:
        raise HTTPException(400, "Could not parse this Org file. Check its dates and timestamps.") from error
    return Response(
        calendar.to_ical(),
        media_type="text/calendar; charset=utf-8",
        headers={
            "Cache-Control": "no-store",
            "X-Calendar-Warnings": json.dumps(warnings[:5], ensure_ascii=True),
        },
    )


@app.get("/calendar.ics")
def calendar_feed(event_type: EventType | None = None) -> Response:
    calendar = Calendar()
    calendar.add("PRODID", "-//Org calendar//Local viewer//EN")
    calendar.add("VERSION", "2.0")
    warnings = []
    loaded = 0
    try:
        paths = configured_files()
    except (ValueError, OSError) as error:
        logger.warning("Invalid calendar configuration: %s", error)
        paths = []
        warnings.append("Invalid ORG_FILES. Use a non-empty JSON array of file paths.")

    for path in paths:
        try:
            parsed, parse_warnings = convert_org(path.read_text(encoding="utf-8-sig"), path, event_type)
            for event in parsed.walk("VEVENT"):
                calendar.add_component(event)
            loaded += 1
            if parse_warnings:
                warnings.append(f"{path.name}: {len(parse_warnings)} parsing warning(s); see server output.")
                for warning in parse_warnings:
                    logger.warning("%s: %s", path, warning)
        except Exception:
            # A bad file must not prevent other configured files from loading.
            logger.exception("Could not read or parse %s", path)
            warnings.append(f"{path.name}: could not read or parse this file; see server output.")

    return Response(
        calendar.to_ical(),
        status_code=200 if loaded else 503,
        media_type="text/calendar; charset=utf-8",
        headers={
            "Cache-Control": "no-store",
            "X-Calendar-Warnings": json.dumps(warnings[:5], ensure_ascii=True),
        },
    )
