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

import html
import os
import sys
from pathlib import Path

from gestion_causas import bitacora as bitacora_mod
from gestion_causas import carpetas as carpetas_mod
from gestion_causas import gmail_client
from gestion_causas import registro as registro_mod
from gestion_causas import reasoning
from gestion_causas.cuadro_resumen import (
    buscar_ceco_en_mensajes as _buscar_ceco_en_mensajes,
    cuadro_completo,
    dominios_citados,
    extraer_campos_cuadro,
    texto_citado,
)
from gestion_causas.empresas import normalizar_empresa
from gestion_causas.gmail_client import COLOR_POR_EMPRESA, EMPRESAS_SIN_EXCEL, ETIQUETA_PROCESADO
from gestion_causas.seguimiento import extraer_direccion

# `actualizar_informe_juicios.py` vive en un repo/carpeta separado del de
# gestion_causas (es un script propio para actualizar el Excel de Juicios
# Vigentes, sin relación funcional con esta migración) — a diferencia de
# normalizar_rit en registro.py (duplicado deliberado por ser trivial),
# escribir filas en el Excel es demasiado código para duplicar sin
# arriesgar que las dos copias diverjan, así que en vez de importarlo como
# paquete se agrega su carpeta a sys.path. La ruta es configurable con la
# variable de entorno RUTA_ACTUALIZADOR_INFORMES para no hardcodear la
# máquina de una sola persona en el código de un repo que en algún momento
# podría correr en otra.
_RUTA_ACTUALIZADOR_INFORMES_DEFAULT = r"C:\Users\usuario\Documents\Temporal 2\Actualizador de informes"


def _ruta_actualizador_informes() -> str:
    return os.environ.get("RUTA_ACTUALIZADOR_INFORMES", _RUTA_ACTUALIZADOR_INFORMES_DEFAULT)


def _importar_actualizador_informe_juicios():
    ruta = _ruta_actualizador_informes()
    if ruta not in sys.path:
        sys.path.insert(0, ruta)
    from actualizar_informe_juicios import RUTA_EXCEL_JUICIOS, agregar_causa
    return RUTA_EXCEL_JUICIOS, agregar_causa


RUTA_EXCEL_JUICIOS, agregar_causa = _importar_actualizador_informe_juicios()

QUERY_CANDIDATOS = (
    'from:(smu.cl OR sb.cl OR gomezyriesco.cl) subject:DEMANDA '
    'after:2026/07/01 -label:"Procesado-GestionCausas"'
)

LISTA_DOCUMENTOS_BASE = [
    "Contrato de trabajo y anexos",
    "Carta de despido",
    "Finiquito",
    "EERR del local de los años 2024, 2025 y 2026",
    "Comparativa de dotación del local antes y después del despido",
    "Testigos",
    "Absolvente",
]


