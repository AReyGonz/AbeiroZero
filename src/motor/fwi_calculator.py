import sqlite3
from datetime import datetime, timedelta
from fwi import FWI

# ==========================================
# CONFIGURACIÓN
# ==========================================
DB_FILE = "meteogalicia_larouco.sqlite"

def inicializar_db_forestal():
    """Asegura que la tabla de memoria forestal exista."""
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS fwi_estado (
            fecha TEXT PRIMARY KEY,
            ffmc REAL,
            dmc REAL,
            dc REAL,
            fwi REAL
        )
    ''')
    conn.commit()
    conn.close()

def obtener_memoria_forestal():
    """Recupera el estado de sequía (FFMC, DMC, DC) del cálculo anterior."""
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT ffmc, dmc, dc FROM fwi_estado ORDER BY fecha DESC LIMIT 1")
    row = c.fetchone()
    conn.close()
    
    if row:
        return {"ffmc": row[0], "dmc": row[1], "dc": row[2]}
    return {"ffmc": 85.0, "dmc": 6.0, "dc": 15.0}

def guardar_nuevo_estado_forestal(fecha, fwi_calc):
    """Guarda la nueva 'memoria' para que el motor la lea mañana."""
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('''
        INSERT INTO fwi_estado (fecha, ffmc, dmc, dc, fwi)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(fecha) DO REPLACE
    ''', (fecha, fwi_calc.ffmc, fwi_calc.dmc, fwi_calc.dc, fwi_calc.fwi))
    conn.commit()
    conn.close()

def interpretar_riesgo(fwi_val):
    if fwi_val < 5.2: return "Bajo 🟢"
    if fwi_val < 11.2: return "Moderado 🟡"
    if fwi_val < 21.3: return "Alto 🟠"
    if fwi_val < 38.0: return "Muy Alto 🔴"
    return "Extremo 🟣"

def calcular_fwi():
    inicializar_db_forestal()
    
    # 1. Consultar Base de Datos para obtener la última lectura real disponible
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    
    c.execute("SELECT temperatura, humedad, viento_vel, timestamp FROM meteo_10min ORDER BY timestamp DESC LIMIT 1")
    ult_registro = c.fetchone()
    
    if not ult_registro:
        print("⚠ Error: La base de datos está vacía. Ejecuta el script de ingesta primero.")
        conn.close()
        return

    temp, hr, viento, ts_medida = ult_registro
    
    # Estandarizar lectura temporal sin "Z"
    ts_medida_limpio = ts_medida.replace("Z", "")
    
    # 2. Definir Ventana Temporal basada en el timestamp real de la medición
    try:
        dt_objetivo = datetime.strptime(ts_medida_limpio, "%Y-%m-%dT%H:%M:%S")
    except ValueError:
        # Alternativa por si el formato de la API viene recortado
        dt_objetivo = datetime.strptime(ts_medida_limpio.split(".")[0], "%Y-%m-%dT%H:%M:%S")
        
    dt_hace_24h = dt_objetivo - timedelta(hours=24)
    
    str_ahora = dt_objetivo.strftime("%Y-%m-%dT%H:%M:%S")
    str_24h = dt_hace_24h.strftime("%Y-%m-%dT%H:%M:%S")

    # Lluvia ACUMULADA real en esa ventana temporal
    c.execute("SELECT SUM(precipitacion) FROM meteo_10min WHERE timestamp >= ? AND timestamp <= ?", (str_24h, str_ahora))
    lluvia_24h = c.fetchone()[0] or 0.0
    conn.close()
    
    # 3. Preparar variables para el FWI
    mes_actual = dt_objetivo.month
    memoria = obtener_memoria_forestal()

    # 4. Cálculo Matemático (Librería FWI)
    fwi_calc = FWI(
        temp, hr, viento, lluvia_24h,
        memoria["ffmc"], memoria["dmc"], memoria["dc"],
        mes_actual
    )
    
    # 5. Persistencia utilizando la fecha del registro procesado
    guardar_nuevo_estado_forestal(dt_objetivo.strftime("%Y-%m-%d"), fwi_calc)

    # 6. Reporte Final
    print("\n" + "="*45)
    print(f"🔥 REPORTE FWI LAROUCO ({ts_medida_limpio}) 🔥")
    print("="*45)
    print(f"🌧️ Lluvia Acumulada (24h): {lluvia_24h:.1f} mm")
    print(f"🌡️ Temp: {temp}ºC | 💧 HR: {hr}% | 💨 Viento: {viento} km/h\n")
    print("CÓDIGOS DE SEQUÍA (Memoria):")
    print(f"  FFMC (Superficie): {fwi_calc.ffmc:.1f}")
    print(f"  DMC (Humus):       {fwi_calc.dmc:.1f}")
    print(f"  DC (Profundo):     {fwi_calc.dc:.1f}\n")
    print("CÓDIGOS DE COMPORTAMIENTO:")
    print(f"  ISI (Propagación): {fwi_calc.isi:.1f}")
    print(f"  BUI (Combustible): {fwi_calc.bui:.1f}")
    print("-" * 45)
    print(f"📊 ÍNDICE FWI GLOBAL: {fwi_calc.fwi:.1f} -> Nivel: {interpretar_riesgo(fwi_calc.fwi)}")
    print("="*45)

if __name__ == "__main__":
    calcular_fwi()
    