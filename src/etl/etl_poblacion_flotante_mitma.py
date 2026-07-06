#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
==============================================================================
 AbeiroZero — Módulo de población flotante (pernoctaciones MITMA)
 Municipio de Larouco (Ourense, Galicia)  ·  Código INE: 32038
==============================================================================

CONTEXTO
--------
AbeiroZero es un sistema de prevención de incendios forestales. Este módulo
aporta la capa de **población flotante**: personas que pernoctaron en Larouco
sin estar empadronadas allí (turistas, propietarios de segunda residencia,
trabajadores temporales). Esta cifra puede multiplicar la población censada
(~320 hab.) en episodios de riesgo alto (verano, puentes, festivos), con dos
efectos directos sobre el sistema:

  1. Mayor probabilidad de ignición antrópica (más presencia humana en monte).
  2. Mayor carga de evacuación si se declara un incendio.

FUENTE DE DATOS
---------------
MITMA Open Data — Estudio de Movilidad con Big Data (versión 2, 2022-en
adelante). Datos derivados de señal de teléfonos móviles de una operadora
(Orange), expandidos a población total mediante factores de expansión.

Licencia: abierta. Atribución obligatoria:
  "Datos: Ministerio de Transportes, Movilidad y Agenda Urbana (MITMA)"

LIMITACIÓN IMPORTANTE
---------------------
La metodología MITMA tiene umbral estadístico de calidad en municipios con
población < ~1.000 hab. Larouco (~320 hab.) puede presentar días sin dato
(NaN / 0.0) que no significan "nadie pernocta", sino "muestra insuficiente
ese día". El script trata estos valores como datos faltantes, no como ceros
reales, y lo indica en el log y en las estadísticas de cobertura.

ESQUEMA REAL DE COLUMNAS (pySpainMobility v1.1.2)
--------------------------------------------------
  get_overnight_stays_data() devuelve:
    date                  | str  | YYYY-MM-DD
    residence_area        | str  | ID MITMA de zona de residencia habitual
    overnight_stay_area   | str  | ID MITMA de zona donde pernoctó
    people                | float| Estimación expandida de personas

  get_zone_relations() devuelve columnas:
    census_sections, census_districts, municipalities,
    municipalities_mitma, districts_mitma, luas_mitma

SALIDAS
-------
  output/
  ├── pernoctaciones_larouco_raw.parquet       ← datos filtrados a Larouco
  ├── poblacion_flotante_diaria.csv            ← serie temporal diaria
  ├── resumen_poblacion_flotante.csv           ← estadísticos y ranking
  ├── mapa_calor_flotantes.png                 ← heatmap mes × día semana
  ├── serie_temporal_flotantes.png             ← serie con banda IQR
  └── proceso.log

USO
---
  python poblacion_flotante_larouco.py
  python poblacion_flotante_larouco.py --start 2022-01-01 --end 2022-12-31
  python poblacion_flotante_larouco.py --start 2023-06-01 --end 2023-09-30 \\
         --output ./mi_salida --cache-dir ./cache

INSTALACIÓN
-----------
  pip install pyspainmobility pandas numpy matplotlib seaborn pyarrow

