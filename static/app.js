// Frontend controller for map interactions, search, playback, and result rendering.
const config = window.APP_CONFIG;

// Cache all DOM nodes that are updated frequently during the app lifecycle.
const collectionSelect = document.querySelector("#collectionSelect");
const startDateInput = document.querySelector("#startDateInput");
const endDateInput = document.querySelector("#endDateInput");
const cloudInput = document.querySelector("#cloudInput");
const limitInput = document.querySelector("#limitInput");
const sequenceModeSelect = document.querySelector("#sequenceModeSelect");
const bboxOutput = document.querySelector("#bboxOutput");
const statusText = document.querySelector("#statusText");
const resultCountText = document.querySelector("#resultCountText");
const drawAreaButton = document.querySelector("#drawAreaButton");
const viewAreaButton = document.querySelector("#viewAreaButton");
const clearAreaButton = document.querySelector("#clearAreaButton");
const searchButton = document.querySelector("#searchButton");
const streetsLayerButton = document.querySelector("#streetsLayerButton");
const satelliteLayerButton = document.querySelector("#satelliteLayerButton");
const playButton = document.querySelector("#playButton");
const exportButton = document.querySelector("#exportButton");
const downloadFramesButton = document.querySelector("#downloadFramesButton");
const speedInput = document.querySelector("#speedInput");
const timelineInput = document.querySelector("#timelineInput");
const resultsList = document.querySelector("#resultsList");
const statsGrid = document.querySelector("#statsGrid");
const timelineScale = document.querySelector("#timelineScale");
const timelineTrack = document.querySelector("#timelineTrack");
const playerImage = document.querySelector("#playerImage");
const playerPlaceholder = document.querySelector("#playerPlaceholder");
const playerTitle = document.querySelector("#playerTitle");
const playerSubtitle = document.querySelector("#playerSubtitle");
const fileNameText = document.querySelector("#fileNameText");
const fileUrlText = document.querySelector("#fileUrlText");
const stacUrlLink = document.querySelector("#stacUrlLink");
const stacUrlCode = document.querySelector("#stacUrlCode");
const titilerUrlCode = document.querySelector("#titilerUrlCode");

// Create the map and load the default satellite basemap first.
const map = L.map("map", { zoomControl: true }).setView(config.default_center, config.default_zoom);
L.control.scale({ imperial: false, metric: true }).addTo(map);

const streetLayer = L.tileLayer("https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png", {
  attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors &copy; <a href="https://carto.com/">CARTO</a>',
  subdomains: "abcd",
  maxZoom: 20
});

const satelliteLayer = L.tileLayer("https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}", {
  attribution: 'Tiles &copy; <a href="https://www.esri.com/">Esri</a>',
  maxZoom: 19
});

satelliteLayer.addTo(map);

// Scene footprints and the currently selected footprint are tracked separately.
const aoiLayer = L.featureGroup().addTo(map);
const footprintLayer = L.geoJSON(null, {
  style: () => ({ color: "#8f4d26", weight: 1.2, fillColor: "#8f4d26", fillOpacity: 0.04, opacity: 0.65 })
}).addTo(map);
const highlightedLayer = L.geoJSON(null, {
  style: () => ({ color: "#173b63", weight: 1.8, fillColor: "#173b63", fillOpacity: 0.06, opacity: 0.75 })
}).addTo(map);

// Central UI state for the current AOI, search results, and player selection.
const state = {
  bbox: null,
  aoiRectangle: null,
  tempRectangle: null,
  anchorLatLng: null,
  drawing: false,
  items: [],
  resultCards: [],
  timelineDots: [],
  selectedIndex: -1,
  playing: false,
  playTimer: null,
  previewStatus: new Map()
};

function setStatus(message) {
  // Surface short progress messages without using alert dialogs.
  statusText.textContent = message;
}

function setResultCount(count) {
  resultCountText.textContent = `${count} scene${count === 1 ? "" : "s"} loaded`;
}

function formatCoordinate(value) {
  return value.toFixed(4);
}

