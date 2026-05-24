"""record_linkage.engine.lsh — Motores LSH.

Decisión de producción (4 fuentes, 2M+ registros):
    DiskBasedLSHEngine + TrustedSourceLSHEngine.

Ver MIGRATION_LOG.md para el rastreo desde la celda 8.4 del notebook fuente.
"""

from .defaults import LSHDefaults
from .disk_based import DiskBasedLSHEngine
from .metrics import EngineMetrics
from .minhash import VectorizedMinHashGenerator
from .state import EngineState
from .trusted import TrustedSourceLSHEngine

__all__ = [
    "DiskBasedLSHEngine",
    "EngineMetrics",
    "EngineState",
    "LSHDefaults",
    "TrustedSourceLSHEngine",
    "VectorizedMinHashGenerator",
]
