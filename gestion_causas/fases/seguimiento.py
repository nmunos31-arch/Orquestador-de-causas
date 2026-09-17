"""Driver Python de la fase 'seguimiento' (ver plan de implementación
docs/superpowers/plans/2026-09-17-driver-python-seguimiento.md): los 5 pasos
de subagentes/seguimiento.md.

Dos fuentes dan de alta pedidos nuevos en cada corrida (borradores de
documentos que Nico ya envió, correos etiquetados a mano con
Esperando-Respuesta). Sobre los pedidos abiertos, revisa si hubo respuesta
real (descartando acuses de recibo), aplica la cadencia de insistencia y
deja un borrador cuando corresponde. Nunca envía correos (solo deja
borradores) ni borra ni cierra nada sin que Nico lo revise."""

from __future__ import annotations

import html as html_mod
import re
from datetime import date
from email.utils import getaddresses
from pathlib import Path

from gestion_causas import agenda as dias_mod
from gestion_causas import bitacora as bitacora_mod
from gestion_causas import gmail_client
from gestion_causas import mapas as mapas_mod
from gestion_causas import reasoning
from gestion_causas import registro as registro_mod
from gestion_causas import seguimiento as seguimiento_mod

CUENTA_TRABAJO = "nmunoz@gomezyriesco.cl"
CUENTA_ACUERDO_DANIELA = "dsanchezv@smu.cl"

UMBRAL_DIAS_HABILES_INSISTENCIA_DOCUMENTOS = 4

TEXTO_A_DOCUMENTOS = "los documentos solicitados"
TEXTO_A_ACUERDO = "el correo anterior"

SCHEMA_CLASIFICAR_PEDIDO = {
    "type": "object",
    "properties": {
        "estado": {"type": "string", "enum": ["completo", "parcial", "sin_respuesta_real"]},
        "items_recibidos": {"type": "array", "items": {"type": "string"}},
        "motivo": {"type": "string"},
    },
    "required": ["estado", "items_recibidos", "motivo"],
}


def _clasificar_pedido(pedido: dict, mensajes_posteriores_reales: list[dict]) -> dict:
    """Le pide a Claude que interprete los mensajes posteriores reales (ya
    descartados los acuses de recibo por `parece_cierre_sin_pedido`) contra
    lo pedido. Comparar texto libre de un correo/adjunto contra una lista de
    ítems en español natural no es mecanizable con regex de forma confiable
    — mismo tipo de juicio que ya usan `smu.py`/`agenda.py` para leer una
    demanda. Devuelve 'sin_respuesta_real' tanto si nada respondió lo
    pedido como si los mensajes son solo informativos y no cuentan como
    respuesta real (memoria
    gestion_causas_seguimiento_no_insistir_solo_informativo)."""
    tipo = pedido.get("tipo", "documentos")
    contexto = {
        "tipo": tipo,
        "items_pedidos": pedido.get("items_pedidos") or [],
        "mensajes_posteriores": [
            {
                "remitente": m.get("sender", ""),
                "asunto": m.get("subject", ""),
                "cuerpo_texto": (m.get("cuerpo_texto") or "")[:2000],
                "adjuntos": [a.get("filename", "") for a in m.get("adjuntos", [])],
            }
            for m in mensajes_posteriores_reales
        ],
    }
    if tipo == "documentos":
        tarea = (
            "Un abogado pidió los documentos listados en 'items_pedidos' (texto libre en "
            "español, ej. 'Últimas 6 liquidaciones de remuneraciones'). Los mensajes en "
            "'mensajes_posteriores' llegaron después de ese pedido (ya se descartaron "
            "acuses de recibo simples). Para cada item de 'items_pedidos', decidí si algún "
            "mensaje posterior lo cubre (por un adjunto cuyo nombre corresponda, o una "
            "respuesta explícita en el texto) y devolvé en 'items_recibidos' el texto "
            "EXACTO (copiado tal cual, sin modificarlo) de cada item de 'items_pedidos' "
            "que sí llegó. 'estado' es 'completo' si llegaron todos, 'parcial' si llegó al "
            "menos uno pero no todos, o 'sin_respuesta_real' si ninguno llegó y los "
            "mensajes posteriores son solo comentarios informativos que no aportan ningún "
            "documento pedido."
        )
    else:
        tarea = (
            "Un abogado envió una propuesta de acuerdo o una consulta puntual y espera la "
            "respuesta de la contraparte. Los mensajes en 'mensajes_posteriores' llegaron "
            "después (ya se descartaron acuses de recibo simples). Decidí: 'completo' si "
            "algún mensaje responde de verdad la propuesta/consulta (acepta, rechaza, "
            "contrapropone, contesta la pregunta); 'sin_respuesta_real' si los mensajes son "
            "solo informativos (un aviso, un 'para su conocimiento', algo que no responde "
            "lo pedido). 'items_recibidos' siempre vacío para este tipo."
        )
    return reasoning.preguntar(tarea, contexto, SCHEMA_CLASIFICAR_PEDIDO)


