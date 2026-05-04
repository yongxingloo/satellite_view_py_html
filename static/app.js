const config = window.APP_CONFIG;

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
const downloadLink = document.querySelector("#downloadLink");

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

const aoiLayer = L.featureGroup().addTo(map);
const footprintLayer = L.geoJSON(null, {
  style: () => ({ color: "#8f4d26", weight: 1.4, fillColor: "#8f4d26", fillOpacity: 0.12 })
}).addTo(map);
const highlightedLayer = L.geoJSON(null, {
  style: () => ({ color: "#173b63", weight: 2, fillColor: "#173b63", fillOpacity: 0.12 })
}).addTo(map);

const state = {
  bbox: null,
  aoiRectangle: null,
  tempRectangle: null,
  anchorLatLng: null,
  drawing: false,
  items: [],
  selectedIndex: -1,
  playing: false,
  playTimer: null
};

function setStatus(message) {
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

function renderStats(stats) {
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
  timelineScale.innerHTML = "";
  timelineTrack.innerHTML = "";

  if (!state.items.length) {
    timelineTrack.innerHTML = '<div class="empty-state">Timeline will appear after a search.</div>';
    return;
  }

  const first = state.items[0];
  const last = state.items[state.items.length - 1];
  timelineScale.innerHTML = `<span>${formatSceneDate(first.datetime)}</span><span>${formatSceneDate(last.datetime)}</span>`;

  if (state.items.length === 1) {
    const dot = document.createElement("button");
    dot.type = "button";
    dot.className = "timeline-dot active";
    dot.style.left = "50%";
    dot.addEventListener("click", () => selectScene(0, false));
    timelineTrack.append(dot);
    return;
  }

  state.items.forEach((scene, index) => {
    const position = (index / (state.items.length - 1)) * 100;
    const dot = document.createElement("button");
    dot.type = "button";
    dot.className = `timeline-dot${index === state.selectedIndex ? " active" : ""}`;
    dot.style.left = `${position}%`;
    dot.title = `${formatSceneDate(scene.datetime)} ${scene.id}`;
    dot.addEventListener("click", () => selectScene(index, false));
    timelineTrack.append(dot);
  });
}

function renderPlayer() {
  setPlayerButtonState();
  if (!state.items.length || state.selectedIndex < 0) {
    playerImage.style.display = "none";
    playerImage.removeAttribute("src");
    playerPlaceholder.hidden = false;
    playerTitle.textContent = "No frame selected";
    playerSubtitle.textContent = "Awaiting overpass search";
    downloadLink.hidden = true;
    return;
  }

  const selected = state.items[state.selectedIndex];
  const frameUrl = selected.frame_url || selected.fallback_frame_url;
  playerTitle.textContent = `${state.selectedIndex + 1} / ${state.items.length}  ${formatSceneDate(selected.datetime)}`;
  playerSubtitle.textContent = `${selected.collection} - ${selected.id} - coverage ${(selected.coverage_score * 100).toFixed(0)}%`;
  timelineInput.value = String(state.selectedIndex);

  if (frameUrl) {
    playerImage.src = frameUrl;
    playerImage.style.display = "block";
    playerPlaceholder.hidden = true;
    downloadLink.href = frameUrl;
    downloadLink.hidden = false;
  } else {
    playerImage.style.display = "none";
    playerImage.removeAttribute("src");
    playerPlaceholder.hidden = false;
    downloadLink.hidden = true;
  }
}

function renderResults() {
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
    const card = document.createElement("article");
    card.className = `result-card${index === state.selectedIndex ? " active" : ""}`;
    card.innerHTML = `
      <div class="result-content">
        <h3>${formatSceneDate(scene.datetime)}</h3>
        <p>${scene.collection} - ${scene.id}</p>
        <p>Coverage ${(scene.coverage_score * 100).toFixed(0)}% - Cloud ${scene.cloud_cover == null ? "--" : `${scene.cloud_cover}%`}</p>
      </div>
    `;
    card.addEventListener("click", () => selectScene(index, true));
    resultsList.append(card);
  });

  renderTimeline();
  renderPlayer();
}

function selectScene(index, focusMap) {
  state.selectedIndex = index;
  const selected = state.items[index];
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
  renderResults();
}

function stopPlayback() {
  state.playing = false;
  playButton.textContent = "Play";
  if (state.playTimer) {
    window.clearInterval(state.playTimer);
    state.playTimer = null;
  }
}

function startPlayback() {
  if (state.items.length < 2) {
    return;
  }
  state.playing = true;
  playButton.textContent = "Pause";
  const intervalMs = Math.max(160, 1000 / Number(speedInput.value || 2));
  state.playTimer = window.setInterval(() => {
    const nextIndex = (state.selectedIndex + 1) % state.items.length;
    selectScene(nextIndex, false);
  }, intervalMs);
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
  if (!state.bbox) {
    setStatus("Choose an area before searching.");
    return;
  }

  stopPlayback();
  setStatus("Python backend is searching remote catalogs...");
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
    state.items = data.scenes;
    state.selectedIndex = state.items.length ? 0 : -1;
    setResultCount(state.items.length);
    renderStats(data.stats);
    renderResults();
    if (state.items.length) {
      setStatus(`Loaded ${state.items.length} scene${state.items.length === 1 ? "" : "s"} from the Python backend.`);
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
    setStatus("Python backend is rendering the animation...");
    await downloadExport("/api/export/animation", { scenes: state.items, fps: Number(speedInput.value) }, "satellite_timelapse.gif");
    setStatus("Downloaded animated GIF generated by the backend.");
  } catch (error) {
    setStatus(error.message);
  }
}

async function downloadFrames() {
  try {
    setStatus("Python backend is packaging frame images...");
    await downloadExport("/api/export/frames", { scenes: state.items }, "satellite_frames.zip");
    setStatus("Downloaded ZIP generated by the backend.");
  } catch (error) {
    setStatus(error.message);
  }
}

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

renderStats({ scene_count: 0, range_label: "--", average_revisit_days: null, average_cloud_cover: null });
renderResults();
setPlayerButtonState();
