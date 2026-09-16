"""Driver Python de la fase 'smu' (Fase 1-2, ingesta y registro — ver spec
en docs/superpowers/specs/2026-09-15-driver-python-gestion-causas-design.md
y, como referencia histórica de las reglas completas, subagentes/smu.md).

Alcance de este módulo (ver plan
docs/superpowers/plans/2026-09-16-driver-python-smu-ingesta.md): busca
correos nuevos de demandas de las 6 empresas del proyecto, extrae el
cuadro-resumen, filtra duplicados, crea la carpeta, guarda la demanda,
escribe la fila del Excel de Juicios Vigentes, registra la causa, etiqueta
el hilo y lo marca procesado. NO arma el borrador de documentos a solicitar
(ver Plan B, un plan separado) — no requiere que orquestador.py haya armado
ningún mapa previo, a diferencia de goteo."""

from __future__ import annotations

from pathlib import Path

from actualizar_informe_juicios import RUTA_EXCEL_JUICIOS, agregar_causa
from gestion_causas import bitacora as bitacora_mod
from gestion_causas import carpetas as carpetas_mod
from gestion_causas import gmail_client
from gestion_causas import registro as registro_mod
from gestion_causas import reasoning
from gestion_causas.cuadro_resumen import cuadro_completo, extraer_campos_cuadro
from gestion_causas.empresas import normalizar_empresa
from gestion_causas.gmail_client import COLOR_POR_EMPRESA, EMPRESAS_SIN_EXCEL, ETIQUETA_PROCESADO
from gestion_causas.seguimiento import extraer_direccion

QUERY_CANDIDATOS = (
    'from:(smu.cl OR sb.cl OR gomezyriesco.cl) subject:DEMANDA '
    'after:2026/07/01 -label:"Procesado-GestionCausas"'
)


def correr(
    contexto_corrida: dict,
    *,
    ruta_registro_causas: Path = registro_mod.RUTA_REGISTRO_CAUSAS,
) -> dict:
    hilos = gmail_client.buscar_hilos(QUERY_CANDIDATOS, max_resultados=50)
    if not hilos:
        return {
            "fase": "smu",
            "titular": "Sin correos nuevos",
            "metricas": [],
            "items": [],
            "acciones": [],
            "notas": [],
        }

    return {
        "fase": "smu",
        "titular": f"{len(hilos)} hilos candidatos",
        "metricas": [],
        "items": [],
        "acciones": [],
        "notas": [],
    }
