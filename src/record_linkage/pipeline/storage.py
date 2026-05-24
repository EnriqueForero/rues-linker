"""
pipeline.storage — record_linkage_pipeline

Componentes:
    - class HybridStorageManager  (origen: notebook celda [192])

NOTA: Lógica de negocio preservada exactamente como en el notebook
fuente. Solo se agregan imports, docstring de módulo y se eliminan
directivas de Jupyter (%%time, !pip, etc.). Ver MIGRATION_LOG.md.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from ._internal import _get_logger


class HybridStorageManager:
    """
    Procesa en disco local rápido, sincroniza a Drive para persistencia.

    Flujo por fase:
    1. Al inicio: pull_from_drive() → copia inputs de Drive → disco local NVMe
    2. Durante:   Todo procesamiento SQLite ocurre en disco local
    3. Al final:  push_to_drive() → copia resultado a Drive (checkpoint seguro)
    4. Reinicio:  Busca checkpoint en Drive, descarga a local, continúa

    Uso:
        storage = HybridStorageManager(Path("/content/drive/MyDrive/workspace"))
        local = storage.pull_from_drive("candidates.db")
        # ... procesar en local ...
        storage.push_to_drive("candidates.db")
    """

    def __init__(self, drive_workspace: Path, local_base: str = "/content/temp_work"):
        """
        Args:
            drive_workspace: Directorio en Google Drive (persistente)
            local_base: Directorio local para procesamiento rápido
        """
        self.drive_dir = Path(drive_workspace)
        self.local_dir = Path(local_base)
        self.local_dir.mkdir(parents=True, exist_ok=True)
        self._logger = _get_logger("HybridStorage")

    def local_path(self, filename: str) -> Path:
        """Retorna ruta local para un archivo."""
        return self.local_dir / filename

    def pull_from_drive(self, filename: str) -> Path:
        """
        Copia archivo de Drive a disco local. Retorna ruta local.
        Si el archivo no existe en Drive, retorna la ruta local (vacía).
        """
        src = self.drive_dir / filename
        dst = self.local_dir / filename
        dst.parent.mkdir(parents=True, exist_ok=True)

        if src.exists():
            import shutil

            shutil.copy2(src, dst)
            size_mb = src.stat().st_size / (1024 * 1024)
            self._logger.info(f"   📥 Pull: {filename} ({size_mb:.1f} MB) Drive → Local")
        else:
            self._logger.debug(f"   ℹ️ {filename} no existe en Drive (se creará localmente)")

        return dst

    def push_to_drive(self, filename: str, retries: int = 3) -> Path:
        """
        Copia archivo de disco local a Drive. Retorna ruta en Drive.
        Incluye retry con backoff exponencial para robustez.
        """
        src = self.local_dir / filename
        dst = self.drive_dir / filename
        dst.parent.mkdir(parents=True, exist_ok=True)

        for attempt in range(retries):
            try:
                shutil.copy2(src, dst)
                size_mb = src.stat().st_size / (1024 * 1024)
                self._logger.info(f"   📤 Push: {filename} ({size_mb:.1f} MB) Local → Drive")
                return dst
            except Exception as e:
                wait = 2**attempt
                self._logger.warning(
                    f"   ⚠️ Push fallido (intento {attempt + 1}/{retries}): {e}. Esperando {wait}s..."
                )
                import time

                time.sleep(wait)

        raise RuntimeError(f"No se pudo copiar {filename} a Drive después de {retries} intentos")

    def cleanup_local(self):
        """Limpia disco local al terminar todo el pipeline."""
        try:
            shutil.rmtree(self.local_dir, ignore_errors=True)
            self._logger.info(f"   🧹 Disco local limpiado: {self.local_dir}")
        except Exception as e:
            self._logger.warning(f"   ⚠️ Error limpiando disco local: {e}")

    def is_local_available(self) -> bool:
        """Verifica si el disco local está disponible (Colab con NVMe)."""
        try:
            return self.local_dir.exists() or self.local_dir.parent.exists()
        except:
            return False
