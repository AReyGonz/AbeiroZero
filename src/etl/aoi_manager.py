import os
import osmnx as ox
import geopandas as gpd
from loguru import logger
from config.settings import settings

def generate_master_aoi():
    """Retrieves Larouco boundary, reprojects to EPSG:25829, saves to GeoPackage."""
    os.makedirs(os.path.dirname(settings.AOI_PATH), exist_ok=True)
    
    try:
        logger.info(f"Fetching AOI for: {settings.AOI_NAME}")
        gdf = ox.geocode_to_gdf(settings.AOI_NAME)
        
        # Reproject to master CRS
        gdf = gdf.to_crs(settings.BASE_CRS)
        
        # Save to standardized format
        gdf.to_file(settings.AOI_PATH, driver="GPKG")
        logger.info(f"Master AOI saved to {settings.AOI_PATH} in {settings.BASE_CRS}")
        return gdf
    except Exception as e:
        logger.error(f"Failed to fetch AOI from OSM: {e}")
        # Implement fallback to local cached file here
        raise e

if __name__ == "__main__":
    generate_master_aoi()