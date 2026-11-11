#!/usr/bin/env python3
"""
GIS Tools — RustGIS process plugin.

Commands:
  set-projection  Assign an EPSG CRS to selected layers (no coordinate rewriting).
  merge-layers    Combine all loaded vector layers; add 'source_layer' attribute.
  export-dxf      Export selected (or all) vector layers to a DXF file.
  load-basemap    Add a web tile basemap (Google, Bing, OSM, ESRI) to the map.
  panel-state     Return the panel's initial/refreshed state.
"""
import json
import os
import sys
from datetime import datetime


# ---------------------------------------------------------------------------
# EPSG tree shown in the panel
# ---------------------------------------------------------------------------
def _build_epsg_nodes():
    def leaf(epsg, label):
        return {"id": str(epsg), "label": f"{label} (EPSG:{epsg})"}

    return [
        {
            "id": "_geographic",
            "label": "Geographic",
            "children": [
                leaf(4326, "WGS 84"),
                leaf(4258, "ETRS89"),
                leaf(4283, "GDA94"),
                leaf(7844, "GDA2020"),
                leaf(4269, "NAD83"),
                leaf(4267, "NAD27"),
            ],
        },
        {
            "id": "_web",
            "label": "Web",
            "children": [
                leaf(3857, "WGS 84 / Web Mercator"),
            ],
        },
        {
            "id": "_au_gda94",
            "label": "Australia — GDA94 / MGA",
            "children": [
                leaf(28349, "Zone 49S"),
                leaf(28350, "Zone 50S"),
                leaf(28351, "Zone 51S"),
                leaf(28352, "Zone 52S"),
                leaf(28353, "Zone 53S"),
                leaf(28354, "Zone 54S"),
                leaf(28355, "Zone 55S"),
                leaf(28356, "Zone 56S"),
            ],
        },
        {
            "id": "_au_gda2020",
            "label": "Australia — GDA2020 / MGA",
            "children": [
                leaf(7849, "Zone 49S"),
                leaf(7850, "Zone 50S"),
                leaf(7851, "Zone 51S"),
                leaf(7852, "Zone 52S"),
                leaf(7853, "Zone 53S"),
                leaf(7854, "Zone 54S"),
                leaf(7855, "Zone 55S"),
                leaf(7856, "Zone 56S"),
            ],
        },
        {
            "id": "_utm_n",
            "label": "UTM — WGS84 North",
            "children": [leaf(32600 + z, f"Zone {z}N") for z in range(1, 61)],
        },
        {
            "id": "_utm_s",
            "label": "UTM — WGS84 South",
            "children": [leaf(32700 + z, f"Zone {z}S") for z in range(1, 61)],
        },
        {
            "id": "_europe",
            "label": "Europe",
            "children": [
                leaf(27700, "British National Grid"),
                leaf(2154,  "RGF93 / Lambert-93"),
                leaf(28992, "Dutch RD New"),
                leaf(25832, "ETRS89 / UTM Zone 32N"),
                leaf(25833, "ETRS89 / UTM Zone 33N"),
                leaf(3035,  "ETRS89 / LAEA Europe"),
                leaf(3034,  "ETRS89 / LCC Europe"),
            ],
        },
        {
            "id": "_namerica",
            "label": "North America",
            "children": [
                leaf(4617, "NAD83(CSRS)"),
                leaf(26917, "NAD83 / UTM Zone 17N"),
                leaf(26918, "NAD83 / UTM Zone 18N"),
                leaf(26919, "NAD83 / UTM Zone 19N"),
                leaf(32614, "WGS84 / UTM Zone 14N"),
                leaf(32615, "WGS84 / UTM Zone 15N"),
                leaf(32616, "WGS84 / UTM Zone 16N"),
                leaf(32617, "WGS84 / UTM Zone 17N"),
            ],
        },
    ]


EPSG_NODES = _build_epsg_nodes()

# Persistent state across button clicks (process stays alive)
_last_epsg = ""
_nav_state = {"features": [], "index": -1, "layer_id": None}
_NAV_FILE = os.path.join(os.path.expanduser("~"), ".geocentroid_nav.json")


def _nav_load():
    try:
        with open(_NAV_FILE) as f:
            d = json.load(f)
            return int(d.get("index", -1)), d.get("layer_id")
    except Exception:
        return -1, None


def _nav_save(index, layer_id):
    try:
        with open(_NAV_FILE, "w") as f:
            json.dump({"index": index, "layer_id": layer_id}, f)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Basemap catalogue
# ---------------------------------------------------------------------------
BASEMAPS = {
    "google_satellite_cn": {
        "name": "Google Satellite (CN)",
        "url": "http://www.google.cn/maps/vt?lyrs=s@189&gl=cn&x={x}&y={y}&z={z}",
        "maxZoom": 20,
    },
    "google_satellite": {
        "name": "Google Satellite",
        "url": "https://mt1.google.com/vt/lyrs=s&x={x}&y={y}&z={z}",
        "maxZoom": 20,
    },
    "google_terrain": {
        "name": "Google Terrain",
        "url": "https://mt1.google.com/vt/lyrs=t&x={x}&y={y}&z={z}",
        "maxZoom": 20,
    },
    "google_roads": {
        "name": "Google Roads",
        "url": "https://mt1.google.com/vt/lyrs=m&x={x}&y={y}&z={z}",
        "maxZoom": 20,
    },
    "google_hybrid": {
        "name": "Google Hybrid",
        "url": "https://mt1.google.com/vt/lyrs=y&x={x}&y={y}&z={z}",
        "maxZoom": 20,
    },
    "bing_aerial": {
        "name": "Bing Aerial",
        "url": "http://ecn.t3.tiles.virtualearth.net/tiles/a{q}.jpeg?g=0",
        "maxZoom": 19,
    },
    "bing_maps": {
        "name": "Bing Maps",
        "url": "http://ecn.dynamic.t0.tiles.virtualearth.net/comp/CompositionHandler/{q}?mkt=en-us",
        "maxZoom": 19,
    },
    "osm": {
        "name": "OpenStreetMap",
        "url": "https://tile.openstreetmap.org/{z}/{x}/{y}.png",
        "maxZoom": 19,
        "attribution": "© OpenStreetMap contributors",
    },
    "open_topo": {
        "name": "OpenTopoMap",
        "url": "https://tile.opentopomap.org/{z}/{x}/{y}.png",
        "maxZoom": 17,
        "attribution": "© OpenStreetMap contributors, © OpenTopoMap",
    },
    "esri_world_imagery": {
        "name": "ESRI World Imagery",
        "url": "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
        "maxZoom": 19,
        "attribution": "Tiles © Esri",
    },
}

BASEMAP_NODES = [
    {
        "id": "_bm_google",
        "label": "Google",
        "children": [
            {"id": "google_satellite_cn", "label": "Satellite (CN)"},
            {"id": "google_satellite",    "label": "Satellite"},
            {"id": "google_terrain",      "label": "Terrain"},
            {"id": "google_roads",        "label": "Roads"},
            {"id": "google_hybrid",       "label": "Hybrid"},
        ],
    },
    {
        "id": "_bm_bing",
        "label": "Bing",
        "children": [
            {"id": "bing_aerial", "label": "Aerial"},
            {"id": "bing_maps",   "label": "Maps"},
        ],
    },
    {
        "id": "_bm_osm",
        "label": "OpenStreetMap",
        "children": [
            {"id": "osm",        "label": "Standard"},
            {"id": "open_topo",  "label": "Topo"},
        ],
    },
    {
        "id": "_bm_esri",
        "label": "ESRI",
        "children": [
            {"id": "esri_world_imagery", "label": "World Imagery"},
        ],
    },
]


# ---------------------------------------------------------------------------
# Transport helpers
# ---------------------------------------------------------------------------
def _call(op, params):
    """Send one request to RustGIS, return the ok value or raise."""
    print(json.dumps({"call": {"op": op, "params": params}}), flush=True)
    reply = json.loads(sys.stdin.readline())
    if "error" in reply:
        raise RuntimeError(reply["error"])
    return reply["ok"]


def _notify(text, error=False):
    p = {"text": text}
    if error:
        p["error"] = True
    _call("host.notify", p)


def _log(text):
    print(json.dumps({"log": text}), flush=True)


# ---------------------------------------------------------------------------
# Combobox input dialog
# ---------------------------------------------------------------------------
def _ask_combobox(title, prompt, values, initial=""):
    """Show a modal dialog with a searchable combobox. Returns selected string or None."""
    import tkinter as tk
    from tkinter import ttk

    result = [None]

    root = tk.Tk()
    root.title(title)
    root.resizable(False, False)
    root.attributes("-topmost", True)

    tk.Label(root, text=prompt, justify="left", padx=12, pady=8).pack(anchor="w")

    var = tk.StringVar(value=initial)
    combo = ttk.Combobox(root, textvariable=var, values=values, width=46)
    combo.pack(padx=12, pady=4)
    combo.focus_set()

    # Filter dropdown as the user types
    def _on_key(_event=None):
        typed = var.get().lower()
        filtered = [v for v in values if typed in v.lower()]
        combo["values"] = filtered if filtered else values

    combo.bind("<KeyRelease>", _on_key)

    def _ok(_event=None):
        result[0] = var.get().strip()
        root.destroy()

    def _cancel(_event=None):
        root.destroy()

    btn = tk.Frame(root)
    btn.pack(pady=10)
    tk.Button(btn, text="OK",     width=10, command=_ok).pack(side="left", padx=6)
    tk.Button(btn, text="Cancel", width=10, command=_cancel).pack(side="left", padx=6)

    combo.bind("<Return>", _ok)
    root.bind("<Escape>", _cancel)
    root.protocol("WM_DELETE_WINDOW", _cancel)

    root.update_idletasks()
    w, h = root.winfo_reqwidth(), root.winfo_reqheight()
    sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
    root.geometry(f"{w}x{h}+{(sw - w) // 2}+{(sh - h) // 2}")

    root.mainloop()
    return result[0]


