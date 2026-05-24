# Evaluación de preparación para PyPI — 20 criterios

**Paquete:** rues-linker · **Versión evaluada:** v2.12.0 (medida) → ajustes aplicados en v2.13.0
**Fecha:** 2026-05-23 · **Escala:** 0 (ausente) a 10 (clase mundial)

> Todas las notas se midieron empíricamente sobre el paquete real: cobertura con
> pytest-cov, build con `python -m build`, validación con `twine check`,
> contenido del wheel inspeccionado, dependencias verificadas. No son estimaciones
> de memoria.

---

## Resumen

| Indicador | Valor |
|---|---|
| Promedio global (20 criterios) | **5.4 / 10** |
| Núcleo técnico (7 criterios sólidos) | 7.6 / 10 |
| Validación / datos (3 criterios) | 3.2 / 10 |
| Bloqueantes PyPI en v2.12.0 | 2 críticos (licencia, py.typed) |
| Bloqueantes PyPI en v2.13.0 | **0** (resueltos en Fase 0) |

---

## Tabla completa (ordenada de mayor a menor)

| # | Criterio | Nota /10 | Estado | Comentario |
|---|---|---:|---|---|
| 1 | Paridad scorer vectorizado | 9 | Sólido | Paridad bit-a-bit con oráculo de regresión (`tests/test_paridad_p1_1.py`). No tocar. |
| 2 | Arquitectura y separación de capas | 8 | Sólido | 129 archivos, capas limpias (engine, pipeline, deduplication, golden). |
| 3 | Suite de tests verde | 8 | Sólido | 235/235 pasan. Robusta en lo que cubre. |
| 4 | CI/CD (lint, matriz, build, publish) | 8 | Sólido | GitHub Actions: ruff, pytest 3.10-3.12, build, twine, trusted publishing OIDC. |
| 5 | Motor on-disk (escala memoria) | 8 | Sólido | Modo disk_based para >1M registros. 14 tests de disco verdes. |
| 6 | Manejo de regímenes con/sin NIT | 7 | Sólido | Perfiles separados; IDF opt-in para sin-NIT. Decisión de diseño correcta. |
| 7 | Reproducibilidad (oráculo, réplicas) | 7 | Sólido | Scripts de réplica por versión + oráculo serializado. |
| 8 | Docstrings y comentarios | 7 | Medio | `deduplicate_unified` con docstring de 2.161 chars. Cobertura desigual. |
| 9 | Config centralizada (perfiles) | 7 | Medio | `extra_features` configurable (column/weight/type). Falta calibrar pesos con datos. |
| 10 | Empaquetado (pyproject, build) | 6 | Medio | Build y twine pasan. En v2.13.0 sube tras añadir py.typed y MANIFEST.in. |
| 11 | README y documentación de usuario | 5 | Medio | Existe y tiene ejemplos, pero falta guía de instalación PyPI y quickstart pulido. |
| 12 | API pública (namespace, exports) | 5 | Medio | `__all__` raíz solo expone Config/Rutas/__version__; falta exportar `deduplicate_unified`. |
| 13 | Type hints declarados (py.typed) | 4 | Débil | Código tiene type hints pero NO declaraba py.typed. RESUELTO en v2.13.0 → sube a ~7. |
| 14 | Dependencias (limpieza, peso) | 4 | Débil | Arrastra fuzzywuzzy (muerta) y python-Levenshtein (redundante con rapidfuzz). Viz pesado en base. |
| 15 | Cobertura de tests | 4 | Débil | 40% sobre 11.421 líneas. Smoke alto, lógica de negocio media. |
| 16 | Manejo de errores / validación entrada | 4 | Débil | Validación básica presente; faltan mensajes claros y validación exhaustiva de entradas. |
| 17 | Benchmarks de escala (2-4M medido) | 2 | Débil | Nada medido sobre >1.456 registros. Rendimiento real a escala desconocido. |
| 18 | Ground truth a escala real | 2 | Débil | Solo datasets ≤1.456. Falta base de verdad grande y estratificada. |
| 19 | Calidad medida sin-NIT (F1 real) | 2 | Débil | Régimen sin-NIT validado solo cualitativamente, sin F1. |
| 20 | Licencia compatible con PyPI | 1 | Bloqueante | Era "Proprietary" sin archivo LICENSE. RESUELTO en v2.13.0 (LICENSE propietario + nota para abrir). |

---

## Cambios aplicados en v2.13.0 (Fase 0)

Tres criterios suben tras la Fase 0:

- **#20 Licencia:** de 1 → resuelto. Archivo `LICENSE` propietario añadido, con
  instrucciones para migrar a MIT/Apache-2.0 si se decide abrir. `pyproject.toml`
  apunta al archivo y declara el classifier. (Nota: licencia propietaria NO permite
  PyPI público; para pypi.org hay que cambiar a una licencia open source.)
- **#13 py.typed:** de 4 → ~7. Marcador PEP 561 creado e incluido en el wheel
  (verificado en el `.whl`).
- **#10 Empaquetado:** de 6 → ~7. `MANIFEST.in` añadido; sdist y wheel limpios;
  twine check pasa.

Promedio global tras Fase 0: ~5.4 → ~5.9.

---

## Orden de impacto para subir la nota global

1. **Fase 1 — Ground truth a escala** (criterios #17, #18, #19): el techo de
   calidad lo pone el dato, no el código. Mover estos tres de 2 a 7 sube el
   promedio más que cualquier otra cosa.
2. **Fase 2 — Limpieza** (#12, #14, #15): exportar API, quitar deps muertas,
   cobertura 40→65%. Fácil y visible.
3. **Fase 3 — Calibración automática** (#9): Optuna contra ground truth. Solo
   tiene valor DESPUÉS de la Fase 1.

Camino crítico: **licencia (hecho) → ground truth → medir → publicar.**
