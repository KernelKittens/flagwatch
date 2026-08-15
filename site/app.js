(() => {
  "use strict";

  const FALLBACK_ZONE = "America/Chicago";
  const ZONE_KEY = "flagwatch.timeZone";
  const state = {
    events: [],
    month: parseMonth(new URLSearchParams(location.search).get("month")) || monthStart(new Date()),
    timeZone: localStorage.getItem(ZONE_KEY) || detectZone(),
    selectedDate: null,
    expandedDates: new Set(),
  };

  const elements = {
    calendar: document.querySelector("#calendar"),
    heading: document.querySelector("#month-heading"),
    status: document.querySelector("#status"),
    timezoneButton: document.querySelector("#timezone-button"),
    timezoneConfirm: document.querySelector("#timezone-confirm"),
    timezoneChooser: document.querySelector("#timezone-chooser"),
    timezoneSelect: document.querySelector("#timezone-select"),
    detectedTimezone: document.querySelector("#detected-timezone"),
    confirmTimezone: document.querySelector("#confirm-timezone"),
    selectedHeading: document.querySelector("#selected-day-heading"),
    selectedEvents: document.querySelector("#selected-day-events"),
    eventDialog: document.querySelector("#event-dialog"),
    eventTitle: document.querySelector("#event-title"),
    eventBody: document.querySelector("#event-detail-body"),
  };

  function detectZone() {
    try {
      return Intl.DateTimeFormat().resolvedOptions().timeZone || FALLBACK_ZONE;
    } catch (_) {
      return FALLBACK_ZONE;
    }
  }

  function monthStart(date) {
    return new Date(Date.UTC(date.getUTCFullYear(), date.getUTCMonth(), 1));
  }

  function parseMonth(value) {
    if (!/^\d{4}-\d{2}$/.test(value || "")) return null;
    const [year, month] = value.split("-").map(Number);
    if (month < 1 || month > 12) return null;
    return new Date(Date.UTC(year, month - 1, 1));
  }

  function monthKey(date) {
    return `${date.getUTCFullYear()}-${String(date.getUTCMonth() + 1).padStart(2, "0")}`;
  }

  function dateKey(date, timeZone = state.timeZone) {
    const parts = new Intl.DateTimeFormat("en-US", {
      timeZone,
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
    }).formatToParts(date);
    const values = Object.fromEntries(parts.map((part) => [part.type, part.value]));
    return `${values.year}-${values.month}-${values.day}`;
  }

  function escapeHtml(value) {
    return String(value ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#039;");
  }

  function eventDays(event) {
    const startKey = dateKey(new Date(event.starts_at));
    const finishKey = dateKey(new Date(event.finishes_at));
    const days = [];
    let cursor = new Date(`${startKey}T12:00:00Z`);
    const last = new Date(`${finishKey}T12:00:00Z`);
    while (cursor <= last) {
      days.push(cursor.toISOString().slice(0, 10));
      cursor.setUTCDate(cursor.getUTCDate() + 1);
    }
    return days;
  }

  function eventsOn(date) {
    return state.events.filter((event) => eventDays(event).includes(date));
  }

  function updateUrl(values = {}) {
    const params = new URLSearchParams(location.search);
    params.set("month", monthKey(state.month));
    for (const [key, value] of Object.entries(values)) {
      if (value) {
        params.set(key, value);
      } else {
        params.delete(key);
      }
    }
    history.replaceState(null, "", `${location.pathname}?${params}`);
  }

  function setMonth(delta) {
    state.month = new Date(
      Date.UTC(state.month.getUTCFullYear(), state.month.getUTCMonth() + delta, 1),
    );
    state.selectedDate = null;
    updateUrl({event: null});
    renderCalendar();
  }

  function renderCalendar() {
    elements.heading.textContent = new Intl.DateTimeFormat("en-US", {
      month: "long",
      year: "numeric",
      timeZone: "UTC",
    }).format(state.month);
    document.title = `${elements.heading.textContent} CTFs | Flagwatch`;
    elements.calendar.replaceChildren();
    ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"].forEach((name) => {
      const heading = document.createElement("div");
      heading.className = "weekday";
      heading.textContent = name;
      elements.calendar.append(heading);
    });

    const first = new Date(state.month);
    first.setUTCDate(1 - first.getUTCDay());
    const currentMonth = state.month.getUTCMonth();
    const today = dateKey(new Date());
    for (let offset = 0; offset < 42; offset += 1) {
      const date = new Date(first);
      date.setUTCDate(first.getUTCDate() + offset);
      const key = date.toISOString().slice(0, 10);
      const cell = document.createElement("div");
      cell.className = "calendar-cell";
      cell.dataset.date = key;
      if (date.getUTCMonth() !== currentMonth) cell.classList.add("outside");
      if (key === state.selectedDate) cell.classList.add("selected");

      const dayButton = document.createElement("button");
      dayButton.type = "button";
      dayButton.className = `day-select${key === today ? " today" : ""}`;
      dayButton.textContent = String(date.getUTCDate());
      dayButton.setAttribute("aria-label", new Intl.DateTimeFormat("en-US", {
        weekday: "long", month: "long", day: "numeric", year: "numeric", timeZone: "UTC",
      }).format(date));
      dayButton.addEventListener("click", () => selectDay(key));
      cell.append(dayButton);

      const eventList = document.createElement("div");
      eventList.className = "cell-events";
      const events = eventsOn(key);
      const expanded = state.expandedDates.has(key);
      const visible = expanded ? events : events.slice(0, 3);
      visible.forEach((event) => eventList.append(eventButton(event, "event-chip")));
      if (!expanded && events.length > 3) {
        const more = document.createElement("button");
        more.type = "button";
        more.className = "more-events";
        more.textContent = `${events.length - 3} more events`;
        more.addEventListener("click", () => {
          state.expandedDates.add(key);
          renderCalendar();
        });
        eventList.append(more);
      }
      cell.append(eventList);
      elements.calendar.append(cell);
    }
    if (state.selectedDate) renderSelectedDay();
  }

  function eventButton(event, className) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = className;
    button.dataset.policy = event.ai_policy;
    button.textContent = event.title;
    button.addEventListener("click", () => openEvent(event));
    return button;
  }

  function selectDay(key) {
    state.selectedDate = key;
    renderCalendar();
  }

  function renderSelectedDay() {
    const date = new Date(`${state.selectedDate}T12:00:00Z`);
    elements.selectedHeading.textContent = new Intl.DateTimeFormat("en-US", {
      weekday: "long", month: "long", day: "numeric", timeZone: "UTC",
    }).format(date);
    elements.selectedEvents.replaceChildren();
    const events = eventsOn(state.selectedDate);
    if (!events.length) {
      const empty = document.createElement("p");
      empty.className = "day-empty";
      empty.textContent = "No CTFs scheduled for this day.";
      elements.selectedEvents.append(empty);
      return;
    }
    events.forEach((event) => elements.selectedEvents.append(eventButton(event, "day-event")));
  }

  function policyLabel(event) {
    if (event.ai_policy_conflicting) return "Conflicting AI rules";
    if (event.analysis_stale) return "AI policy needs rechecking";
    return {
      ai_assisted: "AI assisted",
      banned: "AI banned",
      unknown: "AI policy unknown",
      automated_only_banned: "Automated solvers banned",
    }[event.ai_policy] || "AI policy unknown";
  }

  function formatDateTime(value) {
    return new Intl.DateTimeFormat("en-US", {
      timeZone: state.timeZone,
      month: "short", day: "numeric", year: "numeric", hour: "numeric", minute: "2-digit",
      timeZoneName: "short",
    }).format(new Date(value));
  }

  function duration(event) {
    const hours = Math.round((new Date(event.finishes_at) - new Date(event.starts_at)) / 3600000);
    const days = Math.floor(hours / 24);
    const remainingHours = hours % 24;
    const parts = [
      days ? `${days} day${days === 1 ? "" : "s"}` : "",
      remainingHours ? `${remainingHours} hour${remainingHours === 1 ? "" : "s"}` : "",
    ];
    return parts.filter(Boolean).join(" ");
  }

  function display(value, fallback = "Not listed") {
    if (Array.isArray(value)) return value.length ? value.join(", ") : fallback;
    return value === null || value === undefined || value === "" ? fallback : String(value);
  }

  function icsTimestamp(value) {
    return new Date(value)
      .toISOString()
      .replaceAll("-", "")
      .replaceAll(":", "")
      .replace(".000", "");
  }

  function icsLink(event) {
    const body = [
      "BEGIN:VCALENDAR",
      "VERSION:2.0",
      "PRODID:-//Flagwatch//CTF Calendar//EN",
      "BEGIN:VEVENT",
      `UID:${event.event_key}@flagwatch`,
      `DTSTART:${icsTimestamp(event.starts_at)}`,
      `DTEND:${icsTimestamp(event.finishes_at)}`,
      `SUMMARY:${event.title.replaceAll("\n", " ")}`,
      `URL:${event.official_url}`,
      "END:VEVENT",
      "END:VCALENDAR",
    ].join("\r\n");
    return `data:text/calendar;charset=utf-8,${encodeURIComponent(body)}`;
  }

  function slug(value) {
    return value.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");
  }

  function policyClass(event) {
    if (event.ai_policy === "banned") return "banned";
    if (event.ai_policy === "unknown") return "unknown";
    return "";
  }

  function scheduleLabel(event) {
    if (event.schedule_mode === "staggered") return "Staggered";
    if (event.schedule_mode === "fixed") return "Fixed";
    return "Unknown";
  }

  function locationLabel(event) {
    if (event.online && event.onsite) return "Online and onsite";
    if (event.onsite) return "Onsite";
    return "Online";
  }

  function openEvent(event) {
    elements.eventTitle.textContent = event.title;
    const evidenceLink = event.ai_policy_source
      ? `<a href="${escapeHtml(event.ai_policy_source)}" target="_blank" rel="noopener noreferrer">AI policy source</a>`
      : "";
    const details = [
      ["Starts", formatDateTime(event.starts_at)],
      ["Ends", formatDateTime(event.finishes_at)],
      ["Duration", duration(event)],
      ["Prizes", display(event.prize_summary)],
      ["Team max", display(event.team_max)],
      ["Divisions", display(event.divisions)],
      ["Format", display(event.format)],
      ["Weight", display(event.weight)],
      ["Schedule", scheduleLabel(event)],
      ["Location", locationLabel(event)],
      ["Registration", display(event.registration_status)],
      ["Categories", display(event.categories)],
    ];
    elements.eventBody.innerHTML = `
      <section class="policy-banner ${policyClass(event)}" aria-label="AI policy">
        <strong>${escapeHtml(policyLabel(event))}</strong>
        <span>${escapeHtml(display(event.ai_policy_reason, "No current AI rule was found."))}</span>
        ${event.ai_policy_evidence ? `<p class="evidence">${escapeHtml(event.ai_policy_evidence)}</p>` : ""}
      </section>
      <dl class="detail-grid">${details.map(([term, value]) => `<div class="detail-item"><dt>${escapeHtml(term)}</dt><dd>${escapeHtml(value)}</dd></div>`).join("")}</dl>
      <nav class="event-links" aria-label="Event links">
        <a href="${escapeHtml(event.official_url)}" target="_blank" rel="noopener noreferrer">Official event</a>
        <a href="${escapeHtml(event.ctftime_url)}" target="_blank" rel="noopener noreferrer">CTFtime listing</a>
        ${evidenceLink}
        <a href="${icsLink(event)}" download="${slug(event.title)}.ics">Download ICS</a>
      </nav>`;
    updateUrl({event: event.event_key});
    elements.eventDialog.showModal();
  }

  function closeEvent() {
    if (elements.eventDialog.open) elements.eventDialog.close();
    updateUrl({event: null});
  }

  function populateZones() {
    let zones = [FALLBACK_ZONE, "America/New_York", "America/Denver", "America/Los_Angeles", "Europe/London", "UTC"];
    if (typeof Intl.supportedValuesOf === "function") zones = Intl.supportedValuesOf("timeZone");
    if (!zones.includes(state.timeZone)) zones = [state.timeZone, ...zones];
    elements.timezoneSelect.replaceChildren(...zones.map((zone) => new Option(zone, zone)));
    elements.timezoneSelect.value = state.timeZone;
  }

  function updateTimezoneButton() {
    elements.timezoneButton.textContent = state.timeZone;
    elements.timezoneButton.setAttribute("aria-label", `Change timezone: ${state.timeZone}`);
  }

  function eventFromUrl() {
    const eventKey = new URLSearchParams(location.search).get("event");
    return state.events.find((event) => event.event_key === eventKey);
  }

  function saveZone(zone) {
    state.timeZone = zone || FALLBACK_ZONE;
    localStorage.setItem(ZONE_KEY, state.timeZone);
    updateTimezoneButton();
    populateZones();
    renderCalendar();
    if (elements.eventDialog.open) {
      const event = eventFromUrl();
      if (event) openEvent(event);
    }
  }

  async function loadEvents() {
    try {
      const apiBase = String(window.FLAGWATCH_API_BASE || "").replace(/\/$/, "");
      const response = await fetch(`${apiBase}/api/events`, {headers: {Accept: "application/json"}});
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const payload = await response.json();
      state.events = Array.isArray(payload.events) ? payload.events : [];
      elements.status.textContent = `${state.events.length} CTF${state.events.length === 1 ? "" : "s"} in this feed. Times shown in ${state.timeZone}.`;
      renderCalendar();
      const event = eventFromUrl();
      if (event) openEvent(event);
    } catch (_) {
      elements.status.textContent = "The calendar feed is unavailable right now. Please try again shortly.";
      renderCalendar();
    }
  }

  document.querySelector("#previous-month").addEventListener("click", () => setMonth(-1));
  document.querySelector("#next-month").addEventListener("click", () => setMonth(1));
  document.querySelector("#today").addEventListener("click", () => {
    state.month = monthStart(new Date());
    updateUrl({event: null});
    renderCalendar();
  });
  document.querySelectorAll("[data-close]").forEach((button) => button.addEventListener("click", closeEvent));
  elements.eventDialog.addEventListener("close", () => updateUrl({event: null}));
  elements.eventDialog.addEventListener("cancel", (event) => {
    event.preventDefault();
    closeEvent();
  });
  elements.eventDialog.addEventListener("click", (event) => {
    if (event.target === elements.eventDialog) closeEvent();
  });
  elements.timezoneButton.addEventListener("click", () => {
    populateZones();
    elements.timezoneChooser.showModal();
  });
  elements.confirmTimezone.addEventListener("click", () => saveZone(state.timeZone));
  document.querySelector("#timezone-form").addEventListener("submit", (event) => {
    if (event.submitter?.value === "save") saveZone(elements.timezoneSelect.value);
  });
  elements.timezoneConfirm.addEventListener("close", () => {
    if (elements.timezoneConfirm.returnValue === "confirm") saveZone(state.timeZone);
    if (elements.timezoneConfirm.returnValue === "choose") {
      populateZones();
      elements.timezoneChooser.showModal();
    }
  });

  updateTimezoneButton();
  if (!localStorage.getItem(ZONE_KEY)) {
    elements.detectedTimezone.textContent = state.timeZone;
    elements.confirmTimezone.textContent = `Use ${state.timeZone}`;
    elements.timezoneConfirm.showModal();
  }
  updateUrl();
  loadEvents();
})();
