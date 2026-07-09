import sqlite3
import requests
from datetime import datetime

# ==========================================
# CONFIGURACIÓN
# ==========================================
DB_FILE = "meteogalicia_larouco.sqlite"
ID_ESTACION = 19030 # Larouco
URL_LIVE = "https://servizos.meteogalicia.gal/mgrss/observacion/ultimos10minEstacionsMeteo.action"

def inicializar_db():
    """Asegura que las tablas existan antes de insertar datos."""
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS meteo_10min (
            timestamp TEXT PRIMARY KEY,
            temperatura REAL,
            humedad REAL,
            viento_vel REAL,
            precipitacion REAL
        )
    ''')
    conn.commit()
    conn.close()

def guardar_lectura_db(timestamp, temp, hr, vel, precip):
    """Inserta la métrica en SQLite."""
    # Limpieza básica para estandarizar cadenas de texto de tiempo en SQLite
    timestamp_limpio = timestamp.replace("Z", "")
    
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    try:
        c.execute('''
            INSERT INTO meteo_10min (timestamp, temperatura, humedad, viento_vel, precipitacion)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(timestamp) DO UPDATE SET
                temperatura=excluded.temperatura,
                humedad=excluded.humedad,
                viento_vel=excluded.viento_vel,
                precipitacion=excluded.precipitacion
        ''', (timestamp_limpio, temp, hr, vel, precip))
        conn.commit()
    finally:
        conn.close()

def extraer_variables(medidas):
    """Limpia y extrae las variables del array de MeteoGalicia."""
    data = {"temp": 0.0, "hr": 0.0, "vel": 0.0, "precip": 0.0}
    for m in medidas:
        cod = m.get("codigoParametro", "")
        val = m.get("valor", -9999)
        val_seguro = float(val) if val is not None and float(val) >= 0 else 0.0
        
        # Corrección: Mantener lógica de asignación limpia evitando caídas por valores nulos
        if cod.startswith("TA_AVG"): data["temp"] = float(val) if val is not None else 0.0
        elif cod.startswith("HR_AVG"): data["hr"] = val_seguro
        elif cod.startswith("VV_AVG"): data["vel"] = val_seguro
        elif cod.startswith("PP_SUM"): data["precip"] = val_seguro
    return data

def main_ingesta():
    inicializar_db()
    try:
        r = requests.get(URL_LIVE, params={"idEst": ID_ESTACION}, timeout=15)
        r.raise_for_status()
        data = r.json()
        
        estacion = next((e for e in data.get("listEstacions", [data]) if str(e.get("idEstacion")) == str(ID_ESTACION)), None)
            
        if estacion and "listaMedidas" in estacion:
            timestamp = estacion["instanteLecturaUTC"]
            vars_meteo = extraer_variables(estacion["listaMedidas"])
            guardar_lectura_db(timestamp, vars_meteo["temp"], vars_meteo["hr"], vars_meteo["vel"], vars_meteo["precip"])
            print(f"[{datetime.now().strftime('%H:%M:%S')}] Ingesta OK -> {timestamp}")
            
            # Handoff Automático Activo:
            # Si quieres que el FWI corra inmediatamente después de la ingesta cada 10 min:
            try:
                from fwi_calculator import calcular_fwi
                print("Iniciando cálculo FWI encadenado...")
                calcular_fwi()
            except ImportError:
                print("Nota: fwi_calculator.py no acoplado directamente.")
        else:
            print("⚠ Estructura de la API inesperada o estación no encontrada.")
            
    except requests.exceptions.RequestException as e:
        print(f"❌ Error de red en ingesta: {e}")

if __name__ == "__main__":
    main_ingesta()