def _mensajes_posteriores(
    thread_id: str, mensajes_hilo: list[dict], fecha_envio: str, rit: str | None, mapa_hilos: dict
) -> list[dict]:
    """Mensajes con fecha posterior a `fecha_envio`: los del hilo original
    más los de otros hilos del mismo RIT que el barrido combinado de la
    corrida (mapa_hilos) haya encontrado (seguimiento.md paso 3b) — Gmail no
    siempre encadena por los headers reales, la respuesta puede llegar en un
    hilo que parece "separado" aunque el pedido esté en otro."""
    fecha_envio_dt = date.fromisoformat(fecha_envio)
    candidatos = list(mensajes_hilo)
    if rit:
        for otro_thread_id in mapa_hilos.get("rit_a_hilos", {}).get(rit, []):
            if otro_thread_id == thread_id:
                continue
            candidatos += mapa_hilos.get("hilos", {}).get(otro_thread_id, [])
    return [m for m in candidatos if seguimiento_mod.parsear_fecha(m["date"]).date() > fecha_envio_dt]


def _nombre_para_saludo(destinatario: str) -> str:
    if not destinatario or "@" not in destinatario:
        return ""
    return destinatario.split("@")[0].capitalize()


def _destinatarios_pedido(pedido: dict, mensajes_hilo: list[dict]) -> dict:
    """"Para" = destinatario registrado en el pedido (o, si viene vacío, el
    `to` del último mensaje propio del hilo); "CC" = el resto de los
    participantes del hilo, sin incluir a Nico ni duplicar el "para"."""
    para = pedido.get("destinatario") or ""
    if not para:
        propios = [m for m in mensajes_hilo if seguimiento_mod.extraer_direccion(m.get("sender", "")) == CUENTA_TRABAJO]
        if propios:
            para = seguimiento_mod.destinatarios_de_ultimo_propio(propios[-1], CUENTA_TRABAJO)["para"]

    vistos = {CUENTA_TRABAJO, (para or "").strip().lower()}
    cc: list[str] = []
    for m in mensajes_hilo:
        for campo in ("sender", "to", "cc"):
            for _nombre, direccion in getaddresses([m.get(campo, "") or ""]):
                direccion = direccion.strip().lower()
                if direccion and direccion not in vistos:
                    vistos.add(direccion)
                    cc.append(direccion)
    return {"para": para, "cc": ", ".join(cc)}


def _asunto_respuesta(mensajes_hilo: list[dict]) -> str:
    asunto_base = mensajes_hilo[-1].get("subject", "") if mensajes_hilo else ""
    asunto_normalizado = seguimiento_mod.normalizar_asunto(asunto_base)
    return f"Re: {asunto_normalizado}" if asunto_normalizado else "Re:"


def _texto_plano_a_html(texto: str) -> str:
    return "<br>".join(html_mod.escape(linea) for linea in texto.splitlines())


def _texto_a_lista_html(items: list[str]) -> str:
    return "<ol>" + "".join(f"<li>{html_mod.escape(item)}</li>" for item in items) + "</ol>"


def _cuerpo_con_lista(cuerpo_texto: str, items: list[str]) -> str:
    antes, despues = cuerpo_texto.split("[[LISTA]]")
    antes_html = "<br>".join(html_mod.escape(l) for l in antes.splitlines())
    despues_html = "<br>".join(html_mod.escape(l) for l in despues.splitlines())
    return antes_html + _texto_a_lista_html(items) + despues_html


