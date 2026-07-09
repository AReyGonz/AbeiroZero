# AbeiroZero 🌲🔥

A production-grade wildfire prediction, monitoring, and decision-support platform tailored for the municipality of Larouco (Galicia, Spain). 

## Purpose
AbeiroZero bridges the gap between raw geospatial data and actionable fire intelligence. By aggregating real-time weather, satellite imagery, and static fuel maps, the system calculates ignition risk, physical fire propagation paths, and human vulnerability indexes.

## Architecture
- **Data Engine:** Prefect orchestrating Python ETLs.
- **Geospatial Storage:** PostGIS (Vector) + GeoParquet/COGs (Raster).
- **Core Standard:** EPSG:25829 (ETRS89 / UTM Zone 29N).
- **API:** FastAPI powering the frontend and external integrations.

## Data Sources
* **MeteoGalicia:** 10-minute weather telemetry.
* **Sentinel-2 (AWS):** 5-day revisit vegetation vigor (NDVI) and moisture (NDMI).
* **Copernicus DEM (GLO-30):** Terrain analysis (Slope, Aspect).
* **MFE25:** Spanish Forest Map translated to Canadian FBP fuel models.
* **IGE:** Population and age groups.
* **OSM:** Roads and ways. Villages.
---
* **EFFIS & COP-EMS:** Historical data of fires.
---
* **NASA FIRMS & EUMETSAT MTG:** Discover & Monitor active fires. 