def _epsg_choices():
    """Flat list of 'EPSG:XXXX — Label' strings from the EPSG_NODES tree."""
    choices = []
    def _walk(nodes):
        for node in nodes:
            if "children" in node:
                _walk(node["children"])
            else:
                # id is the numeric code, label is e.g. "WGS 84 (EPSG:4326)"
                epsg = node["id"]
                label = node["label"]
                choices.append(f"EPSG:{epsg} — {label}")
    _walk(EPSG_NODES)
    return choices


# ---------------------------------------------------------------------------
# Panel state builder
# ---------------------------------------------------------------------------
def _panel_state(layers=None):
    """Build the panel items answer from the current map state."""
    if layers is None:
        try:
            layers = _call("host.layers", {}) or []
        except Exception:
            layers = []

    vector_layers = [l for l in layers if not l.get("raster")]
    active = next((l for l in vector_layers if l.get("active")), None)

    if active:
        layer_text = f"{active['name']}"
        geo = active.get("geometry") or ""
        if geo:
            layer_text += f"  [{geo}]"
        features = active.get("features", 0)
        if features:
            layer_text += f"  {features} features"
    else:
        layer_text = "No active vector layer" if vector_layers else "No vector layers loaded"

    merge_text = (
        f"{len(vector_layers)} vector layer(s) will be merged"
        if vector_layers
        else "No vector layers to merge"
    )

    return {
        "panel": {
            "items": {
                "layer-info":    {"text": layer_text},
                "proj-status":   {"text": ""},
                "action-status": {"text": merge_text},
            }
        }
    }


# ---------------------------------------------------------------------------
# Command handlers
# ---------------------------------------------------------------------------
def handle_panel_state(req):
    return _panel_state()


def handle_set_projection(req):
    global _last_epsg
    params = req.get("params") or {}
    panel = req.get("panel") or {}

    epsg = params.get("epsg") or params.get("crs")

    if not epsg:
        chosen = _ask_combobox(
            "Set Projection",
            "Select or type an EPSG projection:",
            _epsg_choices(),
            initial=_last_epsg,
        )
        if not chosen:
            return {"panel": {"items": {"proj-status": {"text": "Cancelled."}}}}
        # Accept bare number "27700" or full "EPSG:27700 — ..." string
        epsg = chosen.split("—")[0].strip().replace("EPSG:", "").strip() if "—" in chosen else chosen.strip()

    _last_epsg = str(epsg).strip()

    # Normalise to "EPSG:XXXX"
    epsg_str = str(epsg).strip()
    if not epsg_str.upper().startswith("EPSG:"):
        epsg_str = f"EPSG:{epsg_str}"

    # Explicit layer param (script/CLI) takes priority
    explicit_layer = params.get("layer")
    if explicit_layer:
        targets = [explicit_layer]
    else:
        # Apply to every selected layer; fall back to active layer
        all_layers = _call("host.layers", {}) or []
        selected = [l["name"] for l in all_layers if l.get("selected")]
        if not selected:
            # Nothing selected — use active layer
            active = next((l["name"] for l in all_layers if l.get("active")), None)
            if not active:
                _notify("No layer selected or active.", error=True)
                return {"panel": {"items": {"proj-status": {"text": "No layer selected."}}}}
            selected = [active]
        targets = selected

    for name in targets:
        _call("layer.defineProjection", {"layer": name, "crs": epsg_str})

    count = len(targets)
    names = ", ".join(targets) if count <= 3 else f"{count} layers"
    msg = f"Projection set to {epsg_str} on {names}"
    _notify(msg)
    _log(msg)

    return {
        "panel": {
            "items": {
                "proj-status": {"text": msg}
            }
        }
    }


# ---------------------------------------------------------------------------
# DXF helpers
# ---------------------------------------------------------------------------
def _sanitize_dxf_name(name):
    for ch in '<>/\\:;?*|,=':
        name = name.replace(ch, '_')
    return name[:255] or "layer"


def _poly_centroid(ring):
    """Signed-area centroid of a ring (list of [x, y, …] positions)."""
    n = len(ring)
    if n < 3:
        return ring[0][0], ring[0][1]
    area = cx = cy = 0.0
    for i in range(n):
        j = (i + 1) % n
        cross = ring[i][0] * ring[j][1] - ring[j][0] * ring[i][1]
        area += cross
        cx += (ring[i][0] + ring[j][0]) * cross
        cy += (ring[i][1] + ring[j][1]) * cross
    area /= 2.0
    if abs(area) < 1e-12:
        xs = [p[0] for p in ring]
        ys = [p[1] for p in ring]
        return sum(xs) / len(xs), sum(ys) / len(ys)
    return cx / (6.0 * area), cy / (6.0 * area)


def _text_height(ring):
    """5 % of the smaller bbox dimension, minimum 0.001."""
    if len(ring) < 2:
        return 1.0
    xs = [p[0] for p in ring]
    ys = [p[1] for p in ring]
    size = min(max(xs) - min(xs), max(ys) - min(ys))
    return max(size * 0.05, 0.001)


def _transform_ring(ring, transformer):
    """Reproject a ring of [lon, lat, …] positions → (x, y) in target CRS."""
    result = []
    for pt in ring:
        x, y = transformer.transform(pt[0], pt[1])
        result.append((x, y))
    return result


def handle_export_dxf(req):
    import ezdxf
    import tkinter as tk
    from tkinter import filedialog
    from pyproj import Transformer

    params = req.get("params") or {}
    panel  = req.get("panel")  or {}
    label_field = params.get("label_field")

    # ── 1. Resolve target CRS ────────────────────────────────────────────────
    epsg = params.get("epsg")
    if not epsg:
        tree_val = (panel.get("values") or {}).get("epsg-tree")
        if tree_val and str(tree_val).lstrip("_").isdigit():
            epsg = int(tree_val)
    if not epsg:
        # Fall back to the map's current display projection
        try:
            view = _call("host.view", {}) or {}
            proj = view.get("projection", "")
            if proj and ":" in proj:
                epsg = int(proj.split(":")[-1])
        except Exception:
            pass
    if not epsg:
        raise RuntimeError(
            "Select an EPSG code in the panel tree before exporting, "
            "or run with {\"epsg\": 27700}."
        )

    epsg_str = f"EPSG:{epsg}"
    _log(f"Target CRS: {epsg_str}")
    transformer = Transformer.from_crs("EPSG:4326", epsg_str, always_xy=True)

    # ── 2. Ask user where to save ────────────────────────────────────────────
    path = params.get("path")
    if not path:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        try:
            root = tk.Tk()
            root.withdraw()
            root.wm_attributes("-topmost", True)
            path = filedialog.asksaveasfilename(
                title="Save DXF As",
                defaultextension=".dxf",
                filetypes=[("DXF files", "*.dxf"), ("All files", "*.*")],
                initialfile=f"export_{ts}.dxf",
            )
            root.destroy()
        except Exception as e:
            _log(f"tkinter dialog failed ({e}), falling back to Desktop")
            desktop = os.path.join(os.path.expanduser("~"), "Desktop")
            os.makedirs(desktop, exist_ok=True)
            path = os.path.join(desktop, f"export_{ts}.dxf")

    if not path:
        raise RuntimeError("Export cancelled.")

    # ── 3. Collect layers ────────────────────────────────────────────────────
    all_layers = _call("host.layers", {}) or []
    vector_layers = [l for l in all_layers if not l.get("raster")]
    selected = [l for l in vector_layers if l.get("selected")]
    targets  = selected if selected else vector_layers

    if not targets:
        raise RuntimeError("No vector layers to export.")

    # ── 4. Build DXF ─────────────────────────────────────────────────────────
    doc = ezdxf.new("R2010")
    doc.header["$INSUNITS"] = 6        # metres
    doc.header["$MEASUREMENT"] = 1     # metric
    msp = doc.modelspace()

    feature_count = 0
    color_cycle = [1, 2, 3, 4, 5, 6, 7]

    for idx, layer in enumerate(targets):
        layer_name = layer["name"]
        dxf_geom  = _sanitize_dxf_name(layer_name)
        dxf_label = _sanitize_dxf_name(layer_name + "_labels")
        color = color_cycle[idx % len(color_cycle)]

        if dxf_geom  not in doc.layers:
            doc.layers.add(name=dxf_geom,  color=color)
        if dxf_label not in doc.layers:
            doc.layers.add(name=dxf_label, color=color)

        _log(f"Exporting '{layer_name}' …")
        fc = _call("host.features", {"layer": layer["id"]}) or {}
        features = fc.get("features") or []

        for feat in features:
            geom   = feat.get("geometry") or {}
            gtype  = geom.get("type", "")
            coords = geom.get("coordinates", [])
            props  = feat.get("properties") or {}

            polygons = []
            if gtype == "Polygon":
                polygons = [coords]
            elif gtype == "MultiPolygon":
                polygons = coords
            else:
                continue

            for polygon in polygons:
                if not polygon:
                    continue
                outer_raw = polygon[0]

                # Reproject outer ring WGS84 → target CRS
                outer = _transform_ring(outer_raw, transformer)
                if outer:
                    msp.add_lwpolyline(outer, dxfattribs={"layer": dxf_geom, "closed": True})

                # Inner rings (holes)
                for inner_raw in polygon[1:]:
                    inner = _transform_ring(inner_raw, transformer)
                    if inner:
                        msp.add_lwpolyline(inner, dxfattribs={"layer": dxf_geom, "closed": True})

                # Label at centroid (already in target CRS)
                label_text = (
                    str(props.get(label_field, layer_name))
                    if label_field and label_field in props
                    else layer_name
                )
                cx, cy = _poly_centroid(outer)
                th = _text_height(outer)

                text = msp.add_text(
                    label_text,
                    dxfattribs={"layer": dxf_label, "height": th},
                )
                text.set_placement(
                    (cx, cy),
                    align=ezdxf.enums.TextEntityAlignment.MIDDLE_CENTER,
                )
                feature_count += 1

    doc.saveas(path)

    basename = os.path.basename(path)
    msg = f"DXF saved: {basename}  ({feature_count} polygons, {epsg_str})"
    _notify(msg)
    _log(f"Saved to {path}")

    return {"panel": {"items": {"action-status": {"text": msg}}}}


