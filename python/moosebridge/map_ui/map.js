(() => {
  "use strict";

  const EMPTY = { type: "FeatureCollection", features: [] };
  const layerSpecs = [
    { key: "groups", label: "Gruppen", color: "#245f96", icon: "boxes", size: 1.05, default: true },
    { key: "units", label: "Einheiten", color: "#37a078", icon: "truck", size: 0.82, default: true },
    { key: "statics", label: "Statische Objekte", color: "#6d746f", icon: "warehouse", size: 0.82, default: true },
    { key: "airbases", label: "Flugplätze", color: "#137f87", icon: "plane-takeoff", size: 0.8, default: true },
    { key: "zones", label: "Zonen", color: "#c19424", icon: "map-pin", default: false },
    { key: "opszones", label: "OPS-Zonen", color: "#8b5ea7", icon: "shield", default: true },
    { key: "opsgroups", label: "OPS-Gruppen", color: "#1e8171", icon: "badge", size: 1.1, default: true },
    { key: "legions", label: "Legionen", color: "#283a4f", icon: "shield", size: 1.18, default: true },
    { key: "intel_contacts", label: "INTEL-Kontakte", color: "#c44343", icon: "crosshair", size: 0.95, default: true },
    { key: "intel_clusters", label: "INTEL-Cluster", color: "#d06f27", icon: "radar", size: 1.05, default: true },
    { key: "missions", label: "Missionen", color: "#ad3c76", icon: "target", size: 1.05, default: true },
  ];
  const coalitionColors = { blue: "#2776b9", red: "#c44343", neutral: "#858d88", unknown: "#59635e" };
  const symbolDefinitions = {
    "unit-airplane": { icon: "Plane", frame: "circle" },
    "unit-helicopter": { icon: "Helicopter", frame: "circle" },
    "unit-ground": { icon: "Truck", frame: "circle" },
    "unit-ship": { icon: "Ship", frame: "circle" },
    "group-airplane": { icon: "Plane", frame: "square" },
    "group-helicopter": { icon: "Helicopter", frame: "square" },
    "group-ground": { icon: "Truck", frame: "square" },
    "group-ship": { icon: "Ship", frame: "square" },
    "static": { icon: "Warehouse", frame: "square" },
    "airbase-airdrome": { icon: "PlaneTakeoff", frame: "circle" },
    "airbase-helipad": { icon: "Helicopter", frame: "circle" },
    "legion-airwing": { icon: "Plane", frame: "diamond" },
    "legion-brigade": { icon: "Shield", frame: "diamond" },
    "legion-other": { icon: "Shield", frame: "diamond" },
    "intel-contact": { icon: "Crosshair", frame: "triangle" },
    "intel-cluster": { icon: "Radar", frame: "circle" },
    "mission": { icon: "Target", frame: "diamond" },
  };
  const mapLayerIds = new Map();
  let latestPicture = EMPTY;
  let fitted = false;
  let reconnectTimer = null;

  const map = new maplibregl.Map({
    container: "map",
    center: [11.8, 53.8],
    zoom: 6.2,
    minZoom: 3,
    style: {
      version: 8,
      sources: {
        osm: {
          type: "raster",
          tiles: ["https://tile.openstreetmap.org/{z}/{x}/{y}.png"],
          tileSize: 256,
          maxzoom: 19,
          attribution: "© OpenStreetMap contributors",
        },
      },
      layers: [{ id: "osm", type: "raster", source: "osm" }],
    },
  });
  map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "bottom-right");

  const elements = {
    connectionDot: document.getElementById("connection-dot"),
    connectionText: document.getElementById("connection-text"),
    dcsClock: document.getElementById("dcs-clock"),
    missionClock: document.getElementById("mission-clock"),
    featureCount: document.getElementById("feature-count"),
    layerPanel: document.getElementById("layer-panel"),
    layerControls: document.getElementById("layer-controls"),
    layersToggle: document.getElementById("layers-toggle"),
    detailPanel: document.getElementById("detail-panel"),
    detailType: document.getElementById("detail-type"),
    detailTitle: document.getElementById("detail-title"),
    detailProperties: document.getElementById("detail-properties"),
    detailClose: document.getElementById("detail-close"),
    errorBanner: document.getElementById("error-banner"),
  };

  function semanticCategory(properties) {
    const category = String(properties.category || "").toLowerCase();
    if (category.includes("helicopter")) return "helicopter";
    if (category.includes("airplane") || category.includes("plane")) return "airplane";
    if (category.includes("ship") || category.includes("naval")) return "ship";
    return "ground";
  }

  function mapSymbol(properties) {
    const layer = properties.layer;
    let definition = "static";
    if (layer === "groups" || layer === "opsgroups") definition = `group-${semanticCategory(properties)}`;
    else if (layer === "units") definition = `unit-${semanticCategory(properties)}`;
    else if (layer === "airbases") definition = properties.category === "HELIPAD" ? "airbase-helipad" : "airbase-airdrome";
    else if (layer === "legions") {
      definition = properties.category === "AIRWING" ? "legion-airwing" : properties.category === "BRIGADE" ? "legion-brigade" : "legion-other";
    } else if (layer === "intel_contacts") definition = "intel-contact";
    else if (layer === "intel_clusters") definition = "intel-cluster";
    else if (layer === "missions") definition = "mission";
    const coalition = Object.hasOwn(coalitionColors, properties.coalition) ? properties.coalition : "unknown";
    return `${definition}-${coalition}`;
  }

  function decoratedPicture(picture) {
    return {
      ...picture,
      features: picture.features.map((feature) => ({
        ...feature,
        properties: { ...feature.properties, map_symbol: mapSymbol(feature.properties || {}) },
      })),
    };
  }

  function drawFrame(context, frame, color) {
    context.fillStyle = color;
    context.strokeStyle = "rgba(255,255,255,0.96)";
    context.lineWidth = 4;
    context.beginPath();
    if (frame === "diamond") {
      context.moveTo(32, 3); context.lineTo(61, 32); context.lineTo(32, 61); context.lineTo(3, 32); context.closePath();
    } else if (frame === "triangle") {
      context.moveTo(32, 3); context.lineTo(61, 58); context.lineTo(3, 58); context.closePath();
    } else if (frame === "square") {
      context.roundRect(4, 7, 56, 50, 8);
    } else {
      context.arc(32, 32, 28, 0, Math.PI * 2);
    }
    context.fill();
    context.stroke();
  }

  function lucideMarkup() {
    const container = document.createElement("div");
    container.hidden = true;
    const names = [...new Set(Object.values(symbolDefinitions).map((definition) => definition.icon.replace(/([a-z])([A-Z])/g, "$1-$2").toLowerCase()))];
    for (const name of names) {
      const icon = document.createElement("i");
      icon.setAttribute("data-lucide", name);
      container.appendChild(icon);
    }
    document.body.appendChild(container);
    if (window.lucide) window.lucide.createIcons();
    const result = new Map();
    for (const svg of container.querySelectorAll("svg[data-lucide]")) {
      svg.setAttribute("width", "34");
      svg.setAttribute("height", "34");
      svg.setAttribute("stroke", "white");
      svg.setAttribute("stroke-width", "2.2");
      result.set(svg.getAttribute("data-lucide"), new XMLSerializer().serializeToString(svg));
    }
    container.remove();
    return result;
  }

  async function registerMapSymbols() {
    const registrations = [];
    const markupByName = lucideMarkup();
    for (const [definitionName, definition] of Object.entries(symbolDefinitions)) {
      for (const [coalition, color] of Object.entries(coalitionColors)) {
        registrations.push(new Promise((resolve) => {
          const canvas = document.createElement("canvas");
          canvas.width = 64; canvas.height = 64;
          const context = canvas.getContext("2d");
          drawFrame(context, definition.frame, color);
          const iconName = definition.icon.replace(/([a-z])([A-Z])/g, "$1-$2").toLowerCase();
          const markup = markupByName.get(iconName);
          if (!markup) { map.addImage(`${definitionName}-${coalition}`, context.getImageData(0, 0, 64, 64), { pixelRatio: 2 }); resolve(); return; }
          const image = new Image();
          image.onload = () => {
            context.drawImage(image, 15, 15, 34, 34);
            map.addImage(`${definitionName}-${coalition}`, context.getImageData(0, 0, 64, 64), { pixelRatio: 2 });
            resolve();
          };
          image.onerror = () => { map.addImage(`${definitionName}-${coalition}`, context.getImageData(0, 0, 64, 64), { pixelRatio: 2 }); resolve(); };
          image.src = `data:image/svg+xml;charset=utf-8,${encodeURIComponent(markup)}`;
        }));
      }
    }
    await Promise.all(registrations);
  }

  function addMapLayer(spec, definition) {
    const existing = mapLayerIds.get(spec.key) || [];
    const id = `${spec.key}-${definition.type}-${existing.length}`;
    map.addLayer({ id, source: definition.source || "picture", ...definition });
    existing.push(id);
    mapLayerIds.set(spec.key, existing);
  }

  async function initializeSourcesAndLayers() {
    await registerMapSymbols();
    map.addSource("picture", { type: "geojson", data: EMPTY, promoteId: "object_id" });
    map.addSource("zone-areas", { type: "geojson", data: EMPTY, promoteId: "object_id" });

    for (const spec of layerSpecs) {
      if (spec.key === "zones" || spec.key === "opszones") {
        addMapLayer(spec, {
          type: "fill",
          source: "zone-areas",
          filter: ["==", ["get", "layer"], spec.key],
          paint: { "fill-color": spec.color, "fill-opacity": spec.key === "opszones" ? 0.2 : 0.1 },
        });
        addMapLayer(spec, {
          type: "line",
          source: "zone-areas",
          filter: ["==", ["get", "layer"], spec.key],
          paint: { "line-color": spec.color, "line-width": spec.key === "opszones" ? 2 : 1 },
        });
        continue;
      }

      addMapLayer(spec, {
        type: "symbol",
        filter: ["==", ["get", "layer"], spec.key],
        layout: {
          "icon-image": ["get", "map_symbol"],
          "icon-size": spec.size || 1,
          "icon-allow-overlap": false,
          "icon-padding": 2,
        },
        paint: {
          "icon-opacity": ["case", ["==", ["get", "alive"], false], 0.32, 0.94],
        },
      });
    }

    map.addLayer({
      id: "mission-links-line",
      type: "line",
      source: "picture",
      filter: ["==", ["get", "layer"], "mission_links"],
      paint: { "line-color": "#ad3c76", "line-width": 2, "line-opacity": 0.7 },
    });
    mapLayerIds.get("missions").push("mission-links-line");
    applyLayerVisibility();
  }

  function circlePolygon(feature) {
    const [lon, lat] = feature.geometry.coordinates;
    const radius = Number(feature.properties.radius_m || 0);
    if (!(radius > 0)) return null;
    const angular = radius / 6371008.8;
    const lat1 = lat * Math.PI / 180;
    const lon1 = lon * Math.PI / 180;
    const ring = [];
    for (let index = 0; index <= 64; index += 1) {
      const bearing = index / 64 * Math.PI * 2;
      const lat2 = Math.asin(Math.sin(lat1) * Math.cos(angular) + Math.cos(lat1) * Math.sin(angular) * Math.cos(bearing));
      const lon2 = lon1 + Math.atan2(
        Math.sin(bearing) * Math.sin(angular) * Math.cos(lat1),
        Math.cos(angular) - Math.sin(lat1) * Math.sin(lat2),
      );
      ring.push([lon2 * 180 / Math.PI, lat2 * 180 / Math.PI]);
    }
    return { ...feature, geometry: { type: "Polygon", coordinates: [ring] } };
  }

  function zoneCollection(picture) {
    return {
      type: "FeatureCollection",
      features: picture.features
        .filter((feature) => ["zones", "opszones"].includes(feature.properties?.layer))
        .map(circlePolygon)
        .filter(Boolean),
    };
  }

  function setPicture(picture) {
    if (!picture || picture.type !== "FeatureCollection") return;
    latestPicture = decoratedPicture(picture);
    const source = map.getSource("picture");
    const zones = map.getSource("zone-areas");
    if (!source || !zones) return;
    source.setData(latestPicture);
    zones.setData(zoneCollection(latestPicture));
    updateCounts();
    updateClocks(picture.properties || {});
    if (!fitted) fitOperationalArea(latestPicture);
  }

  function fitOperationalArea(picture) {
    const candidates = picture.features.filter((feature) => {
      const properties = feature.properties || {};
      return feature.geometry?.type === "Point" && (
        properties.layer === "opszones" ||
        properties.layer === "legions" ||
        (["groups", "units", "statics"].includes(properties.layer) && properties.alive === true)
      );
    });
    if (!candidates.length) return;
    const bounds = new maplibregl.LngLatBounds();
    candidates.forEach((feature) => bounds.extend(feature.geometry.coordinates));
    if (!bounds.isEmpty()) {
      map.fitBounds(bounds, { padding: 70, maxZoom: 9, duration: 0 });
      fitted = true;
    }
  }

  function updateClocks(properties) {
    elements.dcsClock.textContent = properties.dcs_date && properties.dcs_time_of_day
      ? `DCS ${properties.dcs_date} ${properties.dcs_time_of_day}` : "DCS --";
    elements.missionClock.textContent = properties.mission_elapsed ? `Mission ${properties.mission_elapsed}` : "Mission --";
  }

  function updateStatus(status) {
    const connected = Boolean(status?.connected);
    elements.connectionDot.classList.toggle("is-offline", !connected);
    elements.connectionText.textContent = connected ? "DCS verbunden" : "DCS getrennt";
    elements.errorBanner.hidden = !status?.error;
    elements.errorBanner.textContent = status?.error || "";
  }

  function updateCounts() {
    const counts = new Map();
    latestPicture.features.forEach((feature) => {
      const key = feature.properties?.layer;
      counts.set(key, (counts.get(key) || 0) + 1);
    });
    elements.featureCount.textContent = `${latestPicture.features.length} Objekte`;
    document.querySelectorAll("[data-layer-count]").forEach((node) => {
      node.textContent = String(counts.get(node.dataset.layerCount) || 0);
    });
  }

  function buildLayerControls() {
    for (const spec of layerSpecs) {
      const label = document.createElement("label");
      label.className = "layer-control";
      label.innerHTML = `
        <input type="checkbox" data-layer="${spec.key}" ${spec.default ? "checked" : ""}>
        <i data-lucide="${spec.icon}" class="layer-symbol" style="--swatch:${spec.color}"></i>
        <span class="layer-name">${spec.label}</span>
        <span class="layer-count" data-layer-count="${spec.key}">0</span>`;
      elements.layerControls.appendChild(label);
    }
    elements.layerControls.addEventListener("change", applyLayerVisibility);
  }

  function applyLayerVisibility() {
    document.querySelectorAll("[data-layer]").forEach((checkbox) => {
      const visibility = checkbox.checked ? "visible" : "none";
      for (const id of mapLayerIds.get(checkbox.dataset.layer) || []) {
        if (map.getLayer(id)) map.setLayoutProperty(id, "visibility", visibility);
      }
    });
  }

  function readableValue(value) {
    if (typeof value === "number") return Number.isInteger(value) ? String(value) : value.toFixed(3).replace(/0+$/, "").replace(/\.$/, "");
    if (typeof value === "boolean") return value ? "Ja" : "Nein";
    if (Array.isArray(value)) return value.join(", ");
    if (value && typeof value === "object") return JSON.stringify(value);
    return String(value ?? "-");
  }

  function showDetails(feature) {
    const properties = feature.properties || {};
    elements.detailType.textContent = properties.layer || properties.object_type || "Objekt";
    elements.detailTitle.textContent = properties.name || properties.object_id || "Unbenannt";
    elements.detailProperties.replaceChildren();
    const priority = ["object_id", "coalition", "category", "state", "alive", "active", "dcs_type", "radius_m", "x", "y", "z"];
    const ignored = new Set(["name", "layer", "coordinate_system"]);
    const keys = Object.keys(properties).filter((key) => !ignored.has(key));
    keys.sort((a, b) => {
      const ai = priority.indexOf(a);
      const bi = priority.indexOf(b);
      if (ai >= 0 || bi >= 0) return (ai < 0 ? 999 : ai) - (bi < 0 ? 999 : bi);
      return a.localeCompare(b);
    });
    for (const key of keys) {
      const term = document.createElement("dt");
      const description = document.createElement("dd");
      term.textContent = key;
      description.textContent = readableValue(properties[key]);
      elements.detailProperties.append(term, description);
    }
    if (window.innerWidth <= 720) {
      elements.layerPanel.hidden = true;
      elements.layersToggle.setAttribute("aria-expanded", "false");
    }
    elements.detailPanel.hidden = false;
  }

  function connect() {
    clearTimeout(reconnectTimer);
    const protocol = location.protocol === "https:" ? "wss" : "ws";
    const socket = new WebSocket(`${protocol}://${location.host}/ws/global`);
    socket.addEventListener("message", (event) => {
      const message = JSON.parse(event.data);
      if (message.data) setPicture(message.data);
      updateStatus(message.status);
    });
    socket.addEventListener("close", () => {
      updateStatus({ connected: false, error: "Verbindung zum Kartenserver unterbrochen" });
      reconnectTimer = setTimeout(connect, 2000);
    });
  }

  async function loadInitialPicture() {
    try {
      const [pictureResponse, healthResponse] = await Promise.all([
        fetch("/api/picture/global.geojson"),
        fetch("/api/health"),
      ]);
      if (pictureResponse.ok) setPicture(await pictureResponse.json());
      if (healthResponse.ok) updateStatus(await healthResponse.json());
    } catch (error) {
      updateStatus({ connected: false, error: String(error) });
    }
  }

  buildLayerControls();
  elements.layersToggle.addEventListener("click", () => {
    const hidden = !elements.layerPanel.hidden;
    if (!hidden && window.innerWidth <= 720) elements.detailPanel.hidden = true;
    elements.layerPanel.hidden = hidden;
    elements.layersToggle.setAttribute("aria-expanded", String(!hidden));
  });
  elements.detailClose.addEventListener("click", () => { elements.detailPanel.hidden = true; });
  document.addEventListener("keydown", (event) => { if (event.key === "Escape") elements.detailPanel.hidden = true; });

  map.on("load", async () => {
    await initializeSourcesAndLayers();
    loadInitialPicture();
    connect();
  });
  map.on("click", (event) => {
    const layers = [...mapLayerIds.values()].flat().filter((id) => map.getLayer(id));
    const features = map.queryRenderedFeatures(event.point, { layers });
    if (features.length) showDetails(features[0]);
  });
  map.on("mousemove", (event) => {
    const layers = [...mapLayerIds.values()].flat().filter((id) => map.getLayer(id));
    map.getCanvas().style.cursor = map.queryRenderedFeatures(event.point, { layers }).length ? "pointer" : "";
  });

  if (window.lucide) window.lucide.createIcons();
})();
