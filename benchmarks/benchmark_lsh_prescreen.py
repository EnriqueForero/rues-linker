"""benchmarks/benchmark_lsh_prescreen.py — Benchmark reproducible.

Sprint 0.8.0 — Mide el impacto del NITPrescreener vs LSH puro.

Diseño:
    1. Genera dataset sintético reproducible (seed fijo)
    2. Mide tiempo de LSH puro
    3. Mide tiempo de Prescreener + LSH(residual)
    4. Calcula speedup y publica reporte
    5. Verifica que los pares encontrados son CONSISTENTES (no perder fusiones)

Uso:
    cd rues-linker
    python benchmarks/benchmark_lsh_prescreen.py --n 10000 --overlap 0.3
    python benchmarks/benchmark_lsh_prescreen.py --n 50000 --overlap 0.3 --seed 42

Reproducibilidad:
    - Seed fijo en numpy y random
    - Versión del paquete reportada
    - Hash del config
    - Outputs JSON estructurados
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

# Silenciar logger del paquete durante benchmark
logging.basicConfig(level=logging.WARNING)


@dataclass
class BenchmarkConfig:
    """Configuración del benchmark."""
    n_records: int = 10_000
    overlap_pct: float = 0.30  # % de registros con NIT compartido
    n_sources: int = 4
    seed: int = 42
    lsh_threshold: float = 0.58
    lsh_permutations: int = 252
    lsh_ngram: int = 2

    def to_hash(self) -> str:
        """Hash determinístico de la config (para reproducibilidad)."""
        s = json.dumps(asdict(self), sort_keys=True)
        return hashlib.sha256(s.encode()).hexdigest()[:12]


@dataclass
class BenchmarkResult:
    """Resultado de UNA corrida del benchmark."""
    config: dict[str, Any]
    config_hash: str
    timestamp: str
    paquete_version: str

    # Tiempos
    t_dataset_generation_s: float
    t_lsh_only_s: float
    t_prescreen_s: float
    t_lsh_residual_s: float
    t_combined_s: float  # prescreen + lsh_residual

    # Conteos
    n_input: int
    n_lsh_only_pairs: int
    n_prescreen_pairs: int
    n_lsh_residual_pairs: int
    n_combined_pairs: int  # prescreen + lsh_residual

    # Métricas clave
    speedup_lsh: float          # t_lsh_only / t_combined
    reduction_lsh_input: float  # 1 - (residual / input)
    recall_combined: float       # |combined ∩ lsh_only| / |lsh_only|

    metadata: dict[str, Any] = field(default_factory=dict)


def generar_dataset_sintetico(cfg: BenchmarkConfig) -> pd.DataFrame:
    """Genera dataset reproducible con overlap controlado.

    Estructura:
        - Cada registro tiene NIT_BASE y RAZON_SOCIAL
        - cfg.overlap_pct de los registros forman pares con NIT compartido
        - Las razones sociales son variaciones (mayúsculas, espacios extra, abreviaciones)
        - Cada registro asignado a una de cfg.n_sources fuentes
    """
    np.random.seed(cfg.seed)
    n = cfg.n_records

    # Generar NITs base (string de 10 dígitos)
    base_nits = np.array([f"{900_000_000 + i:010d}" for i in range(n)])

    # Generar nombres base
    palabras = ["EMPRESA", "GRUPO", "INDUSTRIAS", "COMERCIAL", "SERVICIOS",
                "TECNOLOGIA", "INVERSIONES", "DISTRIBUIDORA", "INTERNACIONAL",
                "SOLUCIONES", "COMUNICACIONES", "MEDICAS", "CONSTRUCCIONES"]
    suffix = ["SAS", "SA", "LTDA", "EU", "CIA"]

    razones = np.array([
        f"{np.random.choice(palabras)} {np.random.choice(palabras)} "
        f"{i} {np.random.choice(suffix)}"
        for i in range(n)
    ])

    # Crear overlap: cfg.overlap_pct de registros comparten NIT con OTROS
    n_overlap = int(n * cfg.overlap_pct)
    n_overlap = (n_overlap // 2) * 2  # par para que haya match pareado

    # Tomar registros 0..n_overlap y asignarles NITs duplicados de 0..n_overlap/2
    overlap_indices = np.arange(n_overlap)
    np.random.shuffle(overlap_indices)
    half = n_overlap // 2

    for i in range(half):
        idx_a = overlap_indices[i]
        idx_b = overlap_indices[i + half]
        # Ambos toman el mismo NIT base
        base_nits[idx_b] = base_nits[idx_a]
        # Variación de nombre: misma base + sufijo distinto
        razones[idx_b] = razones[idx_a] + " - SUCURSAL"

    # Asignar fuentes (rotación uniforme)
    sources = ["RUES", "EXPORTACIONES", "CRM", "SUPERSOCIEDADES"][: cfg.n_sources]
    src_assignment = np.array([sources[i % len(sources)] for i in range(n)])

    df = pd.DataFrame({
        "NIT": base_nits,
        "NIT_BASE": base_nits,
        "NIT_VALID": np.ones(n, dtype=bool),
        "RAZON_SOCIAL": razones,
        "NOMBRE_LIMPIO": np.array([r.upper().strip() for r in razones]),
        "SRC": src_assignment,
    })
    df = df.reset_index(drop=True)
    return df


def correr_lsh_solo(df: pd.DataFrame, cfg: BenchmarkConfig, work_dir: Path) -> tuple[float, set]:
    """Corre solo LSH y devuelve (tiempo, set_de_pares)."""
    from record_linkage.engine.lsh import DiskBasedLSHEngine

    profile = {
        "lsh_permutations": cfg.lsh_permutations,
        "lsh_threshold": cfg.lsh_threshold,
        "lsh_ngram": cfg.lsh_ngram,
        "lsh_chunk_size": 200_000,
    }
    engine = DiskBasedLSHEngine(profile=profile)

    t0 = time.perf_counter()
    pairs_result = engine.find_candidates(
        df, output_dir=str(work_dir), cross_source_only=False
    )
    t_elapsed = time.perf_counter() - t0

    # Normalizar a set de tuples
    if isinstance(pairs_result, str):
        # Es un path a SQLite. Tabla: candidate_pairs(idx_0, idx_1)
        import sqlite3
        conn = sqlite3.connect(pairs_result)
        df_pairs = pd.read_sql("SELECT idx_0, idx_1 FROM candidate_pairs", conn)
        conn.close()
        pairs = set(zip(df_pairs["idx_0"], df_pairs["idx_1"]))
    else:
        pairs = set(pairs_result)

    # Normalizar todos los pares como (min, max)
    pairs_norm = {(int(min(i, j)), int(max(i, j))) for i, j in pairs}
    return t_elapsed, pairs_norm


def correr_prescreen_y_lsh(
    df: pd.DataFrame, cfg: BenchmarkConfig, work_dir: Path
) -> tuple[float, float, set, set]:
    """Corre Prescreener + LSH(residual). Devuelve tiempos y pares."""
    from record_linkage.engine.lsh import NITPrescreener

    prescreener = NITPrescreener(min_group_size=2, max_group_size=50)

    t0 = time.perf_counter()
    result = prescreener.partition(df)
    t_prescreen = time.perf_counter() - t0

    prescreen_pairs = result.exact_match_pairs

    # Corre LSH solo sobre residual
    t_lsh_res, lsh_residual_pairs = correr_lsh_solo(
        result.residual_df.reset_index(drop=True), cfg, work_dir / "residual"
    )

    return t_prescreen, t_lsh_res, prescreen_pairs, lsh_residual_pairs


def correr_benchmark(cfg: BenchmarkConfig, work_dir: Path) -> BenchmarkResult:
    """Corre el benchmark completo: dataset → LSH solo → Prescreen+LSH."""
    import record_linkage

    print(f"\n{'='*70}\n  BENCHMARK NITPrescreener\n{'='*70}")
    print(f"  Paquete       : v{record_linkage.__version__}")
    print(f"  Config hash   : {cfg.to_hash()}")
    print(f"  n_records     : {cfg.n_records:,}")
    print(f"  overlap_pct   : {cfg.overlap_pct:.0%}")
    print(f"  seed          : {cfg.seed}")

    # 1. Generar dataset
    print(f"\n  📊 Generando dataset...")
    t0 = time.perf_counter()
    df = generar_dataset_sintetico(cfg)
    t_gen = time.perf_counter() - t0
    print(f"     ✅ {len(df):,} registros en {t_gen:.2f}s")
    n_unique_nits = df["NIT_BASE"].nunique()
    print(f"     • NITs únicos    : {n_unique_nits:,}")
    print(f"     • Pares potenciales (mismo NIT): {len(df) - n_unique_nits:,}")

    work_dir.mkdir(parents=True, exist_ok=True)

    # 2. LSH solo (baseline)
    print(f"\n  🔵 LSH SOLO (baseline)...")
    t_lsh, lsh_pairs = correr_lsh_solo(df, cfg, work_dir / "lsh_only")
    print(f"     ✅ LSH solo en {t_lsh:.2f}s → {len(lsh_pairs):,} pares")

    # 3. Prescreen + LSH(residual)
    print(f"\n  🟢 PRESCREEN + LSH(residual)...")
    t_pre, t_lsh_res, ps_pairs, lsh_res_pairs = correr_prescreen_y_lsh(
        df, cfg, work_dir / "combined"
    )
    combined_pairs = ps_pairs | lsh_res_pairs
    t_combined = t_pre + t_lsh_res
    print(f"     ✅ Prescreen: {t_pre:.2f}s → {len(ps_pairs):,} pares NIT-exact")
    print(f"     ✅ LSH(residual): {t_lsh_res:.2f}s → {len(lsh_res_pairs):,} pares")
    print(f"     ✅ Total combinado: {t_combined:.2f}s → {len(combined_pairs):,} pares")

    # 4. Métricas
    speedup = t_lsh / max(t_combined, 0.001)
    n_input = len(df)

    # Reducción del input al LSH
    # En prescreen el residual es lo que queda fuera de los exact_pairs
    # consumed = registros que entraron a grupos NIT
    consumed = set()
    for i, j in ps_pairs:
        consumed.add(i); consumed.add(j)
    reduction = len(consumed) / n_input

    # Recall: ¿qué fracción de los pares LSH-solo capturó el método combinado?
    intersection = combined_pairs & lsh_pairs
    recall = len(intersection) / max(len(lsh_pairs), 1)

    print(f"\n  📊 RESULTADO:")
    print(f"     • Speedup           : {speedup:.2f}× ({t_lsh:.1f}s → {t_combined:.1f}s)")
    print(f"     • Reducción input LSH: {reduction:.1%}")
    print(f"     • Recall combinado   : {recall:.1%} de pares LSH-solo")
    print(f"     • Pares únicos prescreen: {len(ps_pairs - lsh_pairs):,} (no detectados por LSH solo)")

    return BenchmarkResult(
        config=asdict(cfg),
        config_hash=cfg.to_hash(),
        timestamp=datetime.now().isoformat(),
        paquete_version=record_linkage.__version__,
        t_dataset_generation_s=round(t_gen, 3),
        t_lsh_only_s=round(t_lsh, 3),
        t_prescreen_s=round(t_pre, 3),
        t_lsh_residual_s=round(t_lsh_res, 3),
        t_combined_s=round(t_combined, 3),
        n_input=n_input,
        n_lsh_only_pairs=len(lsh_pairs),
        n_prescreen_pairs=len(ps_pairs),
        n_lsh_residual_pairs=len(lsh_res_pairs),
        n_combined_pairs=len(combined_pairs),
        speedup_lsh=round(speedup, 3),
        reduction_lsh_input=round(reduction, 4),
        recall_combined=round(recall, 4),
        metadata={
            "unique_nits": int(n_unique_nits),
            "intersection": len(intersection),
            "prescreen_only": len(ps_pairs - lsh_pairs),
            "lsh_only_missed_by_combined": len(lsh_pairs - combined_pairs),
        },
    )


def main():
    parser = argparse.ArgumentParser(description="Benchmark NITPrescreener vs LSH puro")
    parser.add_argument("--n", type=int, default=10_000, help="Número de registros")
    parser.add_argument("--overlap", type=float, default=0.30, help="Fracción con NIT compartido")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--output", type=str, default="benchmarks/results")
    parser.add_argument("--lsh-threshold", type=float, default=0.58)
    args = parser.parse_args()

    cfg = BenchmarkConfig(
        n_records=args.n,
        overlap_pct=args.overlap,
        seed=args.seed,
        lsh_threshold=args.lsh_threshold,
    )

    out_root = Path(args.output)
    out_root.mkdir(parents=True, exist_ok=True)

    work_dir = out_root / f"workdir_{cfg.to_hash()}"
    result = correr_benchmark(cfg, work_dir)

    # Guardar resultado
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    result_file = out_root / f"bench_{cfg.n_records}_{cfg.to_hash()}_{ts}.json"
    result_file.write_text(json.dumps(asdict(result), indent=2, ensure_ascii=False))
    print(f"\n  💾 Resultado guardado en: {result_file}")

    # Limpiar workdir (mantener solo el JSON)
    import shutil
    if work_dir.exists():
        shutil.rmtree(work_dir, ignore_errors=True)


if __name__ == "__main__":
    main()
