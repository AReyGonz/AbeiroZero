#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
AbeiroZero
Estado del combustible vegetal (Sentinel-2)

Productos:

- NDVI
- NDMI
- Fuel Condition Index (FCI)

AOI:
- src.aoi.boundary.get_aoi()

Fuentes:
- Copernicus STAC API
- Sentinel-2 L2A
"""

import logging
from pathlib import Path
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import rasterio
import requests
import matplotlib.pyplot as plt

from pystac_client import Client
from rasterio.io import MemoryFile
from rasterio.mask import mask

from src.aoi.boundary import get_aoi


# ==========================================================
# CONFIG
# ==========================================================

MAX_CLOUD_COVER = 20
DAYS_BACK = 30

STAC_URL = (
    "https://catalogue.dataspace.copernicus.eu/stac"
)

OUTPUT_DIR = Path("output")
OUTPUT_DIR.mkdir(exist_ok=True)


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
            OUTPUT_DIR / "proceso.log",
            encoding="utf-8"
        ),
        logging.StreamHandler()
    ]
)


# ==========================================================
# STAC SEARCH
# ==========================================================

def search_sentinel_image(aoi):

    bbox = aoi.to_crs(
        "EPSG:4326"
    ).total_bounds

    start_date = (
        datetime.utcnow()
        - timedelta(days=DAYS_BACK)
    ).strftime("%Y-%m-%d")

    end_date = (
        datetime.utcnow()
    ).strftime("%Y-%m-%d")

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
            "No hay imágenes Sentinel-2 válidas."
        )

    items.sort(
        key=lambda x:
        x.properties.get(
            "eo:cloud_cover",
            100
        )
    )

    selected = items[0]

    logging.info(
        f"Escena seleccionada: "
        f"{selected.id}"
    )

    return selected


# ==========================================================
# DOWNLOAD
# ==========================================================

def download_band(url):

    r = requests.get(
        url,
        timeout=300
    )

    r.raise_for_status()

    return r.content


def open_band(asset_url):

    mem = MemoryFile(
        download_band(asset_url)
    )

    return mem.open()


# ==========================================================
# AOI CROP
# ==========================================================

def crop_to_aoi(
    dataset,
    aoi
):

    geom = (
        aoi
        .to_crs(dataset.crs)
        .geometry.iloc[0]
    )

    array, transform = mask(
        dataset,
        [geom.__geo_interface__],
        crop=True
    )

    profile = dataset.profile.copy()

    profile.update(
        height=array.shape[1],
        width=array.shape[2],
        transform=transform
    )

    return array[0], profile


# ==========================================================
# CLOUDS
# ==========================================================

def build_cloud_mask(scl):

    return np.isin(
        scl,
        [
            3,
            8,
            9,
            10,
            11,
        ]
    )


# ==========================================================
# INDICES
# ==========================================================

def safe_index(a, b):

    return np.divide(
        a - b,
        a + b,
        out=np.zeros_like(a),
        where=(a + b) != 0
    ).astype(np.float32)


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


# ==========================================================
# FCI
# ==========================================================

def calculate_fci(
    ndvi,
    ndmi
):

    fci = (
        ((ndvi + 1) / 2)
        +
        (
            1
            -
            ((ndmi + 1) / 2)
        )
    ) / 2

    return fci.astype(
        np.float32
    )


# ==========================================================
# EXPORT
# ==========================================================

def save_raster(
    output_file,
    data,
    profile
):

    profile.update(
        count=1,
        dtype="float32",
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


def save_map(
    array,
    title,
    cmap,
    filename
):

    plt.figure(
        figsize=(8, 8)
    )

    plt.imshow(
        array,
        cmap=cmap
    )

    plt.colorbar()

    plt.title(title)

    plt.axis("off")

    plt.tight_layout()

    plt.savefig(
        OUTPUT_DIR /
        filename,
        dpi=300
    )

    plt.close()


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

        "ndmi_mean":
            float(
                np.nanmean(ndmi)
            ),

        "fci_mean":
            float(
                np.nanmean(fci)
            ),

        "pct_ndmi_bajo":

            float(

                np.nanmean(
                    ndmi < 0.20
                ) * 100

            )
    }

    pd.DataFrame(
        [stats]
    ).to_csv(
        OUTPUT_DIR /
        "estadisticas.csv",
        index=False
    )


# ==========================================================
# MAIN
# ==========================================================

def main():

    logging.info(
        "Cargando AOI..."
    )

    aoi = get_aoi()

    item = search_sentinel_image(
        aoi
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

    scl = open_band(
        assets["SCL"].href
    )

    red_arr, profile = crop_to_aoi(
        red,
        aoi
    )

    nir_arr, _ = crop_to_aoi(
        nir,
        aoi
    )

    swir_arr, _ = crop_to_aoi(
        swir,
        aoi
    )

    scl_arr, _ = crop_to_aoi(
        scl,
        aoi
    )

    red_arr = red_arr.astype(
        np.float32
    )

    nir_arr = nir_arr.astype(
        np.float32
    )

    swir_arr = swir_arr.astype(
        np.float32
    )

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

    ndvi[cloud_mask] = np.nan
    ndmi[cloud_mask] = np.nan

    fci = calculate_fci(
        ndvi,
        ndmi
    )

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

    logging.info(
        "Proceso completado."
    )


if __name__ == "__main__":
    main()