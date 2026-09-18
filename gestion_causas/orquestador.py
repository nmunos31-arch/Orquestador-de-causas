"""Driver mínimo del orquestador de gestion_causas, en Python.

Alcance de este archivo (ver planes en docs/superpowers/plans/): despacha
las 5 fases ('smu', 'goteo', 'agenda', 'seguimiento', 'calendario'). No
reemplaza todavía a la tarea programada `gestion-causas-orquestador` — se
corre a mano en paralelo para comparar resultados contra el subagente viejo.

`seguimiento` y `calendario` solo se despachan en la corrida de la mañana
(`contexto_corrida["corrida"] == "manana"`, campo que ya arma
`cli.cmd_contexto_corrida`): sus umbrales son en días hábiles (seguimiento)
o solo corren los lunes (calendario, que además se autoevalúa internamente
con `es_lunes` — este filtro por "corrida" es una capa extra para no
llamarlas de más en las corridas de la tarde/noche)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from gestion_causas import bitacora as bitacora_mod
from gestion_causas import registro as registro_mod
from gestion_causas.fases import agenda as fases_agenda
from gestion_causas.fases import calendario as fases_calendario
from gestion_causas.fases import goteo as fases_goteo
from gestion_causas.fases import seguimiento as fases_seguimiento
from gestion_causas.fases import smu as fases_smu

RUTA_CONTEXTO_DEFAULT = Path(__file__).parent / "_contexto_corrida.json"

FASES_SOLO_CORRIDA_MANANA = {"seguimiento", "calendario"}


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
    es_corrida_manana = contexto_corrida.get("corrida") == "manana"

    fases = {}
    for nombre, funcion, kwargs_extra in (
        ("smu", fases_smu.correr, {"ruta_registro_ceco": ruta_registro_ceco}),
        ("goteo", fases_goteo.correr, {"ruta_registro_ceco": ruta_registro_ceco}),
        ("agenda", fases_agenda.correr, {}),
        ("seguimiento", fases_seguimiento.correr, {}),
        ("calendario", fases_calendario.correr, {}),
    ):
        if nombre in FASES_SOLO_CORRIDA_MANANA and not es_corrida_manana:
            continue
        try:
            fases[nombre] = funcion(
                contexto_corrida,
                ruta_registro_causas=ruta_registro_causas,
                **kwargs_extra,
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
