# Org calendar

A minimal, read-only local web calendar for Org-mode files.

## Run with Docker

With Docker and Compose installed:

```sh
docker compose up -d --build
```

Open **http://127.0.0.1:18000**. The included `example.org` loads by default.

Drop an `.org` file onto the page or click **Upload .org** to view your own file.
Click **Use default** to return to the example. Uploads are temporary and apply
only to the current tab.

## Run without Docker

Use Python 3.10 or newer:

```sh
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --host 127.0.0.1 --port 8000
```

Open **http://127.0.0.1:8000**.

## Configuration

### Uploaded files

Drop or choose one UTF-8 file with an `.org` suffix. It replaces the displayed
calendar in the current tab. The server converts it without saving it or
changing anyone else's calendar. Invalid uploads leave the previous calendar
in place. The app does not set a file size limit.

Uploads are snapshots. After editing a file, upload it again. **Refresh** reloads
the current snapshot. Reloading the page restores the default calendar.

### Default files

The server reads `example.org` by default. When running Python directly, set
`ORG_FILES` to a JSON array of paths to choose other default files:

```sh
ORG_FILES='["/home/me/notes/agenda.org", "/home/me/notes/projects.org"]' \
  uvicorn main:app --host 127.0.0.1 --port 8000
```

Paths can be absolute, relative to the server's working directory, or start with
`~`. Files are read as UTF-8. Restart the server after changing `ORG_FILES`.
Save edits in your Org editor, then click **Refresh** to reread default files.
**Use default** returns to these files after an upload.

### Docker service

Uvicorn listens on port `8000` inside the container. Compose forwards host port
`18000` to it on localhost. Set `CALENDAR_PORT=18001` if you need another host port.

To save these settings for later Compose commands, create a `.env` file:

```dotenv
CALENDAR_PORT=18000
```

The source checkout is mounted read-only at `/app`. Keep the checkout available
while the service runs. Compose does not mount an Org directory. Upload your
files through the page. HTML, CSS, and JavaScript edits need a page reload.
After Python edits, restart the service:

```sh
docker compose restart calendar
```

Run `docker compose up -d --build` after changing dependencies or these settings.
The image installs Python dependencies using a BuildKit bind mount of
`requirements.txt`, without copying source files. Org file edits only need
**Refresh** for default files, or another upload for snapshots. Logs rotate
automatically.

The `unless-stopped` restart policy restores the service after Docker restarts,
including after a reboot. A manually stopped service stays stopped. Docker must
start at boot. On Linux with systemd, enable it with:

```sh
sudo systemctl enable docker.service containerd.service
```

See Docker's [restart policy documentation](https://docs.docker.com/engine/containers/start-containers-automatically/)
and [boot setup](https://docs.docker.com/engine/install/linux-postinstall/#configure-docker-to-start-on-boot-with-systemd).
For Docker Desktop, enable [starting Docker Desktop when you sign in](https://docs.docker.com/desktop/settings-and-maintenance/settings/#general).

View logs or stop the service:

```sh
docker compose logs -f calendar
docker compose down
```

## Details

Built with Python + FastAPI, [org2ical](https://github.com/j3soon/org2ical),
vanilla JavaScript, and [FullCalendar](https://fullcalendar.io/). No database or
frontend build step is needed. FullCalendar, its iCalendar plugin, and ICAL.js
are bundled in `static/vendor`, including their licenses. The viewer makes no
external browser requests and works offline after dependencies are installed.

- Month and week views, including all-day events and timestamp ranges.
- Blue timestamps, green scheduled entries, and red deadlines. Hover over an
  event for its full title and description.
- Active timestamps and Org repeaters (`+`, `++`, `.+`, with hour/day/week/month/
  year intervals) are exported by org2ical. Repeater modes are shown as fixed
  calendar recurrences; completion-dependent Org behavior is not simulated.
- Local times stay as floating iCalendar times. `09:00` in Org displays as
  `09:00` in the browser's local timezone, including recurring events across DST.
  All-day dates stay dates. The footer shows the browser's timezone.
- DONE, CANCELED, ARCHIVE-tagged entries and inactive timestamps follow
  org2ical's default exclusion rules.
- Missing or unparseable files show a warning; other files still load. Detailed
  parser warnings appear in the server output. Correct the file and refresh to
  recover. A completely unreadable configuration returns HTTP 503 with a valid,
  empty calendar.
- No file writes, editing, synchronization, automatic polling, or file watching.

`GET /calendar.ics` generates a fresh combined feed with `Cache-Control: no-store`.
The optional `?event_type=TIMESTAMP`, `SCHEDULED`, or `DEADLINE` filters the feed.
The UI uses these three feeds because FullCalendar's iCalendar plugin does not
expose ICS categories for event colors. Navigation expands the already-loaded
feed; **Refresh** calls `calendar.refetchEvents()`.

`POST /upload?filename=agenda.org` converts a raw Org file body to iCalendar. The
browser splits it into temporary feeds for the same three event colors. Uploaded
files are not written to disk or retained by the server.

The small conversion layer adds valid all-day types and exclusive end dates,
preserves local wall times, escapes calendar text, and stabilizes event IDs.

## Limitations

- org2ical exports only the start of scheduled and deadline time ranges.
  Standalone active timestamp ranges retain their end times.
- The FullCalendar plugin expands at most 1,000 occurrences per recurring
  series, counted from its original start. Very old or frequent recurring
  series can therefore stop appearing.

## Development

```sh
pip install -r requirements-dev.txt
python -m pytest -q
```

### Browser dependency integrity

`static/vendor/manifest.json` records version-specific source URLs and SHA-256
hashes for the bundled scripts and licenses. Normal tests verify the local
files without network access. Script tags also carry matching integrity hashes,
so browsers refuse to execute scripts whose bytes have changed.

To check that the upstream CDN still matches both the recorded hashes and local
files, explicitly enable the network tests:

```sh
CHECK_VENDOR_UPSTREAM=1 python -m pytest -q tests/test_vendor.py
```

GitHub Actions runs the offline suite and upstream comparisons on pushes and
pull requests. The workflow can also be started manually from the Actions tab.
It uses commit-pinned Actions with read-only repository permissions.

These checks never update files or hashes. When upgrading a library, review the
release and its source, replace the bundled files, and update the manifest and
HTML integrity values together. Preserve the licenses. Do not update a hash just
to silence a failed comparison.

Local copies and integrity hashes reduce exposure to upstream changes, as
described by [OWASP](https://cheatsheetseries.owasp.org/cheatsheets/Third_Party_Javascript_Management_Cheat_Sheet.html).
They do not prove that the original code is benign or free of vulnerabilities.
These checks cover browser assets. Python packages and the Docker base image
are still fetched during installation or image builds.
