import pandas as pd
import requests
from io import StringIO

def descargar_poblacion_larouco_estandar():
    """
    Descarga la población de Larouco ya agrupada en los rangos estándar del IGE 
    (0-14, 15-64, 65+) sin necesidad de post-procesamiento.
    """
    print("Conectando con la API del IGE...")
    
    # URL de la API CSV del IGE apuntando a una tabla de "Grandes grupos de edad"
    # Nota: Sustituye 'XXXX' por el código de la tabla exacta tras generarla en la web del IGE
    # 9915:32038 es el filtro territorial para Larouco
    # url_ige_csv = "https://www.ige.gal/igebdt/igeapi/csv/datos/XXXX/9915:32038" 
    url_ige_csv = "https://www.ige.gal/igebdt/igeapi/csv/datos/1558/0:2025,9915:32038"
    try:
        # 1. Extracción (Petición HTTP)
        respuesta = requests.get(url_ige_csv, timeout=15)
        respuesta.raise_for_status()
        
        # 2. Carga directa en Pandas
        # El IGE usa punto y coma como separador
        df = pd.read_csv(StringIO(respuesta.text), sep=";")
        
        # 3. Filtrado rápido y limpieza de columnas
        # Nos quedamos solo con la columna del grupo de edad y el valor numérico
        # (Ajusta los nombres 'Idade' y 'Dato' si la tabla del IGE usa otros exactos)
        if 'Idade' in df.columns and 'Dato' in df.columns:
            df_resumen = df[['Idade', 'Dato']].copy()
            df_resumen.columns = ['Grupo de Edad (IGE)', 'Población']
            
            # Aseguramos que la población sea un número entero
            df_resumen['Población'] = pd.to_numeric(df_resumen['Población'], errors='coerce').fillna(0).astype(int)
            
            print("\n✔ Datos obtenidos y procesados:\n")
            print(df_resumen.to_markdown(index=False))
            
            # 4. Exportación
            archivo_salida = "larouco_poblacion_ige.csv"
            df_resumen.to_csv(archivo_salida, index=False)
            print(f"\nArchivo guardado con éxito en: {archivo_salida}")
        else:
            print("⚠ Advertencia: El CSV no contiene las columnas esperadas ('Idade', 'Dato').")
            print("Cabeceras disponibles:", df.columns.tolist())

    except requests.exceptions.RequestException as e:
        print(f"❌ Error de red al conectar con el IGE: {e}")

if __name__ == "__main__":
    descargar_poblacion_larouco_estandar()