def _crear_insistencia(pedido: dict, tipo: str, mensajes_hilo: list[dict]) -> tuple[bool, str | None]:
    """Crea el borrador de insistencia (texto A). El comando nunca duplica:
    si la cadena ya tiene otro borrador sin enviar, lo reusa."""
    thread_id = pedido["thread_id"]
    existentes = gmail_client.listar_borradores_de_hilo(thread_id)
    if existentes:
        return False, existentes[0]["id"]

    nombre = _nombre_para_saludo(pedido.get("destinatario", ""))
    que_insistir = TEXTO_A_DOCUMENTOS if tipo == "documentos" else TEXTO_A_ACUERDO
    cuerpo = f"Estimado/a {nombre}:\n\nJunto con saludar, ruego tener presente {que_insistir}.\n\nAtentamente,"
    destinatarios = _destinatarios_pedido(pedido, mensajes_hilo)
    asunto = _asunto_respuesta(mensajes_hilo)
    borrador = gmail_client.crear_borrador(
        destinatarios["para"], asunto, _texto_plano_a_html(cuerpo),
        thread_id=thread_id, html=True, cc=destinatarios["cc"] or None,
    )
    return True, borrador["id"]


def _crear_recordatorio_faltantes(
    pedido: dict, faltantes: list[str], mensajes_hilo: list[dict]
) -> tuple[bool, str | None]:
    """Crea el borrador de recordatorio de faltantes (texto B, solo
    `tipo: documentos` con respuesta parcial). Mismo criterio de no
    duplicar que `_crear_insistencia`."""
    thread_id = pedido["thread_id"]
    existentes = gmail_client.listar_borradores_de_hilo(thread_id)
    if existentes:
        return False, existentes[0]["id"]

    nombre = _nombre_para_saludo(pedido.get("destinatario", ""))
    cuerpo_base = (
        f"Estimado/a {nombre}:\n\nJunto con saludar, ruego tener presente que se "
        "encuentran pendiente los siguientes documentos:\n\n[[LISTA]]\n\nAtentamente,"
    )
    cuerpo_html = _cuerpo_con_lista(cuerpo_base, faltantes)
    destinatarios = _destinatarios_pedido(pedido, mensajes_hilo)
    asunto = _asunto_respuesta(mensajes_hilo)
    borrador = gmail_client.crear_borrador(
        destinatarios["para"], asunto, cuerpo_html,
        thread_id=thread_id, html=True, cc=destinatarios["cc"] or None,
    )
    return True, borrador["id"]


def _tipo_aviso(pedido: dict) -> str:
    """Solo informativo (no cambia la lógica de cadencia): "acuerdo-daniela"
    para el pedido de tipo acuerdo dirigido a Daniela (SMU), "causa-laboral"
    para cualquier otro acuerdo, "documentos" para tipo documentos."""
    if pedido.get("tipo") == "acuerdo":
        destinatario = (pedido.get("destinatario") or "").strip().lower()
        return "acuerdo-daniela" if destinatario == CUENTA_ACUERDO_DANIELA else "causa-laboral"
    return "documentos"


def _evaluar_insistencia(
    pedido: dict,
    fecha_hoy: str,
    mensajes_hilo: list[dict],
    acciones: list[dict],
    items: list[dict],
    ruta_registro_pedidos: Path,
    ruta_registro_seguimiento: Path,
    ruta_registro_causas: Path,
) -> str:
    """Rama mecánica (sin mensajes posteriores reales que interpretar):
    umbral por tipo (4 días hábiles para documentos, 24 horas —aproximadas
    a "al menos un día corrido después"— para acuerdo) y cadencia de
    `puede_insistir`."""
    thread_id = pedido["thread_id"]
    tipo = pedido.get("tipo", "documentos")
    fecha_envio = pedido["fecha_envio"]
    rit = pedido.get("rit")

    if tipo == "documentos":
        corresponde = dias_mod.dias_habiles_entre(fecha_envio, fecha_hoy) >= UMBRAL_DIAS_HABILES_INSISTENCIA_DOCUMENTOS
    else:
        corresponde = date.fromisoformat(fecha_hoy) > date.fromisoformat(fecha_envio)
    if not corresponde:
        registro_mod.registrar_pedido(thread_id, {}, ruta=ruta_registro_pedidos)
        return "sin_novedad"

    cadencia = registro_mod.puede_insistir(
        thread_id, hoy=fecha_hoy, ruta=ruta_registro_seguimiento, ruta_causas=ruta_registro_causas
    )
    if not cadencia["puede"]:
        if "audiencia agendada" in cadencia.get("motivo", ""):
            registro_mod.registrar_pedido(thread_id, {"estado": "gestion_manual"}, ruta=ruta_registro_pedidos)
            acciones.append({
                "rit": rit,
                "que": f"Causa sin audiencia agendada, sin respuesta ({tipo}) — requiere gestión manual",
                "urgencia": "alta",
            })
            bitacora_mod.registrar("Seguimiento: pedido pasa a gestión manual (sin audiencia agendada)", rit=rit)
            return "gestion_manual"
        registro_mod.registrar_pedido(thread_id, {}, ruta=ruta_registro_pedidos)
        return "sin_novedad"

    creado, draft_id = _crear_insistencia(pedido, tipo, mensajes_hilo)
    registro_mod.registrar_pedido(thread_id, {}, ruta=ruta_registro_pedidos)
    if not creado:
        return "sin_novedad"

    registro_mod.registrar_aviso(
        thread_id, _tipo_aviso(pedido), fecha_hoy, rit=rit, draft_id=draft_id, ruta=ruta_registro_seguimiento
    )
    items.append({
        "rit": rit, "titulo": pedido.get("destinatario", ""),
        "detalle": f"{cadencia['n_aviso']}º aviso de insistencia",
    })
    bitacora_mod.registrar(f"Seguimiento: insistencia creada (aviso {cadencia['n_aviso']})", rit=rit)
    return "insistencia"


