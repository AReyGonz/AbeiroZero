# AbeiroZero

Arquitectura ETL y mapas para Abeiro.

## Estructura

```
src/
├── etl/        # scripts de extracción y transformación de datos
└── config/     # configuración no sensible (endpoints, constantes)
data/
├── raw/        # datos descargados sin procesar (no versionado)
└── processed/  # datos limpios/transformados (no versionado)
output/         # resultados finales, JSONs de salida (no versionado)
docs/           # documentación del proyecto
```

## Configuración

1. Copia `.env.example` a `.env`:
   ```powershell
   Copy-Item .env.example .env
   ```
2. Rellena `.env` con tus credenciales reales (Copernicus, etc.). Este archivo
   nunca se sube al repositorio.

## Instalación

```powershell
python -m pip install -r requirements.txt
```

## Scripts disponibles

- `src/etl/etl_MeteoGalicia.py` — descarga la última lectura (10 min) de la
  estación de MeteoGalicia en Larouco (id 19030) y la guarda en
  `output/meteo_larouco_ultimo.json`.

## Fuentes de datos

- **MeteoGalicia**: API REST pública, sin API key.
- **Copernicus Data Space Ecosystem (CDSE)**: requiere cuenta gratuita,
  usada para datos COP-DEM.
