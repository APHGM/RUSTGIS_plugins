# geocentroid-gis-tools

A RustGIS process plugin providing GIS utilities for survey and estimation workflows.

## Features

| Command | Description |
|---|---|
| **Set Projection** | Assign an EPSG CRS to all selected layers |
| **Load Basemap** | Add web tile basemap (Google, Bing, OSM, ESRI) |
| **Merge All Layers** | Combine all vector layers; adds `source_layer` attribute |
| **Export DXF** | Export to DXF with coordinate reprojection |
| **Export Layer** | Save active layer to GPKG / SHP / GeoJSON / KML / KMZ |
| **Save to Original File** | Overwrite source file retaining original format |
| **Export Table to CSV** | Export attribute table (Excel-compatible UTF-8 BOM) |
| **Check Containment** | Find polygons inside other polygons; compute net area |
| **Fix Donuts** | Cut inner polygons as holes; correct area measurement |
| **◀ Prev / Next Feature ▶** | Navigate features one by one with auto-zoom and table selection |

## Installation

Drop the `.rgplugin` file onto the RustGIS window (uninstall previous version first).

## Requirements

- RustGIS 1.x
- Python 3.12 (managed by RustGIS)
- `ezdxf>=1.3`, `pyproj>=3.6`, `shapely>=2.0`, `fiona>=1.9`

## Author

Arun Prashad — [geocentroid.ai](https://geocentroid.ai)
