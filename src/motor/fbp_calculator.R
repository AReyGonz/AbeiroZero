#!/usr/bin/env Rscript
# -*- coding: utf-8 -*-

# ==============================================================================
# MOTOR FBP ESPACIAL (Larouco)
# Integra: Topografía (DEM), Combustibles (MFE), Satélite (Sentinel-2) y Meteo (SQLite)
# Autor: Arquitecto Forestal
# ==============================================================================

# Cargar librerías
suppressPackageStartupMessages({
  library(terra)      # Procesamiento raster ultrarrápido
  library(sf)         # Procesamiento vectorial
  library(cffdrs)     # Ecuaciones oficiales FWI/FBP
  library(RSQLite)    # Lectura de la BD de MeteoGalicia
  library(dplyr)      # Manipulación de datos
})

# ==========================================================
# 1. CONFIGURACIÓN Y RUTAS (Ajusta según tu árbol de carpetas)
# ==========================================================
DIR_OUTPUT <- "output"
DB_PATH    <- "data/db/meteogalicia_larouco.sqlite" # Ajusta a la ruta real de tu BD

# ==========================================================
# 2. LECTURA DE METEOROLOGÍA Y FWI (Desde SQLite)
# ==========================================================
cat("[1/6] Leyendo condiciones meteorológicas y FWI...\n")

con <- dbConnect(RSQLite::SQLite(), DB_PATH)

# Obtener última meteorología (Viento)
meteo <- dbGetQuery(con, "SELECT viento_vel, viento_dir FROM meteo_10min ORDER BY timestamp DESC LIMIT 1")
# Obtener última memoria FWI
fwi <- dbGetQuery(con, "SELECT ffmc, bui FROM fwi_estado ORDER BY fecha DESC LIMIT 1")
dbDisconnect(con)

# Si no hay datos (ej. primera ejecución), ponemos valores por defecto de riesgo alto
FFMC_VAL <- ifelse(nrow(fwi) > 0, fwi$ffmc, 90.0)
BUI_VAL  <- ifelse(nrow(fwi) > 0, fwi$bui, 60.0)
WS_VAL   <- ifelse(nrow(meteo) > 0, meteo$viento_vel, 15.0)
WD_VAL   <- ifelse(nrow(meteo) > 0, meteo$viento_dir, 180.0) # Viento Sur

cat(sprintf("  -> FFMC: %.1f | BUI: %.1f | Viento: %.1f km/h Dir: %.0fº\n", FFMC_VAL, BUI_VAL, WS_VAL, WD_VAL))

# ==========================================================
# 3. LECTURA Y ALINEACIÓN ESPACIAL (Topografía y Satélite)
# ==========================================================
cat("[2/6] Cargando capas Raster (DEM y Sentinel-2)...\n")

# Usaremos la pendiente como raster "Master" para la resolución y extensión
slope_pct <- rast(file.path(DIR_OUTPUT, "larouco_slope_pct.tif"))
aspect    <- rast(file.path(DIR_OUTPUT, "larouco_aspect.tif"))
ndmi      <- rast(file.path(DIR_OUTPUT, "ndmi.tif"))

# Alinear Sentinel-2 (10m) al DEM (30m) si no coinciden exactamente
if (!ext(slope_pct) == ext(ndmi) || !res(slope_pct) == res(ndmi)) {
  ndmi <- resample(ndmi, slope_pct, method="bilinear")
}

# ==========================================================
# 4. PROCESAMIENTO DE COMBUSTIBLES (Vector a Raster)
# ==========================================================
cat("[3/6] Procesando Mapa de Combustibles...\n")

fuels_sf <- st_read(file.path(DIR_OUTPUT, "larouco_combustibles.gpkg"), quiet = TRUE)

# NOTA: Como en tu script python el fuel_type dice "SIN_CLASIFICAR", 
# aquí simularemos un diccionario de traducción genérico asumiendo que tu 
# ETL de Python se actualice para escupir especies.
# Para el FBP, necesitamos códigos estándar: C-1 a C-7, D-1, M-1 a M-4, S-1 a S-3, O-1.
fuels_sf <- fuels_sf %>%
  mutate(fbp_code = case_when(
    fuel_type == "Pinus pinaster" ~ "C-6",
    fuel_type == "Eucalyptus" ~ "M-3",
    fuel_type == "Matorral" ~ "O-1a",
    TRUE ~ "C-6" # Valor por defecto seguro para simulaciones forestales en Galicia
  ))