def handle_load_basemap(req):
    params = req.get("params") or {}
    panel  = req.get("panel")  or {}

    bm_key = params.get("basemap")

    if not bm_key or bm_key not in BASEMAPS:
        bm_choices = [f"{k} — {v['name']}" for k, v in BASEMAPS.items()]
        chosen = _ask_combobox(
            "Load Basemap",
            "Select a basemap:",
            bm_choices,
        )
        if not chosen:
            return {"panel": {"items": {"action-status": {"text": "Cancelled."}}}}
        bm_key = chosen.split("—")[0].strip() if "—" in chosen else chosen.strip()
        if bm_key not in BASEMAPS:
            _notify(f"Unknown basemap key: {bm_key}", error=True)
            return {"panel": {"items": {"action-status": {"text": f"Unknown: {bm_key}"}}}}

    bm = BASEMAPS[bm_key]
    tile_params = {
        "url":     bm["url"],
        "name":    bm["name"],
        "maxZoom": bm.get("maxZoom", 19),
        "overlay": False,
    }
    if "attribution" in bm:
        tile_params["attribution"] = bm["attribution"]

    _call("map.addTiles", tile_params)

    msg = f"Basemap loaded: {bm['name']}"
    _notify(msg)
    _log(msg)

    return {"panel": {"items": {"action-status": {"text": msg}}}}


def handle_merge_layers(req):
    params = req.get("params") or {}
    output_name = params.get("name", "Merged")

    layers = _call("host.layers", {}) or []
    vector_layers = [l for l in layers if not l.get("raster")]

    if not vector_layers:
        raise RuntimeError("No vector layers found to merge.")

    all_features = []
    for layer in vector_layers:
        layer_name = layer["name"]
        layer_id = layer["id"]
        _log(f"Reading features from '{layer_name}' …")
        fc = _call("host.features", {"layer": layer_id})
        features = (fc or {}).get("features") or []
        for feat in features:
            props = feat.get("properties") or {}
            props["source_layer"] = layer_name
            feat["properties"] = props
            all_features.append(feat)

    if not all_features:
        raise RuntimeError("No features found across loaded layers.")

    merged_geojson = {
        "type": "FeatureCollection",
        "features": all_features,
    }

    _call("host.addLayer", {"name": output_name, "geojson": merged_geojson})

    msg = (
        f"Merged {len(all_features)} features from "
        f"{len(vector_layers)} layer(s) into '{output_name}'"
    )
    _notify(msg)
    _log(msg)

    return {
        "panel": {
            "items": {
                "action-status": {"text": msg}
            }
        }
    }


# ---------------------------------------------------------------------------
# Containment helpers
# ---------------------------------------------------------------------------
def _get_target_layer(all_layers, params):
    """Return the single layer to operate on: explicit param > selected > active."""
    vector_layers = [l for l in all_layers if not l.get("raster")]
    name = (params or {}).get("layer")
    if name:
        match = next((l for l in vector_layers if l["name"] == name or l["id"] == name), None)
        if not match:
            raise RuntimeError(f"Layer '{name}' not found.")
        return match
    selected = [l for l in vector_layers if l.get("selected")]
    if selected:
        return selected[0]
    active = next((l for l in vector_layers if l.get("active")), None)
    if not active:
        raise RuntimeError("No layer selected or active.")
    return active


def _build_containment(features):
    """
    Return (items, parents, net_areas).
    items     — list of {idx, feat, shape, area_m2}
    parents   — list of item-index of direct parent, or None
    net_areas — list of float (gross area minus direct-child areas)
    """
    from shapely.geometry import shape as shapely_shape
    from pyproj import Geod

    geod = Geod(ellps="WGS84")
    items = []
    for feat in features:
        geom = feat.get("geometry")
        if not geom or geom.get("type") not in ("Polygon", "MultiPolygon"):
            continue
        try:
            s = shapely_shape(geom)
            if not s.is_valid:
                s = s.buffer(0)
            area_m2 = abs(geod.geometry_area_perimeter(s)[0])
        except Exception:
            continue
        items.append({"feat": feat, "shape": s, "area_m2": area_m2})

    n = len(items)
    parents = [None] * n

    for i in range(n):
        best_parent = None
        best_area = float("inf")
        for j in range(n):
            if i == j:
                continue
            try:
                if items[j]["shape"].contains(items[i]["shape"]):
                    if items[j]["area_m2"] < best_area:
                        best_area = items[j]["area_m2"]
                        best_parent = j
            except Exception:
                continue
        parents[i] = best_parent

    net_areas = [item["area_m2"] for item in items]
    for i, p in enumerate(parents):
        if p is not None:
            net_areas[p] -= items[i]["area_m2"]

    return items, parents, net_areas


# ---------------------------------------------------------------------------
# Layer export helpers
# ---------------------------------------------------------------------------
def _fiona_crs():
    try:
        from fiona.crs import CRS
        return CRS.from_epsg(4326)
    except Exception:
        from fiona.crs import from_epsg
        return from_epsg(4326)


def _infer_schema(features):
    """Infer fiona schema (geometry type + property types) from GeoJSON features."""
    geom_types, keys_seen, prop_types = set(), [], {}
    for feat in features:
        gt = (feat.get("geometry") or {}).get("type", "")
        if gt:
            geom_types.add(gt)
        for k, v in (feat.get("properties") or {}).items():
            if k not in prop_types:
                keys_seen.append(k)
                prop_types[k] = (
                    "bool" if isinstance(v, bool)
                    else "int"   if isinstance(v, int)
                    else "float" if isinstance(v, float)
                    else "str"
                )
    if len(geom_types) == 1:
        gtype = list(geom_types)[0]
    elif any("Polygon" in t for t in geom_types):
        gtype = "MultiPolygon"
    elif any("Line" in t for t in geom_types):
        gtype = "MultiLineString"
    else:
        gtype = "Point" if geom_types else "Unknown"
    return gtype, keys_seen, prop_types


def _geom_to_kml(geom):
    """Convert a GeoJSON geometry dict to a KML geometry XML string."""
    import xml.etree.ElementTree as ET

    def coords_str(ring):
        return " ".join(f"{p[0]},{p[1]},0" for p in ring)

    gtype = geom.get("type", "")
    coords = geom.get("coordinates")
    if not coords:
        return ""

    if gtype == "Point":
        el = ET.Element("Point")
        ET.SubElement(el, "coordinates").text = f"{coords[0]},{coords[1]},0"
    elif gtype == "MultiPoint":
        el = ET.Element("MultiGeometry")
        for pt in coords:
            p = ET.SubElement(el, "Point")
            ET.SubElement(p, "coordinates").text = f"{pt[0]},{pt[1]},0"
    elif gtype == "LineString":
        el = ET.Element("LineString")
        ET.SubElement(el, "coordinates").text = coords_str(coords)
    elif gtype == "MultiLineString":
        el = ET.Element("MultiGeometry")
        for line in coords:
            ls = ET.SubElement(el, "LineString")
            ET.SubElement(ls, "coordinates").text = coords_str(line)
    elif gtype == "Polygon":
        el = ET.Element("Polygon")
        outer = ET.SubElement(ET.SubElement(el, "outerBoundaryIs"), "LinearRing")
        ET.SubElement(outer, "coordinates").text = coords_str(coords[0])
        for hole in coords[1:]:
            inner = ET.SubElement(ET.SubElement(el, "innerBoundaryIs"), "LinearRing")
            ET.SubElement(inner, "coordinates").text = coords_str(hole)
    elif gtype == "MultiPolygon":
        el = ET.Element("MultiGeometry")
        for poly in coords:
            pg = ET.SubElement(el, "Polygon")
            outer = ET.SubElement(ET.SubElement(pg, "outerBoundaryIs"), "LinearRing")
            ET.SubElement(outer, "coordinates").text = coords_str(poly[0])
            for hole in poly[1:]:
                inner = ET.SubElement(ET.SubElement(pg, "innerBoundaryIs"), "LinearRing")
                ET.SubElement(inner, "coordinates").text = coords_str(hole)
    else:
        return ""

    return ET.tostring(el, encoding="unicode")


def _write_kml(features, kml_path, layer_name="export"):
    """Write features to a KML file. Returns count written."""
    import re as _re

    # XML-safe: escape markup chars AND strip control characters invalid in XML 1.0
    _XML_INVALID = _re.compile(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]')

    def esc(s):
        s = _XML_INVALID.sub("", str(s))
        return (s.replace("&", "&amp;")
                 .replace("<", "&lt;")
                 .replace(">", "&gt;")
                 .replace('"', "&quot;")
                 .replace("'", "&apos;"))

    # Ensure parent directory exists
    parent = os.path.dirname(kml_path)
    if parent:
        os.makedirs(parent, exist_ok=True)

    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<kml xmlns="http://www.opengis.net/kml/2.2">',
        f'  <Document><name>{esc(layer_name)}</name>',
    ]
    written = 0
    for feat in features:
        geom = feat.get("geometry")
        props = feat.get("properties") or {}
        if not geom:
            continue
        geom_xml = _geom_to_kml(geom)
        if not geom_xml:
            continue
        name = next((str(props[k]) for k in ("name", "Name", "NAME", "id", "ID") if props.get(k)), f"Feature {written+1}")
        lines.append(f'  <Placemark><name>{esc(name)}</name>')
        if props:
            lines.append('    <ExtendedData>')
            for k, v in props.items():
                if v is not None:
                    lines.append(f'      <Data name="{esc(k)}"><value>{esc(v)}</value></Data>')
            lines.append('    </ExtendedData>')
        lines.append(f'    {geom_xml}')
        lines.append('  </Placemark>')
        written += 1
    lines.append('  </Document></kml>')

    content = "\n".join(lines)
    with open(kml_path, "w", encoding="utf-8") as f:
        f.write(content)

    # Verify file has content (empty file causes "invalid token" in Google Earth)
    size = os.path.getsize(kml_path)
    if size == 0:
        raise RuntimeError(f"KML file was written but is empty: {kml_path}")

    _log(f"KML written: {written} features, {size} bytes → {kml_path}")
    return written


