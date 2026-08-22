# SRP map assets

- `srp-traffic-lanes.geojson` is the offline MapLibre Navigation Map. Its 593
  directed lanes retain Assetto Corsa elevation and use a linear private map
  projection. Telemetry uses that same projection, so there is no OSM warp,
  calibration, or marker snapping. CSP Traffic Planner intersection polygons
  are converted into directed lane transitions for local landmark routing. The
  coordinate convention is explicit: game +X is east/right and game +Z is
  south/down, so geographic latitude increases along game -Z.
- `srp-osm-roads.geojson` and `srp-osm-calibration.json` are retained as the
  earlier geographic experiment. They are not loaded by Game Navigation.

Regenerate the OSM assets with:

```powershell
uv run python scripts/build_srp_osm_data.py build/osm-srp-motorways.json
```

The source response is obtained using `scripts/srp_motorways.overpassql`.

Regenerate the private traffic-lane prototype from a locally obtained CSP
Traffic Planner file with:

```powershell
uv run python scripts/build_srp_traffic_data.py path\to\traffic.json frontend\assets\maps\srp-traffic-lanes.geojson
```

The current prototype was generated from Bardaff's SRP Traffic Plan 1.02. The
author permits personal modification on the resource page, but public
redistribution permission has not been established. Keep this prototype build
private until that permission is confirmed or the geometry is replaced by an
independently authored lane graph.
