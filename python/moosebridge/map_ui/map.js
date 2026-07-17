(() => {
  "use strict";

  const EMPTY = { type: "FeatureCollection", features: [] };
  const layerSpecs = [
    { key: "trajectories", label: "Movement history", color: "#52665d", icon: "route", default: true },
    { key: "groups", label: "Groups", color: "#245f96", icon: "boxes", size: 1.05, default: true },
    { key: "units", label: "Units", color: "#37a078", icon: "truck", size: 0.82, default: true },
    { key: "statics", label: "Static objects", color: "#6d746f", icon: "warehouse", size: 0.82, default: true },
    {
      key: "airbases", label: "Airbases", color: "#137f87", icon: "plane-takeoff", size: 0.8, default: true,
      children: [
        { key: "airdrome", label: "Airdromes", icon: "plane-takeoff", default: true },
        { key: "heliport", label: "Heliports", icon: "fan", default: true },
        { key: "ship", label: "Ships", icon: "ship", default: true },
      ],
    },
    { key: "zones", label: "Zones", color: "#c19424", icon: "map-pin", default: false },
    { key: "territories", label: "Territories", color: "#59635e", icon: "map", default: true },
    { key: "opszones", label: "OPS zones", color: "#8b5ea7", icon: "shield", default: true },
    { key: "opsgroups", label: "OPS groups", color: "#1e8171", icon: "badge", size: 1.1, default: true },
    { key: "legions", label: "Legions", color: "#283a4f", icon: "shield", size: 1.18, default: true },
    { key: "intel_contacts", label: "INTEL contacts", color: "#c44343", icon: "crosshair", size: 0.95, default: true },
    { key: "intel_clusters", label: "INTEL clusters", color: "#d06f27", icon: "radar", size: 1.05, default: true },
    { key: "missions", label: "Missions", color: "#ad3c76", icon: "target", size: 1.05, default: true },
  ];
  const coalitionColors = { blue: "#2776b9", red: "#c44343", neutral: "#858d88", unknown: "#59635e" };
  const filterSpecs = [
    {
      key: "coalition", label: "Coalition",
      options: [
        { key: "blue", label: "Blue", icon: "flag", color: "#2776b9" },
        { key: "red", label: "Red", icon: "flag", color: "#c44343" },
        { key: "neutral", label: "Neutral", icon: "flag", color: "#858d88" },
        { key: "unassigned", label: "Unassigned", icon: "circle-help", color: "#65716b" },
      ],
    },
    {
      key: "status", label: "Status",
      options: [
        { key: "alive", label: "Alive", icon: "activity", color: "#25865f" },
        { key: "dead", label: "Dead", icon: "circle-off", color: "#a65353" },
        { key: "unknown", label: "No status", icon: "circle-help", color: "#65716b" },
      ],
    },
  ];
  const symbolDefinitions = {
    "unit-airplane": { icon: "Plane", frame: "circle" },
    "unit-helicopter": { icon: "Fan", frame: "circle" },
    "unit-ground": { icon: "Truck", frame: "circle" },
    "unit-ship": { icon: "Ship", frame: "circle" },
    "group-airplane": { icon: "Plane", frame: "square" },
    "group-helicopter": { icon: "Fan", frame: "square" },
    "group-ground": { icon: "Truck", frame: "square" },
    "group-ship": { icon: "Ship", frame: "square" },
    "static": { icon: "Warehouse", frame: "square" },
    "airbase-airdrome": { icon: "PlaneTakeoff", frame: "circle" },
    "airbase-helipad": { icon: "Fan", frame: "circle" },
    "airbase-ship": { icon: "Ship", frame: "circle" },
    "legion-airwing": { icon: "Plane", frame: "diamond" },
    "legion-brigade": { icon: "Shield", frame: "diamond" },
    "legion-other": { icon: "Shield", frame: "diamond" },
    "intel-contact": { icon: "Crosshair", frame: "triangle" },
    "intel-cluster": { icon: "Radar", frame: "circle" },
    "mission": { icon: "Target", frame: "diamond" },
  };
  const mapLayerIds = new Map();
  const mapLayerBaseFilters = new Map();
  let latestPicture = EMPTY;
  let fitted = false;
  let reconnectTimer = null;
  let selectedFeature = null;
  let selectedObjectId = null;
  let selectionCandidates = [];
  let selectionIndex = 0;

  const map = new maplibregl.Map({
    container: "map",
    center: [11.8, 53.8],
    zoom: 6.2,
    minZoom: 3,
    style: {
      version: 8,
      glyphs: "https://demotiles.maplibre.org/font/{fontstack}/{range}.pbf",
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
    filterControls: document.getElementById("filter-controls"),
    layersTab: document.getElementById("layers-tab"),
    filtersTab: document.getElementById("filters-tab"),
    layersToggle: document.getElementById("layers-toggle"),
    detailPanel: document.getElementById("detail-panel"),
    detailType: document.getElementById("detail-type"),
    detailTitle: document.getElementById("detail-title"),
    detailSubtitle: document.getElementById("detail-subtitle"),
    detailBadges: document.getElementById("detail-badges"),
    detailSections: document.getElementById("detail-sections"),
    detailStackCount: document.getElementById("detail-stack-count"),
    detailPrevious: document.getElementById("detail-previous"),
    detailNext: document.getElementById("detail-next"),
    detailFocus: document.getElementById("detail-focus"),
    detailCopy: document.getElementById("detail-copy"),
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

  function airbaseCategory(properties) {
    const category = String(properties.category || "").toLowerCase();
    if (category === "helipad" || category === "heliport") return "heliport";
    if (category === "ship") return "ship";
    return "airdrome";
  }

  function coalitionFilterCategory(properties) {
    const coalition = String(properties.coalition || properties.owner || "").toLowerCase();
    return ["blue", "red", "neutral"].includes(coalition) ? coalition : "unassigned";
  }

  function statusFilterCategory(properties) {
    if (properties.alive === true) return "alive";
    if (properties.alive === false) return "dead";
    return "unknown";
  }

  function mapSymbol(properties) {
    const layer = properties.layer;
    let definition = "static";
    if (layer === "groups" || layer === "opsgroups") definition = `group-${semanticCategory(properties)}`;
    else if (layer === "units") definition = `unit-${semanticCategory(properties)}`;
    else if (layer === "airbases") {
      const category = airbaseCategory(properties);
      definition = category === "heliport"
        ? "airbase-helipad"
        : category === "ship"
          ? "airbase-ship"
          : "airbase-airdrome";
    }
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
        properties: {
          ...feature.properties,
          map_symbol: mapSymbol(feature.properties || {}),
          map_category: feature.properties?.layer === "airbases" ? airbaseCategory(feature.properties || {}) : undefined,
          map_coalition: coalitionFilterCategory(feature.properties || {}),
          map_status: statusFilterCategory(feature.properties || {}),
        },
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
    mapLayerBaseFilters.set(id, definition.filter);
    existing.push(id);
    mapLayerIds.set(spec.key, existing);
  }

  async function initializeSourcesAndLayers() {
    await registerMapSymbols();
    map.addSource("picture", { type: "geojson", data: EMPTY, promoteId: "object_id" });
    map.addSource("zone-areas", { type: "geojson", data: EMPTY, promoteId: "object_id" });

    for (const spec of layerSpecs) {
      if (spec.key === "trajectories") {
        addMapLayer(spec, {
          type: "line",
          filter: ["==", ["get", "layer"], spec.key],
          paint: {
            "line-color": ["match", ["get", "map_coalition"], "blue", coalitionColors.blue, "red", coalitionColors.red, "neutral", coalitionColors.neutral, spec.color],
            "line-width": 2.2,
            "line-opacity": 0.72,
          },
        });
        continue;
      }
      if (spec.key === "zones" || spec.key === "territories" || spec.key === "opszones") {
        const areaColor = spec.key === "opszones"
          ? ["case",
              ["==", ["get", "contested"], true], "#d06f27",
              ["match", ["get", "owner"], "blue", coalitionColors.blue, "red", coalitionColors.red, "neutral", coalitionColors.neutral, spec.color],
            ]
          : spec.key === "territories"
            ? ["match", ["get", "coalition"], "blue", coalitionColors.blue, "red", coalitionColors.red, "neutral", coalitionColors.neutral, spec.color]
          : spec.color;
        addMapLayer(spec, {
          type: "fill",
          source: "zone-areas",
          filter: ["==", ["get", "layer"], spec.key],
          paint: { "fill-color": areaColor, "fill-opacity": spec.key === "territories" ? 0.14 : spec.key === "opszones" ? 0.22 : 0.1 },
        });
        addMapLayer(spec, {
          type: "line",
          source: "zone-areas",
          filter: ["==", ["get", "layer"], spec.key],
          paint: { "line-color": areaColor, "line-width": spec.key === "territories" ? 2 : spec.key === "opszones" ? 2.4 : 1.2 },
        });
        addMapLayer(spec, {
          type: "symbol",
          source: "zone-areas",
          minzoom: spec.key === "zones" ? 7 : 4,
          filter: ["==", ["get", "layer"], spec.key],
          layout: {
            "text-field": ["get", "name"],
            "text-size": spec.key === "zones" ? 11 : 12,
            "text-allow-overlap": false,
            "text-padding": 6,
          },
          paint: {
            "text-color": spec.key === "zones" ? "#68500f" : "#28302d",
            "text-halo-color": "rgba(255,255,255,0.9)",
            "text-halo-width": 1.4,
          },
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
    mapLayerBaseFilters.set("mission-links-line", ["==", ["get", "layer"], "mission_links"]);
    mapLayerIds.get("missions").push("mission-links-line");
    applyLayerVisibility();
  }

  function zoneAreaFeature(feature) {
    if (feature.geometry?.type === "Polygon") return feature;
    if (feature.geometry?.type !== "Point") return null;
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
        .filter((feature) => ["zones", "territories", "opszones"].includes(feature.properties?.layer))
        .map(zoneAreaFeature)
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
    if (selectedObjectId) {
      selectionCandidates = selectionCandidates
        .map((candidate) => latestPicture.features.find((feature) => feature.properties?.object_id === candidate.properties?.object_id))
        .filter(Boolean);
      selectionIndex = Math.max(0, selectionCandidates.findIndex((feature) => feature.properties?.object_id === selectedObjectId));
      const refreshed = selectionCandidates[selectionIndex]
        || latestPicture.features.find((feature) => feature.properties?.object_id === selectedObjectId);
      if (refreshed) showDetails(refreshed);
      else closeDetails();
    }
    if (!fitted) fitOperationalArea(latestPicture);
  }

  function fitOperationalArea(picture) {
    const candidates = picture.features.filter((feature) => {
      const properties = feature.properties || {};
      if (properties.layer === "territories" && feature.geometry?.type === "Polygon") return true;
      return feature.geometry?.type === "Point" && (
        properties.layer === "opszones" ||
        properties.layer === "legions" ||
        (["groups", "units", "statics"].includes(properties.layer) && properties.alive === true)
      );
    });
    if (!candidates.length) return;
    const bounds = new maplibregl.LngLatBounds();
    candidates.forEach((feature) => {
      if (feature.geometry.type === "Polygon") feature.geometry.coordinates.flat().forEach((coordinate) => bounds.extend(coordinate));
      else bounds.extend(feature.geometry.coordinates);
    });
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
    elements.connectionText.textContent = connected ? "DCS connected" : "DCS disconnected";
    elements.errorBanner.hidden = !status?.error;
    elements.errorBanner.textContent = status?.error ? "DCS bridge unavailable. Waiting for reconnection." : "";
  }

  function updateCounts() {
    const counts = new Map();
    latestPicture.features.forEach((feature) => {
      const key = feature.properties?.layer;
      counts.set(key, (counts.get(key) || 0) + 1);
      if (feature.properties?.map_category) {
        const categoryKey = `${key}:${feature.properties.map_category}`;
        counts.set(categoryKey, (counts.get(categoryKey) || 0) + 1);
      }
      counts.set(`coalition:${feature.properties?.map_coalition}`, (counts.get(`coalition:${feature.properties?.map_coalition}`) || 0) + 1);
      counts.set(`status:${feature.properties?.map_status}`, (counts.get(`status:${feature.properties?.map_status}`) || 0) + 1);
    });
    const trajectoryCount = counts.get("trajectories") || 0;
    elements.featureCount.textContent = trajectoryCount
      ? `${latestPicture.features.length - trajectoryCount} objects · ${trajectoryCount} tracks`
      : `${latestPicture.features.length} objects`;
    document.querySelectorAll("[data-layer-count]").forEach((node) => {
      node.textContent = String(counts.get(node.dataset.layerCount) || 0);
    });
    document.querySelectorAll("[data-layer-category-count]").forEach((node) => {
      node.textContent = String(counts.get(`${node.dataset.layerCategoryCount}:${node.dataset.category}`) || 0);
    });
    document.querySelectorAll("[data-filter-count]").forEach((node) => {
      node.textContent = String(counts.get(`${node.dataset.filterCount}:${node.dataset.filterValue}`) || 0);
    });
  }

  function layerControlMarkup(spec, attributes = "") {
    return `
      <input type="checkbox" ${attributes} ${spec.default ? "checked" : ""}>
      <i data-lucide="${spec.icon}" class="layer-symbol" style="--swatch:${spec.color || "#65716b"}"></i>
      <span class="layer-name">${spec.label}</span>`;
  }

  function buildLayerControls() {
    for (const spec of layerSpecs) {
      if (spec.children) {
        const group = document.createElement("div");
        group.className = "layer-group";
        const header = document.createElement("div");
        header.className = "layer-group-header";
        const expand = document.createElement("button");
        expand.className = "layer-expand icon-button";
        expand.type = "button";
        expand.title = `Collapse ${spec.label}`;
        expand.setAttribute("aria-label", `Collapse ${spec.label}`);
        expand.setAttribute("aria-expanded", "true");
        expand.innerHTML = '<i data-lucide="chevron-down"></i>';
        const parent = document.createElement("label");
        parent.className = "layer-control layer-control-parent";
        parent.innerHTML = `${layerControlMarkup(spec, `data-layer="${spec.key}"`)}<span class="layer-count" data-layer-count="${spec.key}">0</span>`;
        header.append(expand, parent);

        const children = document.createElement("div");
        children.className = "layer-children";
        for (const child of spec.children) {
          const label = document.createElement("label");
          label.className = "layer-control layer-control-child";
          label.innerHTML = `${layerControlMarkup(child, `data-parent-layer="${spec.key}" data-category="${child.key}"`)}<span class="layer-count" data-layer-category-count="${spec.key}" data-category="${child.key}">0</span>`;
          children.appendChild(label);
        }
        group.append(header, children);
        elements.layerControls.appendChild(group);
        continue;
      }
      const label = document.createElement("label");
      label.className = "layer-control";
      label.innerHTML = `${layerControlMarkup(spec, `data-layer="${spec.key}"`)}<span class="layer-count" data-layer-count="${spec.key}">0</span>`;
      elements.layerControls.appendChild(label);
    }
    elements.layerControls.addEventListener("change", (event) => {
      const target = event.target;
      if (target.matches("[data-layer]")) {
        const spec = layerSpecs.find((candidate) => candidate.key === target.dataset.layer);
        if (spec?.children) {
          document.querySelectorAll(`[data-parent-layer="${spec.key}"]`).forEach((child) => { child.checked = target.checked; });
        }
      } else if (target.matches("[data-parent-layer]")) {
        updateParentLayerControl(target.dataset.parentLayer);
      }
      applyLayerVisibility();
    });
    elements.layerControls.addEventListener("click", (event) => {
      const button = event.target.closest("[data-layer-expand], .layer-expand");
      if (!button) return;
      const children = button.closest(".layer-group").querySelector(".layer-children");
      children.hidden = !children.hidden;
      button.setAttribute("aria-expanded", String(!children.hidden));
      const label = button.closest(".layer-group").querySelector("[data-layer]").dataset.layer;
      button.title = `${children.hidden ? "Expand" : "Collapse"} ${layerSpecs.find((spec) => spec.key === label).label}`;
      button.setAttribute("aria-label", button.title);
    });
  }

  function updateParentLayerControl(layerKey) {
    const parent = document.querySelector(`[data-layer="${layerKey}"]`);
    const children = [...document.querySelectorAll(`[data-parent-layer="${layerKey}"]`)];
    if (!parent || !children.length) return;
    const selected = children.filter((child) => child.checked).length;
    parent.checked = selected > 0;
    parent.indeterminate = selected > 0 && selected < children.length;
  }

  function buildFilterControls() {
    for (const spec of filterSpecs) {
      const section = document.createElement("section");
      section.className = "filter-section";
      const heading = document.createElement("div");
      heading.className = "filter-heading";
      heading.textContent = spec.label;
      if (spec.key === "coalition") {
        const reset = document.createElement("button");
        reset.className = "filter-reset icon-button";
        reset.type = "button";
        reset.title = "Reset filters";
        reset.setAttribute("aria-label", "Reset filters");
        reset.innerHTML = '<i data-lucide="rotate-ccw"></i>';
        heading.appendChild(reset);
      }
      section.appendChild(heading);
      for (const option of spec.options) {
        const label = document.createElement("label");
        label.className = "layer-control filter-control";
        label.innerHTML = `
          <input type="checkbox" data-filter="${spec.key}" data-filter-value="${option.key}" checked>
          <i data-lucide="${option.icon}" class="layer-symbol" style="--swatch:${option.color}"></i>
          <span class="layer-name">${option.label}</span>
          <span class="layer-count" data-filter-count="${spec.key}" data-filter-value="${option.key}">0</span>`;
        section.appendChild(label);
      }
      elements.filterControls.appendChild(section);
    }
    elements.filterControls.addEventListener("change", applyLayerVisibility);
    elements.filterControls.addEventListener("click", (event) => {
      if (!event.target.closest(".filter-reset")) return;
      elements.filterControls.querySelectorAll("[data-filter]").forEach((checkbox) => { checkbox.checked = true; });
      applyLayerVisibility();
    });
  }

  function selectedFilterValues(key) {
    return [...document.querySelectorAll(`[data-filter="${key}"]:checked`)].map((checkbox) => checkbox.dataset.filterValue);
  }

  function applyLayerVisibility() {
    const coalitionFilter = ["in", ["get", "map_coalition"], ["literal", selectedFilterValues("coalition")]];
    const statusFilter = ["in", ["get", "map_status"], ["literal", selectedFilterValues("status")]];
    document.querySelectorAll("[data-layer]").forEach((checkbox) => {
      const visibility = checkbox.checked ? "visible" : "none";
      for (const id of mapLayerIds.get(checkbox.dataset.layer) || []) {
        if (!map.getLayer(id)) continue;
        map.setLayoutProperty(id, "visibility", visibility);
        const filters = [mapLayerBaseFilters.get(id), coalitionFilter, statusFilter].filter(Boolean);
        if (checkbox.dataset.layer === "airbases") {
          const categories = [...document.querySelectorAll('[data-parent-layer="airbases"]:checked')].map((child) => child.dataset.category);
          filters.push(["in", ["get", "map_category"], ["literal", categories]]);
        }
        map.setFilter(id, ["all", ...filters]);
      }
    });
  }

  function readableValue(value) {
    if (typeof value === "number") return Number.isInteger(value) ? String(value) : value.toFixed(3).replace(/0+$/, "").replace(/\.$/, "");
    if (typeof value === "boolean") return value ? "Yes" : "No";
    if (Array.isArray(value)) return value.join(", ");
    if (value && typeof value === "object") return JSON.stringify(value);
    return String(value ?? "-");
  }

  const fieldLabels = {
    category: "Category", coalition: "Coalition", owner: "Owner", state: "State", alive: "Alive", active: "Active",
    unit_count: "Units", alive_unit_count: "Units alive", mission_type: "Mission type", status: "Status", target: "Target",
    target_id: "Target", legion_id: "Legion", opsgroup_id: "OPS group", intel_id: "INTEL source", threat_level: "Threat level",
    threat_level_max: "Max threat", threat_level_sum: "Total threat", threat_level_avg: "Average threat", radius_m: "Radius",
    object_id: "Object ID", name: "Name", type: "Type", airbase_id: "Airbase ID", dcs_type: "DCS type", dcs_category_name: "DCS category", display_name: "Display name",
    group_name: "Group", source: "Source", recce_name: "Detected by", speed: "Speed", size: "Contacts",
    tracked_object_id: "Tracked object", source_layer: "Source layer", sample_count: "Samples", track_sample_count: "Track samples",
    derived_speed_kts: "Current speed", derived_heading_deg: "Movement heading", track_distance_m: "Track distance",
    track_duration_s: "Track duration", distance_m: "Distance", duration_s: "Duration", average_speed_mps: "Average speed",
    last_update_mission_time: "Last DCS update",
  };

  function humanizeKey(key) {
    return fieldLabels[key] || key.replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
  }

  function formattedField(key, value) {
    if (key === "radius_m") return `${Number(value).toLocaleString("en-US", { maximumFractionDigits: 0 })} m`;
    if (key === "speed" || key === "speed_kts") return `${Number(value).toFixed(1)} kt`;
    if (key === "derived_speed_kts") return `${Number(value).toFixed(1)} kt`;
    if (key === "derived_heading_deg") return `${Number(value).toFixed(1)}°`;
    if (key === "average_speed_mps") return `${(Number(value) * 1.9438444924406).toFixed(1)} kt`;
    if (key === "track_distance_m" || key === "distance_m") {
      const distance = Number(value);
      return distance >= 1000 ? `${(distance / 1000).toFixed(1)} km` : `${distance.toFixed(0)} m`;
    }
    if (key === "track_duration_s" || key === "duration_s" || key === "last_update_mission_time") {
      const seconds = Math.max(0, Math.floor(Number(value)));
      const hours = String(Math.floor(seconds / 3600)).padStart(2, "0");
      const minutes = String(Math.floor(seconds % 3600 / 60)).padStart(2, "0");
      const remaining = String(seconds % 60).padStart(2, "0");
      return `${hours}:${minutes}:${remaining}`;
    }
    return readableValue(value);
  }

  function addBadge(text, className = "") {
    const badge = document.createElement("span");
    badge.className = `detail-badge ${className}`.trim();
    badge.textContent = text;
    elements.detailBadges.appendChild(badge);
  }

  function addDetailSection(title, icon, rows) {
    if (!rows.length) return;
    const section = document.createElement("section");
    section.className = "detail-section";
    const heading = document.createElement("h3");
    heading.className = "detail-section-title";
    heading.innerHTML = `<i data-lucide="${icon}"></i><span>${title}</span>`;
    const list = document.createElement("dl");
    list.className = "property-list";
    for (const [label, value] of rows) {
      const term = document.createElement("dt");
      const description = document.createElement("dd");
      term.textContent = label;
      description.textContent = value;
      list.append(term, description);
    }
    section.append(heading, list);
    elements.detailSections.appendChild(section);
  }

  function detailRows(properties, keys, consumed) {
    const rows = [];
    for (const key of keys) {
      if (properties[key] === undefined || properties[key] === null || properties[key] === "") continue;
      rows.push([humanizeKey(key), formattedField(key, properties[key])]);
      consumed.add(key);
    }
    return rows;
  }

  function showDetails(feature) {
    selectedFeature = feature;
    const properties = feature.properties || {};
    selectedObjectId = properties.object_id || null;
    const layerLabel = layerSpecs.find((spec) => spec.key === properties.layer)?.label || properties.object_type || "Object";
    elements.detailType.textContent = [layerLabel, properties.category].filter(Boolean).join(" · ");
    elements.detailTitle.textContent = properties.name || properties.display_name || properties.object_id || "Unnamed object";
    elements.detailSubtitle.textContent = properties.object_id || "";
    elements.detailCopy.hidden = !properties.object_id;
    const stacked = selectionCandidates.length > 1;
    elements.detailStackCount.hidden = !stacked;
    elements.detailPrevious.hidden = !stacked;
    elements.detailNext.hidden = !stacked;
    elements.detailStackCount.textContent = stacked ? `${selectionIndex + 1} / ${selectionCandidates.length}` : "";
    elements.detailBadges.replaceChildren();
    elements.detailSections.replaceChildren();

    const side = String(properties.coalition || properties.owner || "").toLowerCase();
    if (side) addBadge(side, coalitionColors[side] ? `is-${side}` : "");
    if (typeof properties.alive === "boolean") addBadge(properties.alive ? "Alive" : "Dead", properties.alive ? "is-alive" : "is-dead");
    if (typeof properties.active === "boolean") addBadge(properties.active ? "Active" : "Inactive", properties.active ? "is-active" : "is-inactive");
    if (properties.state) addBadge(String(properties.state));

    const consumed = new Set(["name", "layer", "map_symbol", "coordinate_system", "dcs_name", "latitude", "longitude", "x", "y", "z", "category", "coalition", "owner", "state", "alive", "active", "object_type", "dcs_category"]);
    const operational = detailRows(properties, ["mission_type", "status", "target", "target_id", "threat_level", "threat_level_max", "threat_level_sum", "threat_level_avg", "unit_count", "alive_unit_count", "size", "speed", "radius_m", "derived_speed_kts", "derived_heading_deg", "track_distance_m", "track_duration_s", "last_update_mission_time", "sample_count", "distance_m", "duration_s", "average_speed_mps"], consumed);
    if (properties.unit_count !== undefined && properties.alive_unit_count !== undefined) {
      const start = operational.findIndex(([label]) => label === fieldLabels.unit_count);
      operational.splice(Math.max(0, start), 2, ["Strength", `${properties.alive_unit_count} / ${properties.unit_count} alive`]);
    }
    addDetailSection("Operational", "activity", operational);

    if (properties.layer === "airbases") {
      consumed.add("airbase_id");
      consumed.add("source");
      addDetailSection("Airbase", "plane-takeoff", [
        [fieldLabels.object_id, readableValue(properties.object_id)],
        [fieldLabels.name, readableValue(properties.name)],
        [fieldLabels.category, readableValue(properties.category)],
        [fieldLabels.type, readableValue(properties.type)],
      ]);
    } else {
      addDetailSection("Identity and relationships", "fingerprint", detailRows(properties, ["object_id", "tracked_object_id", "source_layer", "display_name", "dcs_type", "dcs_category_name", "group_name", "legion_id", "opsgroup_id", "intel_id", "recce_name", "source"], consumed));
    }

    const position = [];
    if (Number.isFinite(Number(properties.latitude)) && Number.isFinite(Number(properties.longitude))) {
      const lat = Number(properties.latitude); const lon = Number(properties.longitude);
      position.push(["WGS84", `${Math.abs(lat).toFixed(5)}° ${lat >= 0 ? "N" : "S"}, ${Math.abs(lon).toFixed(5)}° ${lon >= 0 ? "E" : "W"}`]);
    }
    if ([properties.x, properties.y, properties.z].some((value) => value !== undefined)) {
      const local = ["x", "y", "z"].map((key) => properties[key] === undefined ? "-" : Number(properties[key]).toFixed(3));
      position.push(["DCS x / y / z", local.join(" / ")]);
    }
    addDetailSection("Position", "map-pin", position);

    const additional = Object.keys(properties)
      .filter((key) => !consumed.has(key) && properties[key] !== null && properties[key] !== "")
      .sort((a, b) => a.localeCompare(b))
      .map((key) => [humanizeKey(key), formattedField(key, properties[key])]);
    addDetailSection("Additional data", "list", additional);
    if (window.lucide) window.lucide.createIcons({ attrs: { "aria-hidden": "true" } });
    if (window.innerWidth <= 720) {
      elements.layerPanel.hidden = true;
      elements.layersToggle.setAttribute("aria-expanded", "false");
    }
    elements.detailPanel.hidden = false;
  }

  function closeDetails() {
    selectedFeature = null;
    selectedObjectId = null;
    selectionCandidates = [];
    selectionIndex = 0;
    elements.detailPanel.hidden = true;
  }

  function showSelectionAt(index) {
    if (!selectionCandidates.length) return;
    selectionIndex = (index + selectionCandidates.length) % selectionCandidates.length;
    showDetails(selectionCandidates[selectionIndex]);
  }

  function focusSelectedFeature() {
    if (!selectedFeature?.geometry) return;
    if (selectedFeature.geometry.type === "Point") {
      map.easeTo({ center: selectedFeature.geometry.coordinates, zoom: Math.max(map.getZoom(), 11), duration: 500 });
    } else if (selectedFeature.geometry.type === "Polygon") {
      const bounds = new maplibregl.LngLatBounds();
      selectedFeature.geometry.coordinates.flat().forEach((coordinate) => bounds.extend(coordinate));
      if (!bounds.isEmpty()) map.fitBounds(bounds, { padding: 100, maxZoom: 12, duration: 500 });
    } else if (selectedFeature.geometry.type === "LineString") {
      const bounds = new maplibregl.LngLatBounds();
      selectedFeature.geometry.coordinates.forEach((coordinate) => bounds.extend(coordinate));
      if (!bounds.isEmpty()) map.fitBounds(bounds, { padding: 100, maxZoom: 12, duration: 500 });
    }
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
      updateStatus({ connected: false, error: "Connection to the map server was lost" });
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
  buildFilterControls();
  function showSettingsTab(tab) {
    const showLayers = tab === "layers";
    elements.layerControls.hidden = !showLayers;
    elements.filterControls.hidden = showLayers;
    elements.layersTab.classList.toggle("is-active", showLayers);
    elements.filtersTab.classList.toggle("is-active", !showLayers);
    elements.layersTab.setAttribute("aria-selected", String(showLayers));
    elements.filtersTab.setAttribute("aria-selected", String(!showLayers));
  }
  elements.layersTab.addEventListener("click", () => showSettingsTab("layers"));
  elements.filtersTab.addEventListener("click", () => showSettingsTab("filters"));
  elements.layersToggle.addEventListener("click", () => {
    const hidden = !elements.layerPanel.hidden;
    if (!hidden && window.innerWidth <= 720) elements.detailPanel.hidden = true;
    elements.layerPanel.hidden = hidden;
    elements.layersToggle.setAttribute("aria-expanded", String(!hidden));
  });
  elements.detailClose.addEventListener("click", closeDetails);
  elements.detailPrevious.addEventListener("click", () => showSelectionAt(selectionIndex - 1));
  elements.detailNext.addEventListener("click", () => showSelectionAt(selectionIndex + 1));
  elements.detailFocus.addEventListener("click", focusSelectedFeature);
  elements.detailCopy.addEventListener("click", async () => {
    if (!selectedObjectId) return;
    try {
      await navigator.clipboard.writeText(selectedObjectId);
      elements.detailCopy.title = "Object ID copied";
      setTimeout(() => { elements.detailCopy.title = "Copy object ID"; }, 1200);
    } catch (_) {
      elements.errorBanner.hidden = false;
      elements.errorBanner.textContent = "Object ID could not be copied.";
    }
  });
  document.addEventListener("keydown", (event) => { if (event.key === "Escape") closeDetails(); });

  map.on("load", async () => {
    await initializeSourcesAndLayers();
    loadInitialPicture();
    connect();
  });
  map.on("click", (event) => {
    const layers = [...mapLayerIds.values()].flat().filter((id) => map.getLayer(id));
    const features = map.queryRenderedFeatures(event.point, { layers });
    const seen = new Set();
    selectionCandidates = features.filter((feature) => {
      const objectId = feature.properties?.object_id;
      if (!objectId || seen.has(objectId)) return false;
      seen.add(objectId);
      return true;
    });
    selectionIndex = 0;
    if (selectionCandidates.length) showDetails(selectionCandidates[0]);
  });
  map.on("mousemove", (event) => {
    const layers = [...mapLayerIds.values()].flat().filter((id) => map.getLayer(id));
    map.getCanvas().style.cursor = map.queryRenderedFeatures(event.point, { layers }).length ? "pointer" : "";
  });

  if (window.lucide) window.lucide.createIcons();
})();