==============================================================================
"""

import argparse
import logging
import os
import sys
import time
from pathlib import Path

import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import numpy as np
import pandas as pd
import seaborn as sns

# ------------------------------------------------------------------------------
# CONSTANTES
# ------------------------------------------------------------------------------

# Código INE de Larouco (Ourense). El MITMA usa su propio esquema de IDs
# (municipalities_mitma), que puede diferir del INE o agregar municipios
# pequeños bajo un sufijo _AM ("agregación de municipios").
INE_LAROUCO = "32038"

# Temporada de alto riesgo de incendio en Galicia (meses, 1-indexed)
MESES_TEMPORADA_ALTA = {6, 7, 8, 9}

# Días de la semana en español para etiquetas (lunes=0)
NOMBRES_DIA = ["Lunes", "Martes", "Miércoles", "Jueves",
               "Viernes", "Sábado", "Domingo"]

NOMBRES_MES = ["Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
               "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre",
               "Diciembre"]


# ------------------------------------------------------------------------------
# LOGGING
# ------------------------------------------------------------------------------

def configurar_logging(ruta_log: Path) -> logging.Logger:
    """Configura logging a consola y fichero simultáneamente."""
    logger = logging.getLogger("abeiro.flotante")
    logger.setLevel(logging.DEBUG)

    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s",
                            datefmt="%Y-%m-%d %H:%M:%S")

    # Handler consola
    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.INFO)
    ch.setFormatter(fmt)

    # Handler fichero
    fh = logging.FileHandler(ruta_log, mode="w", encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt)

    logger.addHandler(ch)
    logger.addHandler(fh)
    return logger


# ------------------------------------------------------------------------------
# PASO 1: RESOLUCIÓN DEL ID MITMA DE LAROUCO
# ------------------------------------------------------------------------------

def resolve_mitma_id(output_directory: str, logger: logging.Logger) -> str:
    """
    Traduce el código INE de Larouco (32038) al identificador MITMA que
    realmente usa el dataset de pernoctaciones.

    La tabla de relaciones de pySpainMobility (get_zone_relations()) contiene
    la columna 'municipalities' con el código INE de 5 dígitos y la columna
    'municipalities_mitma' con el ID que aparece en los datos de movilidad.

    En municipios pequeños, el MITMA agrega varios municipios bajo un único ID
    con sufijo _AM (p.ej. "32038_AM"). Si Larouco está agregado, el script
    sigue funcionando: filtra por el ID agregado y lo documenta en el log,
    pero advierte que los datos incluyen más de un municipio.

    Devuelve el ID MITMA (str) que debe usarse como filtro en overnight_stay_area.
    """
    from pyspainmobility import Zones

    logger.info("Descargando tabla de relaciones de zonificación MITMA...")

    try:
        zones = Zones(zones="municipalities", version=2,
                      output_directory=output_directory)
        rel = zones.get_zone_relations()
    except Exception as e:
        raise RuntimeError(f"No se pudo obtener la tabla de zonas MITMA: {e}") from e

    # La columna 'municipalities' contiene el código INE como string de 5 dígitos
    # Nos aseguramos de que esté en ese formato antes de filtrar
    rel["municipalities"] = rel["municipalities"].astype(str).str.zfill(5)
    coincidencia = rel[rel["municipalities"] == INE_LAROUCO.zfill(5)]

    if coincidencia.empty:
        raise RuntimeError(
            f"El municipio con código INE {INE_LAROUCO} (Larouco) no aparece "
            "en la tabla de relaciones MITMA. Puede que esté agregado bajo otro "
            "código sin mapeo directo. Revisa la tabla manualmente con "
            "Zones(zones='municipalities', version=2).get_zone_relations()."
        )

    mitma_id = coincidencia["municipalities_mitma"].iloc[0]

    if "_AM" in str(mitma_id):
        logger.warning(
            f"Larouco (INE {INE_LAROUCO}) está AGREGADO en la zona MITMA '{mitma_id}'. "
            "Los datos de pernoctaciones incluirán otros municipios de la misma "
            "agregación, no solo Larouco. Las cifras deben interpretarse como "
            "estimación del área agregada, no del municipio individual."
        )
    else:
        logger.info(
            f"Larouco (INE {INE_LAROUCO}) tiene zona MITMA propia: '{mitma_id}'."
        )

    return str(mitma_id)


# ------------------------------------------------------------------------------
# PASO 2: DESCARGA DE PERNOCTACIONES (con caché local)
# ------------------------------------------------------------------------------

def download_overnight_stays(
    start_date: str,
    end_date: str,
    mitma_id: str,
    cache_dir: Path,
    output_directory: str,
    logger: logging.Logger,
) -> pd.DataFrame:
    """
    Descarga los datos de pernoctaciones del MITMA para el período indicado
    y filtra las filas donde overnight_stay_area == mitma_id (Larouco).

    Estrategia de caché: si ya existe un parquet con los datos crudos filtrados
    para este período y este municipio, lo carga directamente sin volver a
    descargar. Esto evita repetir descargas costosas al re-ejecutar el script.

    El parquet crudo se guarda también en output/ para trazabilidad.

    Columnas del DataFrame devuelto (esquema real de pySpainMobility v1.1.2):
      date                  str   YYYY-MM-DD
      residence_area        str   ID MITMA zona de residencia
      overnight_stay_area   str   ID MITMA zona de pernoctación (siempre mitma_id)
      people                float personas estimadas
    """
    from pyspainmobility import Mobility

    # Nombre del fichero de caché: incluye municipio y fechas para evitar
    # colisiones si el script se usa con distintos parámetros
    cache_file = cache_dir / f"raw_{mitma_id}_{start_date}_{end_date}.parquet"

    if cache_file.exists():
        logger.info(f"Caché encontrado: {cache_file}. Cargando sin descargar.")
        return pd.read_parquet(cache_file)

    logger.info(
        f"Descargando pernoctaciones MITMA v2 (municipios) "
        f"del {start_date} al {end_date}. "
        "Esto puede tardar varios minutos según el período solicitado..."
    )

    # Reintentos manuales: pySpainMobility no implementa reintentos internos
    # para la descarga masiva; si la conexión falla a mitad, reintentamos
    # todo el bloque hasta MAX_REINTENTOS veces con espera exponencial.
    MAX_REINTENTOS = 3
    for intento in range(1, MAX_REINTENTOS + 1):
        try:
            mob = Mobility(
                version=2,
                zones="municipalities",
                start_date=start_date,
                end_date=end_date,
                output_directory=output_directory,
                backend="arrow",   # más eficiente en memoria que 'pandas'
            )
            df_raw = mob.get_overnight_stays_data(return_df=True)
            break
        except Exception as e:
            if intento == MAX_REINTENTOS:
                raise RuntimeError(
                    f"Fallo definitivo al descargar pernoctaciones tras "
                    f"{MAX_REINTENTOS} intentos: {e}"
                ) from e
            espera = 2 ** intento
            logger.warning(
                f"Error en intento {intento}/{MAX_REINTENTOS}: {e}. "
                f"Reintentando en {espera}s..."
            )
            time.sleep(espera)

    logger.info(f"Descarga completada. {len(df_raw):,} filas totales (España).")

    # Convertir tipos para asegurar comparaciones correctas
    df_raw["overnight_stay_area"] = df_raw["overnight_stay_area"].astype(str)
    df_raw["residence_area"] = df_raw["residence_area"].astype(str)

    # Filtrar solo las filas donde la zona de pernoctación es Larouco
    df = df_raw[df_raw["overnight_stay_area"] == mitma_id].copy()

    if df.empty:
        logger.error(
            f"El ID MITMA '{mitma_id}' no aparece en ninguna fila de "
            "'overnight_stay_area' para el período {start_date} – {end_date}. "
            "Posibles causas: (1) el municipio está bajo umbral de calidad "
            "estadística todos los días del período; (2) el ID MITMA es "
            "incorrecto. Revisa la tabla de zonas."
        )
        raise RuntimeError("Sin datos de pernoctaciones para Larouco en el período indicado.")

    logger.info(
        f"Filas filtradas a Larouco ({mitma_id}): {len(df):,} "
        f"({df['date'].nunique()} días con al menos un registro)."
    )

    # Advertencia de cobertura: si hay muchos días sin datos, informar
    dias_periodo = (
        pd.to_datetime(end_date) - pd.to_datetime(start_date)
    ).days + 1
    dias_con_datos = df["date"].nunique()
    cobertura_pct = 100 * dias_con_datos / dias_periodo
    logger.info(
        f"Cobertura del período: {dias_con_datos}/{dias_periodo} días "
        f"({cobertura_pct:.1f}%). "
        + ("⚠ Cobertura < 70%: municipio probablemente por debajo del umbral "
           "estadístico MITMA muchos días." if cobertura_pct < 70 else "")
    )

    # Guardar caché y parquet de salida
    cache_dir.mkdir(parents=True, exist_ok=True)
    df.to_parquet(cache_file, index=False)
    logger.debug(f"Caché escrito: {cache_file}")

    return df


# ------------------------------------------------------------------------------
# PASO 3: CÁLCULO DE POBLACIÓN FLOTANTE DIARIA
# ------------------------------------------------------------------------------

def compute_floating_population(
    df: pd.DataFrame,
    mitma_id: str,
    logger: logging.Logger,
) -> pd.DataFrame:
    """
    A partir del DataFrame crudo filtrado a Larouco, calcula por cada día:

      - propios:    personas cuya residence_area es el propio Larouco
                    (proxy de población residente activa esa noche)
      - flotantes:  personas cuya residence_area es DISTINTA a Larouco
                    (población flotante neta: turistas, segunda residencia, etc.)
      - total:      propios + flotantes
      - ratio_flotante: flotantes / total (0-1); NaN si total == 0

    Añade columnas temporales para el análisis estacional:
      fecha, dia_semana (0=lunes), nombre_dia, mes, nombre_mes,
      trimestre, temporada_alta (bool)

    Los días con people == 0.0 en TODAS las filas se tratan como sin dato
    (cobertura insuficiente), no como días con cero pernoctantes.
    """
    df = df.copy()
    df["date"] = pd.to_datetime(df["date"])

    # Separar residentes propios vs. flotantes
    mask_propios = df["residence_area"] == mitma_id
    propios_dia = (
        df[mask_propios]
        .groupby("date")["people"]
        .sum()
        .rename("propios")
    )
    flotantes_dia = (
        df[~mask_propios]
        .groupby("date")["people"]
        .sum()
        .rename("flotantes")
    )

    serie = pd.concat([propios_dia, flotantes_dia], axis=1).fillna(0.0)
    serie["total"] = serie["propios"] + serie["flotantes"]

    # Marcar días sin dato real (total == 0 → sin muestra suficiente)
    sin_dato = serie["total"] == 0.0
    n_sin_dato = sin_dato.sum()
    if n_sin_dato > 0:
        logger.warning(
            f"{n_sin_dato} días con total de pernoctaciones = 0 "
            "(muestra insuficiente según umbral MITMA). Se excluyen del análisis."
        )
        serie = serie[~sin_dato].copy()

    # Ratio población flotante
    serie["ratio_flotante"] = np.where(
        serie["total"] > 0,
        serie["flotantes"] / serie["total"],
        np.nan,
    )

    # Columnas temporales
    serie.index.name = "fecha"
    serie = serie.reset_index()
    serie["dia_semana"] = serie["fecha"].dt.dayofweek   # 0=lunes
    serie["nombre_dia"] = serie["dia_semana"].map(dict(enumerate(NOMBRES_DIA)))
    serie["mes"] = serie["fecha"].dt.month
    serie["nombre_mes"] = serie["mes"].map(
        dict(enumerate(NOMBRES_MES, start=1))
    )
    serie["trimestre"] = serie["fecha"].dt.quarter
    serie["temporada_alta"] = serie["mes"].isin(MESES_TEMPORADA_ALTA)

    # Añadir código INE para compatibilidad con esquema AbeiroZero
    serie["municipio_ine"] = INE_LAROUCO
    serie["municipio_mitma"] = mitma_id

    logger.info(
        f"Serie diaria calculada: {len(serie)} días válidos. "
        f"Flotantes: media={serie['flotantes'].mean():.1f}, "
        f"máx={serie['flotantes'].max():.1f}."
    )
    return serie


# ------------------------------------------------------------------------------
# PASO 4: ANÁLISIS DESCRIPTIVO ORIENTADO A RIESGO
# ------------------------------------------------------------------------------

def analyze_risk_seasonality(
    serie: pd.DataFrame,
    logger: logging.Logger,
) -> pd.DataFrame:
    """
    Genera un resumen estadístico orientado a riesgo de incendio:

      - Estadísticos globales anuales (media, mediana, p90, máximo)
      - Estadísticos por mes
      - Estadísticos por día de la semana
      - Top 10 días de mayor población flotante
      - Comparativa temporada alta (jun-sep) vs. resto del año

    Devuelve un DataFrame resumen exportable a CSV.
    """
    bloques = []

    # — GLOBAL —
    stats_global = {
        "grupo": "GLOBAL",
        "categoria": "Anual",
        "media_flotantes": serie["flotantes"].mean(),
        "mediana_flotantes": serie["flotantes"].median(),
        "p90_flotantes": serie["flotantes"].quantile(0.90),
        "max_flotantes": serie["flotantes"].max(),
        "media_ratio": serie["ratio_flotante"].mean(),
        "n_dias": len(serie),
    }
    bloques.append(pd.DataFrame([stats_global]))

    # — POR MES —
    por_mes = serie.groupby("mes").agg(
        media_flotantes=("flotantes", "mean"),
        mediana_flotantes=("flotantes", "median"),
        p90_flotantes=("flotantes", lambda x: x.quantile(0.90)),
        max_flotantes=("flotantes", "max"),
        media_ratio=("ratio_flotante", "mean"),
        n_dias=("flotantes", "count"),
    ).reset_index()
    por_mes["grupo"] = "MES"
    por_mes["categoria"] = por_mes["mes"].map(
        dict(enumerate(NOMBRES_MES, start=1))
    )
    bloques.append(por_mes.drop(columns="mes"))

    # — POR DÍA DE LA SEMANA —
    por_dia = serie.groupby("dia_semana").agg(
        media_flotantes=("flotantes", "mean"),
        mediana_flotantes=("flotantes", "median"),
        p90_flotantes=("flotantes", lambda x: x.quantile(0.90)),
        max_flotantes=("flotantes", "max"),
        media_ratio=("ratio_flotante", "mean"),
        n_dias=("flotantes", "count"),
    ).reset_index()
    por_dia["grupo"] = "DIA_SEMANA"
    por_dia["categoria"] = por_dia["dia_semana"].map(dict(enumerate(NOMBRES_DIA)))
    bloques.append(por_dia.drop(columns="dia_semana"))

    # — TEMPORADA ALTA vs RESTO —
    for temporada, label in [(True, "Temporada alta (Jun-Sep)"),
                             (False, "Resto del año")]:
        sub = serie[serie["temporada_alta"] == temporada]
        if sub.empty:
            continue
        bloques.append(pd.DataFrame([{
            "grupo": "TEMPORADA",
            "categoria": label,
            "media_flotantes": sub["flotantes"].mean(),
            "mediana_flotantes": sub["flotantes"].median(),
            "p90_flotantes": sub["flotantes"].quantile(0.90),
            "max_flotantes": sub["flotantes"].max(),
            "media_ratio": sub["ratio_flotante"].mean(),
            "n_dias": len(sub),
        }]))

    resumen = pd.concat(bloques, ignore_index=True)

    # — TOP 10 DÍAS DE MÁXIMO RIESGO HUMANO —
    top10 = (
        serie.nlargest(10, "flotantes")[
            ["fecha", "flotantes", "propios", "ratio_flotante",
             "nombre_dia", "nombre_mes", "temporada_alta"]
        ]
        .copy()
    )
    top10["grupo"] = "TOP10_DIAS"
    top10["categoria"] = top10["fecha"].dt.strftime("%Y-%m-%d")
    logger.info("Top 10 días de mayor población flotante estimada:")
    for _, row in top10.iterrows():
        logger.info(
            f"  {row['categoria']} ({row['nombre_dia']}, {row['nombre_mes']}): "
            f"{row['flotantes']:.0f} flotantes | ratio {row['ratio_flotante']:.2%}"
        )

    return resumen


# ------------------------------------------------------------------------------
# PASO 5: VISUALIZACIÓN
# ------------------------------------------------------------------------------

def plot_heatmap(serie: pd.DataFrame, ruta_png: Path, logger: logging.Logger):
    """
    Heatmap mes (Y) × día de la semana (X) con la media de pernoctantes
    flotantes en cada celda. Permite identificar de un vistazo los patrones
    de máximo riesgo humano (verano + fin de semana = máximo de presencia
    no censada en el monte).
    """
    pivot = serie.groupby(["mes", "dia_semana"])["flotantes"].mean().unstack()
    pivot.index = [NOMBRES_MES[m - 1] for m in pivot.index]
    pivot.columns = [NOMBRES_DIA[d] for d in pivot.columns]

    fig, ax = plt.subplots(figsize=(10, 7))
    sns.heatmap(
        pivot,
        annot=True,
        fmt=".0f",
        cmap="YlOrRd",
        linewidths=0.4,
        ax=ax,
        cbar_kws={"label": "Media pernoctantes flotantes (est.)"},
    )
    ax.set_title(
        "Larouco — Población flotante media (pernoctaciones MITMA)\n"
        "por mes y día de la semana",
        fontsize=13, fontweight="bold",
    )
    ax.set_xlabel("Día de la semana")
    ax.set_ylabel("Mes")
    plt.tight_layout()
    fig.savefig(ruta_png, dpi=150)
    plt.close(fig)
    logger.info(f"Heatmap guardado: {ruta_png}")


def plot_serie_temporal(serie: pd.DataFrame, ruta_png: Path, logger: logging.Logger):
    """
    Serie temporal diaria de población flotante con:
      - Línea de media móvil 7 días (suaviza ruido diario)
      - Banda entre percentil 25 y 75 semanal (contexto de variabilidad)
      - Fondo sombreado en meses de temporada alta (jun-sep)
    """
    s = serie.set_index("fecha").sort_index()

    mm7 = s["flotantes"].rolling(7, center=True).mean()
    p25 = s["flotantes"].rolling(7, center=True).quantile(0.25)
    p75 = s["flotantes"].rolling(7, center=True).quantile(0.75)

    fig, ax = plt.subplots(figsize=(14, 5))

    # Sombreado temporada alta
    for year in s.index.year.unique():
        for mes_ini, mes_fin in [(6, 9)]:
            ax.axvspan(
                pd.Timestamp(year=year, month=mes_ini, day=1),
                pd.Timestamp(year=year, month=mes_fin, day=30),
                alpha=0.08, color="red", label="Temporada alta" if year == s.index.year.min() else "",
            )

    ax.fill_between(s.index, p25, p75, alpha=0.25, color="steelblue", label="IQR semanal")
    ax.plot(s.index, s["flotantes"], color="steelblue", alpha=0.4, linewidth=0.7)
    ax.plot(s.index, mm7, color="navy", linewidth=1.5, label="Media móvil 7 días")

    ax.set_title(
        "Larouco — Serie diaria de pernoctantes flotantes (MITMA)",
        fontsize=13, fontweight="bold",
    )
    ax.set_ylabel("Personas estimadas (flotantes)")
    ax.set_xlabel("")
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"{x:,.0f}"))
    ax.legend(fontsize=9)
    plt.tight_layout()
    fig.savefig(ruta_png, dpi=150)
    plt.close(fig)
    logger.info(f"Serie temporal guardada: {ruta_png}")


# ------------------------------------------------------------------------------
# PASO 6: EXPORTACIÓN
# ------------------------------------------------------------------------------

def export_results(
    df_raw: pd.DataFrame,
    serie: pd.DataFrame,
    resumen: pd.DataFrame,
    output_dir: Path,
    logger: logging.Logger,
) -> dict:
    """
    Exporta todos los artefactos de datos a la carpeta de salida. Cada
    exportación es independiente: un fallo en un formato no interrumpe
    el resto.
    """
    rutas = {}

    exportaciones = [
        ("parquet_raw",   output_dir / "pernoctaciones_larouco_raw.parquet",
         lambda: df_raw.to_parquet(output_dir / "pernoctaciones_larouco_raw.parquet", index=False)),
        ("csv_diario",    output_dir / "poblacion_flotante_diaria.csv",
         lambda: serie.to_csv(output_dir / "poblacion_flotante_diaria.csv", index=False, date_format="%Y-%m-%d")),
        ("csv_resumen",   output_dir / "resumen_poblacion_flotante.csv",
         lambda: resumen.to_csv(output_dir / "resumen_poblacion_flotante.csv", index=False, float_format="%.2f")),
    ]

    for clave, ruta, fn in exportaciones:
        try:
            fn()
            rutas[clave] = str(ruta)
            logger.info(f"Exportado: {ruta}")
        except Exception as e:
            logger.error(f"Error exportando {ruta}: {e}")

    return rutas


# ------------------------------------------------------------------------------
# MAIN / ORCHESTRACIÓN
# ------------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Población flotante de Larouco (MITMA) para AbeiroZero.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--start", default="2023-01-01",
        help="Fecha de inicio del período (YYYY-MM-DD). Por defecto: 2023-01-01.",
    )
    parser.add_argument(
        "--end", default="2023-12-31",
        help="Fecha de fin del período (YYYY-MM-DD). Por defecto: 2023-12-31.",
    )
    parser.add_argument(
        "--output", default="output",
        help="Carpeta de salida. Por defecto: ./output/",
    )
    parser.add_argument(
        "--cache-dir", default=".cache_mitma",
        help="Carpeta para caché de descargas. Por defecto: ./.cache_mitma/",
    )
    args = parser.parse_args()

    output_dir = Path(args.output)
    cache_dir = Path(args.cache_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    cache_dir.mkdir(parents=True, exist_ok=True)

    logger = configurar_logging(output_dir / "proceso.log")

    logger.info("=" * 60)
    logger.info("AbeiroZero — Módulo de población flotante (MITMA)")
    logger.info(f"Municipio: Larouco (INE {INE_LAROUCO})")
    logger.info(f"Período: {args.start} → {args.end}")
    logger.info("=" * 60)

    logger.warning(
        "AVISO METODOLÓGICO: Larouco tiene ~320 hab. empadronados. "
        "La muestra MITMA puede ser estadísticamente insuficiente en "
        "días individuales. Los datos deben interpretarse como estimaciones "
        "con posible subestimación, especialmente fuera de temporada alta."
    )

    try:
        # 1. Resolver ID MITMA
        mitma_id = resolve_mitma_id(str(cache_dir), logger)

        # 2. Descargar y filtrar pernoctaciones
        df_raw = download_overnight_stays(
            start_date=args.start,
            end_date=args.end,
            mitma_id=mitma_id,
            cache_dir=cache_dir,
            output_directory=str(cache_dir),
            logger=logger,
        )

        # 3. Calcular serie de población flotante diaria
        serie = compute_floating_population(df_raw, mitma_id, logger)

        # 4. Análisis estadístico orientado a riesgo
        resumen = analyze_risk_seasonality(serie, logger)

        # 5. Visualizaciones
        plot_heatmap(serie, output_dir / "mapa_calor_flotantes.png", logger)
        plot_serie_temporal(serie, output_dir / "serie_temporal_flotantes.png", logger)

        # 6. Exportar datos
        rutas = export_results(df_raw, serie, resumen, output_dir, logger)

        logger.info("=" * 60)
        logger.info("✅ Proceso completado. Archivos generados:")
        for clave, ruta in rutas.items():
            logger.info(f"  {clave}: {ruta}")
        logger.info(f"  heatmap:       {output_dir}/mapa_calor_flotantes.png")
        logger.info(f"  serie:         {output_dir}/serie_temporal_flotantes.png")
        logger.info(f"  log:           {output_dir}/proceso.log")
        logger.info("=" * 60)
        logger.info("Atribución obligatoria de datos: Ministerio de Transportes, "
                    "Movilidad y Agenda Urbana (MITMA) — OpenData Movilidad")

    except Exception as e:
        logger.error(f"ERROR FATAL: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()