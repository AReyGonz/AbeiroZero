# AbeiroZero — Resumen ejecutivo
AbeiroZero es la parte de Abeiro dedicada a la ingesta de datos y el motor científico del proyecto.

## Estado del proyecto
AbeiroZero está **en desarrollo activo**, en fase de prototipo técnico. Ningún resultado, mapa o índice generado debe considerarse validado científica ni operacionalmente. El repositorio es una colección de piezas (ETLs + motores de cálculo), varias todavía no conectadas entre sí.

## Objetivo general
Construir una plataforma de apoyo a la decisión ante incendios forestales para Larouco (Ourense), que combine meteorología, satélite, terreno, combustible forestal, población y red viaria para generar un **mapa único de peligro de incendio**, interpretable sin conocimientos técnicos.

## Arquitectura funcional
- **Fuentes**:
MeteoGalicia: datos meteorológicos en tiempo real con resoluciones de 10 minutos.
Sentinel-2 (API STAC de Copernicus): seguimiento del vigor de la vegetación (NDVI) y de la humedad de la vegetación (NDMI) con una frecuencia aproximada de 5 días.
Copernicus DEM (GLO-30) – AWS: análisis del terreno mediante modelos digitales de elevación (pendiente, orientación y variables topográficas derivadas).
MFE25 (Mapa Forestal de España): cartografía forestal nacional adaptada a los modelos de combustible FBP (Fire Behaviour Prediction) utilizados en Canadá.
IGE (Instituto Galego de Estatística): datos demográficos, población y distribución por grupos de edad.
OpenStreetMap (OSM): red viaria, caminos, carreteras, núcleos de población y otros elementos territoriales.
EFFIS y Copernicus Emergency Management Service (COP-EMS): información histórica de incendios forestales y eventos de emergencia.
NASA FIRMS y EUMETSAT MTG: detección y monitorización de incendios activos casi en tiempo real.
- **ETLs** (`src/etl`): descargan y preparan cada fuente por separado.
- **Motores** (`src/motor`): calculan el índice meteorológico de incendio (FWI) y el comportamiento físico del fuego (FBP).
- **Producto final**: mapa de Índice de Peligro de Incendio (0-100, 5 niveles de color).

Hoy la cadena **no es automática**: cada script se ejecuta de forma manual e independiente.

## Inventario resumido de scripts

| Script | Categoría | Aporta al proyecto | Madurez |
|---|---|---|---|
| `boundary.py` | Utilidad SIG | Define el límite oficial de Larouco, usado por todos los ETL geográficos | Parcial — referencia módulos que no existen en el repo |
| `settings.py` | Configuración | Parámetros comunes (CRS, BD) | Prototipo — apenas usado por el resto |
| `etl_meteogalicia.py` | Meteorología | Descarga temperatura, humedad, viento, lluvia en tiempo real | En desarrollo — desconectado del cálculo FWI (formatos distintos) |
| `etl_estado_combustible_sentinel2.py` | Teledetección | Calcula NDVI/NDMI/FCI (humedad de la vegetación) vía satélite | Parcial — conexión real y funcional con el motor FBP |
| `etl_combustible_mfe.py` | Combustible forestal | Debería clasificar el tipo de vegetación por especie | **Pendiente de validación** — asigna "PENDIENTE_MAPEO" a todo el mapa |
| `etl_topo_dem.py` | Topografía | Pendiente y orientación del terreno (Copernicus DEM) | Parcial — error de programación detectado en el recorte |
| `etl_red_viaria_osm.py` | Red viaria | Carreteras, pistas y núcleos de población | En desarrollo — evacuación es solo un esquema, no código funcional |
| `etl_poblacion.py` | Población | Población por edad y núcleo (IGE) | **No ejecutable** — URL de configuración es un texto de relleno |
| `etl_poblacion_flotante_mitma.py` | Población | Climatología de población flotante (turismo) vía MITMA | En desarrollo — completo pero no integrado en el riesgo final |
| `etl_perimetros_effis.py` | Riesgo histórico | Extrae incendios históricos europeos en la zona | **No ejecutable** — ruta de archivo de entrada es un texto de relleno |
| `etl_perimetros_copernicus_ems.py` | Riesgo histórico | Busca activaciones europeas de emergencia por incendio grave | Experimental — script de consulta puntual |
| `fwi.py` | Cálculo de índices | Implementa el estándar canadiense FWI (peligro meteorológico) | El más maduro — fórmulas fieles a la referencia científica |
| `fwi_calculator.py` | Cálculo de índices | Orquesta el cálculo diario del FWI desde una base de datos local | En desarrollo — esa base de datos no se alimenta aún automáticamente |
| `fbp_calculator.R` | Motor de riesgo | Combina terreno + combustible + satélite + meteo para predecir comportamiento del fuego (velocidad, intensidad, fuego de copas) | **Pendiente de validación** — usa combustible y meteo "por defecto" ante datos incompletos |
| `maps.R` | Producto final | Combina los resultados del FBP en el mapa único de peligro (5 niveles) | **Pendiente de validación** — pesos y umbrales sin calibración documentada |

## Fuentes de datos principales

| Fuente | Organismo | Uso |
|---|---|---|
| MeteoGalicia | Xunta de Galicia | Meteorología en tiempo real |
| Sentinel-2 | Copernicus / ESA | Humedad y vigor de la vegetación |
| Copernicus DEM GLO-30 | UE / AWS | Terreno (pendiente, orientación) |
| MFE25 | MITECO | Base del mapa de combustible forestal |
| IGE | Xunta de Galicia | Población por edad y núcleo |
| MITMA | Ministerio de Transportes | Población flotante (turismo) |
| OpenStreetMap | Comunidad OSM | Límites, carreteras, núcleos |
| EFFIS / Copernicus EMS | UE | Histórico de incendios |

## Flujo de datos (diseño previsto)
1. Se delimita el municipio (`boundary.py`).
2. Se descargan en paralelo: meteorología, terreno, satélite, combustible, red viaria, población, histórico de incendios.
3. `fwi_calculator.py` calcula el peligro meteorológico diario (si hay datos disponibles).
4. `fbp_calculator.R` combina terreno + combustible + satélite + meteo para simular el comportamiento del fuego.
5. `maps.R` sintetiza todo en el mapa final de peligro (0-100, 5 niveles).
6. Población, red viaria e histórico de incendios están construidos pero **aún no integrados** en ese mapa final.