def _write_to_file(features, path, layer_name=None):
    """
    Write GeoJSON features to path.
    Format detected from extension: .shp .gpkg .geojson .json .kml .kmz
    Returns (n_written, driver_name).
    """
    import zipfile

    ext = os.path.splitext(path)[1].lower()
    if not layer_name:
        layer_name = os.path.splitext(os.path.basename(path))[0]

    # KML/KMZ handled without fiona (more reliable)
    if ext in (".kml", ".kmz"):
        kml_path = path if ext == ".kml" else path[:-4] + "_tmp.kml"
        n = _write_kml(features, kml_path, layer_name)
        if ext == ".kmz":
            with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
                zf.write(kml_path, layer_name + ".kml")
            os.remove(kml_path)
        return n, "KML" if ext == ".kml" else "KMZ"

    import fiona

    driver_map = {
        ".shp":     "ESRI Shapefile",
        ".gpkg":    "GPKG",
        ".geojson": "GeoJSON",
        ".json":    "GeoJSON",
    }
    driver = driver_map.get(ext, "GeoJSON")

    gtype, keys, prop_types = _infer_schema(features)

    # SHP: field names max 10 chars; build rename map
    rename = {}
    if driver == "ESRI Shapefile":
        used = {}
        for k in keys:
            short = k[:10]
            if short in used:
                used[short] += 1
                short = k[:8] + str(used[short])
            used[short] = used.get(short, 0)
            rename[k] = short
        keys = [rename[k] for k in keys]
        prop_types = {rename.get(k, k): v for k, v in prop_types.items()}

    schema = {"geometry": gtype, "properties": {k: prop_types[k] for k in keys}}

    written = 0
    with fiona.open(path, "w", driver=driver, schema=schema, crs=_fiona_crs()) as dst:
        for feat in features:
            geom = feat.get("geometry")
            if not geom:
                continue
            raw = feat.get("properties") or {}
            props = {}
            for orig, new_k in (rename.items() if rename else {k: k for k in raw}.items()):
                v = raw.get(orig)
                ptype = prop_types.get(new_k, "str")
                try:
                    if v is None:
                        props[new_k] = None
                    elif ptype == "int":
                        props[new_k] = int(v)
                    elif ptype == "float":
                        props[new_k] = float(v)
                    elif ptype == "bool":
                        props[new_k] = bool(v)
                    else:
                        props[new_k] = str(v)
                except (ValueError, TypeError):
                    props[new_k] = None
            try:
                dst.write({"type": "Feature", "geometry": geom, "properties": props})
                written += 1
            except Exception as e:
                _log(f"Skipped feature: {e}")

    return written, driver


def _save_dialog(title, initial_name, ext_filters):
    """Show a tkinter save dialog. Returns path string or empty string."""
    import tkinter as tk
    from tkinter import filedialog
    try:
        root = tk.Tk()
        root.withdraw()
        root.wm_attributes("-topmost", True)
        path = filedialog.asksaveasfilename(
            title=title,
            filetypes=ext_filters,
            initialfile=initial_name,
        )
        root.destroy()
        return path or ""
    except Exception as e:
        _log(f"tkinter dialog failed: {e}")
        return ""


EXPORT_FILTERS = [
    ("GeoPackage",      "*.gpkg"),
    ("GeoJSON",         "*.geojson"),
    ("Shapefile",       "*.shp"),
    ("KML/KMZ",         "*.kml *.kmz"),
    ("All files",       "*.*"),
]


def handle_export_layer(req):
    params = req.get("params") or {}
    all_layers = _call("host.layers", {}) or []
    target = _get_target_layer(all_layers, params)

    _log(f"Loading '{target['name']}' for export …")
    fc = _call("host.features", {"layer": target["id"]}) or {}
    features = (fc.get("features") or [])
    if not features:
        raise RuntimeError("No features to export.")

    path = params.get("path") or _save_dialog(
        "Export Layer As",
        target["name"] + ".gpkg",
        EXPORT_FILTERS,
    )
    if not path:
        raise RuntimeError("Export cancelled.")

    written, driver = _write_to_file(features, path)
    basename = os.path.basename(path)
    msg = f"Exported: {basename}  ({written} features, {driver})"
    _notify(msg)
    _log(f"Saved to {path}")
    return {"panel": {"items": {"action-status": {"text": msg}}}}


def handle_save_original(req):
    """Save back to the original source file, retaining its format."""
    params = req.get("params") or {}
    all_layers = _call("host.layers", {}) or []
    target = _get_target_layer(all_layers, params)

    # Try to get original source path from layer metadata
    source_path = (
        target.get("path") or target.get("source") or
        target.get("file") or target.get("url") or ""
    )
    # Only use it if it looks like a local file (not http/https)
    if source_path and source_path.lower().startswith("http"):
        source_path = ""

    _log(f"Loading '{target['name']}' for save-original …")
    fc = _call("host.features", {"layer": target["id"]}) or {}
    features = (fc.get("features") or [])
    if not features:
        raise RuntimeError("No features to save.")

    if source_path and os.path.exists(source_path):
        # Confirm overwrite via dialog title
        path = _save_dialog(
            f"Save to original file (overwrite) — {os.path.basename(source_path)}",
            os.path.basename(source_path),
            EXPORT_FILTERS,
        )
    else:
        # Original path unknown — ask user to navigate to it
        safe = "".join(c if c.isalnum() or c in "-_ " else "_" for c in target["name"])
        path = _save_dialog(
            "Save Layer — navigate to original file to overwrite",
            safe + ".gpkg",
            EXPORT_FILTERS,
        )

    if not path:
        raise RuntimeError("Save cancelled.")

    written, driver = _write_to_file(features, path)
    basename = os.path.basename(path)
    msg = f"Saved: {basename}  ({written} features, {driver})"
    _notify(msg)
    _log(f"Saved to {path}")
    return {"panel": {"items": {"action-status": {"text": msg}}}}


def handle_export_table(req):
    import csv
    import tkinter as tk
    from tkinter import filedialog

    params = req.get("params") or {}

    all_layers = _call("host.layers", {}) or []
    target = _get_target_layer(all_layers, params)

    _log(f"Exporting table from '{target['name']}' …")
    fc = _call("host.features", {"layer": target["id"]}) or {}
    features = (fc.get("features") or [])

    if not features:
        raise RuntimeError("No features to export.")

    # Collect all field names in order of first appearance
    all_keys = []
    seen = set()
    for feat in features:
        for k in (feat.get("properties") or {}):
            if k not in seen:
                all_keys.append(k)
                seen.add(k)

    if not all_keys:
        raise RuntimeError("Features have no attributes to export.")

    # Save dialog
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = params.get("path")
    if not path:
        safe_name = "".join(c if c.isalnum() or c in "-_" else "_" for c in target["name"])
        try:
            root = tk.Tk()
            root.withdraw()
            root.wm_attributes("-topmost", True)
            path = filedialog.asksaveasfilename(
                title="Save Table As",
                defaultextension=".csv",
                filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
                initialfile=f"{safe_name}_{ts}.csv",
            )
            root.destroy()
        except Exception as e:
            _log(f"tkinter failed ({e}), using Desktop")
            desktop = os.path.join(os.path.expanduser("~"), "Desktop")
            os.makedirs(desktop, exist_ok=True)
            path = os.path.join(desktop, f"{safe_name}_{ts}.csv")

    if not path:
        raise RuntimeError("Export cancelled.")

    # utf-8-sig BOM so Excel opens the file with correct encoding
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=all_keys, extrasaction="ignore")
        writer.writeheader()
        for feat in features:
            writer.writerow(feat.get("properties") or {})

    basename = os.path.basename(path)
    msg = f"Table exported: {basename}  ({len(features)} rows, {len(all_keys)} columns)"
    _notify(msg)
    _log(f"Saved to {path}")
    return {"panel": {"items": {"action-status": {"text": msg}}}}


def handle_check_containment(req):
    params = req.get("params") or {}

    all_layers = _call("host.layers", {}) or []
    target = _get_target_layer(all_layers, params)

    _log(f"Loading features from '{target['name']}' …")
    fc = _call("host.features", {"layer": target["id"]}) or {}
    features = (fc.get("features") or [])

    if len(features) < 2:
        raise RuntimeError("Need at least 2 polygon features to check containment.")

    items, parents, net_areas = _build_containment(features)
    n = len(items)

    out_features = []
    for i, item in enumerate(items):
        feat = dict(item["feat"])
        props = dict(feat.get("properties") or {})
        props["area_m2"]       = round(item["area_m2"], 2)
        props["net_area_m2"]   = round(net_areas[i], 2)
        props["contains_count"] = sum(1 for p in parents if p == i)
        props["contained_in"]  = (
            str(items[parents[i]]["feat"].get("id", parents[i]))
            if parents[i] is not None else ""
        )
        feat["properties"] = props
        out_features.append(feat)

    out_name = target["name"] + " — Containment"
    _call("host.addLayer", {"name": out_name, "geojson": {"type": "FeatureCollection", "features": out_features}})

    n_pairs  = sum(1 for p in parents if p is not None)
    n_outer  = len({p for p in parents if p is not None})
    msg = (
        f"{n_pairs} inner polygon(s) found inside {n_outer} outer polygon(s). "
        f"See 'net_area_m2' in '{out_name}'."
    )
    _notify(msg)
    _log(msg)
    return {"panel": {"items": {"action-status": {"text": msg}}}}