def _procesar_pedido(
    pedido: dict,
    fecha_hoy: str,
    mapa_hilos: dict,
    ruta_registro_pedidos: Path,
    ruta_registro_seguimiento: Path,
    ruta_registro_causas: Path,
    acciones: list[dict],
    items: list[dict],
) -> str:
    """Ejecuta el paso 3 completo para un pedido abierto. Devuelve uno de:
    'completo', 'insistencia', 'recordatorio', 'gestion_manual',
    'sin_novedad'."""
    thread_id = pedido["thread_id"]
    rit = pedido.get("rit")
    tipo = pedido.get("tipo", "documentos")
    fecha_envio = pedido.get("fecha_envio")

    if not fecha_envio:
        registro_mod.registrar_pedido(thread_id, {}, ruta=ruta_registro_pedidos)
        return "sin_novedad"

    mensajes_hilo = gmail_client.leer_hilo(thread_id)
    posteriores = _mensajes_posteriores(thread_id, mensajes_hilo, fecha_envio, rit, mapa_hilos)
    posteriores_reales = [
        m for m in posteriores if not seguimiento_mod.parece_cierre_sin_pedido(m.get("cuerpo_texto", ""))
    ]

    if posteriores_reales:
        clasificacion = _clasificar_pedido(pedido, posteriores_reales)
        if clasificacion.get("error"):
            acciones.append({
                "rit": rit,
                "que": f"No se pudo interpretar la respuesta del pedido: {clasificacion['error']}",
                "urgencia": "media",
            })
            registro_mod.registrar_pedido(thread_id, {}, ruta=ruta_registro_pedidos)
            return "sin_novedad"

        estado = clasificacion.get("estado")
        if estado == "completo":
            registro_mod.registrar_pedido(thread_id, {"estado": "completo"}, ruta=ruta_registro_pedidos)
            if pedido.get("label_id"):
                gmail_client.quitar_etiqueta_de_hilo(thread_id, pedido["label_id"])
            bitacora_mod.registrar(f"Seguimiento: pedido completado ({tipo})", rit=rit)
            return "completo"

        if estado == "parcial" and tipo == "documentos":
            items_recibidos = sorted(
                set(pedido.get("items_recibidos") or []) | set(clasificacion.get("items_recibidos") or [])
            )
            items_pedidos = pedido.get("items_pedidos") or []
            faltantes = [i for i in items_pedidos if i not in items_recibidos]
            if not faltantes:
                registro_mod.registrar_pedido(
                    thread_id, {"estado": "completo", "items_recibidos": items_recibidos}, ruta=ruta_registro_pedidos
                )
                bitacora_mod.registrar("Seguimiento: pedido completado (documentos)", rit=rit)
                return "completo"

            creado, _draft_id = _crear_recordatorio_faltantes(pedido, faltantes, mensajes_hilo)
            registro_mod.registrar_pedido(
                thread_id, {"estado": "parcial", "items_recibidos": items_recibidos}, ruta=ruta_registro_pedidos
            )
            if not creado:
                return "sin_novedad"
            items.append({
                "rit": rit, "titulo": pedido.get("destinatario", ""),
                "detalle": f"Recordatorio de faltantes: {', '.join(faltantes)}",
            })
            bitacora_mod.registrar(f"Seguimiento: recordatorio de faltantes creado ({len(faltantes)} items)", rit=rit)
            return "recordatorio"

        # 'sin_respuesta_real' (o un 'parcial' inesperado en un pedido tipo
        # acuerdo): sigue el flujo mecánico de insistencia de más abajo,
        # igual que si no hubiera habido ningún mensaje posterior real —
        # justamente el caso que evita insistir sobre un mensaje solo
        # informativo (ver docstring de _clasificar_pedido).

    return _evaluar_insistencia(
        pedido, fecha_hoy, mensajes_hilo, acciones, items,
        ruta_registro_pedidos, ruta_registro_seguimiento, ruta_registro_causas,
    )


