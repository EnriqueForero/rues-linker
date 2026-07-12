"""record_linkage — Pipeline de deduplicación y record linkage para
fuentes empresariales colombianas (RUES, DIAN, CRM, SUPERSOCIEDADES).

Refactor del notebook `2026_02_15_DEDUPLICAR_Y_RECORD_LINKAGE_.ipynb`
a paquete .py estructurado. Lógica de negocio intacta.

Componentes principales:
    - config:        Config y Rutas centralizadas, perfiles LSH
    - utils:         Tiempo, memoria, logging, performance
    - classifier:    Clasificador híbrido (Sección 2)
    - processing:    Limpieza de texto y NIT
    - engine:        Motor de record linkage (LSH + scoring + clustering)
    - golden:        Generación de golden records
    - evaluation:    Ground truth y métricas de calidad
    - reporting:     Reportes, visualizaciones, dashboards
    - pipeline:      Orchestrator de producción
    - deduplication: Modo deduplicación específico
    - optimization:  Optuna y optimización de hiperparámetros
    - exporters:     Exportación multi-formato

La versión es única y vive en `pyproject.toml`; aquí se lee dinámicamente
con `importlib.metadata` para que no exista una segunda fuente de verdad
que pueda desincronizarse.
"""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("rues-linker")
except PackageNotFoundError:  # pragma: no cover - checkout sin instalar
    __version__ = "0.8.0"  # centinela: nunca una versión real

# ── API pública de alto nivel ─────────────────────────────────────────
# `linkage()` es el punto de entrada recomendado. Las demás se exponen para
# casos específicos. Import defensivo: una dependencia opcional ausente no
# debe romper `import record_linkage`.
from .api import linkage
from .config.paths import Rutas
from .config.settings import Config

try:
    from .deduplication.unified import deduplicate_unified
except ImportError:  # pragma: no cover
    deduplicate_unified = None  # type: ignore[assignment]

try:
    from .deduplication.auto import deduplicate_auto
except ImportError:  # pragma: no cover
    deduplicate_auto = None  # type: ignore[assignment]

try:
    from .pipeline.orchestrator import Orchestrator
except ImportError:  # pragma: no cover
    Orchestrator = None  # type: ignore[assignment]

try:
    from .config.profiles import crear_config_orchestrator
except ImportError:  # pragma: no cover
    crear_config_orchestrator = None  # type: ignore[assignment]

try:
    from .evaluation.pairwise import evaluar_pares
except ImportError:  # pragma: no cover
    evaluar_pares = None  # type: ignore[assignment]

# Matching multi-variable: el módulo `matching` existía pero no estaba
# conectado ni exportado en la API pública. Este bloque lo expone.
try:
    from .matching import (
        MatcherPostProcessor,
        MatchingProfile,
        VariableMatcher,
        VariableSpec,
        default_colombia_profile,
        default_international_profile,
    )
except ImportError:  # pragma: no cover
    MatcherPostProcessor = None  # type: ignore[assignment]
    MatchingProfile = None  # type: ignore[assignment]
    VariableMatcher = None  # type: ignore[assignment]
    VariableSpec = None  # type: ignore[assignment]
    default_colombia_profile = None  # type: ignore[assignment]
    default_international_profile = None  # type: ignore[assignment]

__all__ = [
    "Config",
    "MatcherPostProcessor",
    "MatchingProfile",
    "Orchestrator",
    "Rutas",
    "VariableMatcher",
    "VariableSpec",
    "__version__",
    "crear_config_orchestrator",
    "deduplicate_auto",
    "deduplicate_unified",
    "default_colombia_profile",
    "default_international_profile",
    "evaluar_pares",
    "linkage",
]