def correr(
    contexto_corrida: dict,
    *,
    ruta_registro_causas: Path = registro_mod.RUTA_REGISTRO_CAUSAS,
    ruta_registro_ceco: Path = registro_mod.RUTA_REGISTRO_CECO,
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

    items: list[dict] = []
    acciones: list[dict] = []
    notas: list[dict] = []
    causas_nuevas = 0
    borradores_creados = 0
    eerr_reusado_contador = 0

    for hilo_resumen in hilos:
        thread_id = hilo_resumen["id"]
        mensajes = gmail_client.leer_hilo(thread_id)
        if not mensajes:
            continue
        primer_mensaje = mensajes[0]

        if not _origen_cadena(primer_mensaje)["valida"]:
            continue

        campos = extraer_campos_cuadro(primer_mensaje.get("cuerpo_texto", ""))
        if not cuadro_completo(campos):
            notas.append({
                "tipo": "cuadro_incompleto",
                "detalle": f"Hilo {thread_id}: cuadro incompleto o mal formado (falta Rit, Tribunal o Cuantía) — revisar a mano.",
            })
            continue

        empresa = normalizar_empresa(campos.get("demandada", ""))
        if empresa is None:
            continue

        rit = campos["rit"]
        if registro_mod.causa_ya_registrada(rit, ruta=ruta_registro_causas):
            continue

        ceco = _buscar_ceco_en_mensajes(mensajes)

        apellido = campos.get("demandante", "").split()[-1].title() if campos.get("demandante") else rit

        carpeta_existente = carpetas_mod.buscar_carpeta_existente_por_rit(rit)
        carpeta = carpeta_existente or carpetas_mod.crear_carpeta_causa(apellido, empresa, rit)

        demanda_guardada = False
        for adjunto in primer_mensaje.get("adjuntos", []):
            if not adjunto["filename"].lower().endswith(".pdf"):
                continue
            contenido = gmail_client.descargar_adjunto(primer_mensaje["id"], adjunto["attachment_id"])
            if carpetas_mod.es_adjunto_firma(adjunto["filename"], len(contenido)):
                continue
            resultado = carpetas_mod.guardar_adjunto(carpeta, "demanda.pdf", contenido)
            demanda_guardada = resultado["guardado"] or demanda_guardada
            break

        demanda_disponible = demanda_guardada or (carpeta / "demanda.pdf").exists()

        if not demanda_disponible:
            notas.append({
                "tipo": "sin_demanda",
                "detalle": f"{rit}: no se encontró un PDF de demanda en el correo — súbela a mano.",
            })

        ajustes: dict = {}
        if demanda_disponible:
            ajustes = _evaluar_ajustes_demanda(campos, carpeta / "demanda.pdf")
            if ajustes.get("error"):
                acciones.append({
                    "rit": rit,
                    "que": f"No se pudieron detectar los ajustes de la demanda automáticamente: {ajustes['error']}",
                    "urgencia": "alta",
                })

        eerr_copiado = False
        eerr_reusable = None
        if demanda_disponible and ceco and ajustes.get("fecha_despido"):
            eerr_reusable = registro_mod.buscar_eerr_reusable(
                ceco, ajustes["fecha_despido"], ruta=ruta_registro_ceco
            )
            if eerr_reusable:
                causa_reusable = registro_mod.obtener_causa(
                    eerr_reusable["rit_causa"], ruta=ruta_registro_causas
                )
                if causa_reusable and causa_reusable.get("carpeta"):
                    carpeta_reusable = Path(causa_reusable["carpeta"])
                    nombre_eerr = next(
                        (
                            nombre for nombre in carpetas_mod.listar_archivos_carpeta(carpeta_reusable)
                            if carpetas_mod.parece_eerr(nombre)
                        ),
                        None,
                    )
                    if nombre_eerr:
                        resultado_copia = carpetas_mod.copiar_archivo_local(
                            carpeta_reusable / nombre_eerr, carpeta, nombre_eerr
                        )
                        eerr_copiado = resultado_copia["copiado"]
                        if eerr_copiado:
                            eerr_reusado_contador += 1

        # El resumen narrativo solo hace falta para la fila del Excel — Preunic y
        # Salcobrand nunca tienen fila (ver EMPRESAS_SIN_EXCEL), así que ni siquiera
        # vale la pena gastar el llamado a Claude para esos dos casos.
        if empresa not in EMPRESAS_SIN_EXCEL:
            deteccion_resumen = _generar_resumen_narrativo(campos, primer_mensaje.get("cuerpo_texto", ""))
            if deteccion_resumen.get("error"):
                acciones.append({
                    "rit": rit,
                    "que": f"No se pudo redactar el Resumen del Excel automáticamente: {deteccion_resumen['error']}",
                    "urgencia": "media",
                })
            else:
                datos_excel = {
                    "juzgado": campos.get("tribunal", ""),
                    "materia": campos.get("materia", ""),
                    "causa": rit,
                    "cuantia": campos.get("cuantia", ""),
                    "resumen": deteccion_resumen.get("resumen", ""),
                }
                try:
                    agregar_causa(RUTA_EXCEL_JUICIOS, datos_excel)
                except PermissionError:
                    acciones.append({
                        "rit": rit,
                        "que": "El Excel de Juicios Vigentes está abierto/bloqueado — no se pudo escribir la fila. Se reintenta en la próxima corrida.",
                        "urgencia": "alta",
                    })

        documentos_solicitados: list[str] = []
        draft_id = None
        if demanda_disponible:
            documentos_solicitados = _armar_lista_documentos(ajustes, eerr_reusado=eerr_copiado)
            existentes = gmail_client.listar_borradores_de_hilo(thread_id)
            if not existentes:
                destinatario = extraer_direccion(primer_mensaje.get("sender", ""))
                asunto = f"Re: {primer_mensaje.get('subject', '')}"
                cuerpo_html = _cuerpo_html_lista(documentos_solicitados)
                borrador = gmail_client.crear_borrador(
                    destinatario, asunto, cuerpo_html, thread_id=thread_id, html=True
                )
                draft_id = borrador.get("id")
                borradores_creados += 1
            else:
                draft_id = existentes[0]["id"]

        registro_mod.registrar_causa(
            rit,
            {
                "empresa": empresa,
                "demandante": campos.get("demandante", ""),
                "carpeta": str(carpeta),
                "thread_id": thread_id,
                "tiene_demanda": demanda_guardada,
                "aplica_excel": empresa not in EMPRESAS_SIN_EXCEL,
                "ceco": ceco,
                "fecha_despido": ajustes.get("fecha_despido"),
                "borrador_documentos_draft_id": draft_id,
                "documentos_solicitados": documentos_solicitados,
            },
            ruta=ruta_registro_causas,
        )

        color = COLOR_POR_EMPRESA.get(empresa)
        label_empresa = gmail_client.obtener_o_crear_etiqueta(empresa, color=color)
        gmail_client.aplicar_etiqueta_a_hilo(thread_id, label_empresa)
        label_procesado = gmail_client.obtener_o_crear_etiqueta(ETIQUETA_PROCESADO)
        gmail_client.aplicar_etiqueta_a_hilo(thread_id, label_procesado)

        bitacora_mod.registrar(
            f"Causa nueva registrada ({empresa}), carpeta '{carpeta.name}'"
            + ("" if demanda_guardada else " — sin demanda adjunta, súbela a mano")
            + (f"; borrador de documentos creado ({len(documentos_solicitados)} items)" if draft_id else "")
            + (
                "; ADVERTENCIA: no se pudieron detectar ajustes de la demanda automáticamente, "
                "revisar a mano si hay conceptos atípicos"
                if ajustes.get("error")
                else ""
            ),
            rit=rit,
        )

        items.append({"rit": rit, "titulo": f"{empresa} - {campos.get('demandante', '').title()}"})
        causas_nuevas += 1

    resumen = {
        "fase": "smu",
        "titular": _armar_titular(causas_nuevas),
        "metricas": [
            {"etiqueta": "Causas nuevas", "valor": causas_nuevas},
            {"etiqueta": "Borradores de documentos creados", "valor": borradores_creados},
            {"etiqueta": "EERR reusado", "valor": eerr_reusado_contador},
        ],
        "items": items,
        "acciones": acciones,
        "notas": notas,
    }
    return resumen


def _armar_titular(causas_nuevas: int) -> str:
    if causas_nuevas == 0:
        return "Sin causas nuevas"
    return f"{causas_nuevas} causas nuevas registradas"


def _armar_lista_documentos(ajustes: dict, eerr_reusado: bool) -> list[str]:
    """Arma la lista de documentos a solicitar (ver subagentes/smu.md paso
    2k.2-2k.4): parte de la lista base, quita el punto del EERR si se
    reusó uno de una causa anterior del mismo CECO, y agrega los ajustes
    que detectó Claude (base de cálculo distinta, u otros conceptos
    atípicos) justo antes de Testigos y Absolvente."""
    lista = list(LISTA_DOCUMENTOS_BASE)
    if eerr_reusado:
        lista = [documento for documento in lista if "EERR" not in documento]

    ajustes_a_insertar = []
    if ajustes.get("ajuste_base_calculo"):
        ajustes_a_insertar.append("Últimas 6 liquidaciones de remuneraciones")
    ajustes_a_insertar += list(ajustes.get("otros_ajustes", []))

    if not ajustes_a_insertar:
        return lista

    indice_testigos = lista.index("Testigos")
    return lista[:indice_testigos] + ajustes_a_insertar + lista[indice_testigos:]


def _cuerpo_html_lista(documentos: list[str]) -> str:
    """Cuerpo del borrador: únicamente la lista numerada de documentos, sin
    saludo ni firma (ver subagentes/smu.md paso 2k.5). Se manda como HTML
    (`<ol><li>`) para que Gmail la reciba como lista numerada nativa — así
    se puede insertar o quitar un documento en el medio sin renumerar el
    resto a mano."""
    items = "".join(f"<li>{html.escape(documento)}</li>" for documento in documentos)
    return f"<ol>{items}</ol>"


SCHEMA_RESUMEN = {
    "type": "object",
    "properties": {"resumen": {"type": "string"}},
    "required": ["resumen"],
}


def _generar_resumen_narrativo(campos: dict, cuerpo_texto_completo: str) -> dict:
    """Redacta el párrafo "Resumen" del Excel de Juicios Vigentes siguiendo
    la plantilla exacta de docs/2026-07-07-informe-juicios-email-design.md
    (sección "Plantilla del Resumen"). `cuerpo_texto_completo` se pasa
    entero (no solo los campos ya extraídos) porque el bloque "Hechos" y
    "Conceptos demandados" son texto libre, sin acotar con regex."""
    contexto = {"campos_extraidos": campos, "cuerpo_completo_del_correo": cuerpo_texto_completo}
    tarea = (
        'Redactá el párrafo "Resumen" de una fila del Excel de Juicios Vigentes, '
        "siguiendo EXACTAMENTE esta plantilla (reemplazando lo que va entre corchetes, "
        "sin agregar ni quitar nada de la estructura):\n\n"
        '"Demanda de despido injustificado y cobro de prestaciones laborales interpuesta '
        "por [Demandante(s), formato Nombre Propio] por haber sido "
        "[desvinculad[o/a/os/as]] el [fecha de despido] por [causal]. Solicita el pago "
        "total de [Cuantía formateada como $#.###.###] por [conceptos demandados, sin "
        'montos parciales]."\n\n'
        "Reglas: Demandante(s) en formato Nombre Propio (no mayúsculas sostenidas), "
        "varios demandantes separados por comas y 'y' antes del último. Concordancia de "
        "género según el nombre (singular) o plural coherente con el grupo. Fecha y "
        "causal de despido se sacan del bloque 'Hechos' del cuerpo del correo. Formato de "
        "fecha: día con dos dígitos, mes en palabras y minúsculas, año completo (ej. '08 "
        "de enero de 2026'). Conceptos demandados: solo las etiquetas de los conceptos, "
        "sin repetir montos parciales."
    )
    return reasoning.preguntar(tarea, contexto, SCHEMA_RESUMEN)


SCHEMA_AJUSTES_DEMANDA = {
    "type": "object",
    "properties": {
        "fecha_despido": {"type": ["string", "null"]},
        "ajuste_base_calculo": {"type": "boolean"},
        "otros_ajustes": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["fecha_despido", "ajuste_base_calculo", "otros_ajustes"],
}


def _evaluar_ajustes_demanda(campos: dict, ruta_demanda: Path) -> dict:
    """Lee el PDF de la demanda (Claude la lee con su propia herramienta
    Read, en modo visión si es un escaneo) para detectar, más allá de lo
    que ya viene resumido en el cuadro: la fecha exacta de despido, si se
    demanda una base de cálculo distinta de la indemnización (dispara
    pedir las últimas 6 liquidaciones), y cualquier otro concepto atípico
    que necesite un antecedente puntual para desvirtuarlo (ver
    subagentes/smu.md paso 2k.1 y 2k.4)."""
    contexto = {"campos_del_cuadro": campos}
    tarea = (
        "Leé el archivo de la demanda indicado más abajo con tu herramienta Read (si es "
        "un PDF escaneado sin capa de texto, se lee en modo visión página por página — no "
        "leas más de ~10-12 páginas salvo que el petitorio esté evidentemente más "
        "adelante). Andá directo a la sección de Hechos/Antecedentes (primeras páginas, "
        "después de la identificación de las partes) y a la sección final de "
        "Petitorio/Por tanto — saltate el cuerpo intermedio de fundamentos de derecho "
        "(citas de ley, doctrina, jurisprudencia), no aporta nada nuevo frente al cuadro.\n\n"
        "De ahí extraé: (1) la fecha exacta de despido (formato AAAA-MM-DD, o null si no "
        "se puede determinar con certeza); (2) si se demanda una diferencia en la base de "
        "cálculo de la indemnización por años de servicio o de la sustitutiva de aviso "
        "previo (ajuste_base_calculo=true en ese caso); (3) cualquier otro concepto "
        "demandado atípico más allá de lo típico (ej. un descuento indebido en el "
        "finiquito por un préstamo, una diferencia por horas extraordinarias) — por cada "
        "uno, un string corto y escueto con el nombre del antecedente que permitiría "
        "desvirtuarlo o estudiar su procedencia (ej. 'Antecedentes de la procedencia del "
        "préstamo'), sin explicar por qué. Si no hay ninguno, devolvé una lista vacía."
    )
    return reasoning.preguntar(tarea, contexto, SCHEMA_AJUSTES_DEMANDA, ruta_archivo=ruta_demanda)


DOMINIOS_SMU = ("smu.cl", "sb.cl")


def _es_reenvio_de_cuadro_confiable(primer_mensaje: dict) -> bool:
    """El primer mensaje del hilo es de @gomezyriesco.cl — decide, sin
    Claude, si es un reenvío/acuse de recibo que cita un cuadro-resumen
    completo firmado originalmente por alguien de @smu.cl/@sb.cl (cadena
    VÁLIDA), en vez de Nico/Román iniciando una conversación interna (cadena
    NO válida, la usa la fase 'agenda', no esta). Antes esto se lo
    preguntábamos a Claude (`_evaluar_origen_gomezyriesco`); el mismo
    criterio ("¿el texto citado trae un cuadro completo Y viene de ese
    dominio?") ya se puede resolver con las herramientas puro-Python que
    `cuadro_resumen.py` usa para todo lo demás de esta fase — sin llamar a
    Claude para una pregunta que es estructural, no de interpretación de
    lenguaje libre."""
    citado = texto_citado(primer_mensaje.get("cuerpo_texto", ""))
    if not citado:
        return False
    if not cuadro_completo(extraer_campos_cuadro(citado)):
        return False
    return bool(dominios_citados(citado) & set(DOMINIOS_SMU))


def _dominio(remitente: str) -> str:
    direccion = extraer_direccion(remitente)
    return direccion.rsplit("@", 1)[1].lower() if "@" in direccion else ""


def _origen_cadena(primer_mensaje: dict) -> dict:
    """Devuelve {"valida": True|False}. Sin Claude (ver
    `_es_reenvio_de_cuadro_confiable`) — nunca falla, así que ya no hay un
    caso de error que el llamador deba manejar aparte."""
    dominio = _dominio(primer_mensaje.get("sender", ""))
    if dominio in DOMINIOS_SMU:
        return {"valida": True}
    if dominio == "gomezyriesco.cl":
        return {"valida": _es_reenvio_de_cuadro_confiable(primer_mensaje)}
    return {"valida": False}
