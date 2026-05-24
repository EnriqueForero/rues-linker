"""
pipeline.state_manager — record_linkage_pipeline

Componentes:
    - class StateManager  (origen: notebook celda [192])

NOTA: Lógica de negocio preservada exactamente como en el notebook
fuente. Solo se agregan imports, docstring de módulo y se eliminan
directivas de Jupyter (%%time, !pip, etc.). Ver MIGRATION_LOG.md.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path

from ..reporting.strategies import Phase
from ._phase_constants import PHASE_PARAMS, PHASES_ORDER


class StateManager:
    """
    Gestiona el estado persistente del pipeline mediante manifest.json.

    Responsabilidades:
    - Calcular hashes de configuración por fase para detectar cambios
    - Validar si una fase puede reutilizarse (checkpointing)
    - Persistir estado tras cada fase completada
    - Invalidar fases cuando cambia la configuración

    El manifest guarda:
    - Hash de configuración de cada fase
    - Estado (DONE/PENDING)
    - Timestamp de completación
    - Lista de archivos generados
    - Metadatos adicionales (duración, etc.)
    """

    def __init__(self, work_dir: Path):
        """
        Inicializa el gestor de estado.

        Args:
            work_dir: Directorio de trabajo donde se guarda manifest.json
        """
        self.work_dir = work_dir
        self.manifest_file = work_dir / "manifest.json"
        self.manifest = self._load()

    def _load(self) -> dict:
        """Carga manifest existente o retorna diccionario vacío."""
        if self.manifest_file.exists():
            try:
                with open(self.manifest_file, encoding="utf-8") as f:
                    return json.load(f)
            except (OSError, json.JSONDecodeError):
                # Manifest corrupto, empezar de cero
                return {}
        return {}

    def save(self) -> None:
        """Persiste el manifest actual a disco."""
        with open(self.manifest_file, "w", encoding="utf-8") as f:
            json.dump(self.manifest, f, indent=2, default=str, ensure_ascii=False)

    def compute_hash(self, config: dict, phase: Phase, data_sig: str, prev_hash: str) -> str:
        """
        Calcula hash único para una fase basado en:
        - Parámetros relevantes de la fase (definidos en PHASE_PARAMS)
        - Hash de la fase anterior (encadenamiento)
        - Firma de los datos de entrada

        Esto permite detectar cuándo una fase necesita re-ejecutarse.

        Args:
            config: Configuración completa del pipeline
            phase: Fase para la cual calcular el hash
            data_sig: Firma de los datos de entrada
            prev_hash: Hash de la fase anterior (para encadenamiento)

        Returns:
            Hash de 12 caracteres hexadecimales
        """
        params = {}
        profile = config.get("profiles", {}).get(config.get("profile", ""), {})

        # Extraer parámetros relevantes para esta fase
        for key in PHASE_PARAMS[phase]:
            if key in config:
                params[key] = config[key]
            elif key in profile:
                params[key] = profile[key]

        # Crear payload y calcular hash
        payload = json.dumps([params, prev_hash, data_sig], sort_keys=True, default=str)
        return hashlib.md5(payload.encode()).hexdigest()[:12]

    def get_prev_hash(self, phase: Phase) -> str:
        """
        Obtiene hash de la fase anterior para encadenamiento.

        Args:
            phase: Fase actual

        Returns:
            Hash de la fase anterior, o cadena vacía si es L1_PREP
        """
        idx = PHASES_ORDER.index(phase)
        if idx == 0:
            return ""
        prev_phase = PHASES_ORDER[idx - 1]
        return self.manifest.get(prev_phase.value, {}).get("hash", "")

    def is_valid(self, phase: Phase, expected_hash: str) -> bool:
        """
        Verifica si una fase puede reutilizarse.

        Una fase es válida si:
        1. Existe en el manifest
        2. Su hash coincide con el esperado
        3. Su estado es DONE
        4. Todos los archivos generados existen en disco

        Args:
            phase: Fase a verificar
            expected_hash: Hash calculado con la configuración actual

        Returns:
            True si la fase puede reutilizarse
        """
        rec = self.manifest.get(phase.value)

        if not rec:
            return False

        if rec.get("hash") != expected_hash:
            return False

        if rec.get("status") != "DONE":
            return False

        # Verificar que todos los archivos existen
        return all(Path(f).exists() for f in rec.get("files", []))

    def mark_done(
        self, phase: Phase, ph_hash: str, files: list[Path], meta: dict | None = None
    ) -> None:
        """
        Marca una fase como completada exitosamente.

        Args:
            phase: Fase completada
            ph_hash: Hash de configuración de la fase
            files: Lista de archivos generados
            meta: Metadatos adicionales (ej: duración)
        """
        self.manifest[phase.value] = {
            "hash": ph_hash,
            "status": "DONE",
            "timestamp": datetime.now().isoformat(),
            "files": [str(f) for f in files],
            "meta": meta or {},
        }
        self.save()

    def invalidate_from(self, phase: Phase) -> None:
        """
        Invalida una fase y todas las posteriores.

        Usado cuando se quiere forzar re-ejecución desde un punto específico.

        Args:
            phase: Fase desde la cual invalidar (inclusive)
        """
        idx = PHASES_ORDER.index(phase)
        for p in PHASES_ORDER[idx:]:
            if p.value in self.manifest:
                del self.manifest[p.value]
        self.save()
