#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
==============================================================================
 Descarga y procesado de la red viaria OSM del concello de Larouco
 (Ourense, Galicia, España) para gestión de emergencias / incendios
==============================================================================

OBJETIVO
--------
Obtener una red viaria topológicamente consistente y lista para análisis
(rutas de evacuación, accesibilidad, grafos de movilidad) a partir de
OpenStreetMap, mediante la API pública Overpass.

QUÉ HACE, PASO A PASO
----------------------
  1. Resuelve el municipio en Nominatim para obtener el ID de la relación
     administrativa de OSM (más fiable que filtrar por nombre directamente
     en Overpass) y, si está disponible, su polígono para la visualización.
  2. Construye una consulta Overpass que usa esa misma área administrativa
     (area(3600000000+relation_id)) para extraer todas las vías
     (highway=...) dentro del municipio, con reintentos sobre varios
     servidores espejo de Overpass.
  3. Si no se pudo resolver la relación, hace un fallback a una consulta
     por bounding box aproximado (indicado explícitamente).
  4. Parsea la respuesta a un GeoDataFrame con geometría LineString y los
     atributos OSM relevantes.
  5. Limpieza básica: elimina geometrías vacías/nulas, corrige geometrías
     inválidas, elimina duplicados.
  6. Reproyecta a ETRS89 / UTM 29N (EPSG:25829) y calcula longitud (m) e
     identificador único por segmento.
  7. Exporta a GeoPackage, GeoJSON y Shapefile (cada exportación con su
     propio manejo de errores, para que un fallo en un formato no impida
     generar los demás).
  8. Genera una visualización rápida (límite municipal + red clasificada
     por tipo de vía).
  9. Deja un punto de extensión (placeholder documentado, sin
     implementar) para construir un grafo de movilidad con NetworkX,
     pensado para rutas de evacuación, tiempos de acceso e integración
     con capas de riesgo de incendio / DEM.

------------------------------------------------------------------------------
INSTALACIÓN
------------------------------------------------------------------------------
    pip install requests geopandas shapely pandas matplotlib pyproj

Para exportar Shapefile, geopandas necesita 'pyogrio' o 'fiona' instalado
(suele venir como dependencia de geopandas; si falla la exportación a .shp,
instala explícitamente uno de los dos):
    pip install pyogrio

------------------------------------------------------------------------------
USO
------------------------------------------------------------------------------
    python larouco_roads.py
    python larouco_roads.py --salida ./resultado_viario --epsg EPSG:25829
    python larouco_roads.py --categorias motorway,primary,secondary,track

