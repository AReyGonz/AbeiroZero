import geopandas as gpd
from shapely.geometry import box
import os

def extraer_incendios_larouco(ruta_base_datos_effis):
    """
    Lee la base de datos cruda de EFFIS y extrae los perímetros de Larouco.
    """
    print(f"Cargando la base de datos de EFFIS desde: {ruta_base_datos_effis}...")
    print("Esto puede tardar unos segundos dependiendo del tamaño del archivo...")
    
    # 1. Cargar el dataset (puede ser .sqlite, .gpkg o .shp)
    gdf_effis = gpd.read_file(ruta_base_datos_effis)
    
    # 2. Definir el área de Larouco (Bounding Box en coordenadas WGS84 - EPSG:4326)
    # Formato box: minx, miny, maxx, maxy
    minx, miny, maxx, maxy = -7.2212, 42.3168, -7.1354, 42.3685
    bbox_larouco = box(minx, miny, maxx, maxy)
    
    # Creamos un GeoDataFrame temporal con nuestra zona de búsqueda
    gdf_bbox = gpd.GeoDataFrame({'geometry': [bbox_larouco]}, crs="EPSG:4326")
    
    # 3. Homologar sistemas de coordenadas (CRÍTICO)
    # Reproyectamos nuestro BBOX al CRS nativo de la base de datos de EFFIS 
    # para garantizar que la intersección geométrica sea perfecta.
    gdf_bbox = gdf_bbox.to_crs(gdf_effis.crs)
    
    print("Aplicando filtro espacial para aislar Ourense/Larouco...")
    
    # 4. Intersección espacial (Clip)
    # Cortamos la base de datos europea usando nuestro rectángulo de Larouco
    incendios_larouco = gpd.clip(gdf_effis, gdf_bbox)
    
    if incendios_larouco.empty:
        print("⚠ No se encontraron perímetros de incendio en Larouco en este archivo.")
        return
        
    print(f"✔ ¡Éxito! Se han aislado {len(incendios_larouco)} polígonos de incendio.")
    
    # 5. Exportar el resultado a un formato ligero y estándar
    archivo_salida = "perimetros_larouco_effis.geojson"
    # Convertimos de nuevo a Lat/Lon para que sea fácil de abrir en Google Earth, QGIS o web
    incendios_larouco.to_crs("EPSG:4326").to_file(archivo_salida, driver="GeoJSON")
    
    print(f"Resultado guardado correctamente en: {os.path.abspath(archivo_salida)}")

if __name__ == "__main__":
    # Sustituye esta ruta por la ruta donde hayas descargado el Shapefile o SpatiaLite de EFFIS
    # Ejemplo: ruta_archivo = "./ba_modis_2022.shp"
    ruta_archivo = "AQUI_RUTA_A_TU_ARCHIVO_DESCARGADO" 
    
    # Ejecutamos la función
    if ruta_archivo != "AQUI_RUTA_A_TU_ARCHIVO_DESCARGADO":
        extraer_incendios_larouco(ruta_archivo)
    else:
        print("Por favor, actualiza la ruta_archivo con el archivo descargado de Copernicus.")