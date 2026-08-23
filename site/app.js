(() => {
  "use strict";

  const FALLBACK_ZONE = "America/Chicago";
  const ZONE_KEY = "flagwatch.timeZone";
  const SNAPSHOT_KEY = "flagwatch.snapshot.v1";
  const SNAPSHOT_MAX_AGE_MS = 30 * 24 * 60 * 60 * 1000;
  const FETCH_DELAYS_MS = [0, 250, 750];
  const savedZone = readSavedZone();
  const initialZone = savedZone || detectZone();
  const state = {
    events: [],
    scanSummary: null,
    generatedAt: null,
    month: monthFromUrl(initialZone),
    timeZone: initialZone,
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
    scanUpdated: document.querySelector("#scan-updated"),
    scanEvents: document.querySelector("#scan-events"),
    scanSources: document.querySelector("#scan-sources"),
    scanRecheck: document.querySelector("#scan-recheck"),
    scanConfirmed: document.querySelector("#scan-confirmed"),
  };

  function detectZone() {
    try {
      return Intl.DateTimeFormat().resolvedOptions().timeZone || FALLBACK_ZONE;
    } catch (_) {
      return FALLBACK_ZONE;
    }
  }

  function validZone(zone) {
    try {
      new Intl.DateTimeFormat("en-US", {timeZone: zone}).format(new Date());
      return Boolean(zone);
    } catch (_) {
      return false;
    }
  }

  function readSavedZone() {
    const zone = localStorage.getItem(ZONE_KEY);
    if (validZone(zone)) return zone;
    if (zone) localStorage.removeItem(ZONE_KEY);
    return null;
  }

  function partsInZone(date, timeZone) {
    const parts = new Intl.DateTimeFormat("en-US", {
      timeZone,
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
    }).formatToParts(date);
    return Object.fromEntries(parts.map((part) => [part.type, part.value]));
  }

  function monthForDate(date, timeZone) {
    const parts = partsInZone(date, timeZone);
    return new Date(Date.UTC(Number(parts.year), Number(parts.month) - 1, 1));
  }

  function parseMonth(value) {
    if (!/^\d{4}-\d{2}$/.test(value || "")) return null;
    const [year, month] = value.split("-").map(Number);
    if (month < 1 || month > 12) return null;
    return new Date(Date.UTC(year, month - 1, 1));
  }

  function monthFromUrl(timeZone) {
    const month = new URLSearchParams(location.search).get("month");
    return parseMonth(month) || monthForDate(new Date(), timeZone);
  }

  function monthKey(date) {
    return `${date.getUTCFullYear()}-${String(date.getUTCMonth() + 1).padStart(2, "0")}`;
  }

  function dateKey(date, timeZone = state.timeZone) {
    const values = partsInZone(date, timeZone);
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
    const start = new Date(event.starts_at);
    const finish = new Date(event.finishes_at);
    const occupiedFinish = finish > start ? new Date(finish.getTime() - 1) : finish;
    const finishKey = dateKey(occupiedFinish);
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

  function updateUrl(values = {}, mode = "replace") {
    const params = new URLSearchParams(location.search);
    params.set("month", monthKey(state.month));
    for (const [key, value] of Object.entries(values)) {
      if (value) {
        params.set(key, value);
      } else {
        params.delete(key);
      }
    }
    const url = `${location.pathname}?${params}`;
    if (mode === "push") {
      history.pushState(null, "", url);
    } else {
      history.replaceState(null, "", url);
    }
  }

  function setMonth(delta) {
    state.month = new Date(
      Date.UTC(state.month.getUTCFullYear(), state.month.getUTCMonth() + delta, 1),
    );
    state.selectedDate = null;
    updateUrl({event: null}, "push");
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
    const headerRow = document.createElement("div");
    headerRow.className = "calendar-row";
    headerRow.setAttribute("role", "row");
    ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"].forEach((name) => {
      const heading = document.createElement("div");
      heading.className = "weekday";
      heading.setAttribute("role", "columnheader");
      heading.textContent = name;
      headerRow.append(heading);
    });
    elements.calendar.append(headerRow);

    const first = new Date(state.month);
    first.setUTCDate(1 - first.getUTCDay());
    const currentMonth = state.month.getUTCMonth();
    const today = dateKey(new Date());
    let weekRow;
    for (let offset = 0; offset < 42; offset += 1) {
      if (offset % 7 === 0) {
        weekRow = document.createElement("div");
        weekRow.className = "calendar-row";
        weekRow.setAttribute("role", "row");
        elements.calendar.append(weekRow);
      }
      const date = new Date(first);
      date.setUTCDate(first.getUTCDate() + offset);
      const key = date.toISOString().slice(0, 10);
      const cell = document.createElement("div");
      cell.className = "calendar-cell";
      cell.setAttribute("role", "gridcell");
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
      visible.forEach((event) => eventList.append(eventButton(event, "event-chip", true)));
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
      if (events.length) {
        const markers = document.createElement("span");
        markers.className = "mobile-markers";
        markers.setAttribute("aria-label", `${events.length} event${events.length === 1 ? "" : "s"}`);
        events.slice(0, 5).forEach((event) => {
          const marker = document.createElement("span");
          marker.dataset.verification = verificationState(event);
          marker.setAttribute("aria-hidden", "true");
          markers.append(marker);
        });
        cell.append(markers);
      }
      weekRow.append(cell);
    }
    if (state.selectedDate) renderSelectedDay();
  }

  function eventButton(event, className, includeTime = false) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = className;
    button.dataset.verification = verificationState(event);
    const title = document.createElement("span");
    title.className = "event-name";
    title.textContent = event.title;
    button.append(title);
    if (includeTime) {
      const time = document.createElement("span");
      time.className = "event-time";
      time.textContent = new Intl.DateTimeFormat("en-US", {
        timeZone: state.timeZone,
        hour: "numeric",
        minute: "2-digit",
      }).format(new Date(event.starts_at));
      button.setAttribute("aria-label", `${event.title}, starts ${time.textContent}`);
      button.append(time);
    }
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
    events.forEach((event) =>
      elements.selectedEvents.append(eventButton(event, "day-event", true)),
    );
  }

  function policyLabel(event) {
    if (event.ai_policy_conflicting) return "Conflicting AI rules";
    if (event.analysis_stale) return "AI policy needs rechecking";
    return {
      ai_native: "AI native",
      ai_assisted: "AI assisted",
      human_only: "AI-assisted solving prohibited",
      unknown: "AI policy unknown",
    }[event.ai_policy] || "AI policy unknown";
  }

  function policyIsConfirmed(event) {
    return (
      ["ai_native", "ai_assisted", "human_only"].includes(event.ai_policy) &&
      !event.analysis_stale &&
      !event.ai_policy_conflicting
    );
  }

  function verificationState(event) {
    return policyIsConfirmed(event) ? "verified" : "unverified";
  }

  function formatDateTime(value) {
    return new Intl.DateTimeFormat("en-US", {
      timeZone: state.timeZone,
      month: "short", day: "numeric", year: "numeric", hour: "numeric", minute: "2-digit",
      timeZoneName: "short",
    }).format(new Date(value));
  }

  function duration(event) {
    const totalMinutes = Math.max(
      0,
      Math.round((new Date(event.finishes_at) - new Date(event.starts_at)) / 60000),
    );
    const days = Math.floor(totalMinutes / 1440);
    const remainingHours = Math.floor((totalMinutes % 1440) / 60);
    const minutes = totalMinutes % 60;
    const parts = [
      days ? `${days} day${days === 1 ? "" : "s"}` : "",
      remainingHours ? `${remainingHours} hour${remainingHours === 1 ? "" : "s"}` : "",
      minutes ? `${minutes} minute${minutes === 1 ? "" : "s"}` : "",
    ];
    return parts.filter(Boolean).join(" ") || "0 minutes";
  }

  function display(value, fallback = "Unknown") {
    if (Array.isArray(value)) return value.length ? value.join(", ") : fallback;
    return value === null || value === undefined || value === "" ? fallback : String(value);
  }

  function eventStatus(event) {
    const now = Date.now();
    if (now >= new Date(event.finishes_at).getTime()) return "Finished";
    if (now >= new Date(event.starts_at).getTime()) return "Live now";
    return "Upcoming";
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
    if (event.ai_policy === "human_only" && policyIsConfirmed(event)) return "banned";
    if (!policyIsConfirmed(event)) return "unknown";
    return "";
  }

  function policyVerdict(event) {
    const confirmed = policyIsConfirmed(event);
    const eligible = confirmed && ["ai_native", "ai_assisted"].includes(event.ai_policy);
    const checkedAt = event.source_checked_at
      ? `Checked ${formatDateTime(event.source_checked_at)}`
      : "Not checked yet";
    const source = event.ai_policy_source
      ? `<a class="policy-source" href="${escapeHtml(event.ai_policy_source)}" target="_blank" rel="noopener noreferrer">Read official AI rules</a>`
      : "";
    return `
      <section class="policy-verdict ${policyClass(event)}" aria-labelledby="ai-rules-title">
        <div class="policy-heading">
          <p class="eyebrow">AI rules</p>
          <span class="policy-status">${confirmed ? "Verified" : "Needs recheck"}</span>
        </div>
        <h3 id="ai-rules-title">${escapeHtml(policyLabel(event))}</h3>
        <p class="policy-reason">${escapeHtml(display(event.ai_policy_reason, "No published AI rule was found."))}</p>
        ${event.ai_policy_evidence ? `<blockquote>${escapeHtml(event.ai_policy_evidence)}</blockquote>` : ""}
        <p class="policy-checked">${escapeHtml(checkedAt)}</p>
        <div class="policy-actions">
          ${source}
          <strong>${eligible ? "Subscribed members can be pinged" : "No Discord alert"}</strong>
        </div>
      </section>`;
  }

  function scanLedger(event) {
    const sourceState = event.source_scan_status || "not_checked";
    const sourceMark = sourceState === "read" ? "OK" : "!";
    const sourceClass = sourceState === "read" ? "" : " warn";
    const rulesFound = Number(event.source_rule_pages_found || 0);
    const rulesText = rulesFound
      ? `${rulesFound} dedicated rule page${rulesFound === 1 ? "" : "s"} read.`
      : "No dedicated rules page found.";
    const alertAllowed = ["ai_native", "ai_assisted"].includes(event.ai_policy) &&
      policyIsConfirmed(event);
    const decision = alertAllowed ? "Verified, alerts allowed" : "Unverified, no alert";
    const decisionDetail = alertAllowed
      ? "Current official evidence confirms compatible AI use."
      : "Flagwatch will recheck this event and will not notify Discord without current official evidence.";
    return `
      <section class="scan-ledger" aria-labelledby="source-scan-title">
        <div class="scan-ledger-heading">
          <p class="eyebrow">Source check</p>
          <h3 id="source-scan-title">What the scan found</h3>
        </div>
        <ol>
          <li><span class="scan-mark">OK</span><strong>CTFtime record</strong><span>Schedule and official URL imported.</span></li>
          <li><span class="scan-mark${sourceClass}">${sourceMark}</span><strong>Official source</strong><span>${escapeHtml(display(event.source_scan_reason, "Official source has not been checked yet"))}</span></li>
          <li><span class="scan-mark${rulesFound ? "" : " warn"}">${rulesFound ? "OK" : "!"}</span><strong>Rules discovery</strong><span>${escapeHtml(rulesText)}</span></li>
          <li><span class="scan-mark${alertAllowed ? "" : " warn"}">${alertAllowed ? "OK" : "!"}</span><strong>Alert decision</strong><span>${escapeHtml(decisionDetail)}</span></li>
        </ol>
        <div class="alert-decision${alertAllowed ? "" : " warn"}"><strong>${escapeHtml(decision)}</strong></div>
      </section>`;
  }

  function intelTopicLabel(topic) {
    return {
      overview: "Overview",
      eligibility: "Eligibility",
      registration: "Registration",
      format: "Format",
      schedule: "Schedule",
      prizes: "Prizes",
      conduct: "Conduct",
      flag_sharing: "Flag sharing",
      platform: "Platform",
      ai_policy: "AI policy",
      other: "Other rules",
    }[topic] || "Other rules";
  }

  function eventIntelligence(event) {
    const claims = Array.isArray(event.intel_claims) ? event.intel_claims : [];
    if (!claims.length) return "";
    const grouped = new Map();
    claims.forEach((claim) => {
      const topic = intelTopicLabel(claim.topic);
      if (!grouped.has(topic)) grouped.set(topic, []);
      grouped.get(topic).push(claim);
    });
    const groups = [...grouped.entries()].map(([topic, topicClaims]) => `
      <section class="intel-group" aria-labelledby="intel-${slug(topic)}">
        <h4 id="intel-${slug(topic)}">${escapeHtml(topic)}</h4>
        <div class="intel-claims">
          ${topicClaims.map((claim) => `
            <article class="intel-claim">
              <div class="intel-claim-heading">
                <h5>${escapeHtml(claim.label)}</h5>
                <a href="${escapeHtml(claim.source_url)}" target="_blank" rel="noopener noreferrer" aria-label="Source for ${escapeHtml(claim.label)}">Official source</a>
              </div>
              <p class="intel-value">${escapeHtml(claim.value)}</p>
              <blockquote>${escapeHtml(claim.evidence)}</blockquote>
            </article>`).join("")}
        </div>
      </section>`).join("");
    const analyzed = event.intel_analyzed_at
      ? `Checked ${formatDateTime(event.intel_analyzed_at)}`
      : "Analysis time unavailable";
    const model = event.intel_model ? ` with ${event.intel_model}` : "";
    const stale = event.intel_stale ? " Saved intelligence is marked stale." : "";
    return `
      <section class="event-intel" aria-labelledby="event-intel-title">
        <div class="event-intel-heading">
          <p class="eyebrow">Rules dossier</p>
          <h3 id="event-intel-title">Event intelligence</h3>
          <p>Extracted from public event sources${escapeHtml(model)}. Every item includes the supporting quote.</p>
          <small>${escapeHtml(analyzed)}.${escapeHtml(stale)}</small>
        </div>
        ${groups}
      </section>`;
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

  function openEvent(event, updateHistory = true) {
    elements.eventTitle.textContent = event.title;
    const details = [
      ["Status", eventStatus(event)],
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
      ["Organizers", display(event.organizers)],
      ["Participants", display(event.participants)],
    ];
    elements.eventBody.innerHTML = `
      ${policyVerdict(event)}
      ${scanLedger(event)}
      ${eventIntelligence(event)}
      <dl class="detail-grid">${details.map(([term, value]) => `<div class="detail-item"><dt>${escapeHtml(term)}</dt><dd>${escapeHtml(value)}</dd></div>`).join("")}</dl>
      <nav class="event-links" aria-label="Event links">
        <a href="${escapeHtml(event.official_url)}" target="_blank" rel="noopener noreferrer">Official event</a>
        <a href="${escapeHtml(event.ctftime_url)}" target="_blank" rel="noopener noreferrer">CTFtime listing</a>
        <a href="${icsLink(event)}" download="${slug(event.title)}.ics">Download ICS</a>
      </nav>`;
    if (updateHistory) updateUrl({event: event.event_key}, "push");
    if (!elements.eventDialog.open) elements.eventDialog.showModal();
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
      if (event) openEvent(event, false);
    }
  }

  function delay(milliseconds) {
    return new Promise((resolve) => setTimeout(resolve, milliseconds));
  }

  function validSnapshot(payload) {
    return Boolean(
      payload &&
      typeof payload.generated_at === "string" &&
      Array.isArray(payload.events),
    );
  }

  function saveSnapshot(payload) {
    try {
      localStorage.setItem(SNAPSHOT_KEY, JSON.stringify({
        saved_at: new Date().toISOString(),
        payload,
      }));
    } catch (_) {
      return;
    }
  }

  function readSnapshot() {
    try {
      const cached = JSON.parse(localStorage.getItem(SNAPSHOT_KEY) || "null");
      if (!cached || !validSnapshot(cached.payload)) return null;
      const savedAt = new Date(cached.saved_at).getTime();
      if (!Number.isFinite(savedAt) || Date.now() - savedAt > SNAPSHOT_MAX_AGE_MS) return null;
      return cached.payload;
    } catch (_) {
      return null;
    }
  }

  async function fetchSnapshot(url) {
    let lastError;
    for (const wait of FETCH_DELAYS_MS) {
      if (wait) await delay(wait);
      const controller = new AbortController();
      const timeout = setTimeout(() => controller.abort(), 8000);
      try {
        const response = await fetch(url, {
          headers: {Accept: "application/json"},
          signal: controller.signal,
        });
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const payload = await response.json();
        if (!validSnapshot(payload)) throw new Error("Invalid calendar snapshot");
        return payload;
      } catch (error) {
        lastError = error;
      } finally {
        clearTimeout(timeout);
      }
    }
    throw lastError || new Error("Calendar request failed");
  }

  function applySnapshot(payload) {
    state.events = payload.events;
    state.scanSummary = payload.scan_summary || null;
    state.generatedAt = payload.generated_at;
    renderScanSummary();
    renderCalendar();
    const event = eventFromUrl();
    if (event) openEvent(event, false);
  }

  async function loadEvents() {
    const apiBase = String(window.FLAGWATCH_API_BASE || "").replace(/\/$/, "");
    try {
      const payload = await fetchSnapshot(`${apiBase}/api/events`);
      saveSnapshot(payload);
      applySnapshot(payload);
      elements.status.textContent = `Times shown in ${state.timeZone}.`;
    } catch (_) {
      const cached = readSnapshot();
      if (cached) {
        applySnapshot(cached);
        elements.status.textContent = `Showing saved calendar data from ${formatDateTime(cached.generated_at)}. Live refresh is temporarily unavailable. Times shown in ${state.timeZone}.`;
        return;
      }
      elements.status.textContent = "The calendar feed is unavailable right now. Please try again shortly.";
      renderCalendar();
    }
  }

  function renderScanSummary() {
    const summary = state.scanSummary || {
      sources_read: state.events.filter((event) => event.source_scan_status === "read").length,
      sources_need_recheck: state.events.filter(
        (event) => event.source_scan_status !== "read",
      ).length,
      policies_confirmed: state.events.filter(
        (event) => ["ai_native", "ai_assisted"].includes(event.ai_policy) &&
          policyIsConfirmed(event),
      ).length,
    };
    elements.scanUpdated.textContent = state.generatedAt
      ? formatDateTime(state.generatedAt)
      : "Not available";
    elements.scanEvents.textContent = `${state.events.length} CTF${state.events.length === 1 ? "" : "s"}`;
    elements.scanSources.textContent = `${summary.sources_read} source${summary.sources_read === 1 ? "" : "s"}`;
    elements.scanRecheck.textContent = `${summary.sources_need_recheck} need recheck`;
    elements.scanConfirmed.textContent = `${summary.policies_confirmed} confirmed`;
  }

  document.querySelector("#previous-month").addEventListener("click", () => setMonth(-1));
  document.querySelector("#next-month").addEventListener("click", () => setMonth(1));
  document.querySelector("#today").addEventListener("click", () => {
    state.month = monthForDate(new Date(), state.timeZone);
    updateUrl({event: null}, "push");
    renderCalendar();
  });
  document.querySelectorAll("[data-close]").forEach((button) => button.addEventListener("click", closeEvent));
  elements.eventDialog.addEventListener("close", () => updateUrl({event: null}));
  elements.eventDialog.addEventListener("cancel", (event) => {
    event.preventDefault();
    closeEvent();
  });
  elements.eventDialog.addEventListener("click", (event) => {
    const bounds = elements.eventDialog.getBoundingClientRect();
    const onDialogEdge =
      event.clientX <= bounds.left + 4 ||
      event.clientX >= bounds.right - 4 ||
      event.clientY <= bounds.top + 4 ||
      event.clientY >= bounds.bottom - 4;
    if (event.target === elements.eventDialog || onDialogEdge) closeEvent();
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
  addEventListener("popstate", () => {
    state.month = monthFromUrl(state.timeZone);
    renderCalendar();
    const event = eventFromUrl();
    if (event) {
      openEvent(event, false);
    } else if (elements.eventDialog.open) {
      elements.eventDialog.close();
    }
  });

  updateTimezoneButton();
  if (!savedZone) {
    elements.detectedTimezone.textContent = state.timeZone;
    elements.confirmTimezone.textContent = `Use ${state.timeZone}`;
    elements.timezoneConfirm.showModal();
  }
  updateUrl();
  loadEvents();
})();
