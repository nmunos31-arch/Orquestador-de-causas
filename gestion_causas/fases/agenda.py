"""Driver Python de la fase 'agenda' — Plan A + Plan B (ver planes de
implementación docs/superpowers/plans/2026-09-17-driver-python-agenda-plan-a.md
y docs/superpowers/plans/2026-09-17-driver-python-agenda-plan-b-minuta.md):
los 5 pasos de subagentes/agenda.md.

Revisa las causas activas, resuelve su próxima audiencia desde el mapa que
el orquestador ya armó para toda la corrida. En el hito de 14 días corridos
antes de una audiencia Única o de Juicio deja un borrador de ofrecimiento a
Román; en el hito de 4 días hábiles antes de una audiencia Única o
Preparatoria invoca la skill `/minuta-laboral` sobre la carpeta de la causa.
Nunca envía correos (solo deja borradores) ni toca el calendario."""

from __future__ import annotations

import html
from datetime import date
from email.utils import getaddresses
from pathlib import Path

from gestion_causas import agenda as dias_mod
from gestion_causas import bitacora as bitacora_mod
from gestion_causas import gmail_client
from gestion_causas import mapas as mapas_mod
from gestion_causas import reasoning
from gestion_causas import registro as registro_mod
from gestion_causas.seguimiento import extraer_direccion

TIPOS_CON_OFRECIMIENTO = {"Única", "Juicio"}
TIPOS_CON_MINUTA = {"Única", "Preparatoria"}

CUENTA_TRABAJO = "nmunoz@gomezyriesco.cl"

_MESES_ES = {
    1: "enero", 2: "febrero", 3: "marzo", 4: "abril", 5: "mayo", 6: "junio",
    7: "julio", 8: "agosto", 9: "septiembre", 10: "octubre", 11: "noviembre", 12: "diciembre",
}

SCHEMA_OFRECIMIENTO = {
    "type": "object",
    "properties": {
        "demandantes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "apellido": {"type": "string"},
                    "monto_recargo_30": {"type": "integer"},
                    "monto_afc": {"type": "integer"},
                },
                "required": ["apellido", "monto_recargo_30", "monto_afc"],
            },
        },
        "hay_discrepancia": {"type": "boolean"},
        "detalle_discrepancia": {"type": "string"},
    },
    "required": ["demandantes", "hay_discrepancia", "detalle_discrepancia"],
}


def _evaluar_montos_ofrecimiento(texto_cuadro_original: str, ruta_demanda: Path) -> dict:
    """Lee el PDF de la demanda (Claude la lee con su propia herramienta
    Read, en modo visión si es un escaneo sin capa de texto) para extraer,
    por cada demandante de la causa (puede ser uno o varios — no hay ningún
    campo estructurado con la lista de demandantes hoy), los montos exactos
    de Recargo legal 30% y Devolución de AFC. Coteja contra
    `texto_cuadro_original` (el cuerpo del correo con el cuadro resumen
    original, que trae "Conceptos demandados" como texto libre) y avisa si
    hay una discrepancia entre ambos, en vez de ocultarla — la demanda es
    la fuente legal (ver agenda.md paso 3c)."""
    contexto = {"texto_cuadro_original": texto_cuadro_original}
    tarea = (
        "Leé el archivo de la demanda indicado más abajo con tu herramienta Read (si es "
        "un PDF escaneado sin capa de texto, se lee en modo visión). Andá a la sección de "
        "Petitorio/Por tanto (normalmente al final) y extraé, por CADA demandante que "
        "aparezca en la causa: su apellido (tal como aparece en la identificación de las "
        "partes; si hay dos demandantes con el mismo apellido, agregá la inicial del "
        "nombre para distinguirlos), el monto exacto del Recargo legal 30% (recargo por "
        "término injustificado, art. 168 del Código del Trabajo), y el monto exacto de la "
        "Devolución de AFC (aporte al seguro de cesantía). Si la causa tiene un solo "
        "demandante, la lista trae un único elemento.\n\n"
        "Además, compará estos montos contra 'texto_cuadro_original' de más abajo (el "
        "cuerpo del correo con el cuadro resumen original de la demanda): si hay una "
        "diferencia entre lo que dice la demanda y lo que traía el cuadro, marcá "
        "hay_discrepancia=true y describila brevemente en detalle_discrepancia (si no hay "
        "diferencia — o el cuadro no menciona montos —, hay_discrepancia=false y "
        "detalle_discrepancia vacío)."
    )
    return reasoning.preguntar(
        tarea, contexto, SCHEMA_OFRECIMIENTO, ruta_archivo=ruta_demanda,
        etiqueta="agenda.montos_ofrecimiento",
    )


