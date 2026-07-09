import rasterio
import numpy as np
from loguru import logger
from config.settings import settings

def calculate_indices(b4_path, b8_path, b11_path, b12_path, output_dir):
    """Calculates NDVI, NDMI, and NBR. Applies CRS validation."""
    with rasterio.open(b8_path) as b8_src:
        if b8_src.crs.to_string() != settings.BASE_CRS:
            raise ValueError(f"CRS mismatch in Sentinel data. Expected {settings.BASE_CRS}")
        
        b8 = b8_src.read(1).astype(float)
        meta = b8_src.meta
        meta.update(dtype=rasterio.float32, compress='lzw')

    with rasterio.open(b4_path) as b4_src:
        b4 = b4_src.read(1).astype(float)
    with rasterio.open(b11_path) as b11_src:
        b11 = b11_src.read(1).astype(float)
    with rasterio.open(b12_path) as b12_src:
        b12 = b12_src.read(1).astype(float)

    # Safe division ignoring zeroes
    np.seterr(divide='ignore', invalid='ignore')
    
    # Calculate Indices
    ndvi = np.where((b8 + b4) == 0, 0, (b8 - b4) / (b8 + b4))
    ndmi = np.where((b8 + b11) == 0, 0, (b8 - b11) / (b8 + b11))
    nbr = np.where((b8 + b12) == 0, 0, (b8 - b12) / (b8 + b12))

    # Save outputs as Cloud-Optimized GeoTIFFs (COGs logic simplified here)
    for name, data in [("ndvi", ndvi), ("ndmi", ndmi), ("nbr", nbr)]:
        out_path = f"{output_dir}/{name}_latest.tif"
        with rasterio.open(out_path, 'w', **meta) as dst:
            dst.write(data.astype(rasterio.float32), 1)
        logger.info(f"Generated {name.upper()} at {out_path}")