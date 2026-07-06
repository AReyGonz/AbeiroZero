#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Evaluación del estado del combustible vegetal en Larouco
usando Sentinel-2 L2A y STAC API de Copernicus.

Productos:
- NDVI
- NDMI
- NBR
- Fuel Condition Index (FCI)

Autor: Ejemplo
"""

import logging
import os
from pathlib import Path
from datetime import datetime, timedelta

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
import requests

from pystac_client import Client
from rasterio.mask import mask
from rasterio.io import MemoryFile
from shapely.geometry import box, Polygon
import matplotlib.pyplot as plt


# ==========================================================
# CONFIGURACIÓN
# ==========================================================

MAX_CLOUD_COVER = 20
DAYS_BACK = 30

STAC_URL = "https://catalogue.dataspace.copernicus.eu/stac"

OUTPUT_DIR = Path("output")
OUTPUT_DIR.mkdir(exist_ok=True)

TARGET_CRS = "EPSG:25829"

FALLBACK_BBOX = (
    -7.24,
    42.31,
    -7.09,
    42.40
)


# ==========================================================
# LOGGING
# ==========================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler(
            OUTPUT_DIR / "proceso.log",
            encoding="utf-8"
        ),
        logging.StreamHandler()
    ]
)


# ==========================================================
# LÍMITE MUNICIPAL
# ==========================================================

def get_boundary():

    logging.info(
        "Obteniendo límite municipal..."
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

        url = (
            "https://overpass-api.de/api/interpreter"
        )

        response = requests.get(
            url,
            params={"data": query},
            timeout=120
        )

        response.raise_for_status()

        data = response.json()

        polys = []

        for member in (
            data["elements"][0]["members"]
        ):

            if "geometry" not in member:
                continue

            coords = [
                (p["lon"], p["lat"])
                for p in member["geometry"]
            ]

            if len(coords) > 3:
                polys.append(
                    Polygon(coords)
                )

        geom = gpd.GeoSeries(
            polys,
            crs="EPSG:4326"
        ).union_all()

        gdf = gpd.GeoDataFrame(
            {"municipio": ["Larouco"]},
            geometry=[geom],
            crs="EPSG:4326"
        )

        logging.info(
            "Límite obtenido desde OSM."
        )

    except Exception:

        logging.warning(
            "Usando bounding box de respaldo."
        )

        gdf = gpd.GeoDataFrame(
            geometry=[
                box(*FALLBACK_BBOX)
            ],
            crs="EPSG:4326"
        )

    gdf.to_file(
        OUTPUT_DIR /
        "larouco_boundary.gpkg",
        driver="GPKG"
    )

    return gdf


# ==========================================================
# BÚSQUEDA SENTINEL-2
# ==========================================================

def search_sentinel_image(boundary):

    logging.info(
        "Buscando Sentinel-2..."
    )

    bbox = boundary.total_bounds

    start_date = (
        datetime.utcnow()
        - timedelta(days=DAYS_BACK)
    ).strftime("%Y-%m-%d")

    end_date = datetime.utcnow().strftime(
        "%Y-%m-%d"
    )

    client = Client.open(STAC_URL)

    search = client.search(
        collections=["sentinel-2-l2a"],
        bbox=bbox.tolist(),
        datetime=f"{start_date}/{end_date}",
        query={
            "eo:cloud_cover": {
                "lt": MAX_CLOUD_COVER
            }
        }
    )

    items = list(search.items())

    if not items:
        raise RuntimeError(
            "No se encontraron imágenes."
        )

    items = sorted(
        items,
        key=lambda x:
        x.properties.get(
            "eo:cloud_cover", 100
        )
    )

    selected = items[0]

    logging.info(
        f"Escena seleccionada: "
        f"{selected.id}"
    )

    return selected


# ==========================================================
# DESCARGA DE BANDAS
# ==========================================================

def download_band(url):

    logging.info(
        f"Descargando {url}"
    )

    response = requests.get(
        url,
        timeout=300
    )

    response.raise_for_status()

    return response.content


def open_band(asset_url):

    mem = MemoryFile(
        download_band(asset_url)
    )

    return mem.open()


# ==========================================================
# MÁSCARA NUBES
# ==========================================================

def build_cloud_mask(scl):

    mask_cloud = np.isin(
        scl,
        [
            3,   # sombras
            8,   # nube media
            9,   # nube alta
            10,  # cirrus
            11   # nieve
        ]
    )

    return mask_cloud


# ==========================================================
# ÍNDICES
# ==========================================================

def safe_index(a, b):

    result = np.divide(
        a - b,
        a + b,
        out=np.zeros_like(a),
        where=(a + b) != 0
    )

    return result.astype(
        np.float32
    )


def calculate_ndvi(
    nir,
    red
):

    return safe_index(
        nir,
        red
    )


def calculate_ndmi(
    nir,
    swir
):

    return safe_index(
        nir,
        swir
    )


def calculate_nbr(
    nir,
    swir2
):

    return safe_index(
        nir,
        swir2
    )


# ==========================================================
# FCI
# ==========================================================

def calculate_fci(
    ndvi,
    ndmi,
    nbr
):

    """
    FCI experimental.

    Valores altos =
    vegetación densa + seca.
    """

    fci = (
        (ndvi + 1) / 2
        +
        (1 - ((ndmi + 1) / 2))
        +
        (1 - ((nbr + 1) / 2))
    ) / 3

    return fci


# ==========================================================
# EXPORTACIÓN RASTER
# ==========================================================

def save_raster(
    output_file,
    data,
    profile
):

    profile.update(
        dtype="float32",
        count=1,
        compress="lzw"
    )

    with rasterio.open(
        output_file,
        "w",
        **profile
    ) as dst:

        dst.write(
            data.astype(
                np.float32
            ),
            1
        )


# ==========================================================
# ESTADÍSTICAS
# ==========================================================

def generate_statistics(
    ndvi,
    ndmi,
    fci
):

    stats = {
        "ndvi_mean":
            float(
                np.nanmean(ndvi)
            ),
        "ndvi_min":
            float(
                np.nanmin(ndvi)
            ),
        "ndvi_max":
            float(
                np.nanmax(ndvi)
            ),
        "ndmi_mean":
            float(
                np.nanmean(ndmi)
            ),
        "fci_mean":
            float(
                np.nanmean(fci)
            )
    }

    df = pd.DataFrame(
        [stats]
    )

    df.to_csv(
        OUTPUT_DIR /
        "estadisticas.csv",
        index=False
    )


# ==========================================================
# MAPAS
# ==========================================================

def save_map(
    data,
    title,
    cmap,
    filename
):

    plt.figure(
        figsize=(8, 8)
    )

    plt.imshow(
        data,
        cmap=cmap
    )

    plt.colorbar()

    plt.title(title)

    plt.axis("off")

    plt.tight_layout()

    plt.savefig(
        OUTPUT_DIR / filename,
        dpi=300
    )

    plt.close()


# ==========================================================
# MAIN
# ==========================================================

def main():

    boundary = get_boundary()

    item = search_sentinel_image(
        boundary
    )

    assets = item.assets

    red = open_band(
        assets["B04"].href
    )

    nir = open_band(
        assets["B08"].href
    )

    swir = open_band(
        assets["B11"].href
    )

    swir2 = open_band(
        assets["B12"].href
    )

    scl = open_band(
        assets["SCL"].href
    )

    red_arr = red.read(1).astype(
        np.float32
    )

    nir_arr = nir.read(1).astype(
        np.float32
    )

    swir_arr = swir.read(1).astype(
        np.float32
    )

    swir2_arr = swir2.read(1).astype(
        np.float32
    )

    scl_arr = scl.read(1)

    cloud_mask = build_cloud_mask(
        scl_arr
    )

    ndvi = calculate_ndvi(
        nir_arr,
        red_arr
    )

    ndmi = calculate_ndmi(
        nir_arr,
        swir_arr
    )

    nbr = calculate_nbr(
        nir_arr,
        swir2_arr
    )

    ndvi[cloud_mask] = np.nan
    ndmi[cloud_mask] = np.nan
    nbr[cloud_mask] = np.nan

    fci = calculate_fci(
        ndvi,
        ndmi,
        nbr
    )

    profile = red.profile

    save_raster(
        OUTPUT_DIR / "ndvi.tif",
        ndvi,
        profile.copy()
    )

    save_raster(
        OUTPUT_DIR / "ndmi.tif",
        ndmi,
        profile.copy()
    )

    save_raster(
        OUTPUT_DIR / "nbr.tif",
        nbr,
        profile.copy()
    )

    save_raster(
        OUTPUT_DIR /
        "fuel_condition_index.tif",
        fci,
        profile.copy()
    )

    generate_statistics(
        ndvi,
        ndmi,
        fci
    )

    save_map(
        ndvi,
        "NDVI",
        "RdYlGn",
        "mapa_ndvi.png"
    )

    save_map(
        ndmi,
        "NDMI",
        "RdBu",
        "mapa_ndmi.png"
    )

    save_map(
        fci,
        "Fuel Condition Index",
        "RdYlGn_r",
        "mapa_fci.png"
    )

    logging.info(
        "Proceso completado."
    )


if __name__ == "__main__":
    main()