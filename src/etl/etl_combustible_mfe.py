#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
AbeiroZero
MFE25 Galicia -> Modelos de combustible de Larouco

Fuente:
https://www.miteco.gob.es/es/cartografia-y-sig/ide/descargas/biodiversidad/mfe_galicia.html

Workflow

MFE25 Galicia descargado localmente
        ↓
Lectura shapefile
        ↓
AOI Larouco
(src.aoi.boundary.get_aoi)
        ↓
Recorte espacial
        ↓
Inspección atributos
        ↓
Construcción modelo combustible
        ↓
Exportaciones

Outputs:

output/
├── larouco_combustibles.gpkg
├── larouco_combustibles.geojson
├── estadisticas_combustible.csv
├── mapa_combustibles.png
├── mfe25_schema.csv
└── proceso.log
"""

import logging
import sys
from pathlib import Path

import geopandas as gpd
import pandas as pd
import matplotlib.pyplot as plt

from src.aoi.boundary import get_aoi


# ==========================================================
# CONFIG
# ==========================================================

BASE_DIR = Path.cwd()

MFE_FOLDER = (
    BASE_DIR
    / "data"
    / "reference"
    / "mfe25_galicia"
)

OUTPUT_DIR = (
    BASE_DIR
    / "output"
)

OUTPUT_DIR.mkdir(
    parents=True,
    exist_ok=True
)

LOG_FILE = (
    OUTPUT_DIR
    / "proceso.log"
)

TARGET_CRS = "EPSG:25829"


# ==========================================================
# LOGGING
# ==========================================================

logging.basicConfig(
    level=logging.INFO,
    format=(
        "%(asctime)s - "
        "%(levelname)s - "
        "%(message)s"
    ),
    handlers=[
        logging.FileHandler(
            LOG_FILE,
            encoding="utf8"
        ),
        logging.StreamHandler(
            sys.stdout
        )
    ]
)


# ==========================================================
# CARGA MFE
# ==========================================================

def load_mfe_layer():

    shp_files = list(
        MFE_FOLDER.rglob("*.shp")
    )

    if not shp_files:

        raise FileNotFoundError(
            f"No se encontraron shapefiles "
            f"en {MFE_FOLDER}"
        )

    logging.info(
        f"Shapefiles encontrados: "
        f"{len(shp_files)}"
    )

    largest = max(
        shp_files,
        key=lambda p: p.stat().st_size
    )

    logging.info(
        f"Capa seleccionada: "
        f"{largest.name}"
    )

    gdf = gpd.read_file(
        largest
    )

    logging.info(
        f"Teselas cargadas: "
        f"{len(gdf):,}"
    )

    return gdf


# ==========================================================
# LIMPIEZA
# ==========================================================

def clean_data(gdf):

    logging.info(
        "Limpiando geometrías..."
    )

    gdf = gdf.copy()

    gdf = gdf[
        gdf.geometry.notnull()
    ]

    gdf = gdf[
        ~gdf.geometry.is_empty
    ]

    gdf["geometry"] = (
        gdf.buffer(0)
    )

    gdf = gdf.drop_duplicates()

    return gdf


# ==========================================================
# ESQUEMA
# ==========================================================

def export_schema(gdf):

    schema = pd.DataFrame({
        "column":
            gdf.columns,
        "dtype":
            gdf.dtypes.astype(str)
    })

    schema.to_csv(
        OUTPUT_DIR
        / "mfe25_schema.csv",
        index=False
    )

    logging.info(
        "Schema exportado."
    )


# ==========================================================
# CLIP AOI
# ==========================================================

def clip_to_aoi(
    mfe,
    aoi
):

    logging.info(
        "Recortando a Larouco..."
    )

    if mfe.crs != aoi.crs:

        mfe = mfe.to_crs(
            aoi.crs
        )

    clipped = gpd.overlay(
        mfe,
        aoi,
        how="intersection"
    )

    logging.info(
        f"Teselas resultantes: "
        f"{len(clipped):,}"
    )

    return clipped


# ==========================================================
# MODELO COMBUSTIBLE
# ==========================================================

def build_fuel_model(gdf):

    gdf = gdf.copy()

    export_schema(gdf)

    logging.info(
        "Columnas detectadas:"
    )

    for col in gdf.columns:
        logging.info(f"  {col}")

    #
    # TEMPORAL
    #
    # Primera ejecución:
    # revisar output/mfe25_schema.csv
    # y adaptar con los nombres reales
    #

    gdf["fuel_type"] = (
        "PENDIENTE_MAPEO"
    )

    return gdf


# ==========================================================
# ESTADÍSTICAS
# ==========================================================

def calculate_statistics(gdf):

    gdf = gdf.copy()

    gdf["area_ha"] = (
        gdf.geometry.area
        / 10000
    )

    stats = (
        gdf
        .groupby("fuel_type")
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

    total = (
        stats["superficie_ha"]
        .sum()
    )

    stats["porcentaje"] = (
        stats["superficie_ha"]
        / total
        * 100
    )

    stats.to_csv(
        OUTPUT_DIR
        / "estadisticas_combustible.csv",
        index=False
    )

    return stats


# ==========================================================
# EXPORT
# ==========================================================

def export_results(gdf):

    gpkg = (
        OUTPUT_DIR
        / "larouco_combustibles.gpkg"
    )

    geojson = (
        OUTPUT_DIR
        / "larouco_combustibles.geojson"
    )

    gdf.to_file(
        gpkg,
        driver="GPKG"
    )

    gdf.to_file(
        geojson,
        driver="GeoJSON"
    )

    logging.info(
        f"Exportado: {gpkg}"
    )

    logging.info(
        f"Exportado: {geojson}"
    )


# ==========================================================
# MAPA
# ==========================================================

def generate_map(
    fuel_gdf,
    aoi
):

    fig, ax = plt.subplots(
        figsize=(10, 10)
    )

    aoi.boundary.plot(
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
        "Combustibles forestales - Larouco"
    )

    ax.axis("off")

    plt.tight_layout()

    plt.savefig(
        OUTPUT_DIR
        / "mapa_combustibles.png",
        dpi=300
    )

    plt.close()


# ==========================================================
# MAIN
# ==========================================================

def main():

    logging.info(
        "=" * 60
    )

    logging.info(
        "AbeiroZero - MFE25 Larouco"
    )

    logging.info(
        "=" * 60
    )

    aoi = get_aoi()

    mfe = load_mfe_layer()

    mfe = clean_data(
        mfe
    )

    larouco = clip_to_aoi(
        mfe,
        aoi
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
        aoi
    )

    logging.info(
        "Proceso completado."
    )


if __name__ == "__main__":
    main()