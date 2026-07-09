"""
src/aoi/boundary.py
Single authoritative source of the Larouco AOI for the whole platform.
Fallback chain: Nominatim -> Overpass (3 mirrors) -> cached local file -> hand bbox.
Always returns / caches geometry in EPSG:25829.
"""
from pathlib import Path
import geopandas as gpd
from src.config.settings import settings
from src.common.http import session_with_retries

CACHE_PATH = Path(settings.data_dir) / "reference" / "larouco_boundary_25829.gpkg"

def get_aoi(force_refresh: bool = False) -> gpd.GeoDataFrame:
    if CACHE_PATH.exists() and not force_refresh:
        return gpd.read_file(CACHE_PATH)

    sess = session_with_retries()
    gdf = None
    for source in (_from_nominatim, _from_overpass, _from_official_ign):
        try:
            gdf = source(sess)
            break
        except Exception as exc:
            log.warning("%s failed: %s", source.__name__, exc)

    if gdf is None:
        log.error("All live sources failed; falling back to cached/manual bbox.")
        gdf = _from_fallback_bbox()

    gdf = gdf.to_crs(settings.target_crs)          # EPSG:25829
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    gdf.to_file(CACHE_PATH, driver="GPKG")
    return gdf