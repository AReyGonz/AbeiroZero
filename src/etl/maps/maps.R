#!/usr/bin/env Rscript
# -*- coding: utf-8 -*-

# ==============================================================================
# GENERADOR DEL MAPA DE SUSCEPTIBILIDAD FORESTAL
# Combina los outputs del FBP (ROS, HFI, CFB) mediante Álgebra de Mapas
# ==============================================================================

suppressPackageStartupMessages({
  library(terra)
})

DIR_OUTPUT <- "output"

cat("🗺️ Iniciando motor de Álgebra de Mapas para Susceptibilidad...\n")

# 1. CARGA DE RESULTADOS DEL FBP
# ==========================================================
# Leemos los rasters generados por fbp_calculator.R
ros <- rast(file.path(DIR_OUTPUT, "fbp_ros_velocidad.tif"))
hfi <- rast(file.path(DIR_OUTPUT, "fbp_hfi_intensidad.tif"))
cfb <- rast(file.path(DIR_OUTPUT, "fbp_cfb_copas.tif"))

# 2. NORMALIZACIÓN DE VARIABLES (Escala 0 a 1)
# ==========================================================
# Para sumar peras con manzanas, debemos llevar todo a la misma escala matemática.

# a) Velocidad (ROS): Consideramos 30 m/min como un valor extremo (saturación a 1)
ros_norm <- ros / 30.0
ros_norm <- clamp(ros_norm, lower = 0, upper = 1)

# b) Intensidad (HFI): Consideramos 10,000 kW/m como el límite de control humano (saturación a 1)
# Más de 10,000 es fuego catastrófico.
hfi_norm <- hfi / 10000.0
hfi_norm <- clamp(hfi_norm, lower = 0, upper = 1)

# c) Fuego de Copas (CFB): Ya viene de fábrica en escala 0 a 1 (probabilidad).
cfb_norm <- cfb

# 3. ECUACIÓN DE SUSCEPTIBILIDAD (FHI - Fire Hazard Index)
# ==========================================================
# Ponderamos la importancia de cada factor. 
# Ej: 40% velocidad, 40% intensidad, 20% fuego de copas.
# Multiplicamos por 100 para tener un índice de 0 a 100.

cat("🧮 Calculando Índice Ponderado...\n")
peso_ros <- 0.4
peso_hfi <- 0.4
peso_cfb <- 0.2

susceptibilidad_continua <- ((ros_norm * peso_ros) + (hfi_norm * peso_hfi) + (cfb_norm * peso_cfb)) * 100

# 4. RECLASIFICACIÓN TÁCTICA (Niveles de Peligro)
# ==========================================================
# A Protección Civil no le vale un número (ej. 67.4), necesita colores/niveles.
# 0-20: Muy Bajo | 20-40: Bajo | 40-60: Moderado | 60-80: Alto | 80-100: Extremo

matriz_clasificacion <- matrix(c(
  0,  20, 1,   # Nivel 1: Muy Bajo
  20, 40, 2,   # Nivel 2: Bajo
  40, 60, 3,   # Nivel 3: Moderado
  60, 80, 4,   # Nivel 4: Alto
  80, 100, 5   # Nivel 5: Extremo
), ncol=3, byrow=TRUE)

susceptibilidad_clases <- classify(susceptibilidad_continua, matriz_clasificacion, include.lowest=TRUE)

# 5. EXPORTACIÓN
# ==========================================================
cat("💾 Exportando mapas finales...\n")

# Guardamos la versión continua (0-100) para analistas GIS
writeRaster(susceptibilidad_continua, file.path(DIR_OUTPUT, "susceptibilidad_continua.tif"), overwrite=TRUE)

# Guardamos la versión discreta (1-5) para visores web o PDFs
writeRaster(susceptibilidad_clases, file.path(DIR_OUTPUT, "susceptibilidad_clases.tif"), overwrite=TRUE, datatype="INT1U")

# Generar un PNG rápido de previsualización
png(file.path(DIR_OUTPUT, "mapa_susceptibilidad_preview.png"), width=800, height=800, res=150)
paleta_riesgo <- c("#00FF00", "#FFFF00", "#FFA500", "#FF0000", "#800080") # Verde, Amarillo, Naranja, Rojo, Morado
plot(susceptibilidad_clases, col=paleta_riesgo, main="Mapa de Susceptibilidad a Incendios (Larouco)", 
     legend=FALSE, axes=FALSE)
# Añadimos leyenda customizada
legend("bottomleft", legend=c("Muy Bajo", "Bajo", "Moderado", "Alto", "Extremo"), 
       fill=paleta_riesgo, bty="n", title="Nivel de Peligro")
dev.off()

cat("✅ Proceso completado. Mapa final guardado como: susceptibilidad_clases.tif\n")