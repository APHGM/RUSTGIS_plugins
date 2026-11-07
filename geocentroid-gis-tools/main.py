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
    import xml.etree.ElementTree as ET

    def esc(s):
        return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")

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
        # Pick a display name
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

    with open(kml_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    return written


def _write_to_file(features, path):
    """
    Write GeoJSON features to path.
    Format detected from extension: .shp .gpkg .geojson .json .kml .kmz
    Returns (n_written, driver_name).
    """
    import zipfile

    ext = os.path.splitext(path)[1].lower()
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