def _demandantes_validos(evaluacion: dict) -> list | None:
    """`reasoning.preguntar` solo hace json.loads sobre lo que devuelve
    Claude — SCHEMA_OFRECIMIENTO es apenas texto de prompt, nunca se valida
    de verdad. Esta función es la validación real: devuelve la lista de
    `demandantes` solo si es una lista no vacía donde cada elemento trae
    apellido (string no vacío), monto_recargo_30 y monto_afc (enteros); si
    no, devuelve None para que el llamador registre una acción en vez de
    reventar con un KeyError/IndexError/TypeError más adelante."""
    if not isinstance(evaluacion, dict):
        return None
    demandantes = evaluacion.get("demandantes")
    if not isinstance(demandantes, list) or not demandantes:
        return None
    for demandante in demandantes:
        if not isinstance(demandante, dict):
            return None
        apellido = demandante.get("apellido")
        if not isinstance(apellido, str) or not apellido.strip():
            return None
        for campo in ("monto_recargo_30", "monto_afc"):
            monto = demandante.get(campo)
            if not isinstance(monto, int) or isinstance(monto, bool):
                return None
    return demandantes


def _debe_generar_ofrecimiento(causa: dict, audiencia: dict, fecha_hoy: str) -> bool:
    """True si corresponde generar hoy el borrador de ofrecimiento (paso 3
    de agenda.md): el tipo de audiencia es Única o Juicio, la causa no
    marcó `aplica_ofrecimiento: false` (causas que no son una demanda
    laboral estándar contra la empresa), no se generó ya
    (`oferta_borrador_creado`), la causa no tiene ya un `estado_acuerdo`
    (un acuerdo en curso hace que un ofrecimiento nuevo esté de más, aunque
    quede una audiencia de formalidad en el calendario), y ya se cumplió —
    hoy o antes — el hito de 14 días corridos antes de la audiencia."""
    if audiencia.get("tipo") not in TIPOS_CON_OFRECIMIENTO:
        return False
    if causa.get("aplica_ofrecimiento") is False:
        return False
    if causa.get("oferta_borrador_creado"):
        return False
    if causa.get("estado_acuerdo"):
        return False
    fecha_audiencia = audiencia.get("fecha")
    if not fecha_audiencia:
        return False
    hito = dias_mod.dias_corridos_antes(fecha_audiencia, 14)
    return date.fromisoformat(fecha_hoy) >= hito


def _formatear_pesos(monto: int) -> str:
    return f"${monto:,}".replace(",", ".")


def _formatear_fecha_larga(fecha_iso: str) -> str:
    fecha = date.fromisoformat(fecha_iso)
    return f"{fecha.day} de {_MESES_ES[fecha.month]} de {fecha.year}"


def _armar_cuerpo_ofrecimiento(
    demandantes: list[dict], tipo_audiencia: str, fecha_audiencia: str, dias_hasta_audiencia: int
) -> str:
    """Arma el cuerpo del borrador de ofrecimiento EXACTAMENTE con la
    plantilla vigente (memoria gestion_causas_borrador_ofrecimiento_formato,
    corregida el 18.08.2026 — no la plantilla desactualizada de
    agenda.md paso 3e): desglose de Recargo 30%/AFC/Total por cada
    demandante, sin agregar contexto de negociación ni escenarios
    alternativos. La pregunta final ofrece el 60% de (Recargo 30% + AFC)
    por persona, redondeado a un peso entero."""
    fecha_legible = _formatear_fecha_larga(fecha_audiencia)
    tipo_legible = "de juicio" if tipo_audiencia == "Juicio" else "única"

    bloques = []
    ofertas = []
    total_general = 0
    for demandante in demandantes:
        recargo = demandante["monto_recargo_30"]
        afc = demandante["monto_afc"]
        total_persona = recargo + afc
        total_general += total_persona
        apellido = demandante["apellido"]
        bloques.append(
            f"{apellido}:\n"
            f"Recargo 30%: {_formatear_pesos(recargo)}\n"
            f"Devolución AFC: {_formatear_pesos(afc)}\n"
            f"Total: {_formatear_pesos(total_persona)}"
        )
        ofertas.append((apellido, round(total_persona * 0.6)))

    cuerpo = (
        "Estimado Román:\n\n"
        f"En esta causa, con audiencia {tipo_legible} fijada para el {fecha_legible} "
        f"(en {dias_hasta_audiencia} días), se demanda lo siguiente:\n\n"
        + "\n\n".join(bloques) + "\n\n"
    )
    if len(demandantes) > 1:
        cuerpo += f"Total demandado (todos): {_formatear_pesos(total_general)}\n\n"

    if len(ofertas) == 1:
        apellido, oferta = ofertas[0]
        pregunta = (
            f"Por lo anterior, consulto si hago un ofrecimiento por {_formatear_pesos(oferta)} "
            f"para don/doña {apellido}, equivalente al 60% del total"
        )
    else:
        partes = [f"{_formatear_pesos(oferta)} para don/doña {apellido}" for apellido, oferta in ofertas]
        pregunta = (
            "Por lo anterior, consulto si hago un ofrecimiento por "
            + ", ".join(partes[:-1]) + " y " + partes[-1] + ", equivalente al 60% del total"
        )

    return cuerpo + pregunta + "\n\n\nAtentamente,"