def handle_fix_donuts(req):
    """
    Create a new layer where inner polygons become holes in their outer polygon.
    Inner polygons are removed as separate features; outer polygons get interior rings.
    """
    from shapely.geometry import shape as shapely_shape, mapping
    from shapely.ops import unary_union
    try:
        from shapely import orient          # shapely 2.x
    except ImportError:
        from shapely.geometry.polygon import orient  # shapely 1.x
    from pyproj import Geod

    params = req.get("params") or {}

    all_layers = _call("host.layers", {}) or []
    target = _get_target_layer(all_layers, params)

    _log(f"Loading features from '{target['name']}' …")
    fc = _call("host.features", {"layer": target["id"]}) or {}
    features = (fc.get("features") or [])

    if len(features) < 2:
        raise RuntimeError("Need at least 2 polygon features.")

    items, parents, net_areas = _build_containment(features)
    n = len(items)
    geod = Geod(ellps="WGS84")

    out_features = []
    fixed_count = 0
    for i, item in enumerate(items):
        if parents[i] is not None:
            continue  # inner polygon — becomes a hole, skip as separate feature

        # Find all direct children (holes)
        children = [items[j]["shape"] for j in range(n) if parents[j] == i]

        geom = item["shape"]
        if children:
            holes = unary_union(children)
            geom = geom.difference(holes)
            fixed_count += 1

        # RFC 7946: exterior CCW, interior rings CW — required for holes to render
        geom = orient(geom, sign=1.0)

        # Recalculate area from the actual donut geometry (gross - holes)
        donut_area_m2 = abs(geod.geometry_area_perimeter(geom)[0])

        feat = dict(item["feat"])
        feat["geometry"] = mapping(geom)
        props = dict(feat.get("properties") or {})
        props["gross_area_m2"] = round(item["area_m2"], 2)
        props["area_m2"]       = round(donut_area_m2, 2)
        props["holes_cut"]     = len(children)
        feat["properties"] = props
        out_features.append(feat)

    out_name = target["name"] + " — Fixed Donuts"
    _call("host.addLayer", {"name": out_name, "geojson": {"type": "FeatureCollection", "features": out_features}})

    n_removed = sum(1 for p in parents if p is not None)
    msg = (
        f"Fixed {fixed_count} polygon(s): {n_removed} inner polygon(s) converted to holes. "
        f"Layer '{out_name}' added."
    )
    _notify(msg)
    _log(msg)
    return {"panel": {"items": {"action-status": {"text": msg}}}}


# ---------------------------------------------------------------------------
# Feature navigator
# ---------------------------------------------------------------------------
def _geom_bbox(geom):
    """Return [minLng, minLat, maxLng, maxLat] or None."""
    gtype = geom.get("type", "")
    coords = geom.get("coordinates")
    if not coords:
        return None
    depth_map = {"Point": 0, "MultiPoint": 1, "LineString": 1,
                 "MultiLineString": 2, "Polygon": 2, "MultiPolygon": 3}
    depth = depth_map.get(gtype, 2)
    def _flat(c, d):
        if d == 0:
            return [c]
        out = []
        for x in c:
            out.extend(_flat(x, d - 1))
        return out
    pts = _flat(coords, depth)
    lngs = [p[0] for p in pts if len(p) >= 2]
    lats = [p[1] for p in pts if len(p) >= 2]
    if not lngs:
        return None
    pad_lng = max((max(lngs) - min(lngs)) * 0.1, 0.0001)
    pad_lat = max((max(lats) - min(lats)) * 0.1, 0.0001)
    return [min(lngs) - pad_lng, min(lats) - pad_lat,
            max(lngs) + pad_lng, max(lats) + pad_lat]


def _nav_step(action):
    layers = _call("host.layers", {}) or []
    active = next((l for l in layers if not l.get("raster") and l.get("active")), None)
    if not active:
        _notify("No active vector layer.", error=True)
        return {"panel": {"items": {"nav-status": {"text": "No active layer."}}}}

    layer_name = active["name"]
    layer_id = active.get("id") or layer_name

    # Always reload features (process may have restarted)
    raw = _call("host.features", {"layer": layer_name}) or {}
    feats = raw.get("features", []) if isinstance(raw, dict) else []
    n = len(feats)
    if n == 0:
        _notify("No features in layer.", error=True)
        return {"panel": {"items": {"nav-status": {"text": "No features."}}}}

    # Load persisted index; reset if layer changed
    saved_idx, saved_layer = _nav_load()
    if saved_layer != layer_id:
        saved_idx = -1

    if action == "next":
        idx = (saved_idx + 1) % n
    else:  # prev
        idx = (saved_idx - 1) % n

    _nav_save(idx, layer_id)

    feat = feats[idx]

    # --- Zoom to feature bbox ---
    geom = feat.get("geometry") or {}
    bbox = _geom_bbox(geom)
    if bbox:
        for zoom_call, zoom_params in [
            ("map.zoomToBbox",  {"bbox": bbox}),
            ("map.fitBounds",   {"bounds": bbox}),
            ("map.zoomToExtent",{"extent": bbox}),
        ]:
            try:
                _call(zoom_call, zoom_params)
                break
            except Exception:
                continue

    # --- Select feature in attribute table ---
    try:
        _call("layer.select", {"layer": layer_name, "index": idx})
    except Exception:
        pass

    props = feat.get("properties") or {}
    label = next((str(props[k]) for k in ("name", "Name", "NAME", "id", "ID", "label") if props.get(k)), None)
    if not label and props:
        label = str(next(iter(props.values())))
    label = label or "(no attributes)"

    msg = f"Feature {idx + 1} / {n}:  {label}"
    _notify(msg)
    return {"panel": {"items": {"nav-status": {"text": msg}}}}


def handle_feature_next(req):
    return _nav_step("next")


def handle_feature_prev(req):
    return _nav_step("prev")




def _extract_ifc_footprints(ifc_path):
    """
    Extract building footprints from an IFC file using ifcopenshell.geom.
    Returns list of GeoJSON Feature dicts with height_m, height_ft, floors,
    base_z, top_z, elements, area_m2.  Dissolves by building.
    """
    import multiprocessing
    import numpy as np
    import ifcopenshell
    import ifcopenshell.geom as ifc_geom
    from shapely.geometry import Polygon, mapping as shapely_mapping
    from shapely.ops import unary_union

    FLOOR_M = 9.0 * 0.3048  # 9 ft per floor

    f = ifcopenshell.open(ifc_path)
    s = ifc_geom.settings()
    s.set("use-world-coords", True)
    it = ifc_geom.iterator(s, f, multiprocessing.cpu_count())

    rows = []
    bad = 0
    if it.initialize():
        while True:
            sh = it.get()
            v = np.array(sh.geometry.verts).reshape(-1, 3)
            t = np.array(sh.geometry.faces).reshape(-1, 3)
            try:
                tris = [Polygon(v[i][:, :2]) for i in t]
                tris = [p.buffer(0) for p in tris if p.area > 1e-9]
                fp = unary_union(tris).buffer(0.001).buffer(-0.001) if tris else None
            except Exception:
                fp = None
            if fp is None or fp.is_empty:
                bad += 1
            else:
                e = f.by_id(sh.id)
                zmin = float(v[:, 2].min())
                zmax = float(v[:, 2].max())
                rows.append({
                    "geometry": fp,
                    "base_z": round(zmin, 3),
                    "top_z": round(zmax, 3),
                    "height_m": round(zmax - zmin, 3),
                    "name": getattr(e, "Name", None) or "",
                    "ifc_guid": getattr(e, "GlobalId", None) or "",
                })
            if not it.next():
                break

    if not rows:
        return [], 0, bad

    # Dissolve overlapping footprints into building groups
    polys = [r["geometry"] for r in rows]
    all_union = unary_union(polys)
    geom_list = list(all_union.geoms) if all_union.geom_type == "MultiPolygon" else [all_union]

    features = []
    for i, bldg_poly in enumerate(geom_list, 1):
        members = [r for r in rows if bldg_poly.intersects(r["geometry"])]
        if not members:
            continue
        h_max = max(r["height_m"] for r in members)
        base = min(r["base_z"] for r in members)
        top = max(r["top_z"] for r in members)
        area = round(bldg_poly.area, 2)
        floors = max(1, round(h_max / FLOOR_M))
        props = {
            "face_id": i,
            "height_m": round(h_max, 3),
            "height_ft": round(h_max / 0.3048, 2),
            "floors": floors,
            "base_z": round(base, 3),
            "top_z": round(top, 3),
            "elements": len(members),
            "area_m2": area,
        }
        try:
            geom = shapely_mapping(bldg_poly)
        except Exception:
            continue
        features.append({
            "type": "Feature",
            "geometry": geom,
            "properties": props,
        })

    # Sort by area descending, renumber
    features.sort(key=lambda f: -(f["properties"]["area_m2"] or 0))
    for idx, feat in enumerate(features, 1):
        feat["properties"]["face_id"] = idx

    return features, len(rows), bad


def handle_load_ifc(req):
    global _last_epsg
    params = req.get("params") or {}

    # 1 — pick IFC file
    import tkinter as tk
    from tkinter import filedialog
    root = tk.Tk(); root.withdraw(); root.attributes("-topmost", True)
    path = filedialog.askopenfilename(
        title="Select IFC file",
        filetypes=[("IFC files", "*.ifc"), ("All files", "*.*")],
    )
    root.destroy()
    if not path:
        return {"panel": {"items": {"action-status": {"text": "Cancelled."}}}}

    # 2 — ask EPSG (IFC has no CRS)
    epsg = params.get("epsg")
    if not epsg:
        chosen = _ask_combobox(
            "IFC Import — EPSG",
            "IFC has no embedded CRS. Select the coordinate system:",
            _epsg_choices(),
            initial=_last_epsg or "EPSG:32643",
        )
        if not chosen:
            return {"panel": {"items": {"action-status": {"text": "Cancelled."}}}}
        epsg = chosen.split("—")[0].strip().replace("EPSG:", "").strip() if "—" in chosen else chosen.strip()
    _last_epsg = str(epsg).strip()

    _notify(f"Processing IFC: {os.path.basename(path)} …")

    # 3 — extract footprints
    try:
        features, total_elements, bad = _extract_ifc_footprints(path)
    except Exception as exc:
        _notify(f"IFC extraction failed: {exc}", error=True)
        return {"panel": {"items": {"action-status": {"text": f"Error: {exc}"}}}}

    if not features:
        _notify("No geometry found in IFC file.", error=True)
        return {"panel": {"items": {"action-status": {"text": "No geometry found."}}}}

    # 4 — save GPKG
    stem = os.path.splitext(os.path.basename(path))[0]
    gpkg_path = _save_dialog(
        "Save as GeoPackage",
        stem + "_buildings",
        [("GeoPackage", "*.gpkg"), ("All files", "*.*")],
    )
    if not gpkg_path:
        return {"panel": {"items": {"action-status": {"text": "Cancelled."}}}}
    if not gpkg_path.lower().endswith(".gpkg"):
        gpkg_path += ".gpkg"

    written, _ = _write_to_file(features, gpkg_path, layer_name="buildings_lod1")

    # 5 — load into RustGIS
    layer_name = os.path.splitext(os.path.basename(gpkg_path))[0]
    epsg_str = f"EPSG:{epsg}" if not str(epsg).upper().startswith("EPSG:") else str(epsg)
    geojson_fc = {"type": "FeatureCollection", "features": features}
    _call("host.addLayer", {"name": layer_name, "geojson": geojson_fc})
    try:
        _call("layer.defineProjection", {"layer": layer_name, "crs": epsg_str})
    except Exception:
        pass

    msg = f"Loaded {written} buildings ({total_elements} IFC elements) → {layer_name}"
    _notify(msg)
    return {"panel": {"items": {"action-status": {"text": msg}}}}


