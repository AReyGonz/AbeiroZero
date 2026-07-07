#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
=========================================================
POBLACIÓN POR NÚCLEO DE LAROUCO (IGE)
=========================================================

Obtiene:

- Código del núcleo
- Nombre del núcleo
- Población 0-14
- Población 15-64
- Población 65+

y genera:

    larouco_poblacion_por_nucleo.csv
"""

import pandas as pd
import requests

from io import StringIO

# ---------------------------------------------------------
# CONFIGURACIÓN
# ---------------------------------------------------------

ANO = 2025
TABLA_IGE = 1558
CODIGO_MUNICIPIO = "32038"

# Sustituir por el endpoint real del Nomenclátor
URL_NOMENCLATOR = "URL_API_NOMENCLATOR"

# ---------------------------------------------------------
# FUNCIONES
# ---------------------------------------------------------

def obtener_nucleos_municipio():
    """
    Devuelve:

        Village_Code
        Village_Name
    """

    print("Descargando núcleos desde el Nomenclátor del IGE...")

    r = requests.get(URL_NOMENCLATOR, timeout=30)
    r.raise_for_status()

    df = pd.read_csv(
        StringIO(r.text),
        sep=";"
    )

    df = df[
        df["CODIGO_MUNICIPIO"] == CODIGO_MUNICIPIO
    ]

    return df[
        [
            "CODIGO_NUCLEO",
            "NOMBRE_NUCLEO"
        ]
    ].rename(
        columns={
            "CODIGO_NUCLEO": "Village_Code",
            "NOMBRE_NUCLEO": "Village_Name"
        }
    )


def descargar_poblacion_nucleo(
    codigo_nucleo,
    nombre_nucleo
):
    """
    Descarga la estructura poblacional
    para un único núcleo.
    """

    url = (
        f"https://www.ige.gal/igebdt/igeapi/csv/datos/"
        f"{TABLA_IGE}/0:{ANO},9915:{codigo_nucleo}"
    )

    try:

        r = requests.get(
            url,
            timeout=20
        )

        r.raise_for_status()

        df = pd.read_csv(
            StringIO(r.text),
            sep=";"
        )

        resultado = {
            "Village_Code": codigo_nucleo,
            "Village_Name": nombre_nucleo,
            "Population_0_14": 0,
            "Population_15_64": 0,
            "Population_65_plus": 0,
        }

        if (
            "Idade" not in df.columns
            or
            "Dato" not in df.columns
        ):
            return resultado

        df["Dato"] = pd.to_numeric(
            df["Dato"],
            errors="coerce"
        ).fillna(0)

        for _, fila in df.iterrows():

            grupo = str(fila["Idade"])
            valor = int(fila["Dato"])

            if "0-14" in grupo:
                resultado["Population_0_14"] = valor

            elif "15-64" in grupo:
                resultado["Population_15_64"] = valor

            elif "65" in grupo:
                resultado["Population_65_plus"] = valor

        return resultado

    except Exception as e:

        print(
            f"Error en {nombre_nucleo}: {e}"
        )

        return None


def descargar_todos_los_nucleos():

    nucleos = obtener_nucleos_municipio()

    resultados = []

    for _, fila in nucleos.iterrows():

        print(
            f"Procesando {fila['Village_Name']}..."
        )

        datos = descargar_poblacion_nucleo(
            fila["Village_Code"],
            fila["Village_Name"]
        )

        if datos:
            resultados.append(datos)

    return pd.DataFrame(resultados)


# ---------------------------------------------------------
# MAIN
# ---------------------------------------------------------

def main():

    df = descargar_todos_los_nucleos()

    print()
    print(df)

    archivo = (
        "larouco_poblacion_por_nucleo.csv"
    )

    df.to_csv(
        archivo,
        index=False
    )

    print()
    print(
        f"Archivo generado: {archivo}"
    )


if __name__ == "__main__":
    main()