def _armar_asunto_ofrecimiento(causa: dict, rit: str) -> str:
    apellido = causa.get("demandante", "")
    empresa = causa.get("empresa", "")
    return f'Demanda laboral "{apellido} con {empresa}" Rit {rit}'


def _buscar_cadena_interna(rit: str) -> tuple[str, str] | None:
    """Busca la cadena interna que Nico abre con Román al llegar la demanda
    (asunto 'Demanda laboral ... [RIT]', primer mensaje de
    @gomezyriesco.cl — la misma que gestion-causas-smu detecta como interna
    y deja sin tocar). Devuelve (thread_id, asunto_real_del_primer_mensaje),
    o None si todavía no existe (causa nueva, ver agenda.md paso 3g). El
    asunto real se usa para armar la respuesta ("Re: <asunto de esa
    cadena>", agenda.md paso 3g) en vez de reconstruirlo desde los datos
    del registro, que puede no coincidir exactamente (otra ortografía, un
    prefijo "INT-", etc.). Si la búsqueda acotada por asunto no encuentra
    nada, reintenta sin restringir el asunto (causas RIT T-/O-, cuyo primer
    mensaje no necesariamente sigue el patrón "Demanda laboral...")."""
    hilos = gmail_client.buscar_hilos(f'from:gomezyriesco.cl subject:"{rit}"')
    if not hilos:
        hilos = gmail_client.buscar_hilos(f"from:gomezyriesco.cl {rit}")
    for hilo in hilos:
        mensajes = gmail_client.leer_hilo(hilo["id"])
        if mensajes and extraer_direccion(mensajes[0].get("sender", "")).endswith("@gomezyriesco.cl"):
            return hilo["id"], mensajes[0].get("subject", "")
    return None


def _destinatarios_respuesta(thread_id: str) -> str:
    """Todos los participantes internos (@gomezyriesco.cl) de la cadena,
    salvo el propio Nico — el borrador de ofrecimiento debe ir a todos, no
    solo a Román (memoria gestion_causas_borrador_ofrecimiento_formato,
    corrección del 18.08.2026). "Todos" incluye a quien solo aparece como
    destinatario (to/cc) y nunca escribió un mensaje propio — no alcanza
    con mirar el remitente de cada mensaje."""
    mensajes = gmail_client.leer_hilo(thread_id)
    encabezados = []
    for mensaje in mensajes:
        for campo in ("sender", "to", "cc"):
            valor = mensaje.get(campo, "")
            if valor:
                encabezados.append(valor)

    direcciones: list[str] = []
    for _nombre, direccion in getaddresses(encabezados):
        direccion = direccion.strip().lower()
        if direccion.endswith("@gomezyriesco.cl") and direccion != CUENTA_TRABAJO and direccion not in direcciones:
            direcciones.append(direccion)
    return ", ".join(direcciones) if direcciones else "rgomez@gomezyriesco.cl"


def _asunto_de_borrador(detalle: dict) -> str:
    """Extrae el asunto de un dict de detalle de borrador tal como lo
    devuelve la API de Gmail (`listar_borradores_de_hilo`/
    `buscar_borrador_por_asunto`): vive en
    detalle["message"]["payload"]["headers"], buscando el header "subject"
    sin importar mayúsculas."""
    headers = detalle.get("message", {}).get("payload", {}).get("headers", [])
    return next((h.get("value", "") for h in headers if h.get("name", "").lower() == "subject"), "")