function formatBBox(bbox) {
  if (!bbox) {
    return "No area selected yet.";
  }
  const [west, south, east, north] = bbox;
  return `W ${formatCoordinate(west)}, S ${formatCoordinate(south)}, E ${formatCoordinate(east)}, N ${formatCoordinate(north)}`;
}

function normalizeBounds(bounds) {
  const southWest = bounds.getSouthWest();
  const northEast = bounds.getNorthEast();
  return [
    Number(southWest.lng.toFixed(5)),
    Number(southWest.lat.toFixed(5)),
    Number(northEast.lng.toFixed(5)),
    Number(northEast.lat.toFixed(5))
  ];
}

function setBBox(bbox, fitMap = true) {
  // Persist the AOI and mirror it in both the map overlay and the text summary.
  state.bbox = bbox;
  bboxOutput.textContent = formatBBox(bbox);

  if (state.aoiRectangle) {
    aoiLayer.removeLayer(state.aoiRectangle);
  }

  if (!bbox) {
    state.aoiRectangle = null;
    return;
  }

  const latLngBounds = L.latLngBounds([bbox[1], bbox[0]], [bbox[3], bbox[2]]);
  state.aoiRectangle = L.rectangle(latLngBounds, {
    color: "#173b63",
    weight: 2,
    dashArray: "8 6",
    fillOpacity: 0.08
  }).addTo(aoiLayer);

  if (fitMap) {
    map.fitBounds(latLngBounds.pad(0.35));
  }
}

function clearTempRectangle() {
  if (state.tempRectangle) {
    aoiLayer.removeLayer(state.tempRectangle);
    state.tempRectangle = null;
  }
}

function stopDrawing() {
  state.drawing = false;
  state.anchorLatLng = null;
  clearTempRectangle();
  drawAreaButton.dataset.active = "false";
  drawAreaButton.textContent = "Draw area";
}

function startDrawing() {
  state.drawing = true;
  state.anchorLatLng = null;
  clearTempRectangle();
  drawAreaButton.dataset.active = "true";
  drawAreaButton.textContent = "Finish drawing";
  setStatus("Click two opposite corners on the map.");
}

function toggleDrawing() {
  if (state.drawing) {
    stopDrawing();
    setStatus("Area drawing cancelled.");
    return;
  }
  startDrawing();
}

function setActiveMapLayer(name) {
  if (name === "satellite") {
    map.removeLayer(streetLayer);
    satelliteLayer.addTo(map);
    streetsLayerButton.classList.remove("active");
    satelliteLayerButton.classList.add("active");
    return;
  }
  map.removeLayer(satelliteLayer);
  streetLayer.addTo(map);
  satelliteLayerButton.classList.remove("active");
  streetsLayerButton.classList.add("active");
}

function setPlayerButtonState() {
  const renderableFrames = state.items.filter((scene) => scene.frame_url).length;
  playButton.disabled = state.items.length < 2;
  exportButton.disabled = renderableFrames < 2;
  downloadFramesButton.disabled = renderableFrames < 1;
  timelineInput.disabled = state.items.length === 0;
  timelineInput.max = String(Math.max(0, state.items.length - 1));
}

function formatSceneDate(value) {
  if (!value) {
    return "Unknown date";
  }
  return value.slice(0, 10);
}

function differenceInDays(start, end) {
  return Math.max(0, Math.round((new Date(end) - new Date(start)) / 86400000));
}

function resolveScenePreviewUrl(scene) {
  return scene?.frame_url || scene?.fallback_frame_url || "";
}

function getSceneFileName(scene) {
  const previewUrl = resolveScenePreviewUrl(scene);
  if (!previewUrl) {
    return "No preview file";
  }
  return previewUrl.split("/").pop().split("?")[0] || "preview-file";
}

function formatCloudValue(value) {
  if (value == null || Number.isNaN(Number(value))) {
    return "--";
  }
  return Number(value).toFixed(2);
}

function markPreviewStatus(url, status) {
  if (url) {
    state.previewStatus.set(url, status);
  }
}

