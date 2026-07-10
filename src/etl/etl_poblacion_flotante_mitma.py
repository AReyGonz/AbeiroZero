#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
AbeiroZero
Población flotante de Larouco (MITMA). Calcula la climatología de población flotante a partir de los datos históricos de presencia de móviles de MITMA.

Salida principal:
    output/flotantes_climatologia.csv

Columnas:
    dia_anyo
    mes
    dia
    flotantes_media
    flotantes_p25
    flotantes_p75
    flotantes_max
    n_observaciones
    indice_presion_humana
"""

import argparse
import logging
import sys
import time
from pathlib import Path

import pandas as pd

INE_LAROUCO = "32038"
POBLACION_CENSADA = 320


# ==========================================================
# LOGGING
# ==========================================================

def configurar_logging(log_file):

    logger = logging.getLogger("abeirozero")

    if logger.handlers:
        return logger

    logger.setLevel(logging.INFO)

    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(message)s"
    )

    ch = logging.StreamHandler(sys.stdout)
    ch.setFormatter(fmt)

    fh = logging.FileHandler(
        log_file,
        encoding="utf-8"
    )
    fh.setFormatter(fmt)

    logger.addHandler(ch)
    logger.addHandler(fh)

    return logger


# ==========================================================
# RESOLUCIÓN ID MITMA
# ==========================================================

def resolve_mitma_id(output_directory, logger):

    from pyspainmobility import Zones

    logger.info("Resolviendo ID MITMA de Larouco...")

    zones = Zones(
        zones="municipalities",
        version=2,
        output_directory=output_directory
    )

    rel = zones.get_zone_relations()

    rel["municipalities"] = (
        rel["municipalities"]
        .astype(str)
        .str.zfill(5)
    )

    row = rel.loc[
        rel["municipalities"] == INE_LAROUCO
    ]

    if row.empty:
        raise RuntimeError(
            f"No se encontró el INE {INE_LAROUCO}"
        )

    mitma_id = str(
        row["municipalities_mitma"].iloc[0]
    )

    logger.info(
        f"ID MITMA encontrado: {mitma_id}"
    )

    return mitma_id


# ==========================================================
# DESCARGA
# ==========================================================

def download_data(
        start_date,
        end_date,
        mitma_id,
        cache_dir,
        logger):

    from pyspainmobility import Mobility

    cache_file = (
        cache_dir /
        f"raw_{mitma_id}_{start_date}_{end_date}.parquet"
    )

    if cache_file.exists():

        logger.info(
            f"Cargando caché {cache_file}"
        )

        return pd.read_parquet(cache_file)

    logger.info(
        f"Descargando datos MITMA "
        f"{start_date} -> {end_date}"
    )

    for intento in range(3):

        try:

            mob = Mobility(
                version=2,
                zones="municipalities",
                start_date=start_date,
                end_date=end_date,
                output_directory=str(cache_dir),
                backend="arrow",
            )

            df = mob.get_overnight_stays_data(
                return_df=True
            )

            break

        except Exception as e:

            if intento == 2:
                raise

            espera = 2 ** (intento + 1)

            logger.warning(
                f"Error descarga. "
                f"Reintentando en {espera}s"
            )

            time.sleep(espera)

    columnas = {
        "date",
        "residence_area",
        "overnight_stay_area",
        "people",
    }

    faltan = columnas - set(df.columns)

    if faltan:
        raise RuntimeError(
            f"Faltan columnas: {faltan}"
        )

    df["overnight_stay_area"] = (
        df["overnight_stay_area"]
        .astype(str)
    )

    df["residence_area"] = (
        df["residence_area"]
        .astype(str)
    )

    df = df[
        df["overnight_stay_area"] == mitma_id
    ].copy()

    if df.empty:
        raise RuntimeError(
            "Sin registros para Larouco"
        )

    cache_dir.mkdir(
        parents=True,
        exist_ok=True
    )

    df.to_parquet(
        cache_file,
        index=False
    )

    logger.info(
        f"Filtradas {len(df):,} filas"
    )

    return df


# ==========================================================
# CLIMATOLOGÍA FLOTANTES
# ==========================================================

def build_climatology(
        df,
        mitma_id,
        logger):

    logger.info(
        "Calculando climatología..."
    )

    df = df.copy()

    df["date"] = pd.to_datetime(
        df["date"]
    )

    flotantes = (
        df[
            df["residence_area"] != mitma_id
        ]
        .groupby("date")["people"]
        .sum()
        .reset_index()
    )

    flotantes.columns = [
        "date",
        "flotantes"
    ]

    if flotantes.empty:
        raise RuntimeError(
            "Sin observaciones flotantes"
        )

    flotantes["dia_anyo"] = (
        flotantes["date"]
        .dt.dayofyear
    )

    flotantes["mes"] = (
        flotantes["date"]
        .dt.month
    )

    flotantes["dia"] = (
        flotantes["date"]
        .dt.day
    )

    clima = (
        flotantes
        .groupby("dia_anyo")
        .agg(
            mes=("mes", "first"),
            dia=("dia", "first"),
            flotantes_media=("flotantes", "mean"),
            flotantes_p25=(
                "flotantes",
                lambda x: x.quantile(0.25)
            ),
            flotantes_p75=(
                "flotantes",
                lambda x: x.quantile(0.75)
            ),
            flotantes_max=(
                "flotantes",
                "max"
            ),
            n_observaciones=(
                "flotantes",
                "count"
            )
        )
        .reset_index()
    )

    clima[
        "indice_presion_humana"
    ] = (
        clima["flotantes_media"]
        / POBLACION_CENSADA
    )

    logger.info(
        f"Generados "
        f"{len(clima)} días "
        f"de climatología."
    )

    return clima


# ==========================================================
# EXPORTACIÓN
# ==========================================================

def export_results(
        raw_df,
        climatologia,
        output_dir,
        logger):

    output_dir.mkdir(
        parents=True,
        exist_ok=True
    )

    raw_file = (
        output_dir /
        "pernoctaciones_larouco_raw.parquet"
    )

    clima_file = (
        output_dir /
        "flotantes_climatologia.csv"
    )

    raw_df.to_parquet(
        raw_file,
        index=False
    )

    climatologia.to_csv(
        clima_file,
        index=False,
        float_format="%.2f"
    )

    logger.info(
        f"Exportado: {raw_file}"
    )

    logger.info(
        f"Exportado: {clima_file}"
    )


# ==========================================================
# MAIN
# ==========================================================

def main():

    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--start",
        default="2022-01-01"
    )

    parser.add_argument(
        "--end",
        default="2025-12-31"
    )

    parser.add_argument(
        "--output",
        default="output"
    )

    parser.add_argument(
        "--cache-dir",
        default=".cache_mitma"
    )

    args = parser.parse_args()

    output_dir = Path(args.output)
    cache_dir = Path(args.cache_dir)

    output_dir.mkdir(
        parents=True,
        exist_ok=True
    )

    cache_dir.mkdir(
        parents=True,
        exist_ok=True
    )

    logger = configurar_logging(
        output_dir / "proceso.log"
    )

    try:

        mitma_id = resolve_mitma_id(
            str(cache_dir),
            logger
        )

        raw_df = download_data(
            args.start,
            args.end,
            mitma_id,
            cache_dir,
            logger
        )

        climatologia = build_climatology(
            raw_df,
            mitma_id,
            logger
        )

        export_results(
            raw_df,
            climatologia,
            output_dir,
            logger
        )

        logger.info(
            "Proceso completado."
        )

    except Exception as e:

        logger.error(
            f"ERROR FATAL: {e}"
        )

        sys.exit(1)


if __name__ == "__main__":
    main()