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
    { key: "strategic_scope", label: "Strategic scope", color: "#59635e", icon: "scan", default: true },
    { key: "territories", label: "Source territories", color: "#59635e", icon: "map", default: false },
    { key: "frontlines", label: "Frontlines", color: "#573a58", icon: "git-commit-horizontal", default: true },
    { key: "pressure_frontlines", label: "Pressure lines", color: "#9a6f24", icon: "activity", default: false },
    { key: "incursions", label: "Incursions", color: "#d06f27", icon: "shield-alert", size: 1.12, default: true },
    { key: "opszones", label: "OPS zones", color: "#8b5ea7", icon: "shield", default: true },
    { key: "opsgroups", label: "OPS groups", color: "#1e8171", icon: "badge", size: 1.1, default: true },
    { key: "legions", label: "Legions", color: "#283a4f", icon: "shield", size: 1.18, default: true },
    { key: "intel_contacts", label: "INTEL contacts", color: "#c44343", icon: "crosshair", size: 0.95, default: true },
    { key: "intel_clusters", label: "INTEL clusters", color: "#d06f27", icon: "radar", size: 1.05, default: true },
    { key: "loss_reports", label: "Loss reports", color: "#8f3434", icon: "shield-x", size: 1.0, default: true },
    { key: "transport_bridges", label: "Bridges", color: "#a56a27", icon: "construction", default: false },
    { key: "transport_junctions", label: "Transport junctions", color: "#176f77", icon: "network", default: false },
    {
      key: "railway_infrastructure", label: "Rail infrastructure", color: "#4f5552", icon: "train-front", default: false,
      children: [
        { key: "station", label: "Stations", icon: "train-front", default: false },
        { key: "freight_terminal", label: "Freight terminals", icon: "container", default: false },
        { key: "rail_yard", label: "Rail yards", icon: "git-fork", default: false },
        { key: "depot", label: "Depots", icon: "warehouse", default: false },
        { key: "junction", label: "Rail junctions", icon: "network", default: false },
        { key: "bridge", label: "Rail bridges", icon: "construction", default: false },
      ],
    },
    {
      key: "energy_sites", label: "Energy sites", color: "#b38416", icon: "factory", default: false,
      children: [
        { key: "generation", label: "Power plants", icon: "factory", default: false },
        { key: "grid_substation", label: "Grid substations", icon: "network", default: false },
        { key: "converter_station", label: "Converter stations", icon: "activity", default: false },
      ],
    },
    { key: "fuel_storage_sites", label: "Fuel and storage sites", color: "#8a5a32", icon: "fuel", default: false },
    { key: "military_sites", label: "Military sites", color: "#6c5b48", icon: "shield", default: false },
    { key: "industrial_sites", label: "Industrial sites", color: "#76578b", icon: "factory", default: false },
    { key: "maritime_sites", label: "Ports and maritime logistics", color: "#176f77", icon: "anchor", default: false },
    { key: "settlements", label: "Cities and towns", color: "#9a4f4f", icon: "building-2", default: false },
    { key: "surface_land_regions", label: "Connected land", color: "#4f7a57", icon: "land-plot", default: false },
    { key: "surface_water_regions", label: "Connected water", color: "#277c9d", icon: "waves", default: false },
    { key: "topography_water", label: "Water", color: "#3c83a5", icon: "waves", default: false },
    { key: "topography_roads", label: "Road network", color: "#6f675a", icon: "route", default: false },
    { key: "topography_railways", label: "Railways", color: "#4f5552", icon: "train-front", default: false },
    { key: "topography_settlements", label: "Settlement source data", color: "#9a694d", icon: "building-2", default: false },
    { key: "topography_infrastructure", label: "Infrastructure candidates", color: "#76578b", icon: "factory", default: false },
    { key: "topography_landuse", label: "Land use", color: "#66835b", icon: "land-plot", default: false },
    { key: "topography_buildings", label: "Buildings", color: "#77736c", icon: "building", default: false },
    {
      key: "recon_coverage", label: "RECON coverage", color: "#167c73", icon: "scan-search", default: true,
      children: [
        { key: "aggregate", label: "Combined footprint", icon: "scan", color: "#167c73", default: true },
        { key: "assets", label: "Asset footprints", icon: "route", color: "#397f96", default: false },
        { key: "covered", label: "Covered components", icon: "circle-check", color: "#25865f", default: true },
        { key: "uncovered", label: "Uncovered components", icon: "circle-alert", color: "#c45b32", default: true },
      ],
    },
    { key: "strategic_objectives", label: "Strategic objectives", color: "#7d3f68", icon: "flag-triangle-right", size: 1.12, default: true },
    { key: "missions", label: "Missions", color: "#ad3c76", icon: "target", size: 1.05, default: true },
  ];
  const layerSections = [
    {
      key: "forces", label: "Forces", icon: "boxes", color: "#245f96",
      layers: ["groups", "units", "opsgroups", "statics", "trajectories"],
    },
    {
      key: "territorial", label: "Territorial control", icon: "map", color: "#573a58",
      layers: ["strategic_scope", "territories", "frontlines", "pressure_frontlines", "incursions"],
    },
    {
      key: "zones", label: "Zones", icon: "map-pin", color: "#8b5ea7",
      layers: ["zones", "opszones"],
    },
    {
      key: "intelligence", label: "Intelligence", icon: "radar", color: "#c44343",
      layers: ["intel_contacts", "intel_clusters", "recon_coverage"],
    },
    {
      key: "infrastructure", label: "Infrastructure", icon: "landmark", color: "#137f87",
      layers: ["airbases", "settlements", "transport_bridges", "transport_junctions", "railway_infrastructure", "maritime_sites", "energy_sites", "fuel_storage_sites", "military_sites", "industrial_sites"],
    },
    {
      key: "topography", label: "Topography", icon: "map", color: "#3c7069",
      layers: ["surface_land_regions", "surface_water_regions", "topography_water", "topography_roads", "topography_railways", "topography_settlements", "topography_infrastructure", "topography_landuse", "topography_buildings"],
    },
    {
      key: "operations", label: "Operations", icon: "target", color: "#ad3c76",
      layers: ["legions", "strategic_objectives", "missions"],
    },
    {
      key: "events", label: "Events", icon: "history", color: "#8f3434",
      layers: ["loss_reports"],
    },
  ];
  const layerSpecByKey = new Map(layerSpecs.map((spec) => [spec.key, spec]));
  const layerSectionByLayer = new Map(
    layerSections.flatMap((section) => section.layers.map((layer) => [layer, section.key])),
  );
  const coalitionColors = { blue: "#2776b9", red: "#c44343", neutral: "#858d88", unknown: "#59635e" };
  const filterSpecs = [
    {
      key: "coalition", property: "map_coalition", label: "Coalition",
      options: [
        { key: "blue", label: "Blue", icon: "flag", color: "#2776b9" },
        { key: "red", label: "Red", icon: "flag", color: "#c44343" },
        { key: "neutral", label: "Neutral", icon: "flag", color: "#858d88" },
        { key: "unassigned", label: "Unassigned", icon: "circle-help", color: "#65716b" },
      ],
    },
    {
      key: "status", property: "map_status", label: "Status",
      options: [
        { key: "alive", label: "Alive", icon: "activity", color: "#25865f" },
        { key: "dead", label: "Dead", icon: "circle-off", color: "#a65353" },
        { key: "unknown", label: "No status", icon: "circle-help", color: "#65716b" },
      ],
    },
    {
      key: "objective_owner", property: "objective_owner", layer: "strategic_objectives", label: "Objective owner",
      options: [
        { key: "blue", label: "Blue", icon: "flag", color: "#2776b9" },
        { key: "red", label: "Red", icon: "flag", color: "#c44343" },
        { key: "neutral", label: "Neutral", icon: "flag", color: "#858d88" },
        { key: "unassigned", label: "Unassigned", icon: "circle-help", color: "#65716b" },
      ],
    },
    {
      key: "objective_category", property: "objective_category", layer: "strategic_objectives", label: "Objective category",
      options: [
        { key: "airbase", label: "Airbase", icon: "plane-takeoff", color: "#397f96" },
        { key: "farp", label: "FARP", icon: "fan", color: "#397f96" },
        { key: "opszone", label: "OPS zone", icon: "shield", color: "#7d3f68" },
        { key: "territory", label: "City or territory", icon: "map", color: "#9b5548" },
        { key: "depot", label: "Depot", icon: "warehouse", color: "#9a6436" },
        { key: "port", label: "Port", icon: "ship", color: "#397f96" },
        { key: "infrastructure", label: "Infrastructure", icon: "landmark", color: "#75629b" },
        { key: "force", label: "Force", icon: "boxes", color: "#59635e" },
        { key: "custom", label: "Custom", icon: "flag-triangle-right", color: "#7d3f68" },
      ],
    },
    {
      key: "objective_rank", property: "objective_rank", layer: "strategic_objectives", label: "Objective rank",
      options: [
        { key: "top5", label: "Top 5", icon: "chevrons-up", color: "#9f3838" },
        { key: "top10", label: "6-10", icon: "chevron-up", color: "#c27532" },
        { key: "ranked", label: "11+", icon: "minus", color: "#68736d" },
        { key: "unranked", label: "Unranked", icon: "circle-help", color: "#8a928e" },
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
    "loss-report": { icon: "ShieldX", frame: "triangle" },
    "strategic-objective": { icon: "Flag", frame: "diamond" },
    "mission": { icon: "Target", frame: "diamond" },
    "incursion": { icon: "ShieldAlert", frame: "triangle" },
  };
  const mapLayerIds = new Map();
  const mapLayerBaseFilters = new Map();
  const mapLayerBaseOpacities = new Map();
  let latestPicture = EMPTY;
  let latestTopography = EMPTY;
  let latestSurfaceRegions = EMPTY;
  let latestTransportInfrastructure = EMPTY;
  let latestRailwayInfrastructure = EMPTY;
  let latestInfrastructureSites = EMPTY;
  let latestSettlements = EMPTY;
  const strategicVerifications = new Map();
  let topographyViewportAvailable = false;
  let fitted = false;
  let reconnectTimer = null;
  let transportRefreshTimer = null;
  let transportRequestSequence = 0;
  let selectedFeature = null;
  let selectedObjectId = null;
  let selectionCandidates = [];
  let selectionIndex = 0;
  let countUpdateTimer = null;
  const mapAppearanceStorageKeys = {
    basemap: "moosebridge.basemap",
    basemapOpacity: "moosebridge.basemapOpacity",
    territoryOpacity: "moosebridge.territoryOpacity",
    topographyOpacity: "moosebridge.topographyOpacity",
  };
  const basemaps = {
    osm: "basemap-osm",
    "carto-light": "basemap-carto-light",
    "carto-dark": "basemap-carto-dark",
  };

  function storedOpacity(key) {
    const stored = window.localStorage.getItem(key);
    if (stored === null) return 1;
    const value = Number(stored);
    return Number.isFinite(value) && value >= 0 && value <= 1 ? value : 1;
  }

  const storedBasemap = window.localStorage.getItem(mapAppearanceStorageKeys.basemap);
  let selectedBasemap = Object.hasOwn(basemaps, storedBasemap) ? storedBasemap : "osm";
  let basemapOpacity = storedOpacity(mapAppearanceStorageKeys.basemapOpacity);
  let territoryOpacity = storedOpacity(mapAppearanceStorageKeys.territoryOpacity);
  let topographyOpacity = storedOpacity(mapAppearanceStorageKeys.topographyOpacity);

  const map = new maplibregl.Map({
    container: "map",
    center: [11.8, 53.8],
    zoom: 6.2,
    minZoom: 3,
    style: {
      version: 8,
      glyphs: "https://demotiles.maplibre.org/font/{fontstack}/{range}.pbf",
      sources: {
        "basemap-osm": {
          type: "raster",
          tiles: ["https://tile.openstreetmap.org/{z}/{x}/{y}.png"],
          tileSize: 256,
          maxzoom: 19,
          attribution: "© OpenStreetMap contributors",
        },
        "basemap-carto-light": {
          type: "raster",
          tiles: [
            "https://a.basemaps.cartocdn.com/light_all/{z}/{x}/{y}@2x.png",
            "https://b.basemaps.cartocdn.com/light_all/{z}/{x}/{y}@2x.png",
            "https://c.basemaps.cartocdn.com/light_all/{z}/{x}/{y}@2x.png",
            "https://d.basemaps.cartocdn.com/light_all/{z}/{x}/{y}@2x.png",
          ],
          tileSize: 256,
          maxzoom: 20,
          attribution: "© OpenStreetMap contributors © CARTO",
        },
        "basemap-carto-dark": {
          type: "raster",
          tiles: [
            "https://a.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}@2x.png",
            "https://b.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}@2x.png",
            "https://c.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}@2x.png",
            "https://d.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}@2x.png",
          ],
          tileSize: 256,
          maxzoom: 20,
          attribution: "© OpenStreetMap contributors © CARTO",
        },
      },
      layers: Object.entries(basemaps).map(([key, id]) => ({
        id,
        type: "raster",
        source: id,
        layout: { visibility: key === selectedBasemap ? "visible" : "none" },
        paint: { "raster-opacity": basemapOpacity },
      })),
    },
  });
  map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "bottom-right");
  map.on("error", (event) => {
    console.error("Map rendering error:", event.error?.message || event.error || event);
  });

  const elements = {
    connectionDot: document.getElementById("connection-dot"),
    connectionText: document.getElementById("connection-text"),
    dcsClock: document.getElementById("dcs-clock"),
    missionClock: document.getElementById("mission-clock"),
    relationshipState: document.getElementById("relationship-state"),
    escalationScore: document.getElementById("escalation-score"),
    pendingTransition: document.getElementById("pending-transition"),
    blueDoctrine: document.getElementById("blue-doctrine"),
    redDoctrine: document.getElementById("red-doctrine"),
    featureCount: document.getElementById("feature-count"),
    basemapStyle: document.getElementById("basemap-style"),
    basemapOpacity: document.getElementById("basemap-opacity"),
    basemapOpacityValue: document.getElementById("basemap-opacity-value"),
    territoryOpacity: document.getElementById("territory-opacity"),
    territoryOpacityValue: document.getElementById("territory-opacity-value"),
    topographyOpacity: document.getElementById("topography-opacity"),
    topographyOpacityValue: document.getElementById("topography-opacity-value"),
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
    detailF10Marker: document.getElementById("detail-f10-marker"),
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

  function objectiveRankCategory(value) {
    const rank = Number(value);
    if (!Number.isFinite(rank) || rank <= 0) return "unranked";
    if (rank <= 5) return "top5";
    if (rank <= 10) return "top10";
    return "ranked";
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
    else if (layer === "loss_reports") definition = "loss-report";
    else if (layer === "strategic_objectives") definition = "strategic-objective";
    else if (layer === "missions") definition = "mission";
    else if (layer === "incursions") definition = "incursion";
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
          map_category: feature.properties?.map_category || (feature.properties?.layer === "airbases" ? airbaseCategory(feature.properties || {}) : undefined),
          map_coalition: coalitionFilterCategory(feature.properties || {}),
          map_status: statusFilterCategory(feature.properties || {}),
          objective_owner: feature.properties?.layer === "strategic_objectives"
            ? coalitionFilterCategory(feature.properties || {}) : undefined,
          objective_category: feature.properties?.layer === "strategic_objectives"
            ? String(feature.properties?.category || "custom").toLowerCase() : undefined,
          objective_rank: feature.properties?.layer === "strategic_objectives"
            ? objectiveRankCategory(feature.properties?.selection_rank) : undefined,
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
    const opacityProperties = {
      fill: ["fill-opacity"],
      line: ["line-opacity"],
      circle: ["circle-opacity", "circle-stroke-opacity"],
      symbol: ["icon-opacity", "text-opacity"],
    }[definition.type] || [];
    mapLayerBaseOpacities.set(id, Object.fromEntries(
      opacityProperties.map((property) => [property, definition.paint?.[property] ?? 1]),
    ));
    existing.push(id);
    mapLayerIds.set(spec.key, existing);
  }

  function isTopographyLayer(layer) {
    return String(layer || "").startsWith("topography_");
  }

  function infrastructureVisibilityOpacity() {
    return [
      "step", ["zoom"],
      ["match", ["get", "importance_tier"], "critical", 0.96, "high", 0.9, 0],
      9, ["match", ["get", "importance_tier"], "critical", 0.96, "high", 0.92, "medium", 0.82, 0],
      11, ["match", ["get", "importance_tier"], "critical", 0.96, "high", 0.92, "medium", 0.86, 0.72],
    ];
  }

  function loadedVectorTopographyFeatures() {
    if (!topographyViewportAvailable || !map.isStyleLoaded()) return [];
    const features = [];
    const seen = new Set();
    for (const spec of layerSpecs.filter((item) => isTopographyLayer(item.key))) {
      const sourceId = `topography-${spec.key}`;
      if (!map.getSource(sourceId)) continue;
      for (const feature of map.querySourceFeatures(sourceId, { sourceLayer: spec.key })) {
        const objectId = feature.properties?.object_id;
        if (objectId && seen.has(objectId)) continue;
        if (objectId) seen.add(objectId);
        features.push(feature.toJSON ? feature.toJSON() : feature);
      }
    }
    return features;
  }

  function allFeatures() {
    const topography = topographyViewportAvailable ? loadedVectorTopographyFeatures() : latestTopography.features;
    return [
      ...latestPicture.features,
      ...topography,
      ...latestSurfaceRegions.features,
      ...latestTransportInfrastructure.features,
      ...latestRailwayInfrastructure.features,
      ...latestInfrastructureSites.features,
      ...latestSettlements.features,
    ];
  }

  function topographySource(spec) {
    return topographyViewportAvailable
      ? { source: `topography-${spec.key}`, "source-layer": spec.key }
      : { source: "topography" };
  }

  function topographyFilter(spec, conditions = []) {
    const filters = topographyViewportAvailable
      ? [...conditions]
      : [["==", ["get", "layer"], spec.key], ...conditions];
    if (!filters.length) return {};
    return { filter: filters.length === 1 ? filters[0] : ["all", ...filters] };
  }

  async function initializeSourcesAndLayers() {
    await registerMapSymbols();
    map.addSource("picture", { type: "geojson", data: EMPTY, promoteId: "object_id" });
    map.addSource("zone-areas", { type: "geojson", data: EMPTY, promoteId: "object_id" });
    map.addSource("topography", { type: "geojson", data: EMPTY, promoteId: "object_id" });
    if (topographyViewportAvailable) {
      for (const spec of layerSpecs.filter((item) => isTopographyLayer(item.key))) {
        map.addSource(`topography-${spec.key}`, {
          type: "vector",
          tiles: [`${location.origin}/api/topography/tiles/${spec.key}/{z}/{x}/{y}.pbf`],
          minzoom: 8,
          maxzoom: 14,
          promoteId: "object_id",
        });
      }
    }
    map.addSource("surface-regions", { type: "geojson", data: EMPTY, promoteId: "object_id" });
    map.addSource("transport-infrastructure", { type: "geojson", data: EMPTY, promoteId: "object_id" });
    map.addSource("railway-infrastructure", { type: "geojson", data: EMPTY, promoteId: "object_id" });
    map.addSource("infrastructure-sites", { type: "geojson", data: EMPTY, promoteId: "object_id" });
    map.addSource("settlements", { type: "geojson", data: EMPTY, promoteId: "map_feature_id" });

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
      if (spec.key === "frontlines") {
        addMapLayer(spec, {
          type: "line",
          filter: ["==", ["get", "layer"], spec.key],
          paint: {
            "line-color": "rgba(255,255,255,0.92)",
            "line-width": 7,
            "line-opacity": 0.9,
          },
        });
        addMapLayer(spec, {
          type: "line",
          filter: ["==", ["get", "layer"], spec.key],
          paint: {
            "line-color": spec.color,
            "line-width": 4,
            "line-dasharray": [2, 1.2],
            "line-opacity": 0.96,
          },
        });
        continue;
      }
      if (spec.key === "pressure_frontlines") {
        addMapLayer(spec, {
          type: "line",
          filter: ["==", ["get", "layer"], spec.key],
          paint: {
            "line-color": spec.color,
            "line-width": 2.5,
            "line-dasharray": [1.2, 1.6],
            "line-opacity": 0.82,
          },
        });
        continue;
      }
      if (spec.key === "zones" || spec.key === "territories" || spec.key === "strategic_scope" || spec.key === "opszones") {
        const areaColor = spec.key === "opszones"
          ? ["case",
              ["==", ["get", "contested"], true], "#d06f27",
              ["match", ["get", "owner"], "blue", coalitionColors.blue, "red", coalitionColors.red, "neutral", coalitionColors.neutral, spec.color],
            ]
          : spec.key === "strategic_scope"
            ? ["match", ["get", "scope_state"], "blue", coalitionColors.blue, "red", coalitionColors.red, "neutral", "#aeb3ae", "contested", "#d06f27", spec.color]
          : spec.key === "territories"
            ? ["match", ["get", "coalition"], "blue", coalitionColors.blue, "red", coalitionColors.red, "neutral", coalitionColors.neutral, spec.color]
          : spec.color;
        addMapLayer(spec, {
          type: "fill",
          source: "zone-areas",
          filter: ["==", ["get", "layer"], spec.key],
          paint: { "fill-color": areaColor, "fill-opacity": spec.key === "strategic_scope" ? 0.18 : spec.key === "territories" ? 0.1 : spec.key === "opszones" ? 0.22 : 0.1 },
        });
        addMapLayer(spec, {
          type: "line",
          source: "zone-areas",
          filter: ["==", ["get", "layer"], spec.key],
          paint: { "line-color": areaColor, "line-width": spec.key === "strategic_scope" ? 2.5 : spec.key === "territories" ? 1.4 : spec.key === "opszones" ? 2.4 : 1.2 },
        });
        addMapLayer(spec, {
          type: "symbol",
          source: "zone-areas",
          minzoom: spec.key === "zones" ? 7 : spec.key === "strategic_scope" ? 5 : 4,
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
      if (spec.key === "recon_coverage") {
        addMapLayer(spec, {
          type: "fill",
          filter: ["all", ["==", ["get", "layer"], spec.key], ["in", ["get", "map_category"], ["literal", ["aggregate", "assets"]]]],
          paint: {
            "fill-color": ["match", ["get", "map_category"], "assets", "#397f96", "#167c73"],
            "fill-opacity": ["match", ["get", "map_category"], "assets", 0.08, 0.2],
          },
        });
        addMapLayer(spec, {
          type: "line",
          filter: ["all", ["==", ["get", "layer"], spec.key], ["==", ["get", "map_category"], "aggregate"]],
          paint: {
            "line-color": "#12665f",
            "line-width": 2.4,
            "line-opacity": 0.9,
          },
        });
        addMapLayer(spec, {
          type: "line",
          filter: ["all", ["==", ["get", "layer"], spec.key], ["==", ["get", "map_category"], "assets"]],
          paint: {
            "line-color": "#397f96",
            "line-width": 1.4,
            "line-dasharray": [2, 1.5],
            "line-opacity": 0.9,
          },
        });
        addMapLayer(spec, {
          type: "circle",
          filter: ["all", ["==", ["get", "layer"], spec.key], ["in", ["get", "map_category"], ["literal", ["covered", "uncovered"]]]],
          paint: {
            "circle-radius": 7,
            "circle-color": ["match", ["get", "map_category"], "covered", "#25865f", "#c45b32"],
            "circle-stroke-color": "rgba(255,255,255,0.96)",
            "circle-stroke-width": 2.2,
            "circle-opacity": 0.96,
          },
        });
        continue;
      }
      if (spec.key === "strategic_objectives") {
        addMapLayer(spec, {
          type: "symbol",
          minzoom: 5,
          filter: ["==", ["get", "layer"], spec.key],
          layout: {
            "icon-image": ["get", "map_symbol"],
            "icon-size": [
              "interpolate", ["linear"], ["coalesce", ["get", "strategic_value"], 0],
              0, 0.82, 50, 1.02, 100, 1.24,
            ],
            "icon-allow-overlap": true,
            "icon-padding": 3,
          },
          paint: {
            "icon-opacity": ["case", ["==", ["get", "status"], "destroyed"], 0.38, 0.96],
          },
        });
        continue;
      }
      if (spec.key === "surface_land_regions" || spec.key === "surface_water_regions") {
        addMapLayer(spec, {
          type: "fill",
          source: "surface-regions",
          filter: ["==", ["get", "layer"], spec.key],
          paint: {
            "fill-color": spec.color,
            "fill-opacity": spec.key === "surface_land_regions" ? 0.12 : 0.2,
          },
        });
        addMapLayer(spec, {
          type: "line",
          source: "surface-regions",
          filter: spec.key === "surface_water_regions"
            ? ["all", ["==", ["get", "layer"], spec.key], ["!=", ["get", "region_kind"], "maritime"]]
            : ["==", ["get", "layer"], spec.key],
          paint: {
            "line-color": spec.color,
            "line-width": ["case", ["==", ["get", "region_kind"], "mainland"], 2.2, 1.4],
            "line-opacity": 0.9,
          },
        });
        continue;
      }
      if (spec.key === "transport_bridges") {
        addMapLayer(spec, {
          type: "circle",
          source: "transport-infrastructure",
          filter: ["==", ["get", "layer"], spec.key],
          paint: {
            "circle-radius": [
              "interpolate", ["linear"], ["zoom"],
              4, ["interpolate", ["linear"], ["coalesce", ["get", "member_count"], 1], 1, 2.5, 3, 3.25, 8, 4],
              8, ["interpolate", ["linear"], ["coalesce", ["get", "member_count"], 1], 1, 4, 3, 5.2, 8, 6.4],
              11, ["interpolate", ["linear"], ["coalesce", ["get", "member_count"], 1], 1, 5, 3, 6.5, 8, 8],
            ],
            "circle-color": [
              "match", ["get", "importance_tier"],
              "critical", "#b83232", "high", "#d17822", "medium", spec.color, "#7d8581",
            ],
            "circle-stroke-color": "rgba(255,255,255,0.96)",
            "circle-stroke-width": ["interpolate", ["linear"], ["zoom"], 4, 0.8, 9, 1.4, 11, 1.8],
            "circle-opacity": infrastructureVisibilityOpacity(),
            "circle-stroke-opacity": infrastructureVisibilityOpacity(),
          },
        });
        continue;
      }
      if (spec.key === "transport_junctions") {
        addMapLayer(spec, {
          type: "circle",
          source: "transport-infrastructure",
          filter: ["==", ["get", "layer"], spec.key],
          paint: {
            "circle-radius": [
              "interpolate", ["linear"], ["zoom"],
              4, ["*", 0.5, ["+",
                ["match", ["get", "junction_kind"], "interchange", 6, "major_junction", 5, 4],
                ["interpolate", ["linear"], ["coalesce", ["get", "member_count"], 1], 1, 0, 4, 1.5, 12, 3],
              ]],
              8, ["*", 0.8, ["+",
                ["match", ["get", "junction_kind"], "interchange", 6, "major_junction", 5, 4],
                ["interpolate", ["linear"], ["coalesce", ["get", "member_count"], 1], 1, 0, 4, 1.5, 12, 3],
              ]],
              11, ["+",
                ["match", ["get", "junction_kind"], "interchange", 6, "major_junction", 5, 4],
                ["interpolate", ["linear"], ["coalesce", ["get", "member_count"], 1], 1, 0, 4, 1.5, 12, 3],
              ],
            ],
            "circle-color": [
              "match", ["get", "importance_tier"],
              "critical", "#b83232", "high", "#d17822", "medium", spec.color, "#7d8581",
            ],
            "circle-stroke-color": "rgba(255,255,255,0.96)",
            "circle-stroke-width": ["interpolate", ["linear"], ["zoom"], 4, 0.8, 9, 1.4, 11, 1.8],
            "circle-opacity": infrastructureVisibilityOpacity(),
            "circle-stroke-opacity": infrastructureVisibilityOpacity(),
          },
        });
        continue;
      }
      if (spec.key === "railway_infrastructure") {
        addMapLayer(spec, {
          type: "circle",
          source: "railway-infrastructure",
          minzoom: 7,
          filter: ["==", ["get", "layer"], spec.key],
          paint: {
            "circle-radius": [
              "+",
              ["match", ["get", "importance_tier"], "critical", 7, "high", 6, "medium", 5, 4],
              ["interpolate", ["linear"], ["coalesce", ["get", "member_count"], 1], 1, 0, 5, 1.5, 20, 3],
            ],
            "circle-color": [
              "match", ["get", "map_category"],
              "station", "#4f5552",
              "freight_terminal", "#76578b",
              "rail_yard", "#7b6332",
              "depot", "#6c5b48",
              "junction", "#176f77",
              "bridge", "#a56a27",
              spec.color,
            ],
            "circle-stroke-color": [
              "match", ["get", "importance_tier"], "critical", "#b83232", "high", "#d17822", "rgba(255,255,255,0.96)",
            ],
            "circle-stroke-width": ["match", ["get", "importance_tier"], "critical", 3, "high", 2.5, 1.7],
            "circle-opacity": infrastructureVisibilityOpacity(),
            "circle-stroke-opacity": infrastructureVisibilityOpacity(),
          },
        });
        continue;
      }
      if (["energy_sites", "fuel_storage_sites", "military_sites", "industrial_sites", "maritime_sites"].includes(spec.key)) {
        if (["energy_sites", "military_sites", "industrial_sites", "maritime_sites"].includes(spec.key)) {
          const siteAreaFilter = [
            "all",
            ["==", ["get", "layer"], spec.key],
            ["in", ["geometry-type"], ["literal", ["Polygon", "MultiPolygon"]]],
            ["==", ["get", "site_geometry"], "area"],
          ];
          const siteColor = [
            "match", ["get", "importance_tier"],
            "critical", spec.key === "energy_sites" ? "#85600d" : spec.key === "military_sites" ? "#873838" : spec.key === "maritime_sites" ? "#075f70" : "#6f315f",
            "high", spec.key === "energy_sites" ? "#a57716" : spec.key === "military_sites" ? "#8a5b37" : spec.key === "maritime_sites" ? "#177688" : "#754b70",
            "medium", spec.key === "energy_sites" ? "#b38d35" : spec.key === "military_sites" ? "#73634c" : spec.key === "maritime_sites" ? "#338796" : "#6d5d78",
            spec.color,
          ];
          addMapLayer(spec, {
            type: "fill",
            source: "infrastructure-sites",
            minzoom: spec.key === "military_sites" ? 8 : 9,
            filter: siteAreaFilter,
            paint: {
              "fill-color": siteColor,
              "fill-opacity": spec.key === "military_sites"
                ? ["case", ["==", ["get", "targetable_candidate"], true], 0.2, 0.1]
                : ["case", ["==", ["get", "strategic_candidate"], true], 0.2, 0.1],
            },
          });
          addMapLayer(spec, {
            type: "line",
            source: "infrastructure-sites",
            minzoom: spec.key === "military_sites" ? 8 : 9,
            filter: siteAreaFilter,
            paint: {
              "line-color": siteColor,
              "line-width": ["interpolate", ["linear"], ["zoom"], 8, 1.2, 13, 2.2],
              "line-opacity": 0.9,
            },
          });
        }
        const detailedSite = ["energy_sites", "military_sites", "industrial_sites", "maritime_sites"].includes(spec.key);
        const sitePointFilter = [
          "all",
          ["==", ["get", "layer"], spec.key],
          ["==", ["geometry-type"], "Point"],
        ];
        const siteCircleColor = detailedSite
          ? ["match", ["get", "importance_tier"],
            "critical", spec.key === "energy_sites" ? "#85600d" : spec.key === "military_sites" ? "#873838" : spec.key === "maritime_sites" ? "#075f70" : "#6f315f",
            "high", spec.key === "energy_sites" ? "#a57716" : spec.key === "military_sites" ? "#8a5b37" : spec.key === "maritime_sites" ? "#177688" : "#754b70",
            "medium", spec.key === "energy_sites" ? "#b38d35" : spec.key === "military_sites" ? "#73634c" : spec.key === "maritime_sites" ? "#338796" : "#6d5d78",
            spec.color]
          : spec.color;
        const siteOverviewOpacity = ["energy_sites", "industrial_sites", "maritime_sites"].includes(spec.key)
          ? ["step", ["zoom"],
            ["match", ["get", "importance_tier"], "critical", 0.94, "high", 0.94, 0],
            7, ["match", ["get", "importance_tier"], "critical", 0.94, "high", 0.94, "medium", 0.9, 0],
            9, 0.94]
          : 0.94;
        const siteCirclePaint = {
          "circle-radius": [
            "interpolate", ["linear"], ["zoom"],
            5, ["+", 2.5, ["match", ["coalesce", ["get", "scale"], ""], "very_large", 2.5, "large", 1.5, "medium", 0.75, 0]],
            9, ["+", 5, ["match", ["coalesce", ["get", "scale"], ""], "very_large", 2.5, "large", 1.5, "medium", 0.75, 0]],
            13, ["+", 7, ["match", ["coalesce", ["get", "scale"], ""], "very_large", 2.5, "large", 1.5, "medium", 0.75, 0]],
          ],
          "circle-color": siteCircleColor,
          "circle-stroke-color": "rgba(255,255,255,0.96)",
          "circle-stroke-width": ["interpolate", ["linear"], ["zoom"], 5, 0.6, 10, 1.5],
          "circle-opacity": siteOverviewOpacity,
          "circle-stroke-opacity": siteOverviewOpacity,
        };
        addMapLayer(spec, {
          type: "circle",
          source: "infrastructure-sites",
          minzoom: 5,
          maxzoom: spec.key === "military_sites" ? 9 : ["energy_sites", "industrial_sites", "maritime_sites"].includes(spec.key) ? 10 : 24,
          filter: sitePointFilter,
          paint: siteCirclePaint,
        });
        if (detailedSite) {
          addMapLayer(spec, {
            type: "circle",
            source: "infrastructure-sites",
            minzoom: spec.key === "military_sites" ? 9 : 10,
            filter: ["all", ...sitePointFilter.slice(1), ["==", ["get", "source_geometry_type"], "Point"]],
            paint: { ...siteCirclePaint, "circle-opacity": 0.94, "circle-stroke-opacity": 0.94 },
          });
        }
        continue;
      }
      if (spec.key === "settlements") {
        const importanceColor = [
          "match", ["get", "importance_tier"],
          "critical", "#8f2f3c", "high", "#b4524f", "medium", "#c87a62", "#9b8174",
        ];
        const settlementLevels = [
          { classes: ["metropolis", "large_city"], minzoom: 4, labelZoom: 5, radius: 7 },
          { classes: ["medium_city"], minzoom: 6.5, labelZoom: 7, radius: 5.5 },
          { classes: ["small_city", "land_town"], minzoom: 8.5, labelZoom: 9, radius: 4.5 },
        ];
        for (const level of settlementLevels) {
          const classFilter = ["in", ["get", "size_class"], ["literal", level.classes]];
          const areaFilter = [
            "all",
            ["==", ["get", "layer"], spec.key],
            ["==", ["geometry-type"], "Polygon"],
            ["==", ["get", "settlement_geometry"], "urban"],
            classFilter,
          ];
          const administrativeFilter = [
            "all",
            ["==", ["get", "layer"], spec.key],
            ["==", ["geometry-type"], "Polygon"],
            ["==", ["get", "settlement_geometry"], "administrative"],
            classFilter,
          ];
          const pointFilter = [
            "all",
            ["==", ["get", "layer"], spec.key],
            ["==", ["geometry-type"], "Point"],
            classFilter,
          ];
          addMapLayer(spec, {
            type: "fill",
            source: "settlements",
            minzoom: level.minzoom,
            filter: administrativeFilter,
            paint: {
              "fill-color": importanceColor,
              "fill-opacity": ["interpolate", ["linear"], ["zoom"], level.minzoom, 0.015, 10, 0.035],
            },
          });
          addMapLayer(spec, {
            type: "line",
            source: "settlements",
            minzoom: level.minzoom,
            filter: administrativeFilter,
            paint: {
              "line-color": importanceColor,
              "line-width": ["interpolate", ["linear"], ["zoom"], level.minzoom, 0.8, 11, 1.3],
              "line-dasharray": [3, 2],
              "line-opacity": 0.62,
            },
          });
          addMapLayer(spec, {
            type: "fill",
            source: "settlements",
            minzoom: level.minzoom,
            filter: areaFilter,
            paint: {
              "fill-color": importanceColor,
              "fill-opacity": ["interpolate", ["linear"], ["zoom"], level.minzoom, 0.1, 10, 0.16],
            },
          });
          addMapLayer(spec, {
            type: "line",
            source: "settlements",
            minzoom: level.minzoom,
            filter: areaFilter,
            paint: {
              "line-color": importanceColor,
              "line-width": ["interpolate", ["linear"], ["zoom"], level.minzoom, 1, 11, 2],
              "line-opacity": 0.82,
            },
          });
          addMapLayer(spec, {
            type: "circle",
            source: "settlements",
            minzoom: level.minzoom,
            filter: pointFilter,
            paint: {
              "circle-radius": ["interpolate", ["linear"], ["zoom"], level.minzoom, level.radius, 12, level.radius + 3],
              "circle-color": importanceColor,
              "circle-stroke-color": "rgba(255,255,255,0.96)",
              "circle-stroke-width": 1.5,
              "circle-opacity": 0.94,
            },
          });
          addMapLayer(spec, {
            type: "symbol",
            source: "settlements",
            minzoom: level.labelZoom,
            filter: pointFilter,
            layout: {
              "text-field": ["get", "name"],
              "text-size": ["match", ["get", "size_class"], "metropolis", 14, "large_city", 13, "medium_city", 12, 11],
              "text-offset": [0, 1.05],
              "text-anchor": "top",
              "text-allow-overlap": false,
              "text-padding": 8,
            },
            paint: {
              "text-color": "#593b3b",
              "text-halo-color": "rgba(255,255,255,0.94)",
              "text-halo-width": 1.4,
            },
          });
        }
        continue;
      }
      if (spec.key === "topography_water") {
        addMapLayer(spec, {
          type: "fill",
          ...topographySource(spec),
          ...topographyFilter(spec, [["in", ["geometry-type"], ["literal", ["Polygon", "MultiPolygon"]]]]),
          paint: { "fill-color": spec.color, "fill-opacity": 0.34 },
        });
        addMapLayer(spec, {
          type: "line",
          ...topographySource(spec),
          ...topographyFilter(spec),
          paint: { "line-color": "#176f98", "line-width": 2.2, "line-opacity": 0.96 },
        });
        continue;
      }
      if (spec.key === "topography_roads" || spec.key === "topography_railways") {
        addMapLayer(spec, {
          type: "line",
          ...topographySource(spec),
          ...topographyFilter(spec),
          paint: {
            "line-color": "rgba(255,255,255,0.82)",
            "line-width": spec.key === "topography_roads"
              ? ["match", ["get", "category"], "motorway", 5.6, "trunk", 5.0, "primary", 4.5, 3.6]
              : 4.0,
            "line-opacity": 0.9,
          },
        });
        addMapLayer(spec, {
          type: "line",
          ...topographySource(spec),
          ...topographyFilter(spec),
          paint: {
            "line-color": spec.color,
            "line-width": spec.key === "topography_roads"
              ? ["match", ["get", "category"], "motorway", 3.8, "trunk", 3.2, "primary", 2.8, 2.2]
              : 2.4,
            ...(spec.key === "topography_railways" ? { "line-dasharray": [2, 1.3] } : {}),
            "line-opacity": 0.88,
          },
        });
        continue;
      }
      if (spec.key === "topography_settlements" || spec.key === "topography_infrastructure") {
        addMapLayer(spec, {
          type: "fill",
          ...topographySource(spec),
          ...topographyFilter(spec, [["in", ["geometry-type"], ["literal", ["Polygon", "MultiPolygon"]]]]),
          paint: { "fill-color": spec.color, "fill-opacity": 0.16 },
        });
        addMapLayer(spec, {
          type: "circle",
          ...topographySource(spec),
          ...topographyFilter(spec, [["==", ["geometry-type"], "Point"]]),
          paint: { "circle-radius": spec.key === "topography_settlements" ? 5 : 4, "circle-color": spec.color, "circle-stroke-color": "#ffffff", "circle-stroke-width": 1.2 },
        });
        addMapLayer(spec, {
          type: "symbol",
          ...topographySource(spec),
          minzoom: 7,
          ...topographyFilter(spec),
          layout: { "text-field": ["get", "name"], "text-size": 11, "text-offset": [0, 1.1], "text-allow-overlap": false },
          paint: { "text-color": "#313936", "text-halo-color": "rgba(255,255,255,0.92)", "text-halo-width": 1.2 },
        });
        continue;
      }
      if (spec.key === "topography_landuse" || spec.key === "topography_buildings") {
        addMapLayer(spec, {
          type: "fill",
          ...topographySource(spec),
          ...topographyFilter(spec),
          paint: {
            "fill-color": spec.color,
            "fill-opacity": spec.key === "topography_buildings" ? 0.28 : 0.14,
            "fill-outline-color": spec.color,
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
        .filter((feature) => ["zones", "territories", "strategic_scope", "opszones"].includes(feature.properties?.layer))
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
    updateDiplomacy(picture.properties?.diplomacy);
    if (selectedObjectId) {
      selectionCandidates = selectionCandidates
        .map((candidate) => allFeatures().find((feature) => feature.properties?.object_id === candidate.properties?.object_id))
        .filter(Boolean);
      selectionIndex = Math.max(0, selectionCandidates.findIndex((feature) => feature.properties?.object_id === selectedObjectId));
      const refreshed = selectionCandidates[selectionIndex]
        || allFeatures().find((feature) => feature.properties?.object_id === selectedObjectId);
      if (refreshed) showDetails(refreshed);
      else closeDetails();
    }
    if (!fitted) fitOperationalArea(latestPicture);
  }


  function setTopography(topography) {
    if (!topography || topography.type !== "FeatureCollection") return;
    latestTopography = decoratedPicture(topography);
    const source = map.getSource("topography");
    if (!source) return;
    source.setData(latestTopography);
    updateCounts();
  }

  function setSurfaceRegions(surfaceRegions) {
    if (!surfaceRegions || surfaceRegions.type !== "FeatureCollection") return;
    latestSurfaceRegions = decoratedPicture(surfaceRegions);
    const source = map.getSource("surface-regions");
    if (!source) return;
    source.setData(latestSurfaceRegions);
    updateCounts();
  }

  function setTransportInfrastructure(infrastructure) {
    if (!infrastructure || infrastructure.type !== "FeatureCollection") return;
    latestTransportInfrastructure = decoratedPicture(infrastructure);
    const source = map.getSource("transport-infrastructure");
    if (!source) return;
    source.setData(latestTransportInfrastructure);
    updateCounts();
  }

  function transportInfrastructureUrl() {
    const bounds = map.getBounds();
    const zoom = map.getZoom();
    const minimumTier = zoom < 7 ? "critical" : zoom < 9 ? "high" : zoom < 11 ? "medium" : "low";
    const parameters = new URLSearchParams({
      west: String(bounds.getWest()),
      south: String(bounds.getSouth()),
      east: String(bounds.getEast()),
      north: String(bounds.getNorth()),
      minimum_tier: minimumTier,
    });
    return `/api/transport-infrastructure/global.geojson?${parameters}`;
  }

  async function refreshTransportInfrastructure() {
    const requestSequence = ++transportRequestSequence;
    try {
      const response = await fetch(transportInfrastructureUrl());
      if (!response.ok || requestSequence !== transportRequestSequence) return;
      const payload = await response.json();
      if (requestSequence === transportRequestSequence) setTransportInfrastructure(payload);
    } catch (_) {
      // A later move or reconnect will retry the static viewport request.
    }
  }

  function scheduleTransportInfrastructureRefresh() {
    clearTimeout(transportRefreshTimer);
    transportRefreshTimer = setTimeout(refreshTransportInfrastructure, 150);
  }

  function setRailwayInfrastructure(infrastructure) {
    if (!infrastructure || infrastructure.type !== "FeatureCollection") return;
    latestRailwayInfrastructure = decoratedPicture(infrastructure);
    const source = map.getSource("railway-infrastructure");
    if (!source) return;
    source.setData(latestRailwayInfrastructure);
    updateCounts();
  }

  function setInfrastructureSites(infrastructure) {
    if (!infrastructure || infrastructure.type !== "FeatureCollection") return;
    latestInfrastructureSites = decoratedPicture(infrastructure);
    const displayFeatures = [];
    for (const feature of latestInfrastructureSites.features) {
      const longitude = Number(feature.properties?.longitude);
      const latitude = Number(feature.properties?.latitude);
      const isDetailedArea = ["energy_sites", "military_sites", "industrial_sites", "maritime_sites"].includes(feature.properties?.layer)
        && ["Polygon", "MultiPolygon"].includes(feature.geometry?.type);
      if (isDetailedArea) {
        displayFeatures.push({
          ...feature,
          properties: {
            ...feature.properties,
            site_geometry: "area",
            map_feature_id: `${feature.properties.object_id}:area`,
          },
        });
      }
      if (!Number.isFinite(longitude) || !Number.isFinite(latitude)) {
        if (!isDetailedArea) displayFeatures.push(feature);
        continue;
      }
      displayFeatures.push({
        ...feature,
        geometry: { type: "Point", coordinates: [longitude, latitude] },
        properties: {
          ...feature.properties,
          site_geometry: "anchor",
          map_feature_id: `${feature.properties.object_id}:anchor`,
        },
      });
    }
    const source = map.getSource("infrastructure-sites");
    if (!source) return;
    source.setData({ ...latestInfrastructureSites, features: displayFeatures });
    updateCounts();
  }

  function setSettlements(settlements) {
    if (!settlements || settlements.type !== "FeatureCollection") return;
    latestSettlements = decoratedPicture(settlements);
    const displayFeatures = [];
    for (const feature of latestSettlements.features) {
      const { urban_geometry: urbanGeometry, ...displayProperties } = feature.properties || {};
      const isAdministrative = feature.properties?.boundary_kind === "administrative";
      displayFeatures.push({
        ...feature,
        properties: {
          ...displayProperties,
          settlement_geometry: isAdministrative ? "administrative" : "urban",
          map_feature_id: `${feature.properties.object_id}:area`,
        },
      });
      if (["Polygon", "MultiPolygon"].includes(urbanGeometry?.type)) {
        displayFeatures.push({
          ...feature,
          geometry: urbanGeometry,
          properties: {
            ...displayProperties,
            settlement_geometry: "urban",
            map_feature_id: `${feature.properties.object_id}:urban`,
          },
        });
      }
      if (!["Polygon", "MultiPolygon"].includes(feature.geometry?.type)) continue;
      const longitude = Number(feature.properties?.longitude);
      const latitude = Number(feature.properties?.latitude);
      if (!Number.isFinite(longitude) || !Number.isFinite(latitude)) continue;
      displayFeatures.push({
        ...feature,
        geometry: { type: "Point", coordinates: [longitude, latitude] },
        properties: { ...displayProperties, settlement_geometry: "anchor", map_feature_id: `${feature.properties.object_id}:anchor` },
      });
    }
    const source = map.getSource("settlements");
    if (!source) return;
    source.setData({ ...latestSettlements, features: displayFeatures });
    updateCounts();
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

  function displayState(value) {
    return String(value || "peace")
      .split("_")
      .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
      .join(" ");
  }

  function updateDiplomacy(diplomacy) {
    if (!diplomacy) return;
    const state = String(diplomacy.relationship || "peace");
    elements.relationshipState.textContent = displayState(state);
    elements.relationshipState.dataset.state = state;
    elements.escalationScore.textContent = `Escalation ${Number(diplomacy.escalation_score || 0).toFixed(0)}`;
    const pending = diplomacy.pending_transition;
    elements.pendingTransition.hidden = !pending;
    elements.pendingTransition.textContent = pending
      ? `Pending ${displayState(pending.from_state)} to ${displayState(pending.to_state)}`
      : "";
    const doctrines = diplomacy.doctrines || {};
    elements.blueDoctrine.textContent = `Blue ${displayState(doctrines.blue || "balanced")}`;
    elements.redDoctrine.textContent = `Red ${displayState(doctrines.red || "balanced")}`;
  }

  function updateStatus(status) {
    const connected = Boolean(status?.connected);
    elements.connectionDot.classList.toggle("is-offline", !connected);
    elements.connectionText.textContent = connected ? "DCS connected" : "DCS disconnected";
    elements.errorBanner.hidden = !status?.error;
    elements.errorBanner.textContent = status?.error ? "DCS bridge unavailable. Waiting for reconnection." : "";
    const viewportAvailable = Boolean(status?.topography_viewport_available);
    topographyViewportAvailable = viewportAvailable;
    updateDiplomacy(status?.diplomacy);
  }

  function updateCounts() {
    const counts = new Map();
    allFeatures().forEach((feature) => {
      const key = feature.properties?.layer;
      counts.set(key, (counts.get(key) || 0) + 1);
      if (feature.properties?.map_category) {
        const categoryKey = `${key}:${feature.properties.map_category}`;
        counts.set(categoryKey, (counts.get(categoryKey) || 0) + 1);
      }
      counts.set(`coalition:${feature.properties?.map_coalition}`, (counts.get(`coalition:${feature.properties?.map_coalition}`) || 0) + 1);
      counts.set(`status:${feature.properties?.map_status}`, (counts.get(`status:${feature.properties?.map_status}`) || 0) + 1);
      for (const spec of filterSpecs.filter((item) => item.layer === key)) {
        const value = feature.properties?.[spec.property];
        counts.set(`${spec.key}:${value}`, (counts.get(`${spec.key}:${value}`) || 0) + 1);
      }
    });
    const trajectoryCount = counts.get("trajectories") || 0;
    elements.featureCount.textContent = trajectoryCount
      ? `${latestPicture.features.length - trajectoryCount} objects · ${trajectoryCount} tracks`
      : `${latestPicture.features.length} objects`;
    document.querySelectorAll("[data-layer-count]").forEach((node) => {
      const layer = node.dataset.layerCount;
      if (topographyViewportAvailable && isTopographyLayer(layer)) {
        const control = document.querySelector(`input[data-layer="${layer}"]`);
        const source = map.getSource(`topography-${layer}`);
        if (!control?.checked || map.getZoom() < 8) {
          node.textContent = "–";
          node.title = map.getZoom() < 8 ? "Available from zoom level 8" : "Layer disabled";
          return;
        }
        if (source && !map.isSourceLoaded(`topography-${layer}`)) {
          node.textContent = "…";
          node.title = "Loading visible map tiles";
          return;
        }
      }
      node.textContent = String(counts.get(layer) || 0);
      node.title = "Visible features";
    });
    document.querySelectorAll("[data-layer-category-count]").forEach((node) => {
      node.textContent = String(counts.get(`${node.dataset.layerCategoryCount}:${node.dataset.category}`) || 0);
    });
    document.querySelectorAll("[data-filter-count]").forEach((node) => {
      node.textContent = String(counts.get(`${node.dataset.filterCount}:${node.dataset.filterValue}`) || 0);
    });
    document.querySelectorAll("[data-layer-section-count]").forEach((node) => {
      const section = layerSections.find((candidate) => candidate.key === node.dataset.layerSectionCount);
      node.textContent = String(section?.layers.reduce((total, layer) => total + (counts.get(layer) || 0), 0) || 0);
    });
  }

  function layerControlMarkup(spec, attributes = "") {
    return `
      <input type="checkbox" ${attributes} ${spec.default ? "checked" : ""}>
      <i data-lucide="${spec.icon}" class="layer-symbol" style="--swatch:${spec.color || "#65716b"}"></i>
      <span class="layer-name">${spec.label}</span>`;
  }

  function expandButton(label, expanded = true) {
    const button = document.createElement("button");
    button.className = "layer-expand icon-button";
    button.type = "button";
    button.dataset.expandLabel = label;
    button.title = `${expanded ? "Collapse" : "Expand"} ${label}`;
    button.setAttribute("aria-label", button.title);
    button.setAttribute("aria-expanded", String(expanded));
    button.innerHTML = '<i data-lucide="chevron-down"></i>';
    return button;
  }

  function appendLayerControl(spec, container) {
    if (spec.children) {
      const group = document.createElement("div");
      group.className = "layer-group layer-subgroup";
      const header = document.createElement("div");
      header.className = "layer-group-header";
      const parent = document.createElement("label");
      parent.className = "layer-control layer-control-parent";
      parent.innerHTML = `${layerControlMarkup(spec, `data-layer="${spec.key}"`)}<span class="layer-count" data-layer-count="${spec.key}">0</span>`;
      header.append(expandButton(spec.label), parent);

      const children = document.createElement("div");
      children.className = "layer-children";
      for (const child of spec.children) {
        const label = document.createElement("label");
        label.className = "layer-control layer-control-child";
        label.innerHTML = `${layerControlMarkup(child, `data-parent-layer="${spec.key}" data-category="${child.key}"`)}<span class="layer-count" data-layer-category-count="${spec.key}" data-category="${child.key}">0</span>`;
        children.appendChild(label);
      }
      group.append(header, children);
      container.appendChild(group);
      return;
    }
    const label = document.createElement("label");
    label.className = "layer-control";
    label.innerHTML = `${layerControlMarkup(spec, `data-layer="${spec.key}"`)}<span class="layer-count" data-layer-count="${spec.key}">0</span>`;
    container.appendChild(label);
  }

  function buildLayerControls() {
    for (const section of layerSections) {
      const group = document.createElement("section");
      group.className = "layer-group layer-section";
      const header = document.createElement("div");
      header.className = "layer-group-header";
      const parent = document.createElement("label");
      parent.className = "layer-control layer-control-parent layer-section-control";
      parent.innerHTML = `${layerControlMarkup(
        { ...section, default: true },
        `data-layer-section="${section.key}"`,
      )}<span class="layer-count" data-layer-section-count="${section.key}">0</span>`;
      header.append(expandButton(section.label, false), parent);

      const children = document.createElement("div");
      children.className = "layer-children layer-section-children";
      children.hidden = true;
      for (const layerKey of section.layers) appendLayerControl(layerSpecByKey.get(layerKey), children);
      group.append(header, children);
      elements.layerControls.appendChild(group);
    }
    for (const spec of layerSpecs) updateParentLayerControl(spec.key);
    for (const section of layerSections) updateLayerSectionControl(section.key);
    elements.layerControls.addEventListener("change", (event) => {
      const target = event.target;
      if (target.matches("[data-layer-section]")) {
        const section = layerSections.find((candidate) => candidate.key === target.dataset.layerSection);
        for (const layerKey of section.layers) {
          const layer = document.querySelector(`[data-layer="${layerKey}"]`);
          layer.checked = target.checked;
          layer.indeterminate = false;
          document.querySelectorAll(`[data-parent-layer="${layerKey}"]`).forEach((child) => { child.checked = target.checked; });
        }
      } else if (target.matches("[data-layer]")) {
        const spec = layerSpecByKey.get(target.dataset.layer);
        if (spec?.children) {
          document.querySelectorAll(`[data-parent-layer="${spec.key}"]`).forEach((child) => { child.checked = target.checked; });
        }
        updateLayerSectionControl(layerSectionByLayer.get(target.dataset.layer));
      } else if (target.matches("[data-parent-layer]")) {
        updateParentLayerControl(target.dataset.parentLayer);
        updateLayerSectionControl(layerSectionByLayer.get(target.dataset.parentLayer));
      }
      applyLayerVisibility();
    });
    elements.layerControls.addEventListener("click", (event) => {
      const button = event.target.closest(".layer-expand");
      if (!button) return;
      const children = button.closest(".layer-group").querySelector(":scope > .layer-children");
      children.hidden = !children.hidden;
      button.setAttribute("aria-expanded", String(!children.hidden));
      button.title = `${children.hidden ? "Expand" : "Collapse"} ${button.dataset.expandLabel}`;
      button.setAttribute("aria-label", button.title);
    });
  }

  function normalizedOpacity(value) {
    return Math.max(0, Math.min(1, Number(value)));
  }

  function opacityExpression(base, factor) {
    if (factor === 1) return base;
    return typeof base === "number" ? base * factor : ["*", base, factor];
  }

  function applyLayerOpacity(layerKeys, factor) {
    for (const layerKey of layerKeys) {
      for (const id of mapLayerIds.get(layerKey) || []) {
        if (!map.getLayer(id)) continue;
        for (const [property, base] of Object.entries(mapLayerBaseOpacities.get(id) || {})) {
          map.setPaintProperty(id, property, opacityExpression(base, factor));
        }
      }
    }
  }

  function setBasemapStyle(value) {
    selectedBasemap = Object.hasOwn(basemaps, value) ? value : "osm";
    elements.basemapStyle.value = selectedBasemap;
    window.localStorage.setItem(mapAppearanceStorageKeys.basemap, selectedBasemap);
    for (const [key, id] of Object.entries(basemaps)) {
      if (map.getLayer(id)) map.setLayoutProperty(id, "visibility", key === selectedBasemap ? "visible" : "none");
    }
  }

  function setOpacityControl(kind, value) {
    const opacity = normalizedOpacity(value);
    const input = elements[`${kind}Opacity`];
    const output = elements[`${kind}OpacityValue`];
    input.value = String(Math.round(opacity * 100));
    output.value = `${Math.round(opacity * 100)}%`;
    window.localStorage.setItem(mapAppearanceStorageKeys[`${kind}Opacity`], String(opacity));
    if (kind === "basemap") {
      basemapOpacity = opacity;
      for (const id of Object.values(basemaps)) {
        if (map.getLayer(id)) map.setPaintProperty(id, "raster-opacity", opacity);
      }
    } else if (kind === "territory") {
      territoryOpacity = opacity;
      applyLayerOpacity(["territories"], opacity);
    } else if (kind === "topography") {
      topographyOpacity = opacity;
      applyLayerOpacity(layerSections.find((section) => section.key === "topography").layers, opacity);
    }
  }

  function updateParentLayerControl(layerKey) {
    const parent = document.querySelector(`[data-layer="${layerKey}"]`);
    const children = [...document.querySelectorAll(`[data-parent-layer="${layerKey}"]`)];
    if (!parent || !children.length) return;
    const selected = children.filter((child) => child.checked).length;
    parent.checked = selected > 0;
    parent.indeterminate = selected > 0 && selected < children.length;
  }

  function updateLayerSectionControl(sectionKey) {
    if (!sectionKey) return;
    const section = layerSections.find((candidate) => candidate.key === sectionKey);
    const parent = document.querySelector(`[data-layer-section="${sectionKey}"]`);
    if (!section || !parent) return;
    const children = section.layers.map((layer) => document.querySelector(`[data-layer="${layer}"]`));
    const selected = children.filter((child) => child.checked).length;
    parent.checked = selected > 0;
    parent.indeterminate = children.some((child) => child.indeterminate) || (selected > 0 && selected < children.length);
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
    document.querySelectorAll("[data-layer]").forEach((checkbox) => {
      const visibility = checkbox.checked ? "visible" : "none";
      const layer = checkbox.dataset.layer;
      const tacticalFilters = isTopographyLayer(checkbox.dataset.layer)
        ? []
        : filterSpecs
          .filter((spec) => !spec.layer || spec.layer === layer)
          .map((spec) => ["in", ["get", spec.property], ["literal", selectedFilterValues(spec.key)]]);
      for (const id of mapLayerIds.get(layer) || []) {
        if (!map.getLayer(id)) continue;
        map.setLayoutProperty(id, "visibility", visibility);
        const filters = [mapLayerBaseFilters.get(id), ...tacticalFilters].filter(Boolean);
        const children = [...document.querySelectorAll(`[data-parent-layer="${layer}"]:checked`)];
        if (children.length || document.querySelector(`[data-parent-layer="${layer}"]`)) {
          const categories = children.map((child) => child.dataset.category);
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
    if (typeof value === "string" && value.startsWith("[") && value.endsWith("]")) {
      try {
        const parsed = JSON.parse(value);
        if (Array.isArray(parsed)) return parsed.length ? parsed.join(", ") : "-";
      } catch (_error) {
        // Keep malformed or ordinary bracketed text unchanged.
      }
    }
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
    last_update_mission_time: "Last DCS update", footprint_area_m2: "Footprint area",
    importance_score: "Importance score", importance_tier: "Importance tier",
    strategic_value: "Strategic value", priority: "Priority", selection_rank: "Selection rank",
    selection_category: "Selection category", selection_limit: "Selection limit", component_count: "Components",
    control_object_id: "Control object", ownership_policy: "Ownership policy", scope_state: "Strategic scope",
    goal_count: "Goals", blue_goal_id: "Blue goal", blue_goal_action: "Blue action", blue_goal_status: "Blue goal status",
    red_goal_id: "Red goal", red_goal_action: "Red action", red_goal_status: "Red goal status",
    energy_roles: "Energy roles", energy_sources: "Energy sources", output_mw: "Electrical output",
    voltage_kv: "Grid voltage",
    maritime_roles: "Maritime roles", cargo_types: "Cargo types", quay_length_m: "Quay length",
    berth_count: "Berths",
    network_analysis_complete: "Analysis", network_disconnected_if_lost: "Loss effect",
    network_alternative_route_found: "Alternative route", network_criticality_score: "Network criticality",
    network_detour_added_m: "Additional distance", network_detour_distance_m: "Detour distance",
    network_detour_ratio: "Detour ratio", network_portal_pair_count: "Tested route pairs",
    network_analysis_radius_m: "Analysis radius", network_analysis_limit_m: "Route limit",
    verification_state: "Verification status",
    observed_object_count: "Observed DCS objects", observation_complete: "Observation complete",
    target_component_count: "Target components",
  };

  function humanizeKey(key) {
    return fieldLabels[key] || key.replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
  }

  function formattedField(key, value) {
    if (key === "verification_state") {
      const labels = {
        unverified: "Unverified",
        represented: "Represented",
        not_represented: "Not represented",
        not_represented_in_dcs: "Not represented",
      };
      return labels[String(value)] || readableValue(value);
    }
    if (key === "radius_m") return `${Number(value).toLocaleString("en-US", { maximumFractionDigits: 0 })} m`;
    if (key === "capacity_m3") return `${Number(value).toLocaleString("en-US", { maximumFractionDigits: 0 })} m³`;
    if (key === "output_mw") return `${Number(value).toLocaleString("en-US", { maximumFractionDigits: 1 })} MW`;
    if (key === "voltage_kv") return `${Number(value).toLocaleString("en-US", { maximumFractionDigits: 1 })} kV`;
    if (key === "quay_length_m") {
      const distance = Number(value);
      return distance >= 1000 ? `${(distance / 1000).toFixed(1)} km` : `${distance.toFixed(0)} m`;
    }
    if (key === "footprint_area_m2") {
      const area = Number(value);
      return area >= 1_000_000
        ? `${(area / 1_000_000).toLocaleString("en-US", { maximumFractionDigits: 2 })} km²`
        : `${area.toLocaleString("en-US", { maximumFractionDigits: 0 })} m²`;
    }
    if (key === "importance_score") return Number(value).toFixed(1);
    if (key === "strategic_value" || key === "priority") return `${Number(value).toFixed(1)} / 100`;
    if (key === "health") return `${(Number(value) * 100).toFixed(1)}%`;
    if (key === "network_criticality_score") return `${Number(value).toFixed(1)} / 100`;
    if (key === "network_detour_ratio") return `${Number(value).toFixed(2)}x`;
    if (["network_detour_added_m", "network_detour_distance_m", "network_analysis_radius_m", "network_analysis_limit_m"].includes(key)) {
      const distance = Number(value);
      return distance >= 1000 ? `${(distance / 1000).toFixed(1)} km` : `${distance.toFixed(0)} m`;
    }
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

  function addStrategicGoalControls(properties) {
    const section = document.createElement("section");
    section.className = "detail-section strategic-goal-controls";
    const heading = document.createElement("h3");
    heading.className = "detail-section-title";
    heading.innerHTML = '<i data-lucide="list-plus"></i><span>Goal selection</span>';
    const controls = document.createElement("div");
    controls.className = "goal-control-row";
    const coalitionControl = document.createElement("div");
    coalitionControl.className = "segmented-control";
    coalitionControl.setAttribute("aria-label", "Goal coalition");
    let selectedCoalition = "blue";
    const status = document.createElement("div");
    status.className = "goal-control-status";
    const createButton = document.createElement("button");
    createButton.className = "command-button";
    createButton.type = "button";
    createButton.innerHTML = '<i data-lucide="plus"></i><span>Create goal</span>';

    function refreshControl() {
      status.classList.remove("is-error");
      coalitionControl.querySelectorAll("button").forEach((button) => {
        const selected = button.dataset.coalition === selectedCoalition;
        button.classList.toggle("is-selected", selected);
        button.setAttribute("aria-pressed", String(selected));
      });
      const goalId = properties[`${selectedCoalition}_goal_id`];
      createButton.disabled = Boolean(goalId);
      status.textContent = goalId
        ? `${properties[`${selectedCoalition}_goal_action`]} goal · ${properties[`${selectedCoalition}_goal_status`]}`
        : "No goal selected";
    }

    for (const coalition of ["blue", "red"]) {
      const button = document.createElement("button");
      button.type = "button";
      button.dataset.coalition = coalition;
      button.textContent = coalition.charAt(0).toUpperCase() + coalition.slice(1);
      button.addEventListener("click", () => {
        selectedCoalition = coalition;
        refreshControl();
      });
      coalitionControl.appendChild(button);
    }
    createButton.addEventListener("click", async () => {
      createButton.disabled = true;
      status.textContent = "Creating goal...";
      try {
        const response = await fetch("/api/strategic-goals", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ objective_id: properties.object_id, coalition: selectedCoalition }),
        });
        const result = await response.json();
        if (!response.ok) throw new Error(result.detail || "Goal creation failed");
        const goal = result.goal;
        properties[`${selectedCoalition}_goal_id`] = goal.goal_id;
        properties[`${selectedCoalition}_goal_action`] = goal.action;
        properties[`${selectedCoalition}_goal_status`] = goal.status;
        status.textContent = `${goal.action} goal · ${goal.status}`;
      } catch (error) {
        createButton.disabled = false;
        status.textContent = String(error.message || error);
        status.classList.add("is-error");
      }
    });
    controls.append(coalitionControl, createButton);
    section.append(heading, controls, status);
    elements.detailSections.appendChild(section);
    refreshControl();
  }

  function addStrategicVerificationControls(properties) {
    const sourceId = String(properties.object_id || "");
    const eligibleLayers = new Set([
      "settlements", "transport_bridges", "transport_junctions", "railway_infrastructure",
      "energy_sites", "fuel_storage_sites", "military_sites", "industrial_sites", "maritime_sites",
    ]);
    if (!sourceId || !eligibleLayers.has(properties.layer)) return;

    const current = strategicVerifications.get(sourceId) || {
      source_id: sourceId, state: "unverified",
      observed_objects: [], observation_complete: false, target_components: [], notes: "",
    };
    const isAdmitted = (verification) => {
      return verification.state === "represented" && Boolean(verification.target_components?.length);
    };
    const section = document.createElement("section");
    section.className = "detail-section verification-controls";
    const heading = document.createElement("h3");
    heading.className = "detail-section-title";
    heading.innerHTML = '<i data-lucide="badge-check"></i><span>DCS verification</span>';

    const stateLabel = document.createElement("label");
    stateLabel.textContent = "Status";
    const stateSelect = document.createElement("select");
    for (const [value, label] of [
      ["unverified", "Unverified"], ["represented", "Represented"],
      ["not_represented", "Not represented"],
    ]) {
      const option = document.createElement("option");
      option.value = value;
      option.textContent = label;
      option.selected = current.state === value;
      stateSelect.appendChild(option);
    }

    const observedLabel = document.createElement("label");
    observedLabel.textContent = "Observed DCS objects";
    const observedInput = document.createElement("textarea");
    observedInput.rows = 5;
    observedInput.readOnly = true;
    observedInput.placeholder = "Run the infrastructure verification script to capture the baseline.";
    observedInput.value = (current.observed_objects || []).map((item) => {
      const typeName = item.type_name || "unknown type";
      const displayName = item.display_name ? ` | ${item.display_name}` : "";
      return `${item.object_id} | ${typeName}${displayName}`;
    }).join("\n");

    const componentLabel = document.createElement("label");
    componentLabel.textContent = "Target components";
    const componentInput = document.createElement("textarea");
    componentInput.rows = 3;
    componentInput.value = (current.target_components || []).map((item) => {
      const role = item.role || "infrastructure component";
      const weight = Number(item.weight || 1);
      return `${item.object_id} | ${role} | ${weight}`;
    }).join("\n");

    const notesLabel = document.createElement("label");
    notesLabel.textContent = "Notes";
    const notesInput = document.createElement("input");
    notesInput.type = "text";
    notesInput.value = current.notes || "";

    const status = document.createElement("div");
    status.className = "goal-control-status";
    const observationStatus = current.observation_complete ? "complete baseline" : "partial baseline";
    status.textContent = `${current.observed_objects?.length || 0} observed (${observationStatus}) · `
      + `${current.target_components?.length || 0} target(s) · ${isAdmitted(current) ? "admitted" : "not admitted"}`;
    const saveButton = document.createElement("button");
    saveButton.className = "command-button";
    saveButton.type = "button";
    saveButton.innerHTML = '<i data-lucide="save"></i><span>Save verification</span>';
    saveButton.addEventListener("click", async () => {
      saveButton.disabled = true;
      status.classList.remove("is-error");
      status.textContent = "Saving...";
      try {
        const targetComponents = componentInput.value.split(/\r?\n/).map((line) => line.trim()).filter(Boolean).map((line) => {
          const [objectId, role, weight] = line.split("|").map((part) => part.trim());
          return { object_id: objectId, role: role || "infrastructure component", weight: weight ? Number(weight) : 1 };
        });
        const response = await fetch(`/api/strategic-verifications/${encodeURIComponent(sourceId)}`, {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            state: stateSelect.value,
            observed_objects: current.observed_objects || [],
            observation_complete: current.observation_complete === true,
            target_components: targetComponents,
            notes: notesInput.value,
          }),
        });
        const result = await response.json();
        if (!response.ok) throw new Error(result.detail || "Verification could not be saved");
        strategicVerifications.set(sourceId, result.verification);
        const saved = result.verification;
        status.textContent = `${saved.observed_objects.length} observed (${saved.observation_complete ? "complete baseline" : "partial baseline"}) · `
          + `${saved.target_components.length} target(s) · ${result.admitted ? "admitted" : "not admitted"}`;
        if (selectedFeature?.properties?.object_id === sourceId) {
          Object.assign(selectedFeature.properties, strategicVerificationDetailProperties(saved));
          showDetails(selectedFeature);
        }
      } catch (error) {
        status.textContent = String(error.message || error);
        status.classList.add("is-error");
      } finally {
        saveButton.disabled = false;
      }
    });

    const assessmentStatus = document.createElement("div");
    assessmentStatus.className = "goal-control-status";
    assessmentStatus.textContent = "Current state not assessed";
    const assessButton = document.createElement("button");
    assessButton.className = "command-button";
    assessButton.type = "button";
    assessButton.disabled = !(current.observed_objects || []).length;
    assessButton.innerHTML = '<i data-lucide="activity"></i><span>Assess current state</span>';
    assessButton.addEventListener("click", async () => {
      assessButton.disabled = true;
      assessmentStatus.classList.remove("is-error");
      assessmentStatus.textContent = "Surveying DCS scenery...";
      try {
        const response = await fetch(`/api/strategic-verifications/${encodeURIComponent(sourceId)}/assess`, {
          method: "POST",
        });
        const result = await response.json();
        if (!response.ok) throw new Error(result.detail || "Current state could not be assessed");
        const assessment = result.assessment;
        const minDamage = assessment.damage_min == null ? "?" : `${Math.round(assessment.damage_min * 100)}%`;
        const maxDamage = assessment.damage_max == null ? "?" : `${Math.round(assessment.damage_max * 100)}%`;
        const damage = minDamage === maxDamage ? minDamage : `${minDamage}-${maxDamage}`;
        assessmentStatus.textContent = `${assessment.state} · damage ${damage} · `
          + `${assessment.destroyed_count} destroyed, ${assessment.damaged_count} damaged, `
          + `${assessment.unknown_count} unknown · ${assessment.complete ? "complete" : "bounded estimate"}`;
      } catch (error) {
        assessmentStatus.textContent = String(error.message || error);
        assessmentStatus.classList.add("is-error");
      } finally {
        assessButton.disabled = !(current.observed_objects || []).length;
      }
    });

    const grid = document.createElement("div");
    grid.className = "verification-grid";
    stateLabel.appendChild(stateSelect);
    componentLabel.appendChild(componentInput);
    notesLabel.appendChild(notesInput);
    observedLabel.appendChild(observedInput);
    grid.append(
      stateLabel, observedLabel, componentLabel, notesLabel,
      saveButton, status, assessButton, assessmentStatus,
    );
    section.append(heading, grid);
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

  function strategicVerificationDetailProperties(verification) {
    return {
      verification_state: verification.state,
      observed_object_count: verification.observed_objects?.length || 0,
      observation_complete: verification.observation_complete === true,
      target_component_count: verification.target_components?.length || 0,
    };
  }

  function withCurrentStrategicVerification(properties) {
    const verification = strategicVerifications.get(String(properties.object_id || ""));
    return verification
      ? { ...properties, ...strategicVerificationDetailProperties(verification) }
      : properties;
  }

  function railNetworkImpactRows(properties, consumed) {
    if (properties.network_analysis_complete === undefined) return [];
    const keys = [
      "network_analysis_complete", "network_disconnected_if_lost", "network_alternative_route_found",
      "network_criticality_score", "network_detour_added_m", "network_detour_distance_m",
      "network_detour_ratio", "network_portal_pair_count", "network_analysis_radius_m",
      "network_analysis_limit_m",
    ];
    keys.forEach((key) => consumed.add(key));
    if (!properties.network_analysis_complete) return [["Analysis", "Not completed"]];

    const lossEffect = properties.network_disconnected_if_lost
      ? "Network disconnected"
      : properties.network_alternative_route_found
        ? "Detour required"
        : "No material route impact";
    const rows = [
      ["Analysis", "Complete"],
      ["Loss effect", lossEffect],
      ["Network criticality", formattedField("network_criticality_score", properties.network_criticality_score)],
      ["Tested route pairs", readableValue(properties.network_portal_pair_count)],
      ["Alternative route", properties.network_alternative_route_found ? "Available" : "None"],
    ];
    if (properties.network_alternative_route_found) {
      rows.push(
        ["Additional distance", formattedField("network_detour_added_m", properties.network_detour_added_m)],
        ["Detour distance", formattedField("network_detour_distance_m", properties.network_detour_distance_m)],
        ["Detour ratio", formattedField("network_detour_ratio", properties.network_detour_ratio)],
      );
    }
    rows.push(
      ["Analysis radius", formattedField("network_analysis_radius_m", properties.network_analysis_radius_m)],
      ["Route limit", formattedField("network_analysis_limit_m", properties.network_analysis_limit_m)],
    );
    return rows.filter(([, value]) => value !== undefined && value !== null && !String(value).includes("NaN"));
  }

  function showDetails(feature) {
    selectedFeature = feature;
    const properties = withCurrentStrategicVerification(feature.properties || {});
    selectedObjectId = properties.object_id || null;
    const layerLabel = layerSpecs.find((spec) => spec.key === properties.layer)?.label || properties.object_type || "Object";
    elements.detailType.textContent = [layerLabel, properties.category].filter(Boolean).join(" · ");
    const unnamedTitle = properties.layer === "fuel_storage_sites"
      ? "Unnamed fuel storage site"
      : properties.layer === "energy_sites"
        ? "Unnamed energy site"
        : properties.layer === "military_sites"
          ? "Unnamed military site"
          : properties.layer === "industrial_sites"
            ? "Unnamed industrial site"
          : properties.layer === "maritime_sites"
            ? "Unnamed maritime site"
          : "Unnamed object";
    const displayName = properties.name && properties.name !== properties.object_id
      ? properties.name
      : properties.display_name && properties.display_name !== properties.object_id
        ? properties.display_name
        : unnamedTitle;
    elements.detailTitle.textContent = displayName;
    elements.detailSubtitle.textContent = properties.object_id || "";
    elements.detailCopy.hidden = !properties.object_id;
    elements.detailF10Marker.hidden = !markerPointForFeature(feature);
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

    const consumed = new Set(["name", "layer", "map_symbol", "map_coalition", "map_status", "map_category", "objective_owner", "objective_category", "objective_rank", "coordinate_system", "dcs_name", "latitude", "longitude", "x", "y", "z", "category", "coalition", "owner", "state", "alive", "active", "object_type", "dcs_category"]);
    if (properties.layer === "strategic_objectives") addStrategicGoalControls(properties);
    addStrategicVerificationControls(properties);
    const operational = detailRows(properties, ["mission_type", "status", "target", "target_id", "threat_level", "threat_level_max", "threat_level_sum", "threat_level_avg", "unit_count", "alive_unit_count", "size", "speed", "radius_m", "derived_speed_kts", "derived_heading_deg", "track_distance_m", "track_duration_s", "last_update_mission_time", "sample_count", "distance_m", "duration_s", "average_speed_mps"], consumed);
    if (properties.unit_count !== undefined && properties.alive_unit_count !== undefined) {
      const start = operational.findIndex(([label]) => label === fieldLabels.unit_count);
      operational.splice(Math.max(0, start), 2, ["Strength", `${properties.alive_unit_count} / ${properties.unit_count} alive`]);
    }
    addDetailSection("Operational", "activity", operational);

    if (properties.layer === "strategic_objectives") {
      addDetailSection("Strategic assessment", "flag-triangle-right", detailRows(properties, [
        "strategic_value", "priority", "scope_state", "selection_category", "selection_rank",
        "selection_limit", "health", "contested", "control_object_id",
        "ownership_policy", "component_count", "component_ids", "goal_count",
        "blue_goal_id", "blue_goal_action", "blue_goal_status",
        "red_goal_id", "red_goal_action", "red_goal_status", "source_kind", "source_object_id",
      ], consumed));
    }

    if (properties.layer === "railway_infrastructure") {
      addDetailSection("Rail network impact", "network", railNetworkImpactRows(properties, consumed));
    }

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

  function markerPointForFeature(feature) {
    const properties = feature?.properties || {};
    const x = Number(properties.x); const z = Number(properties.z);
    if (Number.isFinite(x) && Number.isFinite(z)) {
      const y = Number(properties.y);
      return { x, y: Number.isFinite(y) ? y : 0, z };
    }
    const latitude = Number(properties.latitude); const longitude = Number(properties.longitude);
    if (Number.isFinite(latitude) && Number.isFinite(longitude)) {
      return { latitude, longitude, altitude: 0 };
    }
    const geometry = feature?.geometry;
    if (geometry?.type === "Point" && geometry.coordinates?.length >= 2) {
      return { longitude: Number(geometry.coordinates[0]), latitude: Number(geometry.coordinates[1]), altitude: 0 };
    }
    const coordinates = [];
    function collect(value) {
      if (!Array.isArray(value)) return;
      if (value.length >= 2 && Number.isFinite(Number(value[0])) && Number.isFinite(Number(value[1]))) {
        coordinates.push([Number(value[0]), Number(value[1])]);
        return;
      }
      value.forEach(collect);
    }
    collect(geometry?.coordinates);
    if (!coordinates.length) return null;
    const longitudes = coordinates.map(([lon]) => lon);
    const latitudes = coordinates.map(([, lat]) => lat);
    return {
      longitude: (Math.min(...longitudes) + Math.max(...longitudes)) / 2,
      latitude: (Math.min(...latitudes) + Math.max(...latitudes)) / 2,
      altitude: 0,
    };
  }

  async function createF10Marker() {
    const point = markerPointForFeature(selectedFeature);
    if (!selectedFeature || !point) return;
    const properties = selectedFeature.properties || {};
    elements.detailF10Marker.disabled = true;
    elements.detailF10Marker.title = "Creating DCS F10 marker...";
    try {
      const response = await fetch("/api/dcs-markers", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          point,
          properties: {
            object_id: properties.object_id,
            name: properties.name,
            display_name: properties.display_name,
            layer: properties.layer,
            object_type: properties.object_type,
            category: properties.category,
            selection_category: properties.selection_category,
            dcs_type: properties.dcs_type,
            coalition: properties.coalition,
            owner: properties.owner,
            status: properties.status,
            state: properties.state,
            alive: properties.alive,
          },
        }),
      });
      const result = await response.json();
      if (!response.ok) throw new Error(result.detail || "DCS F10 marker creation failed");
      const suffix = result.marker?.mark_id === undefined ? "" : ` (#${result.marker.mark_id})`;
      elements.detailF10Marker.title = `DCS F10 marker created${suffix}`;
      setTimeout(() => { elements.detailF10Marker.title = "Create DCS F10 marker"; }, 1800);
    } catch (error) {
      elements.detailF10Marker.title = "Create DCS F10 marker";
      elements.errorBanner.hidden = false;
      elements.errorBanner.textContent = String(error.message || error);
    } finally {
      elements.detailF10Marker.disabled = false;
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
      const [pictureResponse, surfaceRegionsResponse, railwayResponse, infrastructureResponse, settlementsResponse, verificationsResponse, healthResponse] = await Promise.all([
        fetch("/api/picture/global.geojson"),
        fetch("/api/surface-regions/global.geojson"),
        fetch("/api/railway-infrastructure/global.geojson"),
        fetch("/api/infrastructure-sites/global.geojson"),
        fetch("/api/settlements/global.geojson"),
        fetch("/api/strategic-verifications"),
        fetch("/api/health"),
      ]);
      if (pictureResponse.ok) setPicture(await pictureResponse.json());
      if (surfaceRegionsResponse.ok) setSurfaceRegions(await surfaceRegionsResponse.json());
      if (railwayResponse.ok) setRailwayInfrastructure(await railwayResponse.json());
      if (infrastructureResponse.ok) setInfrastructureSites(await infrastructureResponse.json());
      if (settlementsResponse.ok) setSettlements(await settlementsResponse.json());
      if (verificationsResponse.ok) {
        const payload = await verificationsResponse.json();
        strategicVerifications.clear();
        for (const item of payload.verifications || []) strategicVerifications.set(item.source_id, item);
      }
      if (healthResponse.ok) {
        const status = await healthResponse.json();
        updateStatus(status);
        if (!status.topography_viewport_available) {
          const topographyResponse = await fetch("/api/topography/global.geojson");
          if (topographyResponse.ok) setTopography(await topographyResponse.json());
        }
      }
      await refreshTransportInfrastructure();
    } catch (error) {
      updateStatus({ connected: false, error: String(error) });
    }
  }

  buildLayerControls();
  buildFilterControls();
  setBasemapStyle(selectedBasemap);
  setOpacityControl("basemap", basemapOpacity);
  setOpacityControl("territory", territoryOpacity);
  setOpacityControl("topography", topographyOpacity);
  elements.basemapStyle.addEventListener("change", (event) => setBasemapStyle(event.target.value));
  elements.basemapOpacity.addEventListener("input", (event) => {
    setOpacityControl("basemap", Number(event.target.value) / 100);
  });
  elements.territoryOpacity.addEventListener("input", (event) => {
    setOpacityControl("territory", Number(event.target.value) / 100);
  });
  elements.topographyOpacity.addEventListener("input", (event) => {
    setOpacityControl("topography", Number(event.target.value) / 100);
  });
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
  elements.detailF10Marker.addEventListener("click", createF10Marker);
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
    try {
      const healthResponse = await fetch("/api/health");
      if (healthResponse.ok) updateStatus(await healthResponse.json());
    } catch (_) {
      topographyViewportAvailable = false;
    }
    await initializeSourcesAndLayers();
    setOpacityControl("territory", territoryOpacity);
    setOpacityControl("topography", topographyOpacity);
    loadInitialPicture();
    connect();
  });
  map.on("idle", updateCounts);
  map.on("moveend", scheduleTransportInfrastructureRefresh);
  map.on("sourcedata", (event) => {
    if (!String(event.sourceId || "").startsWith("topography-")) return;
    clearTimeout(countUpdateTimer);
    countUpdateTimer = setTimeout(updateCounts, 120);
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