function preloadPreviewUrl(url) {
  if (!url) {
    return Promise.reject(new Error("No preview URL available."));
  }

  const knownStatus = state.previewStatus.get(url);
  if (knownStatus === "ready") {
    return Promise.resolve(url);
  }
  if (knownStatus === "error") {
    return Promise.reject(new Error("Preview file could not be loaded."));
  }

  return new Promise((resolve, reject) => {
    const probe = new Image();
    const timeoutId = window.setTimeout(() => {
      markPreviewStatus(url, "error");
      reject(new Error("Preview file timed out while loading."));
    }, 8000);

    probe.onload = () => {
      window.clearTimeout(timeoutId);
      markPreviewStatus(url, "ready");
      resolve(url);
    };
    probe.onerror = () => {
      window.clearTimeout(timeoutId);
      markPreviewStatus(url, "error");
      reject(new Error("Preview file could not be loaded."));
    };
    probe.src = url;
  });
}

function renderStats(stats) {
  // Rebuild the summary cards from the latest backend stats payload.
  const cards = [
    { label: "Scenes", value: stats.scene_count ?? 0, note: "Frames in sequence" },
    { label: "Range", value: stats.range_label ?? "--", note: "Current timespan" },
    { label: "Revisit", value: stats.average_revisit_days == null ? "--" : `${stats.average_revisit_days}d`, note: "Average interval" },
    { label: "Cloud", value: stats.average_cloud_cover == null ? "--" : `${stats.average_cloud_cover}%`, note: "Average cloud cover" }
  ];
  statsGrid.innerHTML = cards.map((card) => `
    <article class="stat-card">
      <span class="status-label">${card.label}</span>
      <strong>${card.value}</strong>
      <p>${card.note}</p>
    </article>
  `).join("");
}

function renderTimeline() {
  // Place timeline dots by capture date so temporal gaps are visible.
  state.timelineDots = [];
  timelineScale.innerHTML = "";
  timelineTrack.innerHTML = "";

  if (!state.items.length) {
    timelineTrack.innerHTML = '<div class="empty-state">Timeline will appear after a search.</div>';
    return;
  }

  const datedScenes = state.items
    .map((scene, index) => ({ scene, index }))
    .filter((entry) => entry.scene.datetime)
    .sort((left, right) => new Date(left.scene.datetime) - new Date(right.scene.datetime));

  const firstEntry = datedScenes[0] || { scene: state.items[0], index: 0 };
  const lastEntry = datedScenes[datedScenes.length - 1] || { scene: state.items[state.items.length - 1], index: state.items.length - 1 };
  const totalDays = datedScenes.length > 1 ? differenceInDays(firstEntry.scene.datetime, lastEntry.scene.datetime) : 0;

  timelineScale.innerHTML = `
    <span>${formatSceneDate(firstEntry.scene.datetime)}</span>
    <span>${totalDays ? `${totalDays} days` : "Single day"}</span>
    <span>${formatSceneDate(lastEntry.scene.datetime)}</span>
  `;

  if (datedScenes.length <= 1) {
    const dot = document.createElement("button");
    dot.type = "button";
    dot.className = "timeline-dot active";
    dot.style.left = "50%";
    dot.title = firstEntry.scene ? `${formatSceneDate(firstEntry.scene.datetime)} ${firstEntry.scene.id}` : "Scene";
    dot.addEventListener("click", () => selectScene(firstEntry.index, false));
    timelineTrack.append(dot);
    state.timelineDots.push(dot);
    return;
  }

  const firstTime = new Date(firstEntry.scene.datetime).getTime();
  const lastTime = new Date(lastEntry.scene.datetime).getTime();
  const spanMs = Math.max(1, lastTime - firstTime);

  datedScenes.forEach(({ scene, index }) => {
    const position = ((new Date(scene.datetime).getTime() - firstTime) / spanMs) * 100;
    const dot = document.createElement("button");
    dot.type = "button";
    dot.className = `timeline-dot${index === state.selectedIndex ? " active" : ""}`;
    dot.style.left = `calc(1rem + (${position} * (100% - 2rem) / 100))`;
    dot.title = `${formatSceneDate(scene.datetime)} ${scene.id}`;
    dot.addEventListener("click", () => selectScene(index, false));
    timelineTrack.append(dot);
    state.timelineDots.push(dot);
  });
}