def _verificar_borradores_pendientes(ruta_registro_causas: Path, ruta_registro_pedidos: Path) -> dict:
    """Paso 1a: para cada causa con un borrador de documentos registrado,
    revisa si Nico ya lo envió (mismo criterio que
    `cli.cmd_verificar_borradores_pendientes`, llamando a `registro_mod`/
    `gmail_client` directo en vez de por subprocess)."""
    causas = registro_mod.causas_con_borrador_pendiente(ruta=ruta_registro_causas)
    pendientes = []
    enviados = []
    descartados = []
    for causa in causas:
        draft_id = causa["borrador_documentos_draft_id"]
        rit = causa.get("rit")
        if gmail_client.borrador_existe(draft_id):
            pendientes.append({"rit": rit, "draft_id": draft_id, "thread_id": causa.get("thread_id")})
            continue

        thread_id = causa.get("thread_id")
        ultimo_propio = None
        if thread_id:
            for m in gmail_client.leer_hilo(thread_id):
                if seguimiento_mod.extraer_direccion(m.get("sender", "")) == CUENTA_TRABAJO:
                    ultimo_propio = m

        if ultimo_propio is not None:
            destinatarios = seguimiento_mod.destinatarios_de_ultimo_propio(ultimo_propio, CUENTA_TRABAJO)
            fecha_envio = str(seguimiento_mod.parsear_fecha(ultimo_propio["date"]).date())
            registro_mod.registrar_pedido(thread_id, {
                "rit": rit, "tipo": "documentos", "message_id": ultimo_propio["id"],
                "fecha_envio": fecha_envio, "destinatario": destinatarios["para"],
                "items_pedidos": causa.get("documentos_solicitados") or [],
                "estado": "esperando", "origen": "borrador_enviado",
            }, ruta=ruta_registro_pedidos)
            enviados.append({"rit": rit, "thread_id": thread_id, "fecha_envio": fecha_envio})
        else:
            descartados.append(rit)

        registro_mod.registrar_causa(rit, {"borrador_documentos_draft_id": None}, ruta=ruta_registro_causas)
    return {"pendientes": pendientes, "enviados": enviados, "descartados": descartados}


def _pedidos_desde_etiqueta(ruta_registro_pedidos: Path) -> dict:
    """Paso 1b: pedidos/propuestas que Nico mandó a mano, marcados con la
    etiqueta Esperando-Respuesta (mismo criterio que
    `cli.cmd_pedidos_desde_etiqueta`)."""
    label_id = gmail_client.obtener_o_crear_etiqueta(gmail_client.ETIQUETA_ESPERANDO_RESPUESTA)
    hilos = gmail_client.buscar_hilos(f"label:{gmail_client.ETIQUETA_ESPERANDO_RESPUESTA}")

    creados = []
    ya_registrados = []
    for hilo in hilos:
        thread_id = hilo["id"]
        if registro_mod.obtener_pedido(thread_id, ruta=ruta_registro_pedidos) is not None:
            ya_registrados.append(thread_id)
            continue
        mensajes = gmail_client.leer_hilo(thread_id)
        propios = [m for m in mensajes if seguimiento_mod.extraer_direccion(m.get("sender", "")) == CUENTA_TRABAJO]
        if not propios:
            continue
        ultimo_propio = propios[-1]
        destinatarios = seguimiento_mod.destinatarios_de_ultimo_propio(ultimo_propio, CUENTA_TRABAJO)
        asunto_normalizado = seguimiento_mod.normalizar_asunto(ultimo_propio["subject"])
        tiene_lista = bool(re.search(r"^\s*(\d+[.)]|[-*])\s+\S", ultimo_propio["cuerpo_texto"], re.MULTILINE))
        datos = {
            "rit": registro_mod.extraer_rit(asunto_normalizado + " " + ultimo_propio["cuerpo_texto"]),
            "tipo": "documentos" if tiene_lista else "acuerdo",
            "message_id": ultimo_propio["id"],
            "fecha_envio": str(seguimiento_mod.parsear_fecha(ultimo_propio["date"]).date()),
            "destinatario": destinatarios["para"],
            "estado": "esperando",
            "origen": "etiqueta",
            "label_id": label_id,
        }
        registro_mod.registrar_pedido(thread_id, datos, ruta=ruta_registro_pedidos)
        creados.append({"thread_id": thread_id, **datos})
    return {"creados": creados, "ya_registrados": ya_registrados}


