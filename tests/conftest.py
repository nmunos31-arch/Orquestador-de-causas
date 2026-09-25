import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest


@pytest.fixture(autouse=True)
def _bitacora_temporal(tmp_path, monkeypatch):
    """Las fases llaman a `bitacora.registrar` sin `ruta`, así que sin esto
    cada corrida de tests agrega líneas falsas (M-1-2026, etc.) a la
    bitácora real. El default se fija al definir la función, por eso se
    parchea `__defaults__` y no la constante del módulo."""
    from gestion_causas import bitacora

    monkeypatch.setattr(bitacora.registrar, "__defaults__", (None, tmp_path / "bitacora.md"))