def handle_debug_select(req):
    """Try every plausible selection API and report which ones work."""
    layers = _call("host.layers", {}) or []
    active = next((l for l in layers if not l.get("raster") and l.get("active")), None)
    if not active:
        _notify("No active layer.", error=True)
        return {"panel": {"items": {"nav-status": {"text": "No active layer."}}}}

    name = active["name"]
    raw = _call("host.features", {"layer": name}) or {}
    feats = raw.get("features", []) if isinstance(raw, dict) else []
    if not feats:
        _notify("No features.", error=True)
        return {"panel": {"items": {"nav-status": {"text": "No features."}}}}

    feat = feats[0]
    feat_id = feat.get("id")

    candidates = [
        ("layer.selectFeatures",   {"layer": name, "indices": [0]}),
        ("layer.selectFeatures",   {"layer": name, "features": [0]}),
        ("layer.selectFeatures",   {"layer": name, "ids": [1]}),
        ("layer.selectFeatures",   {"layer": name, "index": 0}),
        ("layer.selectFeature",    {"layer": name, "index": 0}),
        ("layer.selectFeature",    {"layer": name, "id": feat_id if feat_id is not None else 1}),
        ("layer.select",           {"layer": name, "index": 0}),
        ("layer.select",           {"layer": name, "indices": [0]}),
        ("layer.select",           {"layer": name, "feature": 0}),
        ("layer.setSelection",     {"layer": name, "indices": [0]}),
        ("layer.setSelection",     {"layer": name, "ids": [1]}),
        ("layer.highlightFeature", {"layer": name, "index": 0}),
        ("feature.select",         {"layer": name, "index": 0}),
        ("map.selectFeature",      {"layer": name, "index": 0}),
        ("host.selectFeature",     {"layer": name, "index": 0}),
    ]

    results = []
    for call_name, params in candidates:
        try:
            _call(call_name, params)
            results.append(f"OK: {call_name} {list(params.keys())}")
        except Exception as e:
            results.append(f"ERR: {call_name} → {e}")

    report = "\n".join(results)
    desktop = os.path.join(os.path.expanduser("~"), "Desktop")
    out_path = os.path.join(desktop, "gis_debug_select.txt")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(report + "\n")
    _notify(f"Debug results saved to: {out_path}")
    return {"panel": {"items": {"nav-status": {"text": f"Saved: {out_path}"}}}}


# ---------------------------------------------------------------------------
# Buffer Points by Area
# ---------------------------------------------------------------------------

_AREA_UNITS = {
    "sq km":    1_000_000.0,
    "sq m":     1.0,
    "hectares": 10_000.0,
    "acres":    4_046.856,
}