def _crear_borrador_ofrecimiento(rit: str, cuerpo: str, asunto: str) -> tuple[str, bool, bool]:
    """Crea el borrador de ofrecimiento: responde dentro de la cadena
    interna si ya existe (usando el asunto REAL de esa cadena, "Re: <asunto
    de esa cadena>" — agenda.md paso 3g, no el reconstruido desde el
    registro), o crea un correo nuevo como respaldo si Nico todavía no la
    abrió. Nunca duplica un borrador de ofrecimiento ya existente — pero
    tampoco confunde con un borrador ajeno que comparte la misma cadena
    interna (p. ej. una respuesta a medio escribir de otro asunto): solo se
    trata como "nuestro" un borrador cuyo asunto menciona el RIT; si
    ninguno de los borradores de la cadena lo menciona, se crea uno nuevo
    igual que si la cadena no tuviera borradores.

    Devuelve (draft_id, creado, borrador_ajeno_detectado):
    - `creado` es True solo si esta llamada efectivamente creó un borrador
      nuevo (False si reusó uno ya existente que sí menciona el RIT).
    - `borrador_ajeno_detectado` es True cuando la cadena interna tenía
      borradores pero ninguno mencionaba el RIT (para que el llamador avise
      a Nico a revisar manualmente esa cadena)."""
    cuerpo_html = html.escape(cuerpo).replace("\n", "<br>\n")
    encontrado = _buscar_cadena_interna(rit)
    if encontrado:
        thread_id, asunto_real_hilo = encontrado
        existentes = gmail_client.listar_borradores_de_hilo(thread_id)
        propios = [d for d in existentes if rit in _asunto_de_borrador(d)]
        if propios:
            return propios[0]["id"], False, False
        borrador_ajeno_detectado = bool(existentes)
        destinatarios = _destinatarios_respuesta(thread_id)
        asunto_respuesta = f"Re: {asunto_real_hilo}" if asunto_real_hilo else f"Re: {asunto}"
        borrador = gmail_client.crear_borrador(
            destinatarios, asunto_respuesta, cuerpo_html, thread_id=thread_id, html=True
        )
        return borrador["id"], True, borrador_ajeno_detectado
    else:
        existentes = gmail_client.buscar_borrador_por_asunto(asunto)
        if existentes:
            return existentes[0]["id"], False, False
        borrador = gmail_client.crear_borrador("rgomez@gomezyriesco.cl", asunto, cuerpo_html, html=True)
        return borrador["id"], True, False


def _procesar_ofrecimiento(
    causa: dict, audiencia: dict, fecha_hoy: str, ruta_registro_causas: Path, acciones: list[dict]
) -> bool:
    """Ejecuta el paso 3 completo para una causa (si corresponde): evalúa
    los montos con Claude, arma el correo con la plantilla fija, y lo deja
    como borrador. Devuelve True si se creó (o reusó) un borrador."""
    rit = causa["rit"]
    if not _debe_generar_ofrecimiento(causa, audiencia, fecha_hoy):
        return False

    carpeta = causa.get("carpeta")
    ruta_demanda = Path(carpeta) / "demanda.pdf" if carpeta else None
    if not ruta_demanda or not ruta_demanda.exists():
        acciones.append({
            "rit": rit,
            "que": (
                "Tocó el hito de 14 días para el ofrecimiento, pero no se encontró "
                "demanda.pdf en la carpeta de la causa — revisar a mano."
            ),
            "urgencia": "media",
        })
        return False

    texto_cuadro = ""
    thread_id_origen = causa.get("thread_id")
    if thread_id_origen:
        mensajes_origen = gmail_client.leer_hilo(thread_id_origen)
        if mensajes_origen:
            texto_cuadro = mensajes_origen[0].get("cuerpo_texto", "")

    evaluacion = _evaluar_montos_ofrecimiento(texto_cuadro, ruta_demanda)
    if evaluacion.get("error"):
        acciones.append({
            "rit": rit,
            "que": f"No se pudo calcular el ofrecimiento automáticamente: {evaluacion['error']}",
            "urgencia": "media",
        })
        return False

    demandantes = _demandantes_validos(evaluacion)
    if demandantes is None:
        acciones.append({
            "rit": rit,
            "que": (
                "No se pudieron extraer montos válidos por demandante para el ofrecimiento — "
                "respuesta de Claude no tiene el formato esperado."
            ),
            "urgencia": "media",
        })
        return False

    if evaluacion.get("hay_discrepancia"):
        acciones.append({
            "rit": rit,
            "que": f"Discrepancia: {evaluacion.get('detalle_discrepancia', '')}",
            "urgencia": "alta",
        })

    fecha_audiencia = audiencia["fecha"]
    dias_hasta_audiencia = (date.fromisoformat(fecha_audiencia) - date.fromisoformat(fecha_hoy)).days
    cuerpo = _armar_cuerpo_ofrecimiento(
        demandantes, audiencia["tipo"], fecha_audiencia, dias_hasta_audiencia
    )
    asunto = _armar_asunto_ofrecimiento(causa, rit)
    draft_id, creado, borrador_ajeno_detectado = _crear_borrador_ofrecimiento(rit, cuerpo, asunto)

    registro_mod.registrar_causa(rit, {"oferta_borrador_creado": True}, ruta=ruta_registro_causas)
    if creado:
        bitacora_mod.registrar(f"Borrador de ofrecimiento creado (draft {draft_id})", rit=rit)
    else:
        bitacora_mod.registrar(
            f"Ya existía un borrador de ofrecimiento (draft {draft_id}) — revisar si es el correcto", rit=rit
        )
    if borrador_ajeno_detectado:
        acciones.append({
            "rit": rit,
            "que": (
                "Se encontró un borrador en la cadena interna que no parece ser el de "
                "ofrecimiento (no menciona el RIT) — revisar manualmente."
            ),
            "urgencia": "media",
        })
    return True