def _armar_titular(insistencias: int, gestion_manual: int) -> str:
    if insistencias == 0 and gestion_manual == 0:
        return "Sin novedades"
    partes = []
    if insistencias:
        plural = "s" if insistencias != 1 else ""
        partes.append(f"{insistencias} insistencia{plural} creada{plural}")
    if gestion_manual:
        plural = "s" if gestion_manual != 1 else ""
        verbo = "requieren" if gestion_manual != 1 else "requiere"
        partes.append(f"{gestion_manual} pedido{plural} {verbo} gestión manual")
    return ", ".join(partes)


def correr(
    contexto_corrida: dict,
    *,
    ruta_registro_pedidos: Path = registro_mod.RUTA_REGISTRO_PEDIDOS,
    ruta_registro_causas: Path = registro_mod.RUTA_REGISTRO_CAUSAS,
    ruta_registro_seguimiento: Path = registro_mod.RUTA_REGISTRO_SEGUIMIENTO,
) -> dict:
    fecha_hoy = contexto_corrida["fecha_hoy"]

    # Idempotente (ver docstring) — se corre sin condición en vez de intentar
    # detectar "primera corrida".
    registro_mod.migrar_pedidos_bootstrap(
        ruta_pedidos=ruta_registro_pedidos,
        ruta_seguimiento=ruta_registro_seguimiento,
        ruta_causas=ruta_registro_causas,
    )

    acciones: list[dict] = []
    notas: list[dict] = []
    items: list[dict] = []

    verificacion = _verificar_borradores_pendientes(ruta_registro_causas, ruta_registro_pedidos)
    etiqueta = _pedidos_desde_etiqueta(ruta_registro_pedidos)
    for creado in etiqueta["creados"]:
        if not creado.get("rit"):
            notas.append({
                "tipo": "pedido_sin_rit",
                "detalle": f"Pedido dado de alta sin RIT detectado (hilo {creado['thread_id']}) — revisar a mano.",
            })
    pedidos_nuevos = len(verificacion["enviados"]) + len(etiqueta["creados"])

    abiertos = registro_mod.pedidos_abiertos(ruta=ruta_registro_pedidos, ruta_causas=ruta_registro_causas)
    if not abiertos:
        return {
            "fase": "seguimiento",
            "titular": "Sin pedidos abiertos para revisar" if pedidos_nuevos == 0 else "Sin novedades",
            "metricas": [
                {"etiqueta": "Pedidos nuevos dados de alta", "valor": pedidos_nuevos},
                {"etiqueta": "Pedidos abiertos revisados", "valor": 0},
                {"etiqueta": "Completados", "valor": 0},
                {"etiqueta": "Insistencias creadas", "valor": 0},
                {"etiqueta": "Recordatorios de faltantes creados", "valor": 0},
            ],
            "items": [],
            "acciones": acciones,
            "notas": notas,
        }

    mapa_hilos = mapas_mod.leer_mapa_hilos(contexto_corrida)

    completados = 0
    insistencias = 0
    recordatorios = 0
    gestion_manual = 0

    for pedido in abiertos:
        resultado = _procesar_pedido(
            pedido, fecha_hoy, mapa_hilos,
            ruta_registro_pedidos, ruta_registro_seguimiento, ruta_registro_causas,
            acciones, items,
        )
        if resultado == "completo":
            completados += 1
        elif resultado == "insistencia":
            insistencias += 1
        elif resultado == "recordatorio":
            recordatorios += 1
        elif resultado == "gestion_manual":
            gestion_manual += 1

    return {
        "fase": "seguimiento",
        "titular": _armar_titular(insistencias, gestion_manual),
        "metricas": [
            {"etiqueta": "Pedidos nuevos dados de alta", "valor": pedidos_nuevos},
            {"etiqueta": "Pedidos abiertos revisados", "valor": len(abiertos)},
            {"etiqueta": "Completados", "valor": completados},
            {"etiqueta": "Insistencias creadas", "valor": insistencias},
            {"etiqueta": "Recordatorios de faltantes creados", "valor": recordatorios},
        ],
        "items": items,
        "acciones": acciones,
        "notas": notas,
    }
