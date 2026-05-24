"""
classifier.runner — record_linkage_pipeline

Componentes:
    - function ejecutar_proceso_clasificacion_directo  (origen: notebook celda [96])

NOTA: Lógica de negocio preservada exactamente como en el notebook
fuente. Solo se agregan imports, docstring de módulo y se eliminan
directivas de Jupyter (%%time, !pip, etc.). Ver MIGRATION_LOG.md.
"""

from __future__ import annotations

import gc
import os
import pickle
import time
from typing import Any

import pandas as pd

from .hybrid import ClasificadorHibridoOptimizado


def ejecutar_proceso_clasificacion_directo(
    df_a_clasificar: pd.DataFrame,
    columna_razon_social: str,
    realizar_entrenamiento: bool,
    config_modelo: dict[str, Any],
    df_entrenamiento_empresas: pd.DataFrame | None = None,
    col_entrenamiento_empresas: str | None = None,
    df_entrenamiento_personas: pd.DataFrame | None = None,
    col_entrenamiento_personas: str | None = None,
    ruta_guardado_modelo: str | None = None,
    batch_size: int = 250_000,
) -> tuple[pd.DataFrame, ClasificadorHibridoOptimizado]:
    """
    Clasificación DIRECTA - sin merge problemático.
    Clasifica todos los registros directamente.
    """
    inicio_proceso = time.time()

    print("=" * 70)
    print("🚀 CLASIFICACIÓN DIRECTA (SIN MERGE)")
    print("=" * 70)
    print(f"📊 Total de registros: {len(df_a_clasificar):,}")
    print(f"🔧 Configuración: batch_size={batch_size:,}")

    # Crear clasificador
    clasificador = ClasificadorHibridoOptimizado(config_modelo)

    if realizar_entrenamiento:
        if df_entrenamiento_empresas is None or df_entrenamiento_personas is None:
            raise ValueError("❌ Se requieren DataFrames de entrenamiento")

        print("\n🧠 Entrenando clasificador...")
        clasificador.entrenar(
            df_entrenamiento_empresas,
            col_entrenamiento_empresas,
            df_entrenamiento_personas,
            col_entrenamiento_personas,
        )

        if ruta_guardado_modelo:
            os.makedirs(os.path.dirname(ruta_guardado_modelo), exist_ok=True)
            with open(ruta_guardado_modelo, "wb") as f:
                pickle.dump(clasificador, f)
            print(f"💾 Modelo guardado en: {ruta_guardado_modelo}")
    else:
        if not ruta_guardado_modelo or not os.path.exists(ruta_guardado_modelo):
            raise FileNotFoundError(f"❌ Modelo no encontrado: {ruta_guardado_modelo}")
        with open(ruta_guardado_modelo, "rb") as f:
            clasificador = pickle.load(f)
        print(f"📂 Modelo cargado desde: {ruta_guardado_modelo}")

    # Clasificación por lotes
    n_records = len(df_a_clasificar)
    df_trabajo = df_a_clasificar.reset_index(drop=True).copy()

    if n_records <= batch_size:
        print("\n📝 Procesando en un único lote...")
        df_resultados = clasificador.clasificar_lote(df_trabajo[columna_razon_social])
    else:
        n_batches = (n_records + batch_size - 1) // batch_size
        print(f"\n📦 Dividiendo en {n_batches} lotes")

        result_chunks = []
        for batch_idx in range(n_batches):
            start_idx = batch_idx * batch_size
            end_idx = min((batch_idx + 1) * batch_size, n_records)
            print(f"\n🔄 Lote {batch_idx + 1}/{n_batches}: registros {start_idx:,} a {end_idx:,}")

            batch_series = df_trabajo[columna_razon_social].iloc[start_idx:end_idx]
            batch_results = clasificador.clasificar_lote(batch_series)
            result_chunks.append(batch_results)

            if batch_idx % 5 == 0:
                gc.collect()

        df_resultados = pd.concat(result_chunks, ignore_index=True)

    # Combinar con datos originales
    df_clasificado = pd.concat([df_trabajo, df_resultados], axis=1)

    # Marcar registros con RAZON_SOCIAL vacía como inválido
    mask_vacio = df_clasificado[columna_razon_social].isna() | (
        df_clasificado[columna_razon_social].astype(str).str.strip() == ""
    )
    n_vacios = mask_vacio.sum()
    if n_vacios > 0:
        df_clasificado.loc[mask_vacio, "clasificacion"] = "invalido"
        print(f"\n⚠️ {n_vacios:,} registros con RAZON_SOCIAL vacía marcados como inválido")

    # Análisis de resultados
    print("\n" + "=" * 70)
    print("📊 ANÁLISIS DE RESULTADOS")
    print("=" * 70)

    conteo = df_clasificado["clasificacion"].value_counts()
    conteo_pct = (conteo / len(df_clasificado) * 100).round(2)

    for tipo in ["empresa", "persona", "incierto", "invalido"]:
        if tipo in conteo.index:
            print(f"   {tipo.upper():<10}: {conteo[tipo]:>12,} ({conteo_pct[tipo]:>5.2f}%)")

    print(f"\n📈 Puntaje promedio: {df_clasificado['puntaje_total'].mean():.2f}")
    print(f"🌟 Regla de oro aplicada: {df_clasificado['regla_oro_aplicada'].sum():,} casos")

    tiempo_total = time.time() - inicio_proceso
    print(f"\n⚡ Tiempo total: {tiempo_total:.2f}s ({tiempo_total / 60:.2f} min)")
    print(f"⚡ Velocidad: {n_records / tiempo_total:,.0f} registros/segundo")

    print("\n" + "=" * 70)
    print("🎉 CLASIFICACIÓN COMPLETADA")
    print("=" * 70)

    return df_clasificado, clasificador
