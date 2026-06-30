"""
Descarga la última lectura disponible (resolución 10 minutos) de la estación
de Larouco (MeteoGalicia API REST, sin API key) y la guarda en un JSON.

Estación: Larouco, idEstacion = 19030
Endpoint: https://servizos.meteogalicia.gal/mgrss/observacion/ultimos10minEstacionsMeteo.action

Por qué este endpoint:
  Es el más granular disponible (10 min) y devuelve directamente un único
  objeto por estación con instanteLecturaUTC + listaMedidas, sin envoltorios
  de listas de instantes ni necesidad de ordenar/elegir el más reciente:
  ya es, por definición, la última lectura. Más eficiente que el horario
  (ultimosHorariosEstacions) y mucho más que el diario (datosDiarios...).

Códigos de parámetro CONFIRMADOS con respuesta real de la API para esta
estación en este endpoint:
  - TA_AVG_1.5m    -> temperatura (a 1.5m; existe también TA_AVG_0.1m, no se usa)
  - HR_AVG_1.5m    -> humedad relativa media
  - VV_AVG_10m     -> velocidad del viento media a 10m (SÍ presente aquí,
                       a diferencia del endpoint horario)
  - DV_AVG_10m     -> dirección del viento media a 10m
  - PP_SUM_1.5m    -> precipitación (chuvia)

Nota sobre validación: en el ejemplo real, PP_SUM_1.5m viene con
lnCodigoValidacion=3 ("dato erróneo") aunque su valor sea 0.0, y HF_SUM_2m
también validación=3. El script no descarta estos datos automáticamente,
pero expone el flag "validado" en la salida para que el consumidor del
JSON pueda decidir si confiar en ellos.

Limpieza: en humedad, viento y precipitación, cualquier valor negativo
(MeteoGalicia usa -9999.0 para "no disponible") se convierte a 0.
Temperatura no se toca: un negativo ahí es una helada real.

Manejo de caracteres especiales:
  La API devuelve texto en gallego con acentos, "ñ", etc. Se fuerza UTF-8
  tanto en la petición como en la escritura del JSON, capturando errores de
  codificación para que un carácter inesperado no tumbe el script.
"""

import json
import requests

ID_ESTACION = 19030
URL = "https://servizos.meteogalicia.gal/mgrss/observacion/ultimos10minEstacionsMeteo.action"
OUTPUT_FILE = "meteo_larouco_ultimo.json"

# Prefijos confirmados con la respuesta real de la API (endpoint 10min).
PARAMETROS = {
    "TA_AVG_1.5m": "temperatura",
    "HR_AVG": "humedad_relativa",
    "VV_AVG": "viento_velocidad",
    "DV_AVG": "viento_direccion",
    "PP_SUM": "precipitacion",
}

NO_NEGATIVOS = {"humedad_relativa", "viento_velocidad", "precipitacion"}


def limpiar_valor(valor, categoria):
    """Si la categoría no admite negativos, normaliza cualquier valor raro a 0."""
    if categoria not in NO_NEGATIVOS:
        return valor
    try:
        valor = float(valor)
        return valor if valor >= 0 else 0.0
    except (TypeError, ValueError):
        return 0.0


def texto_seguro(valor):
    """
    Normaliza cualquier texto que pueda venir con caracteres especiales
    (acentos, eñes, símbolos en gallego/español) a una cadena UTF-8 limpia.
    """
    if valor is None:
        return None
    try:
        if isinstance(valor, bytes):
            return valor.decode("utf-8", errors="replace")
        return str(valor)
    except (UnicodeDecodeError, UnicodeEncodeError):
        return None


def extraer_estacion(data):
    """
    Soporta tanto el formato observado realmente (objeto único o lista
    de objetos planos, uno por estación) como una posible envoltura tipo
    {"listEstacions": [...]}, por robustez ante cambios en la API.
    """
    if isinstance(data, dict) and "idEstacion" in data:
        # Respuesta de una sola estación, formato plano (caso esperado
        # al filtrar con idEst=19030)
        return data

    if isinstance(data, dict):
        # Posible envoltura con alguna clave de lista
        for clave in data:
            if isinstance(data[clave], list):
                data = data[clave]
                break

    if isinstance(data, list):
        for item in data:
            if str(item.get("idEstacion")) == str(ID_ESTACION):
                return item
        raise StopIteration

    raise TypeError("Formato de respuesta no reconocido")


def main():
    try:
        r = requests.get(
            URL,
            params={"idEst": ID_ESTACION},
            timeout=20,
        )
        r.raise_for_status()
        r.encoding = "utf-8"
        data = r.json()
    except requests.RequestException as e:
        raise SystemExit(f"Error al llamar a la API de MeteoGalicia: {e}")
    except json.JSONDecodeError as e:
        raise SystemExit(f"La API no devolvió JSON válido: {e}")
    except UnicodeDecodeError as e:
        raise SystemExit(f"Error de codificación al leer la respuesta: {e}")

    try:
        estacion = extraer_estacion(data)
    except StopIteration:
        raise SystemExit(f"No se encontró la estación {ID_ESTACION} en la respuesta.")
    except (KeyError, TypeError) as e:
        raise SystemExit(f"Estructura de respuesta inesperada: {e}")

    medidas = {}
    for m in estacion.get("listaMedidas", []):
        codigo = m.get("codigoParametro", "") or ""
        for prefijo, categoria in PARAMETROS.items():
            if codigo.startswith(prefijo):
                medidas[categoria] = {
                    "valor": limpiar_valor(m.get("valor"), categoria),
                    "unidad": texto_seguro(m.get("unidade")),
                    "parametro": texto_seguro(m.get("nomeParametro")),
                    "validado": m.get("lnCodigoValidacion") == 1,
                }
                break

    resultado = {
        "concello": "Larouco",
        "idEstacion": ID_ESTACION,
        "fecha_utc": estacion.get("instanteLecturaUTC"),
        "medidas": medidas,
    }

    try:
        with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
            json.dump(resultado, f, ensure_ascii=False, indent=2)
    except (OSError, UnicodeEncodeError) as e:
        raise SystemExit(f"No se pudo guardar el archivo JSON: {e}")

    print(f"Guardado: {OUTPUT_FILE}")
    print(json.dumps(resultado, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()