function updateSelectionStyles() {
  // Keep the active result card and active timeline dot visually in sync.
  state.resultCards.forEach((card, index) => {
    card.classList.toggle("active", index === state.selectedIndex);
  });
  state.timelineDots.forEach((dot, index) => {
    dot.classList.toggle("active", index === state.selectedIndex);
  });
}

function updateHighlightedScene(focusMap) {
  // The selected scene footprint is drawn separately from the full footprint set.
  const selected = state.items[state.selectedIndex];
  highlightedLayer.clearLayers();
  if (selected && selected.geometry) {
    highlightedLayer.addData(selected.geometry);
    if (focusMap) {
      const bounds = highlightedLayer.getBounds();
      if (bounds.isValid()) {
        map.fitBounds(bounds.pad(0.25));
      }
    }
  }
}

function renderPlayer() {
  // The preview panel only reflects the current selection; it does not own search state.
  setPlayerButtonState();
  if (!state.items.length || state.selectedIndex < 0) {
    playerImage.style.display = "none";
    playerImage.removeAttribute("src");
    playerPlaceholder.hidden = false;
    playerTitle.textContent = "No frame selected";
    playerSubtitle.textContent = "Awaiting overpass search";
    fileNameText.textContent = "No file selected";
    fileUrlText.textContent = "Run a search to inspect the selected frame source.";
    stacUrlCode.textContent = "No STAC URL available.";
    titilerUrlCode.textContent = "No TiTiler URL available.";
    stacUrlLink.hidden = true;
    return;
  }

  const selected = state.items[state.selectedIndex];
  const frameUrl = resolveScenePreviewUrl(selected);
  const stacUrl = selected.browser_url || "";
  const fileName = getSceneFileName(selected);
  playerTitle.textContent = `${state.selectedIndex + 1} / ${state.items.length}  ${formatSceneDate(selected.datetime)}`;
  playerSubtitle.textContent = `${selected.collection} - ${selected.id} - cloud ${formatCloudValue(selected.cloud_cover)}%`;
  timelineInput.value = String(state.selectedIndex);
  fileNameText.textContent = fileName;
  fileUrlText.textContent = `Scene ${selected.id} from ${selected.collection}`;
  stacUrlCode.textContent = stacUrl || "No STAC URL available.";
  titilerUrlCode.textContent = frameUrl || "No TiTiler URL available.";
  stacUrlLink.hidden = !stacUrl;
  if (stacUrl) {
    stacUrlLink.href = stacUrl;
  }

  if (frameUrl) {
    if (playerImage.src !== frameUrl) {
      playerImage.src = frameUrl;
    }
    playerImage.style.display = "block";
    playerPlaceholder.hidden = true;
  } else {
    playerImage.style.display = "none";
    playerImage.removeAttribute("src");
    playerPlaceholder.hidden = false;
  }
}

function renderResults() {
  // Full result rendering happens once per search, not on every playback tick.
  state.resultCards = [];
  footprintLayer.clearLayers();
  highlightedLayer.clearLayers();
  resultsList.innerHTML = "";

  if (!state.items.length) {
    resultsList.innerHTML = '<div class="empty-state">No scenes loaded yet.</div>';
    renderTimeline();
    renderPlayer();
    return;
  }

  state.items.forEach((scene, index) => {
    if (scene.geometry) {
      footprintLayer.addData(scene.geometry);
    }
    const previewUrl = resolveScenePreviewUrl(scene);
    const thumbnailUrl = scene.fallback_frame_url || previewUrl;
    const thumbnailMarkup = thumbnailUrl
      ? `<img class="result-thumb" src="${thumbnailUrl}" alt="Preview for ${scene.id}" loading="lazy" decoding="async">`
      : `<div class="result-thumb result-thumb-empty">No preview</div>`;
    const card = document.createElement("article");
    card.className = "result-card";
    card.innerHTML = `
      ${thumbnailMarkup}
      <div class="result-content">
        <h3>${formatSceneDate(scene.datetime)}</h3>
        <p>${scene.collection} - ${scene.id}</p>
        <p>${getSceneFileName(scene)}</p>
        <p>Coverage ${(scene.coverage_score * 100).toFixed(0)}% - Cloud ${formatCloudValue(scene.cloud_cover)}%</p>
      </div>
    `;
    card.addEventListener("click", () => selectScene(index, true));
    resultsList.append(card);
    state.resultCards.push(card);
  });

  renderTimeline();
  updateHighlightedScene(false);
  updateSelectionStyles();
  renderPlayer();
}

