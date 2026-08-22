# SRP map assets

- `srp-traffic-lanes.geojson` is the offline MapLibre Navigation Map. Its 593
  directed lanes retain Assetto Corsa elevation and use a linear private map
  projection. Telemetry uses that same projection directly, without external
  geographic calibration, road snapping, or map warping. CSP Traffic Planner
  intersection polygons are converted into directed lane transitions for local
  landmark routing. The coordinate convention is explicit: game +X is
  east/right and game +Z is south/down, so latitude increases along game -Z.

Regenerate the private traffic-lane prototype from a locally obtained CSP
Traffic Planner file with:

```powershell
uv run python scripts/build_srp_traffic_data.py path\to\traffic.json frontend\assets\maps\srp-traffic-lanes.geojson --development-route-output backend\dev_assets\srp-development-route.json
```

The current prototype was generated from Bardaff's SRP Traffic Plan 1.02. The
author permits personal modification on the resource page, but public
redistribution permission has not been established. Keep this prototype build
private until that permission is confirmed or the geometry is replaced by an
independently authored lane graph.

The optional development route is stored outside `frontend/`. It is used only
by `backend/dev_server.py` and is not included in public release packages.
