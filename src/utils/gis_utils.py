import functools
import geopandas as gpd

def enforce_crs(target_epsg=25829):
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            result = func(*args, **kwargs)
            if isinstance(result, gpd.GeoDataFrame):
                if result.crs is None:
                    raise ValueError("GeoDataFrame has no CRS assigned.")
                if result.crs.to_epsg() != target_epsg:
                    return result.to_crs(epsg=target_epsg)
            return result
        return wrapper
    return decorator