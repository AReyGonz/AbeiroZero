import geopandas as gpd
import rasterio
import pytest
from pathlib import Path

TARGET_EPSG = 25829
VECTOR_OUTPUTS = Path("output/samples").glob("*.gpkg")
RASTER_OUTPUTS = Path("output/samples").glob("*.tif")

@pytest.mark.parametrize("path", list(VECTOR_OUTPUTS))
def test_vector_crs(path):
    gdf = gpd.read_file(path)
    assert gdf.crs is not None, f"{path} has no CRS defined"
    assert gdf.crs.to_epsg() == TARGET_EPSG, f"{path} is {gdf.crs}, expected EPSG:{TARGET_EPSG}"

@pytest.mark.parametrize("path", list(RASTER_OUTPUTS))
def test_raster_crs(path):
    with rasterio.open(path) as src:
        assert src.crs is not None, f"{path} has no CRS"
        assert src.crs.to_epsg() == TARGET_EPSG, f"{path} is {src.crs}, expected EPSG:{TARGET_EPSG}"