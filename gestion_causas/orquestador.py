"""Driver mínimo del orquestador de gestion_causas, en Python.

Alcance de este archivo (ver plan
docs/superpowers/plans/2026-09-15-driver-python-goteo-piloto.md): solo
despacha la fase 'goteo'. Las demás fases (smu, agenda, seguimiento,
calendario) se agregan en planes posteriores, una vez validado este patrón.
No reemplaza todavía a la tarea programada `gestion-causas-orquestador` — se
corre a mano en paralelo para comparar resultados contra el subagente viejo.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from gestion_causas import bitacora as bitacora_mod
from gestion_causas import registro as registro_mod
from gestion_causas.fases import goteo as fases_goteo

RUTA_CONTEXTO_DEFAULT = Path(__file__).parent / "_contexto_corrida.json"


def correr(
    ruta_contexto: Path = RUTA_CONTEXTO_DEFAULT,
    *,
    ruta_registro_causas: Path = registro_mod.RUTA_REGISTRO_CAUSAS,
    ruta_registro_ceco: Path = registro_mod.RUTA_REGISTRO_CECO,
) -> dict:
    if not Path(ruta_contexto).exists():
        raise FileNotFoundError(
            f"No existe el contexto de corrida en {ruta_contexto}. "
            "Este driver requiere que ya se haya armado con "
            "`python -m gestion_causas.cli contexto-corrida` antes de correrlo."
        )
    contexto_corrida = json.loads(Path(ruta_contexto).read_text(encoding="utf-8"))

    fases = {}
    for nombre, funcion in (("goteo", fases_goteo.correr),):
        try:
            fases[nombre] = funcion(
                contexto_corrida,
                ruta_registro_causas=ruta_registro_causas,
                ruta_registro_ceco=ruta_registro_ceco,
            )
        except Exception as e:
            mensaje = f"{type(e).__name__}: {e}"
            bitacora_mod.registrar(f"Fase '{nombre}' falló: {mensaje}")
            fases[nombre] = {"fase": nombre, "error": mensaje}

    return {"fecha_hoy": contexto_corrida.get("fecha_hoy"), "fases": fases}


def main(argv=None) -> int:
    resultado = correr()
    print(json.dumps(resultado, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