function selectScene(index, focusMap) {
  state.selectedIndex = index;
  updateHighlightedScene(focusMap);
  updateSelectionStyles();
  renderPlayer();
}

function stopPlayback() {
  state.playing = false;
  playButton.textContent = "Play";
  if (state.playTimer) {
    window.clearTimeout(state.playTimer);
    state.playTimer = null;
  }
}

function findNextIndex(startIndex) {
  if (!state.items.length) {
    return -1;
  }
  return (startIndex + 1) % state.items.length;
}

async function advancePlayback() {
  // Playback advances only through frames that can actually be loaded in the browser.
  if (!state.playing || state.items.length < 2) {
    return;
  }

  let attempts = 0;
  let nextIndex = state.selectedIndex;

  while (attempts < state.items.length) {
    nextIndex = findNextIndex(nextIndex);
    const scene = state.items[nextIndex];
    const previewUrl = resolveScenePreviewUrl(scene);

    if (!previewUrl) {
      attempts += 1;
      continue;
    }

    try {
      await preloadPreviewUrl(previewUrl);
      if (!state.playing) {
        return;
      }
      selectScene(nextIndex, false);
      const intervalMs = Math.max(220, 1000 / Number(speedInput.value || 2));
      state.playTimer = window.setTimeout(() => {
        advancePlayback().catch((error) => {
          setStatus(error.message);
          stopPlayback();
        });
      }, intervalMs);
      return;
    } catch (_error) {
      attempts += 1;
    }
  }

  setStatus("Playback stopped because no additional preview files could be loaded.");
  stopPlayback();
}

function startPlayback() {
  if (state.items.length < 2) {
    return;
  }
  state.playing = true;
  playButton.textContent = "Pause";
  advancePlayback().catch((error) => {
    setStatus(error.message);
    stopPlayback();
  });
}

function togglePlayback() {
  if (state.playing) {
    stopPlayback();
    return;
  }
  startPlayback();
}

async function postJson(url, payload) {
  const response = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload)
  });

  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    throw new Error(data.error || `Request failed with HTTP ${response.status}`);
  }

  return response;
}

async function searchScenes() {
  // Send the current filters and AOI to the backend search endpoint.
  if (!state.bbox) {
    setStatus("Choose an area before searching.");
    return;
  }

  stopPlayback();
  setStatus("Searching scenes...");
  searchButton.disabled = true;

  try {
    const response = await postJson("/api/search", {
      collection: collectionSelect.value,
      start_date: startDateInput.value,
      end_date: endDateInput.value,
      max_cloud: Number(cloudInput.value),
      limit: Number(limitInput.value),
      sequence_mode: sequenceModeSelect.value,
      bbox: state.bbox
    });
    const data = await response.json();
    state.previewStatus = new Map();
    state.items = data.scenes;
    state.selectedIndex = state.items.length ? 0 : -1;
    setResultCount(state.items.length);
    renderStats(data.stats);
    renderResults();
    if (state.items.length) {
      setStatus(`Loaded ${state.items.length} scene${state.items.length === 1 ? "" : "s"}.`);
    } else {
      setStatus("No matching scenes were returned for that search.");
    }
  } catch (error) {
    state.items = [];
    state.selectedIndex = -1;
    renderStats({ scene_count: 0, range_label: "--", average_revisit_days: null, average_cloud_cover: null });
    renderResults();
    setResultCount(0);
    setStatus(error.message);
  } finally {
    searchButton.disabled = false;
  }
}

async function downloadExport(url, payload, fileName) {
  // Helper used by both export buttons to trigger browser downloads.
  const response = await postJson(url, payload);
  const blob = await response.blob();
  const objectUrl = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = objectUrl;
  anchor.download = fileName;
  anchor.click();
  window.setTimeout(() => URL.revokeObjectURL(objectUrl), 1000);
}