def _make_point_buffer(lon, lat, radius_m, is_geographic, n=72):
    """Return a Polygon circle. Handles geographic (degrees) and projected (metres) CRS."""
    import math
    from shapely.geometry import Polygon
    if is_geographic:
        lat_r = math.radians(lat)
        cos_lat = math.cos(lat_r)
        deg_lat = 1.0 / 111_320.0
        deg_lon = 1.0 / (111_320.0 * cos_lat) if cos_lat > 1e-9 else deg_lat
        pts = []
        for i in range(n):
            a = 2 * math.pi * i / n
            pts.append((lon + radius_m * math.sin(a) * deg_lon,
                        lat + radius_m * math.cos(a) * deg_lat))
        pts.append(pts[0])
        return Polygon(pts)
    else:
        from shapely.geometry import Point
        return Point(lon, lat).buffer(radius_m, resolution=n // 4)


def _coords_are_geographic(features):
    """Heuristic: if the first point's x is in [-180,180] and y in [-90,90] → geographic."""
    for f in features[:5]:
        geom = f.get("geometry") or {}
        coords = geom.get("coordinates")
        if not coords:
            continue
        # Point: [x, y]
        if isinstance(coords[0], (int, float)):
            x, y = coords[0], coords[1]
        else:
            x, y = coords[0][0], coords[0][1]
        return -180 <= x <= 180 and -90 <= y <= 90
    return True  # default assume geographic


def _ask_buffer_dialog(layer_names, default_layer, numeric_cols, feature_names=None):
    """Show Buffer Points dialog. Returns dict or None if cancelled.

    feature_names: list of display names for each feature (for per-feature table).
    """
    import tkinter as tk
    from tkinter import ttk, messagebox

    result = {"ok": False}
    feature_names = feature_names or []

    root = tk.Tk()
    root.title("Buffer Points by Area")
    root.resizable(True, False)
    root.attributes("-topmost", True)

    tk.Label(root, text="Buffer Points by Area", font=("Segoe UI", 11, "bold")).pack(padx=16, pady=(14, 2))
    tk.Label(root, text="Creates a circular polygon buffer sized to a target area.",
             font=("Segoe UI", 9), fg="#555").pack(padx=16, pady=(0, 10))

    # Layer
    f0 = tk.Frame(root); f0.pack(padx=16, pady=3, fill="x")
    tk.Label(f0, text="Point layer:", width=18, anchor="w", font=("Segoe UI", 9)).pack(side="left")
    layer_var = tk.StringVar(value=default_layer or (layer_names[0] if layer_names else ""))
    ttk.Combobox(f0, textvariable=layer_var, values=layer_names, state="readonly",
                 width=30, font=("Segoe UI", 9)).pack(side="left")

    # Mode radio
    mode_var = tk.StringVar(value="per_feature" if feature_names else "fixed")
    tk.Label(root, text="Buffer size:", font=("Segoe UI", 9, "bold"), anchor="w").pack(
        padx=16, pady=(10, 2), fill="x")

    # Fixed area row
    f1 = tk.Frame(root); f1.pack(padx=28, pady=2, fill="x")
    tk.Radiobutton(f1, text="Fixed area for all points:", variable=mode_var, value="fixed",
                   font=("Segoe UI", 9)).pack(side="left")
    fixed_var = tk.StringVar(value="4")
    tk.Entry(f1, textvariable=fixed_var, width=8, font=("Segoe UI", 9)).pack(side="left", padx=(4, 4))
    fixed_unit_var = tk.StringVar(value="sq km")
    ttk.Combobox(f1, textvariable=fixed_unit_var, values=list(_AREA_UNITS.keys()),
                 state="readonly", width=10, font=("Segoe UI", 9)).pack(side="left")

    # Column row
    f2 = tk.Frame(root); f2.pack(padx=28, pady=2, fill="x")
    tk.Radiobutton(f2, text="From attribute column:", variable=mode_var, value="column",
                   font=("Segoe UI", 9)).pack(side="left")
    col_var = tk.StringVar(value=numeric_cols[0] if numeric_cols else "")
    ttk.Combobox(f2, textvariable=col_var, values=numeric_cols, state="readonly",
                 width=20, font=("Segoe UI", 9)).pack(side="left", padx=(4, 4))
    col_unit_var = tk.StringVar(value="sq m")
    ttk.Combobox(f2, textvariable=col_unit_var, values=list(_AREA_UNITS.keys()),
                 state="readonly", width=10, font=("Segoe UI", 9)).pack(side="left")

    # Per-feature table row
    f_pf_radio = tk.Frame(root); f_pf_radio.pack(padx=28, pady=(2, 0), fill="x")
    pf_unit_var = tk.StringVar(value="sq km")
    tk.Radiobutton(f_pf_radio, text="Enter per-feature areas:", variable=mode_var,
                   value="per_feature", font=("Segoe UI", 9)).pack(side="left")
    ttk.Combobox(f_pf_radio, textvariable=pf_unit_var, values=list(_AREA_UNITS.keys()),
                 state="readonly", width=10, font=("Segoe UI", 9)).pack(side="left", padx=(4, 0))

    # Table of feature rows (name + editable area entry)
    f_table = tk.Frame(root, relief="sunken", bd=1)
    f_table.pack(padx=40, pady=(4, 0), fill="x")

    # Header
    hdr = tk.Frame(f_table, bg="#e0e0e0")
    hdr.pack(fill="x")
    tk.Label(hdr, text="Feature", width=24, anchor="w", font=("Segoe UI", 8, "bold"),
             bg="#e0e0e0").pack(side="left", padx=(4, 0))
    tk.Label(hdr, text="Area", width=10, anchor="w", font=("Segoe UI", 8, "bold"),
             bg="#e0e0e0").pack(side="left")

    pf_entries = []  # list of StringVar, one per feature
    for name in feature_names:
        row = tk.Frame(f_table)
        row.pack(fill="x")
        tk.Label(row, text=str(name)[:30], width=24, anchor="w",
                 font=("Segoe UI", 9)).pack(side="left", padx=(4, 0))
        var = tk.StringVar(value="")
        tk.Entry(row, textvariable=var, width=10, font=("Segoe UI", 9)).pack(side="left", padx=(0, 4))
        pf_entries.append(var)

    if not feature_names:
        tk.Label(f_table, text="(load a layer first)", font=("Segoe UI", 8), fg="#888").pack(pady=2)

    # Output name
    f3 = tk.Frame(root); f3.pack(padx=16, pady=(10, 4), fill="x")
    tk.Label(f3, text="Output layer name:", width=18, anchor="w", font=("Segoe UI", 9)).pack(side="left")
    out_var = tk.StringVar(value=(default_layer + "_buffer") if default_layer else "buffer")
    tk.Entry(f3, textvariable=out_var, width=30, font=("Segoe UI", 9)).pack(side="left")

    # Buttons
    fb = tk.Frame(root); fb.pack(padx=16, pady=12, fill="x")

    def on_ok():
        mode = mode_var.get()
        try:
            if mode == "fixed":
                float(fixed_var.get())
            elif mode == "column":
                if not col_var.get():
                    messagebox.showerror("No column", "Select an attribute column.", parent=root)
                    return
            elif mode == "per_feature":
                if not pf_entries:
                    messagebox.showerror("No features", "No features to edit.", parent=root)
                    return
                for i, var in enumerate(pf_entries):
                    v = var.get().strip()
                    if not v:
                        messagebox.showerror(
                            "Missing value",
                            f"Enter an area value for '{feature_names[i]}'.",
                            parent=root,
                        )
                        return
                    try:
                        float(v)
                    except ValueError:
                        messagebox.showerror(
                            "Invalid value",
                            f"'{v}' is not a number for '{feature_names[i]}'.",
                            parent=root,
                        )
                        return
        except ValueError:
            messagebox.showerror("Invalid", "Enter a valid number for area.", parent=root)
            return

        result.update({
            "ok": True,
            "layer": layer_var.get(),
            "mode": mode,
            "fixed_area": fixed_var.get(),
            "fixed_unit": fixed_unit_var.get(),
            "col": col_var.get(),
            "col_unit": col_unit_var.get(),
            "pf_areas": [v.get().strip() for v in pf_entries],
            "pf_unit": pf_unit_var.get(),
            "out_name": out_var.get().strip() or "buffer",
        })
        root.destroy()

    def on_cancel():
        root.destroy()

    tk.Button(fb, text="OK", width=10, font=("Segoe UI", 9),
              command=on_ok, default="active").pack(side="right", padx=(4, 0))
    tk.Button(fb, text="Cancel", width=10, font=("Segoe UI", 9),
              command=on_cancel).pack(side="right")

    root.bind("<Return>", lambda e: on_ok())
    root.bind("<Escape>", lambda e: on_cancel())
    root.update_idletasks()
    w, h = root.winfo_reqwidth(), root.winfo_reqheight()
    sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
    root.geometry(f"{w}x{h}+{(sw-w)//2}+{(sh-h)//2}")
    root.mainloop()

    return result if result["ok"] else None


def handle_buffer_points(req):
    import math
    from shapely.geometry import mapping as shapely_mapping

    # 1 — get available point layers
    layers_info = _call("host.layers", {}) or []
    point_layers = [l["name"] for l in layers_info if not l.get("raster")]
    if not point_layers:
        _notify("No vector layers loaded.", error=True)
        return {"panel": {"items": {"action-status": {"text": "No layers loaded."}}}}

    # Detect active layer for default
    active = next((l["name"] for l in layers_info if not l.get("raster") and l.get("active")), point_layers[0])

    # Fetch features of active layer to discover numeric columns and feature names
    raw = _call("host.features", {"layer": active}) or {}
    sample_features = raw.get("features", []) if isinstance(raw, dict) else []
    numeric_cols = []
    feature_names = []
    if sample_features:
        props0 = sample_features[0].get("properties") or {}
        for k, v in props0.items():
            try:
                float(str(v).replace(",", "").strip())
                numeric_cols.append(k)
            except (ValueError, TypeError):
                pass
        # Build display names: prefer "name" / "label" / "id" column, else "Point N"
        name_key = next((k for k in props0 if k.lower() in ("name", "label", "id", "site")), None)
        for i, f in enumerate(sample_features, 1):
            p = f.get("properties") or {}
            feature_names.append(str(p.get(name_key, f"Point {i}")) if name_key else f"Point {i}")

    # 2 — show dialog
    cfg = _ask_buffer_dialog(point_layers, active, numeric_cols, feature_names)
    if cfg is None:
        return {"panel": {"items": {"action-status": {"text": "Cancelled."}}}}

    layer_name = cfg["layer"]

    # 3 — fetch all features of chosen layer (re-fetch if layer changed)
    if layer_name != active:
        raw = _call("host.features", {"layer": layer_name}) or {}
    features_in = raw.get("features", []) if isinstance(raw, dict) else []
    if not features_in:
        _notify("Layer has no features.", error=True)
        return {"panel": {"items": {"action-status": {"text": "No features."}}}}

    is_geo = _coords_are_geographic(features_in)

    # unit factor depends on mode
    if cfg["mode"] == "fixed":
        unit_factor = _AREA_UNITS.get(cfg["fixed_unit"], 1.0)
    elif cfg["mode"] == "column":
        unit_factor = _AREA_UNITS.get(cfg["col_unit"], 1.0)
    else:  # per_feature
        unit_factor = _AREA_UNITS.get(cfg["pf_unit"], 1.0)

    # 4 — build buffer polygons
    out_features = []
    skipped = 0
    for idx, feat in enumerate(features_in):
        geom = feat.get("geometry") or {}
        props = dict(feat.get("properties") or {})
        coords = geom.get("coordinates")
        if not coords:
            skipped += 1; continue

        gtype = geom.get("type", "")
        if gtype == "Point":
            lon, lat = coords[0], coords[1]
        elif gtype == "MultiPoint":
            lon, lat = coords[0][0], coords[0][1]
        else:
            skipped += 1; continue

        # Determine area in m²
        if cfg["mode"] == "fixed":
            try:
                area_m2 = float(cfg["fixed_area"]) * unit_factor
            except ValueError:
                skipped += 1; continue
        elif cfg["mode"] == "column":
            raw_val = props.get(cfg["col"], None)
            try:
                area_m2 = float(str(raw_val).replace(",", "").strip()) * unit_factor
            except (ValueError, TypeError):
                skipped += 1; continue
        else:  # per_feature
            pf_areas = cfg.get("pf_areas", [])
            if idx >= len(pf_areas):
                skipped += 1; continue
            try:
                area_m2 = float(pf_areas[idx]) * unit_factor
            except (ValueError, TypeError):
                skipped += 1; continue

        radius_m = math.sqrt(area_m2 / math.pi)

        try:
            circle = _make_point_buffer(lon, lat, radius_m, is_geo)
            circle_geom = shapely_mapping(circle)
        except Exception as e:
            _log(f"Buffer error for feature: {e}")
            skipped += 1; continue

        props["buffer_area_m2"] = round(area_m2, 3)
        props["buffer_area_sqkm"] = round(area_m2 / 1_000_000, 6)
        props["buffer_radius_m"] = round(radius_m, 3)
        out_features.append({"type": "Feature", "geometry": circle_geom, "properties": props})

    if not out_features:
        _notify("No point features could be buffered.", error=True)
        return {"panel": {"items": {"action-status": {"text": "No bufferable points."}}}}

    # 5 — save GPKG
    out_name = cfg["out_name"]
    gpkg_path = _save_dialog(
        "Save buffer layer as GeoPackage",
        out_name,
        [("GeoPackage", "*.gpkg"), ("All files", "*.*")],
    )
    if not gpkg_path:
        return {"panel": {"items": {"action-status": {"text": "Cancelled."}}}}
    if not gpkg_path.lower().endswith(".gpkg"):
        gpkg_path += ".gpkg"

    written, _ = _write_to_file(out_features, gpkg_path, layer_name=out_name)

    # 6 — load into RustGIS (keep same CRS as input)
    geojson_fc = {"type": "FeatureCollection", "features": out_features}
    _call("host.addLayer", {"name": out_name, "geojson": geojson_fc})

    # Try to copy CRS from source layer
    try:
        src_crs = _call("layer.crs", {"layer": layer_name})
        if src_crs:
            _call("layer.defineProjection", {"layer": out_name, "crs": src_crs})
    except Exception:
        pass

    skip_msg = f" ({skipped} skipped)" if skipped else ""
    msg = f"Buffered {written} points → {out_name}{skip_msg}"
    _notify(msg)
    return {"panel": {"items": {"action-status": {"text": msg}}}}


# ---------------------------------------------------------------------------
# Add Points
# ---------------------------------------------------------------------------

def _ask_add_points_dialog():
    """Show a dialog: choose Manual entry OR CSV file.
    Returns (mode, data) where:
      mode="manual"  → data = list of raw text lines from the text box
      mode="csv"     → data = (path:str, rows:list[dict])
      mode=None      → cancelled
    """
    import tkinter as tk
    from tkinter import ttk, filedialog, messagebox

    result = {"mode": None, "lines": [], "csv_path": "", "csv_rows": []}

    root = tk.Tk()
    root.title("Add Points")
    root.resizable(False, False)
    root.attributes("-topmost", True)

    # --- header ---
    tk.Label(root, text="Add Points", font=("Segoe UI", 11, "bold")).pack(padx=16, pady=(14, 2))
    tk.Label(
        root,
        text="Paste lat/lon pairs  OR  load a CSV file.\n"
             "Manual format (one per line):  name, lat, lon  or  lat, lon",
        font=("Segoe UI", 9), justify="left", fg="#444",
    ).pack(padx=16, pady=(0, 8), anchor="w")

    # --- text area ---
    frame_txt = tk.LabelFrame(root, text="Manual entry", font=("Segoe UI", 9))
    frame_txt.pack(padx=16, fill="x")
    txt = tk.Text(frame_txt, width=52, height=10, font=("Consolas", 9))
    txt.pack(padx=6, pady=6)
    txt.insert("1.0", "# name, latitude, longitude\n# e.g.:\nSample 1, 12.84708054, 77.67642019\nSample 2, 12.84990186, 77.66265996\n")

    # --- csv row ---
    frame_csv = tk.Frame(root)
    frame_csv.pack(padx=16, pady=(8, 0), fill="x")
    csv_var = tk.StringVar(value="")
    tk.Label(frame_csv, text="CSV file:", font=("Segoe UI", 9)).pack(side="left")
    csv_entry = tk.Entry(frame_csv, textvariable=csv_var, width=36, state="readonly",
                         font=("Segoe UI", 9), readonlybackground="#f0f0f0")
    csv_entry.pack(side="left", padx=(4, 4))

    def browse_csv():
        p = filedialog.askopenfilename(
            title="Select CSV file",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
            parent=root,
        )
        if p:
            csv_var.set(p)

    tk.Button(frame_csv, text="Browse…", font=("Segoe UI", 9), command=browse_csv).pack(side="left")

    # --- buttons ---
    frame_btn = tk.Frame(root)
    frame_btn.pack(padx=16, pady=12, fill="x")

    def on_ok():
        csv_path = csv_var.get().strip()
        if csv_path:
            # CSV mode: parse and return rows
            import csv as _csv
            try:
                with open(csv_path, newline="", encoding="utf-8-sig") as fh:
                    reader = _csv.DictReader(fh)
                    rows = [dict(r) for r in reader]
                if not rows:
                    messagebox.showerror("Empty CSV", "The CSV file has no data rows.", parent=root)
                    return
            except Exception as e:
                messagebox.showerror("CSV Error", str(e), parent=root)
                return
            result["mode"] = "csv"
            result["csv_path"] = csv_path
            result["csv_rows"] = rows
        else:
            # Manual mode
            raw_lines = [l for l in txt.get("1.0", "end").splitlines()
                         if l.strip() and not l.strip().startswith("#")]
            if not raw_lines:
                messagebox.showerror("No data", "Enter at least one coordinate line.", parent=root)
                return
            result["mode"] = "manual"
            result["lines"] = raw_lines
        root.destroy()

    def on_cancel():
        root.destroy()

    tk.Button(frame_btn, text="OK", width=10, font=("Segoe UI", 9),
              command=on_ok, default="active").pack(side="right", padx=(4, 0))
    tk.Button(frame_btn, text="Cancel", width=10, font=("Segoe UI", 9),
              command=on_cancel).pack(side="right")

    root.bind("<Return>", lambda e: on_ok())
    root.bind("<Escape>", lambda e: on_cancel())
    root.update_idletasks()
    w, h = root.winfo_reqwidth(), root.winfo_reqheight()
    sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
    root.geometry(f"{w}x{h}+{(sw-w)//2}+{(sh-h)//2}")
    root.mainloop()

    return result["mode"], result


def _detect_latlon_cols(headers):
    """Return (lat_col, lon_col) from a list of CSV header names, or (None, None)."""
    lat_keys = {"lat", "latitude", "y", "northing", "ylat"}
    lon_keys = {"lon", "lng", "longitude", "x", "easting", "xlon", "xlong"}
    lat_col = next((h for h in headers if h.strip().lower() in lat_keys), None)
    lon_col = next((h for h in headers if h.strip().lower() in lon_keys), None)
    return lat_col, lon_col


def _ask_col_picker(headers, title="Select columns"):
    """Show two comboboxes to let user pick lat/lon column names. Returns (lat_col, lon_col) or (None,None)."""
    import tkinter as tk
    from tkinter import ttk
    picked = {"lat": None, "lon": None}

    root = tk.Tk()
    root.title(title)
    root.attributes("-topmost", True)
    root.resizable(False, False)

    tk.Label(root, text="Could not auto-detect lat/lon columns.\nPlease select them:",
             font=("Segoe UI", 9), justify="left").pack(padx=16, pady=(12, 6), anchor="w")

    for label, key in [("Latitude column:", "lat"), ("Longitude column:", "lon")]:
        f = tk.Frame(root)
        f.pack(padx=16, pady=3, fill="x")
        tk.Label(f, text=label, width=20, anchor="w", font=("Segoe UI", 9)).pack(side="left")
        cb = ttk.Combobox(f, values=headers, state="readonly", width=24, font=("Segoe UI", 9))
        cb.pack(side="left")
        if key == "lat":
            lat_cb = cb
        else:
            lon_cb = cb

    frame_btn = tk.Frame(root)
    frame_btn.pack(padx=16, pady=10, fill="x")

    def on_ok():
        picked["lat"] = lat_cb.get() or None
        picked["lon"] = lon_cb.get() or None
        root.destroy()

    def on_cancel():
        root.destroy()

    tk.Button(frame_btn, text="OK", width=10, font=("Segoe UI", 9),
              command=on_ok, default="active").pack(side="right", padx=(4, 0))
    tk.Button(frame_btn, text="Cancel", width=10, font=("Segoe UI", 9),
              command=on_cancel).pack(side="right")

    root.bind("<Return>", lambda e: on_ok())
    root.bind("<Escape>", lambda e: on_cancel())
    root.update_idletasks()
    w, h = root.winfo_reqwidth(), root.winfo_reqheight()
    sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
    root.geometry(f"{w}x{h}+{(sw-w)//2}+{(sh-h)//2}")
    root.mainloop()

    return picked["lat"], picked["lon"]


def handle_add_points(req):
    global _last_epsg
    params = req.get("params") or {}

    # 1 — dialog: manual or CSV
    mode, data = _ask_add_points_dialog()
    if mode is None:
        return {"panel": {"items": {"action-status": {"text": "Cancelled."}}}}

    # 2 — build raw (name, lat, lon, extra_props) list
    raw_points = []  # list of {"name":str, "lat":float, "lon":float, **extra}

    if mode == "manual":
        for i, line in enumerate(data["lines"], 1):
            parts = [p.strip() for p in line.split(",")]
            try:
                if len(parts) >= 3:
                    name = parts[0]
                    lat, lon = float(parts[1]), float(parts[2])
                elif len(parts) == 2:
                    name = f"Point {i}"
                    lat, lon = float(parts[0]), float(parts[1])
                else:
                    _log(f"Skipping line (too few fields): {line}")
                    continue
            except ValueError:
                # first token might be non-numeric but rest fail too
                _log(f"Skipping unparseable line: {line}")
                continue
            raw_points.append({"name": name, "lat": lat, "lon": lon})

    else:  # csv
        rows = data["csv_rows"]
        headers = list(rows[0].keys()) if rows else []
        lat_col, lon_col = _detect_latlon_cols(headers)
        if not lat_col or not lon_col:
            lat_col, lon_col = _ask_col_picker(headers, "CSV Column Mapping")
        if not lat_col or not lon_col:
            return {"panel": {"items": {"action-status": {"text": "Cancelled."}}}}

        # name column heuristic
        name_keys = {"name", "label", "id", "site", "point", "description", "desc"}
        name_col = next((h for h in headers
                         if h.strip().lower() in name_keys and h not in (lat_col, lon_col)), None)

        for i, row in enumerate(rows, 1):
            try:
                lat = float(row[lat_col])
                lon = float(row[lon_col])
            except (ValueError, KeyError):
                _log(f"Skipping CSV row {i}: bad lat/lon")
                continue
            name = row.get(name_col, f"Point {i}") if name_col else f"Point {i}"
            extra = {k: v for k, v in row.items() if k not in (lat_col, lon_col)}
            raw_points.append({"name": name, "lat": lat, "lon": lon, **extra})

    if not raw_points:
        _notify("No valid coordinate rows found.", error=True)
        return {"panel": {"items": {"action-status": {"text": "No valid points."}}}}

    # 3 — EPSG for the input coordinates (default WGS84)
    epsg = params.get("epsg")
    if not epsg:
        chosen = _ask_combobox(
            "Add Points — Input CRS",
            "Select the coordinate system of the input coordinates:",
            _epsg_choices(),
            initial=_last_epsg or "EPSG:4326 — WGS 84",
        )
        if not chosen:
            return {"panel": {"items": {"action-status": {"text": "Cancelled."}}}}
        epsg = chosen.split("—")[0].strip().replace("EPSG:", "").strip() if "—" in chosen else chosen.strip()
    _last_epsg = str(epsg).strip()
    epsg_str = f"EPSG:{epsg}" if not str(epsg).upper().startswith("EPSG:") else str(epsg)

    # 4 — build GeoJSON features (lon=X, lat=Y for WGS84 and most projected)
    features = []
    for i, pt in enumerate(raw_points, 1):
        props = {k: v for k, v in pt.items() if k not in ("lat", "lon")}
        props["point_id"] = i
        props.setdefault("name", f"Point {i}")
        # lon, lat order for GeoJSON
        geom = {"type": "Point", "coordinates": [pt["lon"], pt["lat"]]}
        features.append({"type": "Feature", "geometry": geom, "properties": props})

    # 5 — save GPKG
    default_name = (os.path.splitext(os.path.basename(data.get("csv_path", "")))[0]
                    if mode == "csv" and data.get("csv_path") else "points")
    gpkg_path = _save_dialog(
        "Save points as GeoPackage",
        default_name,
        [("GeoPackage", "*.gpkg"), ("All files", "*.*")],
    )
    if not gpkg_path:
        return {"panel": {"items": {"action-status": {"text": "Cancelled."}}}}
    if not gpkg_path.lower().endswith(".gpkg"):
        gpkg_path += ".gpkg"

    written, _ = _write_to_file(features, gpkg_path)

    # 6 — load into RustGIS
    layer_name = os.path.splitext(os.path.basename(gpkg_path))[0]
    geojson_fc = {"type": "FeatureCollection", "features": features}
    _call("host.addLayer", {"name": layer_name, "geojson": geojson_fc})
    try:
        _call("layer.defineProjection", {"layer": layer_name, "crs": epsg_str})
    except Exception:
        pass

    msg = f"Added {written} points → {layer_name}"
    _notify(msg)
    return {"panel": {"items": {"action-status": {"text": msg}}}}


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
HANDLERS = {
    "set-projection":    handle_set_projection,
    "merge-layers":      handle_merge_layers,
    "export-dxf":        handle_export_dxf,
    "load-basemap":      handle_load_basemap,
    "export-layer":      handle_export_layer,
    "save-original":     handle_save_original,
    "export-table":      handle_export_table,
    "check-containment": handle_check_containment,
    "fix-donuts":        handle_fix_donuts,
    "feature-next":      handle_feature_next,
    "feature-prev":      handle_feature_prev,
    "load-ifc":          handle_load_ifc,
    "buffer-points":     handle_buffer_points,
    "add-points":        handle_add_points,
    "debug-select":      handle_debug_select,
    "panel-state":       handle_panel_state,
}

for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    try:
        req = json.loads(line) or {}
        cmd_id = req.get("id", "")
        handler = HANDLERS.get(cmd_id)
        if handler is None:
            raise RuntimeError(f"Unknown command '{cmd_id}'")
        result = handler(req)
        print(json.dumps({"ok": result}), flush=True)
    except Exception as exc:
        print(json.dumps({"error": str(exc)}), flush=True)