# Convertimos a factor temporal para poder rasterizar
fuels_sf$fbp_id <- as.numeric(as.factor(fuels_sf$fbp_code))
diccionario_combustibles <- data.frame(
  id = unique(fuels_sf$fbp_id),
  fbp_code = unique(fuels_sf$fbp_code)
)

# Rasterizar el polígono usando la rejilla del DEM
fuels_rast <- rasterize(vect(fuels_sf), slope_pct, field="fbp_id")

# ==========================================================
# 5. CALIBRACIÓN DEL FMC MEDIANTE NDMI (La innovación)
# ==========================================================
cat("[4/6] Calibrando Humedad Foliar (FMC) con Sentinel-2 NDMI...\n")

# El Foliar Moisture Content (FMC) por defecto en verano es ~97%.
# Usaremos el NDMI para alterarlo espacialmente. NDMI bajo = sequía = FMC bajo.
# Fórmula empírica lineal simple para el ejemplo:
fmc_rast <- 97 + (ndmi * 30) 
# Limitamos los valores a márgenes biológicos razonables (80% muy seco, 120% muy húmedo)
fmc_rast <- clamp(fmc_rast, lower=80, upper=120)

# ==========================================================
# 6. PREPARACIÓN DEL DATAFRAME PARA CFFDRS
# ==========================================================
cat("[5/6] Estructurando datos para el motor matemático...\n")

# Extraemos las coordenadas de cada píxel
coords <- crds(slope_pct)

# Unimos todos los rasters en un solo bloque (stack)
stack_fbp <- c(fuels_rast, slope_pct, aspect, fmc_rast)
names(stack_fbp) <- c("fuel_id", "GS", "SA", "FMC")

# Convertimos a DataFrame (solo los píxeles que no son NA)
df_pixels <- as.data.frame(stack_fbp, xy=TRUE, na.rm=TRUE)

# Recuperamos el string ("C-6", etc.) cruzando con el diccionario
df_pixels <- merge(df_pixels, diccionario_combustibles, by.x="fuel_id", by.y="id")

# Renombramos y añadimos las variables meteorológicas constantes
fbp_input <- df_pixels %>%
  rename(FUELTYPE = fbp_code, LONG = x, LAT = y) %>%
  mutate(
    ID = row_number(),
    FFMC = FFMC_VAL,
    BUI  = BUI_VAL,
    WS   = WS_VAL,
    WD   = WD_VAL,
    DJ   = as.POSIXlt(Sys.Date())$yday + 1 # Día Juliano
  )

# ==========================================================
# 7. EJECUCIÓN DEL CFFDRS (FBP)
# ==========================================================
cat("[6/6] Calculando predicción de comportamiento de fuego (FBP)...\n")

# La magia ocurre aquí. Calcula ROS (Rate of spread), HFI (Intensity), CFB (Crown Fire), etc.
fbp_output <- fbp(fbp_input)

# Unimos el resultado espacial de vuelta con sus coordenadas
resultado_espacial <- cbind(fbp_input[, c("LONG", "LAT")], fbp_output)

# ==========================================================
# 8. EXPORTACIÓN A RASTER (TIFFs)
# ==========================================================
cat("Exportando mapas de riesgo a GeoTIFF...\n")

# Función helper para volver a convertir la columna a Raster
export_to_tiff <- function(df, col_name, filename) {
  r <- rast(df[, c("LONG", "LAT", col_name)], type="xyz", crs=crs(slope_pct))
  writeRaster(r, file.path(DIR_OUTPUT, filename), overwrite=TRUE)
}

# Exportamos las 3 variables tácticas más importantes:
# 1. ROS (Rate of Spread - m/min)
export_to_tiff(resultado_espacial, "ROS", "fbp_ros_velocidad.tif")
# 2. HFI (Head Fire Intensity - kW/m)
export_to_tiff(resultado_espacial, "HFI", "fbp_hfi_intensidad.tif")
# 3. CFB (Crown Fire Fraction - Probabilidad fuego de copas 0-1)
export_to_tiff(resultado_espacial, "CFB", "fbp_cfb_copas.tif")

cat("\n✅ ¡ÉXITO! Análisis FBP completado. Archivos generados:\n")
cat("  - output/fbp_ros_velocidad.tif\n")
cat("  - output/fbp_hfi_intensidad.tif\n")
cat("  - output/fbp_cfb_copas.tif\n")
