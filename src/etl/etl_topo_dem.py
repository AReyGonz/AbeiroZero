#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
==============================================================================
 Descarga y procesado del DEM Copernicus GLO-30 para el concello de Larouco
 (Ourense, Galicia, España)
==============================================================================

Qué hace este script, paso a paso:
  1. Obtiene el polígono administrativo de Larouco. Primero lo intenta vía
     Nominatim (más simple y fiable: ya devuelve el polígono "cosido").
     Si falla, lo intenta vía Overpass reconstruyendo el polígono a partir
     de los segmentos de la relación (linemerge + polygonize, respetando
     roles "outer"/"inner"). Si ambos fallan, usa un bounding box de
     respaldo (aproximado, indicado explícitamente).
  2. Calcula qué teselas (tiles) de 1°x1° del Copernicus DEM GLO-30 cubren
     esa zona y las descarga del bucket público de AWS Open Data
     (s3://copernicus-dem-30m), sin credenciales.
  3. Mosaica (si hace falta) y recorta el DEM al polígono del concello.
  4. Reproyecta a ETRS89 / UTM 29N (EPSG:25829) con gdalwarp.
  5. Calcula pendiente (grados y %) y orientación (aspect, 0-360°, 0=Norte)
     con gdaldem.
  6. Genera una visualización con matplotlib (DEM, pendiente, orientación),
     respetando los píxeles sin datos (nodata).

------------------------------------------------------------------------------
INSTALACIÓN
------------------------------------------------------------------------------
Recomendado (conda/mamba), porque así te aseguras de tener las utilidades
de línea de comandos de GDAL (gdalwarp, gdaldem), no solo la librería:

    conda create -n larouco_dem -c conda-forge python=3.11 gdal rasterio geopandas shapely
    conda activate larouco_dem
    pip install requests numpy matplotlib

Solo con pip (en algunos sistemas gdalwarp/gdaldem no quedan en el PATH;
el script lo detecta y avisa con un mensaje claro si faltan):

    pip install rasterio geopandas requests numpy matplotlib shapely

------------------------------------------------------------------------------
USO
------------------------------------------------------------------------------
    python larouco_dem.py
    python larouco_dem.py --salida ./resultado_larouco --epsg EPSG:25829
    python larouco_dem.py --municipio "Larouco, Ourense, Galicia, España"

==============================================================================
"""

import argparse
import math
import os
import shutil
import subprocess
import sys

import geopandas as gpd
import matplotlib.pyplot as plt
import numpy as np
import rasterio
import requests
from rasterio.io import MemoryFile
from rasterio.mask import mask as rio_mask
from rasterio.merge import merge as rio_merge
from requests.adapters import HTTPAdapter
from shapely.geometry import LineString, box
from shapely.ops import linemerge, polygonize, unary_union
from urllib3.util.retry import Retry

# ------------------------------------------------------------------------------
# CONFIGURACIÓN POR DEFECTO
# ------------------------------------------------------------------------------

NOMBRE_MUNICIPIO_DEFECTO = "Larouco, Ourense, Galicia, España"
EPSG_DESTINO_DEFECTO = "EPSG:25829"  # ETRS89 / UTM 29N (estándar en Galicia)

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
OVERPASS_URL = "https://overpass-api.de/api/interpreter"
S3_BASE_URL = "https://copernicus-dem-30m.s3.amazonaws.com"

# Nominatim exige identificarse con un User-Agent descriptivo (política de uso)
HEADERS_HTTP = {"User-Agent": "larouco-dem-script/1.0 (uso educativo/personal)"}

# Bounding box de respaldo (lon_min, lat_min, lon_max, lat_max), WGS84.
# Es aproximado: cubre con margen el término municipal real
# (centro ~42.346N, -7.164W; superficie ~23.7 km²). Solo se usa si fallan
# tanto Nominatim como Overpass.
BBOX_RESPALDO = (-7.24, 42.31, -7.09, 42.40)

# Aviso de atribución que exige la licencia de Copernicus DEM (Airbus/DLR/ESA)
# en caso de distribuir o comunicar el dato (modificado o no) a terceros,
# incluido uso comercial. La licencia es gratuita y permite uso comercial,
# pero la atribución es obligatoria. Texto literal exigido por la licencia
# (no se debe modificar su redacción si se reproduce públicamente):
AVISO_LICENCIA_COPERNICUS = (
    "produced using Copernicus WorldDEM-30 \u00a9 DLR e.V. 2010-2014 and "
    "\u00a9 Airbus Defence and Space GmbH 2014-2018 provided under COPERNICUS "
    "by the European Union and ESA; all rights reserved"
)
# Texto completo de la licencia:
# https://documentation.dataspace.copernicus.eu/APIs/SentinelHub/Data/DEM/resources/license/License-COPDEM-30.pdf
# Nota: esto NO es asesoramiento legal; revisa la licencia completa antes de
# un uso comercial/productivo.


# ------------------------------------------------------------------------------
# UTILIDADES
# ------------------------------------------------------------------------------

def crear_sesion_http(reintentos=3):
    """
    Crea una sesión requests con reintentos automáticos ante errores de
    red/conexión y códigos 5xx, para hacer las descargas más robustas.
    """
    sesion = requests.Session()
    retry = Retry(
        total=reintentos,
        backoff_factor=1.5,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET"],
    )
    adaptador = HTTPAdapter(max_retries=retry)
    sesion.mount("https://", adaptador)
    sesion.mount("http://", adaptador)
    sesion.headers.update(HEADERS_HTTP)
    return sesion


def comprobar_herramientas_gdal():
    """
    Comprueba que gdalwarp y gdaldem (utilidades de línea de comandos de
    GDAL) estén disponibles en el PATH. Si faltan, lanza un error claro
    en vez de un FileNotFoundError críptico más adelante.
    """
    faltantes = [cmd for cmd in ("gdalwarp", "gdaldem") if shutil.which(cmd) is None]
    if faltantes:
        raise RuntimeError(
            "Faltan utilidades de GDAL en el PATH: " + ", ".join(faltantes) + ". "
            "Instálalas con 'conda install -c conda-forge gdal' "
            "(con pip a veces no se instalan los binarios de línea de comandos)."
        )


# ------------------------------------------------------------------------------
# PASO 1: LÍMITE ADMINISTRATIVO DEL MUNICIPIO
# ------------------------------------------------------------------------------

def obtener_limite_via_nominatim(sesion, nombre_municipio):
    """
    Pide a Nominatim el polígono del municipio directamente (polygon_geojson=1).
    Nominatim ya devuelve el polígono "cosido" y listo, sin que tengamos que
    reconstruirlo a partir de segmentos sueltos.
    """
    params = {
        "q": nombre_municipio,
        "format": "jsonv2",
        "polygon_geojson": 1,
        "limit": 1,
    }
    r = sesion.get(NOMINATIM_URL, params=params, timeout=60)
    r.raise_for_status()
    resultados = r.json()

    if not resultados:
        raise RuntimeError("Nominatim no devolvió resultados.")

    geojson = resultados[0].get("geojson")
    if geojson is None or geojson.get("type") not in ("Polygon", "MultiPolygon"):
        raise RuntimeError("Nominatim no devolvió un polígono utilizable.")

    from shapely.geometry import shape
    geom = shape(geojson)

    return gpd.GeoDataFrame({"name": [nombre_municipio]}, geometry=[geom], crs="EPSG:4326")


def obtener_limite_via_overpass(sesion):
    """
    Alternativa a Nominatim: pide la relación de límite administrativo a
    Overpass y reconstruye el polígono correctamente.

    IMPORTANTE: las relaciones de límites de OSM vienen partidas en
    segmentos ("ways"), no como anillos cerrados por miembro. Hay que:
      1. Separar los segmentos por rol ("outer" forma el contorno,
         "inner" forma huecos/enclaves).
      2. Unir los segmentos de cada grupo con linemerge (encajan por sus
         extremos aunque vengan en distinto orden/orientación).
      3. Cerrar los anillos resultantes con polygonize.
      4. Restar los huecos ("inner") al contorno ("outer").
    """
    query = """
    [out:json][timeout:90];
    relation
      ["boundary"="administrative"]
      ["admin_level"="8"]
      ["name"="Larouco"];
    out geom;
    """
    r = sesion.get(OVERPASS_URL, params={"data": query}, timeout=120)
    r.raise_for_status()
    data = r.json()

    if not data.get("elements"):
        raise RuntimeError("Overpass no devolvió ninguna relación.")

    relacion = data["elements"][0]

    lineas_outer, lineas_inner = [], []
    for miembro in relacion.get("members", []):
        if "geometry" not in miembro or len(miembro["geometry"]) < 2:
            continue
        coords = [(p["lon"], p["lat"]) for p in miembro["geometry"]]
        linea = LineString(coords)
        if miembro.get("role") == "inner":
            lineas_inner.append(linea)
        else:
            lineas_outer.append(linea)

    if not lineas_outer:
        raise RuntimeError("La relación no tiene segmentos 'outer'.")

    contorno_unido = linemerge(lineas_outer)
    poligonos_outer = list(polygonize(contorno_unido))
    if not poligonos_outer:
        raise RuntimeError("No se pudieron cerrar los anillos exteriores (geometría incompleta).")

    geom = unary_union(poligonos_outer)

    if lineas_inner:
        huecos_unidos = linemerge(lineas_inner)
        poligonos_inner = list(polygonize(huecos_unidos))
        if poligonos_inner:
            geom = geom.difference(unary_union(poligonos_inner))

    return gpd.GeoDataFrame({"name": ["Larouco"]}, geometry=[geom], crs="EPSG:4326")


def obtener_limite_municipio(nombre_municipio, ruta_salida_gpkg):
    """
    Orquesta la obtención del límite: Nominatim -> Overpass -> bbox de
    respaldo, en ese orden. Guarda el resultado en GeoPackage para que
    quede constancia de qué geometría se usó.
    """
    sesion = crear_sesion_http()

    print(f"Buscando límite administrativo de '{nombre_municipio}' en Nominatim...")
    try:
        gdf = obtener_limite_via_nominatim(sesion, nombre_municipio)
        print("OK: límite obtenido vía Nominatim.")
    except Exception as e1:
        print(f"  Nominatim falló ({e1}). Probando con Overpass...")
        try:
            gdf = obtener_limite_via_overpass(sesion)
            print("OK: límite obtenido vía Overpass.")
        except Exception as e2:
            print(f"  Overpass también falló ({e2}).")
            print(f"  AVISO: usando bounding box aproximado de respaldo: {BBOX_RESPALDO}")
            print("  (Este bbox es una aproximación manual, no el límite administrativo exacto.)")
            gdf = gpd.GeoDataFrame(geometry=[box(*BBOX_RESPALDO)], crs="EPSG:4326")

    gdf.to_file(ruta_salida_gpkg, driver="GPKG")
    print(f"Límite guardado en: {ruta_salida_gpkg}")
    return gdf


# ------------------------------------------------------------------------------
# PASO 2-3: DESCARGA, MOSAICO Y RECORTE DEL DEM
# ------------------------------------------------------------------------------

def nombre_tile(lat_tile, lon_tile):
    """
    Construye el nombre de tesela Copernicus DEM GLO-30 a partir de las
    coordenadas (enteras) de su esquina suroeste.
    Ejemplo: lat_tile=42, lon_tile=-8 -> Copernicus_DSM_COG_10_N42_00_W008_00_DEM
    """
    ns = "N" if lat_tile >= 0 else "S"
    ew = "E" if lon_tile >= 0 else "W"
    return f"Copernicus_DSM_COG_10_{ns}{abs(lat_tile):02d}_00_{ew}{abs(lon_tile):03d}_00_DEM"


def listar_tiles_necesarios(gdf):
    """
    Determina qué teselas de 1°x1° cubren el bounding box del polígono.
    Las teselas se nombran por su esquina suroeste, así que hay que usar
    floor() en ambos extremos (no ceil en el máximo, que añadiría una
    tesela de más si el límite cae justo en un grado entero).
    """
    minx, miny, maxx, maxy = gdf.total_bounds
    lat_min_t, lat_max_t = math.floor(miny), math.floor(maxy)
    lon_min_t, lon_max_t = math.floor(minx), math.floor(maxx)

    tiles = [
        nombre_tile(lat, lon)
        for lat in range(lat_min_t, lat_max_t + 1)
        for lon in range(lon_min_t, lon_max_t + 1)
    ]
    return tiles


def descargar_tiles(tiles, sesion):
    """
    Descarga cada tesela desde el bucket público de AWS y la abre como
    dataset de rasterio en memoria (sin escribir a disco temporalmente).

    OJO con el ciclo de vida de MemoryFile: hay que mantener vivas tanto
    la instancia de MemoryFile como el dataset abierto sobre ella mientras
    se use; si solo guardamos el dataset, Python puede recolectar el
    MemoryFile y dejar el dataset apuntando a memoria liberada. Por eso
    aquí guardamos ambos en sendas listas.
    """
    memfiles, datasets = [], []

    for tile in tiles:
        url = f"{S3_BASE_URL}/{tile}/{tile}.tif"
        print(f"Descargando: {url}")
        try:
            r = sesion.get(url, timeout=180)
            if r.status_code == 404:
                print(f"  AVISO: la tesela {tile} no existe en el bucket (zona fuera de cobertura). Se omite.")
                continue
            r.raise_for_status()

            memfile = MemoryFile(r.content)
            dataset = memfile.open()
            memfiles.append(memfile)
            datasets.append(dataset)
        except requests.exceptions.RequestException as e:
            print(f"  ERROR descargando {tile}: {e}")

    if not datasets:
        raise RuntimeError(
            "No se pudo descargar ninguna tesela. Revisa la conexión a internet "
            "o si la zona realmente tiene cobertura en Copernicus DEM GLO-30."
        )

    return memfiles, datasets


def mosaicar_y_recortar(datasets, gdf, ruta_salida):
    """
    Si hay más de una tesela, las mosaica. Después recorta el resultado
    al polígono exacto del municipio (no solo al bbox), dejando como
    nodata los píxeles fuera del polígono.
    """
    print(f"Mosaicando {len(datasets)} tesela(s)...")
    mosaico, transform = rio_merge(datasets)

    meta = datasets[0].meta.copy()
    meta.update(height=mosaico.shape[1], width=mosaico.shape[2], transform=transform)

    # Mosaico en memoria, para poder recortarlo sin pasar por disco
    with MemoryFile() as memfile_mosaico:
        with memfile_mosaico.open(**meta) as dst:
            dst.write(mosaico)

        with memfile_mosaico.open() as src:
            print("Recortando al polígono del municipio...")
            geometrias = gdf.geometry.values
            imagen_recortada, transform_recortada = rio_mask(src, geometrias, crop=True)
            nodata = src.nodata if src.nodata is not None else -32768.0

            meta_recorte = src.meta.copy()
            meta_recorte.update(
                height=imagen_recortada.shape[1],
                width=imagen_recortada.shape[2],
                transform=transform_recortada,
                nodata=nodata,
            )

            with rasterio.open(ruta_salida, "w", **meta_recorte) as dst:
                dst.write(imagen_recortada)

    print(f"DEM recortado (WGS84) guardado en: {ruta_salida}")


# ------------------------------------------------------------------------------
# PASO 4-5: REPROYECCIÓN Y CÁLCULO DE PENDIENTE / ORIENTACIÓN
# ------------------------------------------------------------------------------

def reproyectar_dem(ruta_entrada, ruta_salida, epsg_destino):
    """
    Reproyecta el DEM recortado al CRS de destino usando gdalwarp
    (más sencillo y robusto que reimplementar la reproyección a mano
    con rasterio.warp para este caso de uso).
    """
    print(f"Reproyectando a {epsg_destino}...")
    cmd = [
        "gdalwarp",
        "-t_srs", epsg_destino,
        "-r", "bilinear",
        "-overwrite",
        ruta_entrada,
        ruta_salida,
    ]
    resultado = subprocess.run(cmd, check=False, capture_output=True, text=True)
    if resultado.returncode != 0:
        raise RuntimeError(f"gdalwarp falló:\n{resultado.stderr}")
    print(f"DEM reproyectado guardado en: {ruta_salida}")


def calcular_pendiente_y_orientacion(ruta_dem, ruta_slope_deg, ruta_slope_pct, ruta_aspect):
    """
    Calcula, a partir del DEM ya reproyectado a un CRS métrico (UTM):
      - Pendiente en grados.
      - Pendiente en porcentaje.
      - Orientación (aspect) en grados 0-360, 0 = Norte, sentido horario.
        Las celdas planas se fuerzan a 0 (-zero_for_flat) en vez de -9999,
        que es el comportamiento por defecto de gdaldem.
    """
    pasos = [
        ("Pendiente en grados", ["gdaldem", "slope", ruta_dem, ruta_slope_deg]),
        ("Pendiente en %", ["gdaldem", "slope", ruta_dem, ruta_slope_pct, "-p"]),
        ("Orientación (aspect)", ["gdaldem", "aspect", ruta_dem, ruta_aspect, "-zero_for_flat"]),
    ]
    for etiqueta, cmd in pasos:
        print(f"Calculando: {etiqueta}...")
        resultado = subprocess.run(cmd, check=False, capture_output=True, text=True)
        if resultado.returncode != 0:
            raise RuntimeError(f"{etiqueta} falló ({' '.join(cmd)}):\n{resultado.stderr}")

    print(f"Pendiente (grados): {ruta_slope_deg}")
    print(f"Pendiente (%):      {ruta_slope_pct}")
    print(f"Orientación:        {ruta_aspect}")


# ------------------------------------------------------------------------------
# PASO 6: VISUALIZACIÓN
# ------------------------------------------------------------------------------

def leer_enmascarado(ruta):
    """Lee la banda 1 de un ráster y enmascara los píxeles nodata para
    que no distorsionen la escala de color al visualizar."""
    with rasterio.open(ruta) as src:
        datos = src.read(1).astype("float64")
        if src.nodata is not None:
            datos = np.ma.masked_equal(datos, src.nodata)
        else:
            datos = np.ma.masked_invalid(datos)
        return datos


def visualizar(ruta_dem, ruta_slope_deg, ruta_aspect, ruta_png):
    print("Generando visualización...")
    dem = leer_enmascarado(ruta_dem)
    slope = leer_enmascarado(ruta_slope_deg)
    aspect = leer_enmascarado(ruta_aspect)

    fig, ejes = plt.subplots(1, 3, figsize=(18, 6))

    im0 = ejes[0].imshow(dem, cmap="terrain")
    ejes[0].set_title("Elevación (m)")
    plt.colorbar(im0, ax=ejes[0], fraction=0.046)

    im1 = ejes[1].imshow(slope, cmap="magma")
    ejes[1].set_title("Pendiente (°)")
    plt.colorbar(im1, ax=ejes[1], fraction=0.046)

    im2 = ejes[2].imshow(aspect, cmap="twilight", vmin=0, vmax=360)
    ejes[2].set_title("Orientación (°, 0=N)")
    plt.colorbar(im2, ax=ejes[2], fraction=0.046)

    for eje in ejes:
        eje.set_xticks([])
        eje.set_yticks([])

    fig.suptitle("Larouco (Ourense) — Copernicus DEM GLO-30")
    plt.tight_layout()
    fig.savefig(ruta_png, dpi=150)
    print(f"Visualización guardada en: {ruta_png}")
    plt.close(fig)


# ------------------------------------------------------------------------------
# MAIN
# ------------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--municipio", default=NOMBRE_MUNICIPIO_DEFECTO, help="Nombre a buscar en Nominatim.")
    parser.add_argument("--epsg", default=EPSG_DESTINO_DEFECTO, help="CRS de destino (por defecto EPSG:25829).")
    parser.add_argument("--salida", default="salidas_larouco", help="Carpeta de salida.")
    args = parser.parse_args()

    out = args.salida
    os.makedirs(out, exist_ok=True)

    rutas = {
        "boundary": os.path.join(out, "larouco_boundary.gpkg"),
        "dem_wgs84": os.path.join(out, "larouco_dem_clip_wgs84.tif"),
        "dem_utm": os.path.join(out, f"larouco_dem_{args.epsg.replace(':', '')}.tif"),
        "slope_deg": os.path.join(out, "larouco_slope_deg.tif"),
        "slope_pct": os.path.join(out, "larouco_slope_pct.tif"),
        "aspect": os.path.join(out, "larouco_aspect.tif"),
        "png": os.path.join(out, "larouco_visualizacion.png"),
        "atribucion": os.path.join(out, "ATRIBUCION.txt"),
    }

    # Escribimos el aviso de atribución exigido por la licencia de
    # Copernicus DEM. Inclúyelo cuando distribuyas o publiques resultados
    # derivados de este DEM (también en uso comercial).
    with open(rutas["atribucion"], "w", encoding="utf-8") as f:
        f.write(AVISO_LICENCIA_COPERNICUS + "\n")

    memfiles, datasets = [], []
    try:
        comprobar_herramientas_gdal()

        gdf = obtener_limite_municipio(args.municipio, rutas["boundary"])
        tiles = listar_tiles_necesarios(gdf)
        print("\nTeselas Copernicus DEM necesarias:")
        for t in tiles:
            print(f"  - {t}")
        print()

        sesion = crear_sesion_http()
        memfiles, datasets = descargar_tiles(tiles, sesion)

        mosaicar_y_recortar(datasets, gdf, rutas["dem_wgs84"])
        reproyectar_dem(rutas["dem_wgs84"], rutas["dem_utm"], args.epsg)
        calcular_pendiente_y_orientacion(
            rutas["dem_utm"], rutas["slope_deg"], rutas["slope_pct"], rutas["aspect"]
        )
        visualizar(rutas["dem_utm"], rutas["slope_deg"], rutas["aspect"], rutas["png"])

        print("\n✅ Proceso completado. Archivos generados:")
        for clave, ruta in rutas.items():
            print(f"  - {ruta}")

    except Exception as e:
        print(f"\n❌ ERROR: {e}", file=sys.stderr)
        sys.exit(1)

    finally:
        # Cerramos explícitamente los datasets y MemoryFile abiertos en memoria
        for ds in datasets:
            try:
                ds.close()
            except Exception:
                pass
        for mf in memfiles:
            try:
                mf.close()
            except Exception:
                pass


if __name__ == "__main__":
    main()