def _debe_generar_minuta(causa: dict, audiencia: dict, fecha_hoy: str) -> bool:
    """True si corresponde invocar hoy la skill /minuta-laboral (paso 4 de
    agenda.md): el tipo de audiencia es Única o Preparatoria (no Juicio — la
    minuta de juicio tiene su propia lógica, fuera de este proyecto), la
    causa no marcó `aplica_minuta_laboral: false`, no se generó ya
    (`minuta_ejecutada`), y ya se cumplió — hoy o antes — el hito de 4 días
    hábiles antes de la audiencia. A diferencia de `_debe_generar_ofrecimiento`,
    no mira `estado_acuerdo`: la minuta de prueba sigue siendo necesaria
    aunque haya un acuerdo en curso."""
    if audiencia.get("tipo") not in TIPOS_CON_MINUTA:
        return False
    if causa.get("aplica_minuta_laboral") is False:
        return False
    if causa.get("minuta_ejecutada"):
        return False
    fecha_audiencia = audiencia.get("fecha")
    if not fecha_audiencia:
        return False
    hito = dias_mod.dias_habiles_antes(fecha_audiencia, 4)
    return date.fromisoformat(fecha_hoy) >= hito


def _docs_minuta_existentes(carpeta: Path) -> set[str]:
    """Nombres de archivo de los .docx en `carpeta` cuyo nombre menciona
    "minuta" (case-insensitive) — se compara antes/después de invocar la
    skill para detectar, por efecto observable, si generó un archivo nuevo
    (un exit code 0 del subprocess no garantiza que la skill haya completado
    su flujo)."""
    return {p.name for p in carpeta.glob("*.docx") if "minuta" in p.name.lower()}


def _invocar_minuta_laboral(carpeta: Path, rit: str) -> dict:
    """Invoca la skill /minuta-laboral (sin tocarla — sigue viviendo aparte,
    fuera de este rediseño) sobre la carpeta de la causa. Devuelve el dict
    de `reasoning.invocar_skill` tal cual (`{"ok": True, ...}` o
    `{"error": ...}`); el llamador decide qué hacer con el error."""
    prompt = (
        f"/minuta-laboral {carpeta}\n\n"
        f"Trabajá únicamente sobre la carpeta de la causa {rit} indicada arriba "
        "(ya tiene la plantilla, la demanda y los documentos de prueba disponibles)."
    )
    return reasoning.invocar_skill(prompt, carpeta)


