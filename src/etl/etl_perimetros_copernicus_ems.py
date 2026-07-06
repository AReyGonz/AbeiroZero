import requests
import geopandas as gpd
from shapely.geometry import box, shape
import pandas as pd

def buscar_activaciones_ems_larouco():
    """
    Busca en el catálogo de Copernicus EMS Rapid Mapping qué activaciones
    (perímetros de alta resolución) intersectan con la zona de Larouco.
    """
    print("Iniciando escaneo del catálogo de Copernicus EMS Rapid Mapping...")
    
    # 1. Definimos nuestro Bounding Box (Larouco, Ourense)
    # Coordenadas WGS84 (EPSG:4326)
    minx, miny, maxx, maxy = -7.2212, 42.3168, -7.1354, 42.3685
    larouco_geom = box(minx, miny, maxx, maxy)
    
    # 2. Endpoint del catálogo público de Copernicus EMS
    # Este endpoint devuelve el listado maestro de activaciones y sus metadatos
    api_url = "https://rapidmapping.emergency.copernicus.eu/backend/dashboard-api/public-activations/"
    
    try:
        response = requests.get(api_url, timeout=15)
        response.raise_for_status()
        activaciones = response.json()
        
    except requests.exceptions.RequestException as e:
        print(f"❌ Error al conectar con la API de Copernicus: {e}")
        return

    hallazgos = []
    
    print(f"Catálogo descargado. Analizando {len(activaciones)} emergencias históricas...")

    # 3. Procesamiento y filtrado de la carga útil (Payload)
    for evento in activaciones:
        # Filtro Nivel 1: Atributos alfanuméricos (Solo Incendios en España para ahorrar CPU)
        tipo_evento = evento.get("event_type", {}).get("slug", "").lower()
        paises = [p.get("short_name", "").lower() for p in evento.get("countries", [])]
        
        if "wildfire" not in tipo_evento or "spain" not in paises:
            continue
            
        # Filtro Nivel 2: Análisis Espacial Topológico
        # Extraemos la geometría del Área de Interés (AOI) de la activación
        aoi_geojson = evento.get("aoi_geometry")
        
        if aoi_geojson:
            try:
                # Convertimos el GeoJSON del servidor a un objeto geométrico de Shapely
                geom_evento = shape(aoi_geojson)
                
                # Comprobamos si el polígono de la emergencia intersecta con el BBOX de Larouco
                if geom_evento.intersects(larouco_geom):
                    codigo_ems = evento.get("activation_code")
                    titulo = evento.get("title")
                    fecha = evento.get("event_date")
                    
                    hallazgos.append({
                        "Código": codigo_ems,
                        "Fecha": fecha,
                        "Título": titulo,
                        "URL Descarga": f"https://rapidmapping.emergency.copernicus.eu/{codigo_ems}/download"
                    })
            except Exception as e:
                # Tolerancia a fallos: Ignoramos geometrías corruptas del servidor
                pass

    # 4. Presentación de resultados
    if not hallazgos:
        print("\n⚠ No se encontraron activaciones de EMS de alta resolución para Larouco.")
        print("Esto significa que la emergencia no fue lo suficientemente grave a nivel nacional como para pedir activación a Europa, o el perímetro principal no llegó a estas coordenadas.")
    else:
        print("\n✔ ¡BINGO! Se han encontrado las siguientes activaciones de alta precisión:\n")
        
        # Usamos Pandas para imprimir una tabla limpia en la consola
        df_resultados = pd.DataFrame(hallazgos)
        print(df_resultados.to_markdown(index=False))
        
        print("\nSiguiente paso: Visita las URLs para descargar los archivos .zip con los Shapefiles/GeoPackages vectoriales.")

if __name__ == "__main__":
    buscar_activaciones_ems_larouco()