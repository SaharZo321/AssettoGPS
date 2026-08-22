# SRP map assets

- `srp.svg` is the exact, lightweight Simple Map. It is the default and has no
  turn-by-turn navigation capability.
- `srp-osm-roads.geojson` is a clipped offline OpenStreetMap motorway extract
  for the optional MapLibre Navigation Map. Ordered OSM ways preserve one-way
  carriageway direction for matching and future routing.
- `srp-osm-calibration.json` maps Assetto Corsa X/Z coordinates into the local
  OSM display. SRP is not a geographically exact copy of Tokyo, so the map
  matcher treats this as a locally corrected estimate and safely falls back to
  the Simple Map if WebGL or the offline assets are unavailable.

Regenerate the OSM assets with:

```powershell
uv run python scripts/build_srp_osm_data.py build/osm-srp-motorways.json
```

The source response is obtained using `scripts/srp_motorways.overpassql`.
