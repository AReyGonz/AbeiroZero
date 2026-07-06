#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
ETL MFE Galicia -> Modelos de combustible para Larouco

Autor: Ejemplo
Python: 3.11+

Dependencias:

pip install geopandas pandas requests shapely pyproj matplotlib \
            fiona rasterio tqdm

Objetivos:
- Descargar MFE Galicia
- Obtener límite de Larouco
- Recortar información forestal
- Construir una capa de combustibles
- Generar estadísticas
- Exportar resultados
"""

import os
import sys
import zipfile
import logging
from pathlib import Path

import requests
import pandas as pd
import geopandas as gpd
import matplotlib.pyplot as plt

from tqdm import tqdm
from shapely.geometry import shape, box

# ------------------------------------------------------------------------------
# CONFIGURACIÓN
# ------------------------------------------------------------------------------

BASE_DIR = Path.cwd()

DATA_DIR = BASE_DIR / "data"
OUTPUT_DIR = BASE_DIR / "output"

DATA_DIR.mkdir(exist_ok=True)
OUTPUT_DIR.mkdir(exist_ok=True)

LOG_FILE = OUTPUT_DIR / "proceso.log"

MFE_URL = (
    "https://www.mapama.gob.es/app/descargas/"
    "descargafichero.aspx?f=mfe_Galicia.rar"
)

MFE_FILE = DATA_DIR / "mfe_galicia.rar"

TARGET_CRS = "EPSG:25829"

# Bounding box de respaldo aproximado
FALLBACK_BBOX = (
    -7.24,
    42.31,
    -7.09,
    42.40
)

# ------------------------------------------------------------------------------
# LOGGING
# ------------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf8"),
        logging.StreamHandler(sys.stdout)
    ]
)

# ------------------------------------------------------------------------------
# DESCARGA
# ------------------------------------------------------------------------------


def download_mfe():
    """
    Descarga el MFE Galicia si no existe.
    """

    if MFE_FILE.exists():
        logging.info("El archivo MFE ya existe.")
        return

    logging.info("Descargando MFE Galicia...")

    response = requests.get(
        MFE_URL,
        stream=True,
        timeout=300
    )

    response.raise_for_status()

    total_size = int(
        response.headers.get(
            "content-length",
            0
        )
    )

    with open(MFE_FILE, "wb") as f:

        with tqdm(
            total=total_size,
            unit="B",
            unit_scale=True
        ) as pbar:

            for chunk in response.iter_content(
                chunk_size=8192
            ):

                if chunk:
                    f.write(chunk)
                    pbar.update(len(chunk))

    logging.info("Descarga finalizada.")


# ------------------------------------------------------------------------------
# EXTRACCIÓN
# ------------------------------------------------------------------------------


def extract_data():

    extract_folder = DATA_DIR / "mfe_galicia"

    if extract_folder.exists():
        return extract_folder

    logging.info(
        "Extraer manualmente si el fichero es .rar "
        "y no dispone de soporte unrar."
    )

    return extract_folder


# ------------------------------------------------------------------------------
# LÍMITE MUNICIPAL
# ------------------------------------------------------------------------------


def get_municipality_boundary():

    overpass_url = (
        "https://overpass-api.de/api/interpreter"
    )

    query = """
    [out:json][timeout:60];
    relation
      ["boundary"="administrative"]
      ["admin_level"="8"]
      ["name"="Larouco"];
    out geom;
    """

    try:

        r = requests.get(
            overpass_url,
            params={"data": query},
            timeout=120
        )

        r.raise_for_status()

        data = r.json()

        if len(data["elements"]) == 0:
            raise ValueError()

        from shapely.geometry import Polygon
        from shapely.ops import unary_union

        polygons = []

        for member in data["elements"][0]["members"]:

            if "geometry" not in member:
                continue

            coords = [
                (p["lon"], p["lat"])
                for p in member["geometry"]
            ]

            if len(coords) >= 4:
                polygons.append(
                    Polygon(coords)
                )

        geom = unary_union(polygons)

        gdf = gpd.GeoDataFrame(
            {"name": ["Larouco"]},
            geometry=[geom],
            crs="EPSG:4326"
        )

        logging.info(
            "Límite obtenido desde OSM."
        )

    except Exception:

        logging.warning(
            "No se pudo obtener Larouco desde OSM."
        )

        gdf = gpd.GeoDataFrame(
            geometry=[
                box(*FALLBACK_BBOX)
            ],
            crs="EPSG:4326"
        )

    gdf = gdf.to_crs(TARGET_CRS)

    output = OUTPUT_DIR / "larouco_boundary.gpkg"

    gdf.to_file(
        output,
        driver="GPKG"
    )

    return gdf


# ------------------------------------------------------------------------------
# CARGA DEL MFE
# ------------------------------------------------------------------------------


def load_mfe_layer(folder):

    shp_files = list(
        folder.rglob("*.shp")
    )

    if not shp_files:

        raise FileNotFoundError(
            "No se encontraron Shapefiles"
        )

    logging.info(
        f"Encontradas {len(shp_files)} capas."
    )

    largest = max(
        shp_files,
        key=lambda x: x.stat().st_size
    )

    logging.info(
        f"Usando capa: {largest.name}"
    )

    return gpd.read_file(largest)


# ------------------------------------------------------------------------------
# LIMPIEZA
# ------------------------------------------------------------------------------


def clean_data(gdf):

    logging.info(
        "Ejecutando limpieza..."
    )

    gdf = gdf.copy()

    gdf = gdf[
        ~gdf.geometry.is_empty
    ]

    gdf = gdf[
        gdf.geometry.notnull()
    ]

    gdf["geometry"] = (
        gdf.buffer(0)
    )

    gdf = gdf.drop_duplicates()

    return gdf


# ------------------------------------------------------------------------------
# RECORTE
# ------------------------------------------------------------------------------


def clip_to_larouco(
    mfe,
    boundary
):

    logging.info(
        "Recortando municipio..."
    )

    if mfe.crs != TARGET_CRS:
        mfe = mfe.to_crs(
            TARGET_CRS
        )

    return gpd.overlay(
        mfe,
        boundary,
        how="intersection"
    )


# ------------------------------------------------------------------------------
# COMBUSTIBLES
# ------------------------------------------------------------------------------


def build_fuel_model(gdf):

    """
    Ajustar según campos reales.
    """

    logging.info(
        "Construyendo modelo de combustible..."
    )

    print("\nCampos disponibles:\n")

    for c in gdf.columns:
        print(c)

    gdf["fuel_type"] = (
        "SIN_CLASIFICAR"
    )

    # Ejemplo simplificado
    # Adaptar tras inspeccionar
    # estructura real del MFE.

    return gdf


# ------------------------------------------------------------------------------
# ESTADÍSTICAS
# ------------------------------------------------------------------------------


def calculate_statistics(gdf):

    gdf = gdf.copy()

    gdf["area_ha"] = (
        gdf.area / 10000
    )

    stats = (
        gdf.groupby("fuel_type")
        .agg(
            superficie_ha=(
                "area_ha",
                "sum"
            ),
            n_poligonos=(
                "fuel_type",
                "count"
            )
        )
        .reset_index()
    )

    total = stats[
        "superficie_ha"
    ].sum()

    stats["porcentaje"] = (
        stats["superficie_ha"]
        / total
        * 100
    )

    csv_path = (
        OUTPUT_DIR
        / "estadisticas_combustible.csv"
    )

    stats.to_csv(
        csv_path,
        index=False
    )

    return stats


# ------------------------------------------------------------------------------
# EXPORTACIÓN
# ------------------------------------------------------------------------------


def export_results(gdf):

    gdf.to_file(
        OUTPUT_DIR /
        "larouco_combustibles.gpkg",
        driver="GPKG"
    )

    gdf.to_file(
        OUTPUT_DIR /
        "larouco_combustibles.geojson",
        driver="GeoJSON"
    )

    gdf.to_file(
        OUTPUT_DIR /
        "larouco_combustibles.shp"
    )


# ------------------------------------------------------------------------------
# MAPA
# ------------------------------------------------------------------------------


def generate_map(
    fuel_gdf,
    boundary_gdf
):

    fig, ax = plt.subplots(
        figsize=(10, 10)
    )

    boundary_gdf.boundary.plot(
        ax=ax,
        color="black",
        linewidth=2
    )

    fuel_gdf.plot(
        ax=ax,
        column="fuel_type",
        legend=True
    )

    ax.set_title(
        "Modelos de combustible - Larouco"
    )

    ax.set_axis_off()

    plt.tight_layout()

    plt.savefig(
        OUTPUT_DIR /
        "mapa_combustibles.png",
        dpi=300
    )

    plt.close()


# ------------------------------------------------------------------------------
# MAIN
# ------------------------------------------------------------------------------


def main():

    download_mfe()

    folder = extract_data()

    boundary = (
        get_municipality_boundary()
    )

    mfe = load_mfe_layer(folder)

    mfe = clean_data(mfe)

    larouco = clip_to_larouco(
        mfe,
        boundary
    )

    fuel = build_fuel_model(
        larouco
    )

    calculate_statistics(
        fuel
    )

    export_results(
        fuel
    )

    generate_map(
        fuel,
        boundary
    )

    logging.info(
        "Proceso completado."
    )


if __name__ == "__main__":
    main()
