"use strict";

document.addEventListener("DOMContentLoaded", () => {
  const refresh = document.getElementById("refresh");
  const upload = document.getElementById("upload");
  const reset = document.getElementById("reset");
  const fileInput = document.getElementById("org-file");
  const dropOverlay = document.getElementById("drop-overlay");
  const sourceLabel = document.getElementById("source");
  const status = document.getElementById("status");
  const warning = document.getElementById("warning");
  const empty = document.getElementById("empty");
  const timezone = Intl.DateTimeFormat().resolvedOptions().timeZone;
  document.getElementById("timezone").textContent = `Local time · ${timezone}`;

  if (!window.FullCalendar || !window.ICAL || !FullCalendar.ICalendar) {
    status.textContent = "Calendar could not load.";
    warning.textContent = "Calendar scripts could not load. Restore the bundled files and reload the page.";
    warning.hidden = false;
    refresh.addEventListener("click", () => window.location.reload());
    return;
  }

  const sourceStatus = new Map();
  let loading = true;
  let uploading = false;
  let uploadedFile = null;
  let eventCount = 0;
  let lastRefresh = "";
  const types = [
    ["TIMESTAMP", "#3779c4"],
    ["SCHEDULED", "#27835c"],
    ["DEADLINE", "#c64b50"],
  ];

  function updateStatus() {
    const results = [...sourceStatus.values()];
    const messages = [...new Set(results.flatMap((result) => result.warnings))];
    const failed = results.some((result) => !result.ok);
    status.textContent = uploading ? "Reading Org file…" : loading ? "Refreshing calendar…" :
      failed ? "Some events could not load." : `Updated ${lastRefresh}`;
    warning.textContent = messages.join(" ");
    warning.hidden = messages.length === 0;
    refresh.disabled = upload.disabled = reset.disabled = loading || uploading;
    refresh.setAttribute("aria-busy", String(loading || uploading));
    empty.hidden = loading || uploading || failed || eventCount > 0;
  }

  function eventSources(snapshot = null) {
    return types.map(([type, color]) => ({
      url: snapshot ? snapshot.urls[type] : `/calendar.ics?event_type=${type}`,
      format: "ics",
      backgroundColor: type === "SCHEDULED" ? "transparent" : color,
      borderColor: color,
      textColor: type === "SCHEDULED" ? color : "#fff",
      success(events, response) {
        sourceStatus.set(type, {
          ok: response.ok,
          warnings: snapshot ? snapshot.warnings : JSON.parse(response.headers.get("X-Calendar-Warnings") || "[]"),
        });
        return events;
      },
      failure() {
        sourceStatus.set(type, {
          ok: false,
          warnings: ["Could not load the calendar. Check the server and press Refresh to try again."],
        });
        updateStatus();
      },
    }));
  }

  function setSources(snapshot) {
    const previous = uploadedFile;
    uploadedFile = snapshot;
    sourceStatus.clear();
    sourceLabel.textContent = snapshot ? `${snapshot.name} · Re-upload after edits` : "Default calendar";
    reset.hidden = !snapshot;
    calendar.batchRendering(() => {
      calendar.getEventSources().forEach((source) => source.remove());
      eventSources(snapshot).forEach((source) => calendar.addEventSource(source));
    });
    if (previous) Object.values(previous.urls).forEach((url) => URL.revokeObjectURL(url));
  }

  const calendar = new FullCalendar.Calendar(document.getElementById("calendar"), {
    initialView: "dayGridMonth",
    headerToolbar: { left: "prev,next today", center: "title", right: "dayGridMonth,timeGridWeek" },
    buttonText: { today: "Today", month: "Month", week: "Week" },
    timeZone: "local",
    firstDay: 0,
    height: "auto",
    nowIndicator: true,
    editable: false,
    selectable: false,
    navLinks: false,
    dayMaxEvents: 3,
    allDayText: "All day",
    eventDisplay: "block",
    eventTimeFormat: { hour: "2-digit", minute: "2-digit", hour12: false },
    slotLabelFormat: { hour: "2-digit", minute: "2-digit", hour12: false },
    scrollTime: "08:00:00",
    eventSources: eventSources(),
    loading(isLoading) {
      loading = isLoading;
      if (!isLoading) lastRefresh = new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
      updateStatus();
    },
    eventsSet(events) {
      eventCount = events.length;
      updateStatus();
    },
    eventDidMount({ event, el, timeText }) {
      const description = event.extendedProps.description || "";
      el.title = `${event.title}\n${event.allDay ? "All day" : timeText}${description ? `\n\n${description}` : ""}`;
    },
    windowResize() {
      calendar.setOption("dayHeaderFormat", window.innerWidth < 600 ? { weekday: "narrow" } : { weekday: "short" });
    },
  });

  upload.addEventListener("click", () => fileInput.click());
  async function uploadFile(file) {
    if (!file || loading || uploading) return;
    const urls = {};
    uploading = true;
    updateStatus();
    try {
      if (!file.name.toLowerCase().endsWith(".org")) throw new Error("Choose an .org file.");
      const response = await fetch(`/upload?filename=${encodeURIComponent(file.name)}`, {
        method: "POST",
        headers: { "Content-Type": "application/octet-stream" },
        body: file,
      });
      if (!response.ok) {
        const error = await response.json().catch(() => ({}));
        throw new Error(error.detail || "Could not read this Org file.");
      }
      const data = new ICAL.Component(ICAL.parse(await response.text()));
      const events = data.getAllSubcomponents("vevent");
      // The iCalendar plugin takes GET URLs. Keep one in-memory feed per color.
      for (const [type] of types) {
        const feed = new ICAL.Component("vcalendar");
        feed.addPropertyWithValue("version", "2.0");
        feed.addPropertyWithValue("prodid", "-//Org calendar//Upload//EN");
        for (const event of events) {
          if (event.getFirstPropertyValue("categories") === type) {
            feed.addSubcomponent(new ICAL.Component(event.toJSON()));
          }
        }
        urls[type] = URL.createObjectURL(new Blob([feed.toString()], { type: "text/calendar" }));
      }
      uploading = false;
      setSources({ name: file.name, urls, warnings: JSON.parse(response.headers.get("X-Calendar-Warnings") || "[]") });
    } catch (error) {
      Object.values(urls).forEach((url) => URL.revokeObjectURL(url));
      uploading = false;
      updateStatus();
      warning.textContent = error.message || "Could not read this Org file.";
      warning.hidden = false;
    } finally {
      uploading = false;
      fileInput.value = "";
      // Preserve any upload error displayed above.
      refresh.disabled = upload.disabled = reset.disabled = loading;
      refresh.setAttribute("aria-busy", String(loading));
    }
  }

  fileInput.addEventListener("change", () => uploadFile(fileInput.files[0]));

  let dragDepth = 0;
  function isFileDrag(event) {
    return Array.from(event.dataTransfer?.types || []).includes("Files");
  }
  function clearDrag() {
    dragDepth = 0;
    dropOverlay.hidden = true;
  }
  document.addEventListener("dragenter", (event) => {
    if (!isFileDrag(event)) return;
    event.preventDefault();
    dragDepth += 1;
    dropOverlay.hidden = loading || uploading;
  });
  document.addEventListener("dragover", (event) => {
    if (!isFileDrag(event)) return;
    event.preventDefault();
    event.dataTransfer.dropEffect = loading || uploading ? "none" : "copy";
  });
  document.addEventListener("dragleave", () => {
    dragDepth = Math.max(0, dragDepth - 1);
    if (!dragDepth) clearDrag();
  });
  document.addEventListener("drop", (event) => {
    if (!isFileDrag(event)) return;
    event.preventDefault();
    clearDrag();
    if (loading || uploading) return;
    const files = event.dataTransfer.files;
    if (files.length !== 1) {
      warning.textContent = "Drop one .org file at a time.";
      warning.hidden = false;
      return;
    }
    uploadFile(files[0]);
  });
  document.addEventListener("dragend", clearDrag);
  window.addEventListener("blur", clearDrag);
  reset.addEventListener("click", () => setSources(null));
  refresh.addEventListener("click", () => calendar.refetchEvents());
  calendar.render();
});