async function exportAnimation() {
  try {
    setStatus("Rendering animation...");
    await downloadExport("/api/export/animation", { scenes: state.items, fps: Number(speedInput.value) }, "satellite_timelapse.gif");
    setStatus("Downloaded animated GIF.");
  } catch (error) {
    setStatus(error.message);
  }
}

async function downloadFrames() {
  try {
    setStatus("Preparing frame download...");
    await downloadExport("/api/export/frames", { scenes: state.items }, "satellite_frames.zip");
    setStatus("Downloaded ZIP.");
  } catch (error) {
    setStatus(error.message);
  }
}

// Wire all UI actions after function definitions so startup order stays predictable.
drawAreaButton.addEventListener("click", toggleDrawing);
viewAreaButton.addEventListener("click", () => {
  setBBox(normalizeBounds(map.getBounds()), false);
  setStatus("Using the current map view as the search area.");
});
clearAreaButton.addEventListener("click", () => {
  stopPlayback();
  stopDrawing();
  state.items = [];
  state.selectedIndex = -1;
  setBBox(null, false);
  footprintLayer.clearLayers();
  highlightedLayer.clearLayers();
  renderStats({ scene_count: 0, range_label: "--", average_revisit_days: null, average_cloud_cover: null });
  renderResults();
  setResultCount(0);
  setStatus("Area and search results cleared.");
});
searchButton.addEventListener("click", searchScenes);
streetsLayerButton.addEventListener("click", () => setActiveMapLayer("streets"));
satelliteLayerButton.addEventListener("click", () => setActiveMapLayer("satellite"));
playButton.addEventListener("click", togglePlayback);
exportButton.addEventListener("click", exportAnimation);
downloadFramesButton.addEventListener("click", downloadFrames);
speedInput.addEventListener("input", () => {
  if (state.playing) {
    stopPlayback();
    startPlayback();
  }
});
timelineInput.addEventListener("input", () => {
  stopPlayback();
  selectScene(Number(timelineInput.value), false);
});

// Map click/drag events power the two-corner rectangle drawing workflow.
map.on("click", (event) => {
  if (!state.drawing) {
    return;
  }

  if (!state.anchorLatLng) {
    state.anchorLatLng = event.latlng;
    clearTempRectangle();
    state.tempRectangle = L.rectangle(L.latLngBounds(event.latlng, event.latlng), {
      color: "#8f4d26",
      weight: 2,
      dashArray: "6 4",
      fillOpacity: 0.06
    }).addTo(aoiLayer);
    return;
  }

  const bounds = L.latLngBounds(state.anchorLatLng, event.latlng);
  setBBox(normalizeBounds(bounds), true);
  stopDrawing();
  setStatus("Area selected. You can search now.");
});

map.on("mousemove", (event) => {
  if (!state.drawing || !state.anchorLatLng || !state.tempRectangle) {
    return;
  }
  state.tempRectangle.setBounds(L.latLngBounds(state.anchorLatLng, event.latlng));
});

// Keep preview load status so playback can skip frames that fail to load.
playerImage.addEventListener("load", () => {
  markPreviewStatus(playerImage.currentSrc, "ready");
});

playerImage.addEventListener("error", () => {
  const selected = state.items[state.selectedIndex];
  const previewUrl = resolveScenePreviewUrl(selected);
  markPreviewStatus(previewUrl, "error");
  playerImage.style.display = "none";
  playerImage.removeAttribute("src");
  playerPlaceholder.hidden = false;
  fileUrlText.textContent = previewUrl
    ? "The preview file failed to load for this frame."
    : "This scene does not expose a direct preview file.";
  if (state.playing) {
    advancePlayback().catch((error) => {
      setStatus(error.message);
      stopPlayback();
    });
  }
});

// Bootstrap the initial empty UI, then draw the default AOI injected by Flask.
renderStats({ scene_count: 0, range_label: "--", average_revisit_days: null, average_cloud_cover: null });
renderResults();
setPlayerButtonState();
if (Array.isArray(config.default_bbox) && config.default_bbox.length === 4) {
  setBBox(config.default_bbox, true);
  setStatus("Default area loaded. Search to begin.");
}
