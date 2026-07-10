import os
import requests
import pandas as pd
from datetime import datetime

# ==================================================
# CONFIGURACIÓN
# ==================================================

ID_ESTACION = 19030  # Larouco

URL_LIVE = (
    "https://servizos.meteogalicia.gal/mgrss/observacion/"
    "ultimos10minEstacionsMeteo.action"
)

CSV_FILE = "../data/sample/larouco_10min.csv"

# ==================================================
# UTILIDADES
# ==================================================

def to_float(valor):
    """Conversión robusta a float."""
    try:
        return float(valor)
    except (TypeError, ValueError):
        return None


def extraer_variables(lista_medidas):
    """
    Extrae únicamente las variables necesarias.
    """

    datos = {
        "temp_1_5m": None,
        "hr_1_5m": None,
        "vv_racha_10m": None,
        "pp_sum": None
    }

    for medida in lista_medidas:

        codigo = medida.get("codigoParametro", "")
        valor = to_float(medida.get("valor"))

        if codigo == "TA_AVG_1.5m":
            datos["temp_1_5m"] = valor

        elif codigo == "HR_AVG_1.5m":
            datos["hr_1_5m"] = valor

        elif codigo == "VV_RACHA_10m":
            datos["vv_racha_10m"] = valor

        elif codigo == "PP_SUM":
            datos["pp_sum"] = valor

    return datos


def guardar_csv(registro):
    """
    Guarda en CSV evitando duplicados por timestamp.
    """

    os.makedirs(os.path.dirname(CSV_FILE), exist_ok=True)

    if os.path.exists(CSV_FILE):

        df = pd.read_csv(CSV_FILE)

        if registro["timestamp"] in df["timestamp"].astype(str).values:
            print("Registro ya existente.")
            return

        df = pd.concat(
            [df, pd.DataFrame([registro])],
            ignore_index=True
        )

    else:
        df = pd.DataFrame([registro])

    df.sort_values("timestamp", inplace=True)

    df.to_csv(CSV_FILE, index=False)

    print(f"CSV actualizado: {CSV_FILE}")


# ==================================================
# INGESTA
# ==================================================

def main():

    try:

        r = requests.get(
            URL_LIVE,
            params={"idEst": ID_ESTACION},
            timeout=20
        )

        r.raise_for_status()

        data = r.json()

        estacion = next(
            (
                e
                for e in data.get("listEstacions", [data])
                if str(e.get("idEstacion")) == str(ID_ESTACION)
            ),
            None,
        )

        if estacion is None:
            print("Estación no encontrada.")
            return

        medidas = estacion.get("listaMedidas", [])

        variables = extraer_variables(medidas)

        registro = {
            "timestamp": estacion["instanteLecturaUTC"],
            **variables,
        }

        guardar_csv(registro)

        print(
            f"[{datetime.now():%Y-%m-%d %H:%M:%S}] "
            f"Ingesta correcta"
        )

    except requests.exceptions.RequestException as exc:
        print(f"Error de red: {exc}")

    except Exception as exc:
        print(f"Error inesperado: {exc}")


if __name__ == "__main__":
    main()