def _procesar_minuta(
    causa: dict, audiencia: dict, fecha_hoy: str, ruta_registro_causas: Path, acciones: list[dict]
) -> bool:
    """Ejecuta el paso 4 completo para una causa (si corresponde): invoca la
    skill /minuta-laboral y, si detecta que generó un .docx nuevo, registra
    `minuta_ejecutada`. Devuelve True si se generó la minuta."""
    rit = causa["rit"]
    if not _debe_generar_minuta(causa, audiencia, fecha_hoy):
        return False

    carpeta_str = causa.get("carpeta")
    carpeta = Path(carpeta_str) if carpeta_str else None
    if not carpeta or not carpeta.exists():
        acciones.append({
            "rit": rit,
            "que": (
                "Tocó el hito de 4 días hábiles para la minuta, pero no se encontró "
                "la carpeta de la causa — revisar a mano."
            ),
            "urgencia": "media",
        })
        return False

    docs_antes = _docs_minuta_existentes(carpeta)
    resultado = _invocar_minuta_laboral(carpeta, rit)
    if resultado.get("error"):
        acciones.append({
            "rit": rit,
            "que": f"No se pudo generar la minuta automáticamente: {resultado['error']}",
            "urgencia": "media",
        })
        return False

    docs_despues = _docs_minuta_existentes(carpeta)
    if not (docs_despues - docs_antes):
        acciones.append({
            "rit": rit,
            "que": (
                "La skill /minuta-laboral terminó pero no se detectó una minuta nueva "
                "en la carpeta de la causa — revisar a mano."
            ),
            "urgencia": "media",
        })
        return False

    registro_mod.registrar_causa(rit, {"minuta_ejecutada": True}, ruta=ruta_registro_causas)
    bitacora_mod.registrar("Minuta generada a 4 días hábiles de la audiencia", rit=rit)
    return True


def correr(
    contexto_corrida: dict,
    *,
    ruta_registro_causas: Path = registro_mod.RUTA_REGISTRO_CAUSAS,
) -> dict:
    causas = registro_mod.causas_para_goteo(
        hoy=contexto_corrida["fecha_hoy"], dias_ventana_post_audiencia=0, ruta=ruta_registro_causas
    )
    if not causas:
        return {
            "fase": "agenda",
            "titular": "Sin causas activas para revisar agenda",
            "metricas": [],
            "items": [],
            "acciones": [],
            "notas": [],
        }

    mapa_audiencias = mapas_mod.leer_mapa_audiencias(contexto_corrida)

    items: list[dict] = []
    acciones: list[dict] = []
    notas: list[dict] = []
    ofrecimientos_creados = 0
    minutas_generadas = 0
    sin_evento = 0

    for causa in causas:
        rit = causa["rit"]
        audiencia = mapa_audiencias.get("rit_a_audiencia", {}).get(rit)
        if not audiencia:
            sin_evento += 1
            continue
        if audiencia.get("tipo") == "Ambiguo":
            notas.append({
                "tipo": "audiencia_ambigua",
                "detalle": (
                    f"{rit}: no se pudo determinar el tipo de audiencia "
                    f"({audiencia.get('resumen', '')}) — revisar a mano."
                ),
            })
            continue

        titulo = f"{causa.get('demandante', '')} con {causa.get('empresa', '')}"
        if _procesar_ofrecimiento(causa, audiencia, contexto_corrida["fecha_hoy"], ruta_registro_causas, acciones):
            ofrecimientos_creados += 1
            items.append({"rit": rit, "titulo": titulo, "detalle": "Borrador de ofrecimiento creado"})

        # Hitos independientes (14 días corridos vs. 4 días hábiles antes de
        # la audiencia): una causa puede disparar ambos el mismo día.
        if _procesar_minuta(causa, audiencia, contexto_corrida["fecha_hoy"], ruta_registro_causas, acciones):
            minutas_generadas += 1
            items.append({"rit": rit, "titulo": titulo, "detalle": "Minuta de prueba generada"})

    resumen = {
        "fase": "agenda",
        "titular": _armar_titular(ofrecimientos_creados, minutas_generadas),
        "metricas": [
            {"etiqueta": "Causas revisadas", "valor": len(causas)},
            {"etiqueta": "Borradores de ofrecimiento creados", "valor": ofrecimientos_creados},
            {"etiqueta": "Minutas generadas", "valor": minutas_generadas},
            {"etiqueta": "Sin evento de calendario todavía", "valor": sin_evento},
        ],
        "items": items,
        "acciones": acciones,
        "notas": notas,
    }
    return resumen


def _armar_titular(ofrecimientos_creados: int, minutas_generadas: int) -> str:
    if ofrecimientos_creados == 0 and minutas_generadas == 0:
        return "Sin novedades"
    partes = []
    if ofrecimientos_creados:
        plural = "es" if ofrecimientos_creados != 1 else ""
        partes.append(f"{ofrecimientos_creados} borrador{plural} de ofrecimiento creado{plural}")
    if minutas_generadas:
        plural = "s" if minutas_generadas != 1 else ""
        partes.append(f"{minutas_generadas} minuta{plural} generada{plural}")
    return ", ".join(partes)