==============================================================================
"""

import argparse
import logging
import sys
import time
import uuid
from pathlib import Path

import geopandas as gpd
import matplotlib.pyplot as plt
import requests
from requests.adapters import HTTPAdapter

from shapely.geometry import (
    LineString,
    Point,
    box,
    shape
)
from shapely.validation import make_valid
from urllib3.util.retry import Retry

# ------------------------------------------------------------------------------
# CONFIGURACIÓN
# ------------------------------------------------------------------------------

NOMBRE_MUNICIPIO_DEFECTO = "Larouco, Ourense, Galicia, España"
EPSG_DESTINO_DEFECTO = "EPSG:25829"  # ETRS89 / UTM 29N, estándar en Galicia

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"

# Varios servidores espejo de Overpass: si uno falla o está saturado,
# se prueba con el siguiente (mejora la robustez frente a caídas puntuales
# del servicio, algo habitual en la instancia pública alemana).
OVERPASS_MIRRORS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.openstreetmap.fr/api/interpreter",
]

HEADERS_HTTP = {"User-Agent": "larouco-roads-script/1.0 (uso educativo/gestion-emergencias)"}

# Categorías de vía a incluir (valores de la etiqueta OSM "highway")
CATEGORIAS_VIAS_DEFECTO = [
    "motorway", "trunk", "primary", "secondary", "tertiary",
    "unclassified", "residential", "service", "track", "path",
]

# Atributos OSM que se conservan como columnas del GeoDataFrame
ATRIBUTOS_OSM = ["highway", "name", "surface", "tracktype", "maxspeed", "oneway", "access", "smoothness"]

# Bounding box de respaldo (lon_min, lat_min, lon_max, lat_max), WGS84,
# usado únicamente si Nominatim no logra resolver la relación del municipio.
# Es aproximado (centro ~42.346N, -7.164W; superficie ~23.7 km²).
BBOX_RESPALDO = (-7.24, 42.31, -7.09, 42.40)

# Colores por tipo de vía para la visualización (jerarquía vial habitual)
COLORES_VIAS = {
    "motorway": "#7b0000",
    "trunk": "#a50000",
    "primary": "#d73027",
    "secondary": "#fc8d59",
    "tertiary": "#fee08b",
    "unclassified": "#999999",
    "residential": "#4575b4",
    "service": "#74add1",
    "track": "#1a9850",
    "path": "#66bd63",
}

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("larouco_roads")


# ------------------------------------------------------------------------------
# UTILIDADES DE RED
# ------------------------------------------------------------------------------

def crear_sesion_http(reintentos=3):
    """Sesión requests con reintentos automáticos (backoff) ante errores de
    red y códigos 5xx/429, para hacer las consultas más robustas."""
    sesion = requests.Session()
    retry = Retry(
        total=reintentos,
        backoff_factor=1.5,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET", "POST"],
    )
    adaptador = HTTPAdapter(max_retries=retry)
    sesion.mount("https://", adaptador)
    sesion.mount("http://", adaptador)
    sesion.headers.update(HEADERS_HTTP)
    return sesion


# ------------------------------------------------------------------------------
# PASO 1: RESOLUCIÓN DEL MUNICIPIO (NOMINATIM)
# ------------------------------------------------------------------------------

def obtener_relacion_municipio(sesion, nombre_municipio):
    """
    Consulta Nominatim para obtener:
      - el ID de la relación OSM del municipio (para construir luego una
        consulta Overpass exacta sobre esa misma área administrativa), y
      - su polígono (si Nominatim lo devuelve), útil para la visualización
        y como referencia del límite real del concello.

    Se prioriza el primer resultado de tipo 'relation' (los límites
    administrativos en OSM son relaciones, no nodos ni ways sueltos).
    """
    params = {"q": nombre_municipio, "format": "jsonv2", "polygon_geojson": 1, "limit": 5}
    r = sesion.get(NOMINATIM_URL, params=params, timeout=60)
    r.raise_for_status()
    resultados = r.json()

    if not resultados:
        raise RuntimeError("Nominatim no devolvió ningún resultado para el municipio.")

    candidato = next((res for res in resultados if res.get("osm_type") == "relation"), resultados[0])

    relation_id = candidato["osm_id"] if candidato.get("osm_type") == "relation" else None
    geom = shape(candidato["geojson"]) if candidato.get("geojson") else None

    if relation_id is None:
        logger.warning("Nominatim no devolvió una relación administrativa; se usará fallback por bbox.")

    return relation_id, geom


# ------------------------------------------------------------------------------
# PASO 2-3: CONSULTA A OVERPASS (ÁREA ADMINISTRATIVA O BBOX DE RESPALDO)
# ------------------------------------------------------------------------------

def construir_query_por_area(relation_id, categorias):
    """
    Construye la consulta Overpass QL usando el área de la relación
    administrativa exacta resuelta en Nominatim. El ID de área de Overpass
    para una relación es 3600000000 + relation_id (convención de Overpass).
    'out body geom;' devuelve, para cada way, sus coordenadas completas
    (lat/lon por nodo) sin necesidad de resolver nodos por separado.
    """
    overpass_area_id = 3600000000 + relation_id
    filtro_highway = "|".join(categorias)
    return f"""
    [out:json][timeout:180];
    area({overpass_area_id})->.searchArea;
    (
      way["highway"~"^({filtro_highway})$"](area.searchArea);
    );
    out body geom;
    """


def construir_query_por_bbox(bbox, categorias):
    """Consulta Overpass alternativa por bounding box (lon_min, lat_min,
    lon_max, lat_max), usada solo si no se pudo resolver la relación
    administrativa del municipio."""
    minx, miny, maxx, maxy = bbox
    filtro_highway = "|".join(categorias)
    return f"""
    [out:json][timeout:180];
    (
      way["highway"~"^({filtro_highway})$"]({miny},{minx},{maxy},{maxx});
    );
    out body geom;
    """
def construir_query_nucleos(relation_id):
    """
    Obtiene núcleos de población OSM.
    """

    area_id = 3600000000 + relation_id

    return f"""
    [out:json][timeout:120];

    area({area_id})->.searchArea;

    (
      node["place"~"^(city|town|village|hamlet|isolated_dwelling)$"](area.searchArea);
    );

    out body;
    """

def consultar_overpass(sesion, query):
    """
    Envía la consulta a Overpass probando varios servidores espejo en
    orden hasta que uno responda correctamente. Maneja tanto fallos de
    conexión como indisponibilidad temporal del servicio (errores 5xx,
    timeouts), que son habituales en la instancia pública de Overpass.
    """
    ultimo_error = None
    for url in OVERPASS_MIRRORS:
        try:
            logger.info(f"Consultando Overpass en {url} ...")
            r = sesion.post(url, data={"data": query}, timeout=200)
            r.raise_for_status()
            data = r.json()
            n = len(data.get("elements", []))
            logger.info(f"Respuesta recibida de {url}: {n} elementos.")
            if n == 0:
                logger.warning("La consulta no devolvió elementos; puede que la zona/categorías estén vacías.")
            return data
        except (requests.exceptions.RequestException, ValueError) as e:
            logger.warning(f"Fallo consultando {url}: {e}")
            ultimo_error = e
            time.sleep(2)

    raise RuntimeError(
        f"No se pudo consultar ningún servidor Overpass tras probar {len(OVERPASS_MIRRORS)} espejos. "
        f"Último error: {ultimo_error}"
    )


# ------------------------------------------------------------------------------
# PASO 4: PARSEO A GEODATAFRAME
# ------------------------------------------------------------------------------

def parsear_respuesta_overpass(data, atributos):
    """
    Convierte los elementos 'way' de la respuesta de Overpass (formato
    'out body geom') en registros con geometría LineString y los atributos
    OSM seleccionados. Se descartan elementos que no sean 'way', sin
    geometría, o con menos de 2 puntos (no forman una línea válida).
    """
    registros = []
    for el in data.get("elements", []):
        if el.get("type") != "way" or "geometry" not in el:
            continue

        coords = [(p["lon"], p["lat"]) for p in el["geometry"]]
        if len(coords) < 2:
            continue

        try:
            geometria = LineString(coords)
        except Exception:
            continue

        tags = el.get("tags", {})
        registro = {"osm_id": el["id"]}
        for atributo in atributos:
            registro[atributo] = tags.get(atributo)
        registro["geometry"] = geometria
        registros.append(registro)

    return registros

def parsear_nucleos_osm(data):
    """
    Convierte los nodos OSM etiquetados como núcleos
    de población en registros geográficos.
    """

    registros = []

    for el in data.get("elements", []):

        if el.get("type") != "node":
            continue

        tags = el.get("tags", {})

        nombre = tags.get("name")

        if not nombre:
            continue

        registros.append({
            "osm_id": el["id"],
            "Village_Name": nombre,
            "place": tags.get("place"),
            "geometry": Point(
                el["lon"],
                el["lat"]
            ),
        })

    return registros

def construir_geodataframe(registros):
    if not registros:
        raise RuntimeError(
            "No se obtuvo ninguna vía válida tras parsear la respuesta de Overpass. "
            "Revisa las categorías solicitadas o el área de búsqueda."
        )
    return gpd.GeoDataFrame(registros, geometry="geometry", crs="EPSG:4326")


# ------------------------------------------------------------------------------
# PASO 5: LIMPIEZA BÁSICA
# ------------------------------------------------------------------------------

def limpiar_datos(gdf):
    """
    Limpieza básica orientada a dejar la red lista para análisis:
      - Elimina geometrías nulas o vacías.
      - Corrige geometrías inválidas con shapely.validation.make_valid
        (puede convertir autointersecciones en MultiLineString; las
        geometrías que dejen de ser líneas tras la corrección se
        descartan, ya que no sirven para análisis de red).
      - Elimina duplicados exactos por osm_id (Overpass no debería
        devolver duplicados, pero se comprueba por seguridad si se
        combinaran varias consultas en el futuro).
    """
    n_inicial = len(gdf)

    gdf = gdf[gdf.geometry.notnull()]
    gdf = gdf[~gdf.geometry.is_empty]

    gdf["geometry"] = gdf.geometry.apply(lambda g: g if g.is_valid else make_valid(g))
    gdf = gdf[gdf.geometry.geom_type.isin(["LineString", "MultiLineString"])]

    gdf = gdf.drop_duplicates(subset="osm_id").reset_index(drop=True)

    logger.info(f"Limpieza de datos: {n_inicial} -> {len(gdf)} segmentos.")
    return gdf


# ------------------------------------------------------------------------------
# PASO 6: ATRIBUTOS DERIVADOS (REQUIERE CRS MÉTRICO)
# ------------------------------------------------------------------------------

def calcular_atributos_derivados(gdf_metrico):
    """
    Calcula, sobre un GeoDataFrame ya reproyectado a un CRS métrico
    (EPSG:25829): la longitud en metros de cada segmento, y un
    identificador único de segmento (independiente del osm_id, útil si
    en el futuro se fragmentan vías al construir el grafo de movilidad).
    """
    gdf_metrico = gdf_metrico.copy()
    gdf_metrico["length_m"] = gdf_metrico.geometry.length.round(2)
    gdf_metrico["id"] = [str(uuid.uuid4())[:8] for _ in range(len(gdf_metrico))]
    return gdf_metrico


# ------------------------------------------------------------------------------
# PASO 7: EXPORTACIÓN
# ------------------------------------------------------------------------------

def exportar(gdf, boundary_gdf, carpeta_salida):
    """
    Exporta la red viaria a GeoPackage, GeoJSON y Shapefile. Cada formato
    se exporta de forma independiente: si uno falla (por ejemplo, falta de
    un driver de escritura), no impide que se generen los demás. También
    exporta el límite municipal usado, como referencia.
    """
    carpeta_salida = Path(carpeta_salida)
    carpeta_salida.mkdir(parents=True, exist_ok=True)

    rutas = {}
    exportaciones = [
        ("gpkg", carpeta_salida / "roads_larouco.gpkg", "GPKG"),
        ("geojson", carpeta_salida / "roads_larouco.geojson", "GeoJSON"),
        ("shp", carpeta_salida / "roads_larouco.shp", "ESRI Shapefile"),
    ]

    for clave, ruta, driver in exportaciones:
        try:
            gdf.to_file(ruta, driver=driver)
            rutas[clave] = str(ruta)
            logger.info(f"Exportado {driver}: {ruta}")
        except Exception as e:
            logger.error(f"Error exportando a {driver} ({ruta}): {e}")

    try:
        ruta_boundary = carpeta_salida / "larouco_boundary.gpkg"
        boundary_gdf.to_file(ruta_boundary, driver="GPKG")
        rutas["boundary"] = str(ruta_boundary)
        logger.info(f"Exportado límite municipal: {ruta_boundary}")
    except Exception as e:
        logger.error(f"Error exportando el límite municipal: {e}")

    return rutas

def exportar_nucleos(
    villages_gdf,
    carpeta_salida
):
    """
    Exporta los núcleos de población.
    """

    carpeta_salida = Path(carpeta_salida)

    try:

        ruta = (
            carpeta_salida /
            "larouco_villages.geojson"
        )

        villages_gdf.to_file(
            ruta,
            driver="GeoJSON"
        )

        logger.info(
            f"Núcleos exportados: {ruta}"
        )

    except Exception as e:

        logger.error(
            f"Error exportando núcleos: {e}"
        )

    try:

        ruta_gpkg = (
            carpeta_salida /
            "larouco_villages.gpkg"
        )

        villages_gdf.to_file(
            ruta_gpkg,
            driver="GPKG"
        )

        logger.info(
            f"Núcleos exportados: {ruta_gpkg}"
        )

    except Exception as e:

        logger.error(
            f"Error exportando núcleos GPKG: {e}"
        )

# ------------------------------------------------------------------------------
# PASO 8: VISUALIZACIÓN
# ------------------------------------------------------------------------------

def visualizar(gdf, boundary_gdf, ruta_png):
    """Genera un mapa rápido con el límite municipal y la red viaria
    clasificada por tipo de vía (highway), con leyenda y guardado a PNG."""
    logger.info("Generando visualización...")

    fig, ax = plt.subplots(figsize=(10, 10))

    boundary_gdf.boundary.plot(ax=ax, color="black", linewidth=1.5, label="Límite municipal", zorder=1)

    for tipo, color in COLORES_VIAS.items():
        subconjunto = gdf[gdf["highway"] == tipo]
        if not subconjunto.empty:
            ancho = 2.0 if tipo in ("motorway", "trunk", "primary") else 1.0
            subconjunto.plot(ax=ax, color=color, linewidth=ancho, label=tipo, zorder=2)

    ax.set_title("Red viaria de Larouco (OSM), clasificada por tipo de vía")
    ax.legend(loc="lower left", fontsize=8, framealpha=0.9)
    ax.set_xlabel("X (EPSG:25829, m)")
    ax.set_ylabel("Y (EPSG:25829, m)")
    ax.set_aspect("equal")

    plt.tight_layout()
    fig.savefig(ruta_png, dpi=150)
    plt.close(fig)
    logger.info(f"Visualización guardada en: {ruta_png}")


# ------------------------------------------------------------------------------
# PUNTO DE EXTENSIÓN: GRAFO DE MOVILIDAD PARA EVACUACIÓN (PLACEHOLDER)
# ------------------------------------------------------------------------------

def construir_grafo_evacuacion(gdf):
    """
    PLACEHOLDER DE AMPLIACIÓN FUTURA (no implementado en esta versión).

    Pensado para ampliar este script hacia un sistema de planificación de
    evacuaciones / prevención de incendios. Ideas de implementación:

      1. Construir un grafo con NetworkX (nx.Graph o nx.DiGraph si se
         respeta 'oneway') donde:
           - los nodos son los extremos (primer y último punto) de cada
             LineString de `gdf` (y los puntos de cruce entre vías, que
             habría que detectar con una unión topológica previa),
           - las aristas son los segmentos de vía, con 'length_m' como
             peso base.
      2. Ajustar el peso de cada arista con un factor de coste según
         'surface', 'tracktype' y 'smoothness' (p.ej. penalizar pistas en
         mal estado para vehículos de emergencia pesados).
      3. Calcular rutas de evacuación óptimas (Dijkstra / A* de NetworkX)
         desde núcleos de población hacia puntos de encuentro o vías
         principales de salida.
      4. Calcular tiempos de acceso (isócronas) desde un punto de origen
         (p.ej. un parque de bomberos) usando una velocidad estimada por
         tipo de vía.
      5. Integrar capas ráster de riesgo de incendio y el DEM (pendiente
         e inclinación, ver script de procesado de Copernicus DEM) para
         penalizar o excluir tramos de alto riesgo o pendiente excesiva.

    Requeriría añadir 'networkx' a las dependencias y datos adicionales
    de riesgo/DEM que quedan fuera del alcance de este script.
    """
    logger.info("construir_grafo_evacuacion(): no implementado todavía (punto de extensión documentado).")
    return None


# ------------------------------------------------------------------------------
# MAIN
# ------------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--municipio", default=NOMBRE_MUNICIPIO_DEFECTO, help="Nombre a buscar en Nominatim.")
    parser.add_argument("--epsg", default=EPSG_DESTINO_DEFECTO, help="CRS de destino (por defecto EPSG:25829).")
    parser.add_argument("--salida", default="salidas_larouco_roads", help="Carpeta de salida.")
    parser.add_argument(
        "--categorias",
        default=",".join(CATEGORIAS_VIAS_DEFECTO),
        help="Categorías 'highway' a incluir, separadas por comas.",
    )
    args = parser.parse_args()

    categorias = [c.strip() for c in args.categorias.split(",") if c.strip()]

    try:
        sesion = crear_sesion_http()

        logger.info(f"Resolviendo municipio '{args.municipio}' en Nominatim...")
        relation_id, boundary_geom = obtener_relacion_municipio(sesion, args.municipio)

        villages_gdf = None

        if relation_id is not None:

            logger.info(
                "Descargando núcleos OSM..."
            )

            query_nucleos = construir_query_nucleos(
                relation_id
            )

            data_nucleos = consultar_overpass(
                sesion,
                query_nucleos
            )

            registros_nucleos = parsear_nucleos_osm(
                data_nucleos
            )

            if registros_nucleos:

                villages_gdf = gpd.GeoDataFrame(
                    registros_nucleos,
                    geometry="geometry",
                    crs="EPSG:4326"
                )

                logger.info(
                    f"Núcleos encontrados: "
                    f"{len(villages_gdf)}"
                )

        if boundary_geom is None:
            logger.warning(f"Sin polígono de Nominatim; se usa bbox de respaldo: {BBOX_RESPALDO}")
            boundary_geom = box(*BBOX_RESPALDO)

        boundary_gdf = gpd.GeoDataFrame({"name": [args.municipio]}, geometry=[boundary_geom], crs="EPSG:4326")

        if relation_id is not None:
            query = construir_query_por_area(relation_id, categorias)
        else:
            logger.warning("Consultando Overpass por bounding box de respaldo (no se obtuvo relación exacta).")
            query = construir_query_por_bbox(BBOX_RESPALDO, categorias)

        data = consultar_overpass(sesion, query)
        registros = parsear_respuesta_overpass(data, ATRIBUTOS_OSM)
        gdf = construir_geodataframe(registros)
        gdf = limpiar_datos(gdf)

        logger.info(f"Reproyectando a {args.epsg}...")
        gdf_utm = gdf.to_crs(args.epsg)
        boundary_utm = boundary_gdf.to_crs(args.epsg)

        if villages_gdf is not None:

            villages_gdf = villages_gdf.to_crs(
                args.epsg)
            
        gdf_utm = calcular_atributos_derivados(gdf_utm)

        rutas = exportar(gdf_utm, boundary_utm, args.salida)

        if villages_gdf is not None:

            exportar_nucleos(
                villages_gdf,
                args.salida)

        ruta_png = str(Path(args.salida) / "roads_larouco_visualizacion.png")
        visualizar(gdf_utm, boundary_utm, ruta_png)

        construir_grafo_evacuacion(gdf_utm)

        logger.info("Proceso completado. Resumen:")
        logger.info(f"  Segmentos de vía: {len(gdf_utm)}")
        logger.info(f"  Longitud total de la red: {gdf_utm['length_m'].sum() / 1000:.2f} km")
        for clave, ruta in rutas.items():
            logger.info(f"  {clave}: {ruta}")
        logger.info(f"  visualizacion: {ruta_png}")

    except Exception as e:
        logger.error(f"ERROR: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()