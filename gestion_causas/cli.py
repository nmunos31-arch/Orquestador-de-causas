#!/usr/bin/env python3
"""
CLI mecánica para la gestión de causas nuevas desde nmunoz@gomezyriesco.cl
(Fase 1). La IA que corre la tarea programada orquesta estos subcomandos con
Bash/PowerShell y toma las decisiones que requieren leer prosa libre (qué
dice el cuadro resumen, cómo redactar el Resumen); cada subcomando aquí hace
una sola cosa mecánica y determinística, e imprime JSON a stdout para que la
IA lo lea.

Ningún subcomando envía correos ni borra nada — ver gestion_causas/gmail_client.py.

USO (ver también SKILL.md de la tarea "gestion-causas-smu"):
    python -m gestion_causas.cli diagnostico
    python -m gestion_causas.cli buscar-hilos --query "..."
    python -m gestion_causas.cli leer-hilo --thread-id <id>
    python -m gestion_causas.cli guardar-adjunto --message-id <id> --attachment-id <id> --carpeta <ruta> --nombre-archivo <nombre>
    python -m gestion_causas.cli etiquetar-empresa --thread-id <id> --empresa "Rendic Hermanos"
    python -m gestion_causas.cli marcar-procesado --thread-id <id>
    python -m gestion_causas.cli crear-carpeta --apellido <ap> --empresa <emp> --rit <rit>
    python -m gestion_causas.cli registrar-causa --rit <rit> --datos-json <ruta.json>
    python -m gestion_causas.cli bitacora --mensaje "..." [--rit <rit>]
"""

import argparse
import html
import json
import re
import sys
import datetime
from datetime import date, timedelta
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from . import agenda as agenda_mod
from . import bitacora as bitacora_mod
from . import calendar_client
from . import carpetas as carpetas_mod
from . import gmail_client
from . import gmail_personal_client
from . import ics as ics_mod
from . import panel as panel_mod
from . import registro as registro_mod
from . import seguimiento as seguimiento_mod


# Contexto comun de una corrida del orquestador (ver cmd_contexto_corrida):
# fecha de hoy, estado de los 3 tokens y cache de calendario, resueltos una
# sola vez para que las 4 fases no los redescubran cada una por su cuenta.
RUTA_CONTEXTO_CORRIDA = Path(__file__).parent / "_contexto_corrida.json"
CUENTA_TRABAJO = "nmunoz@gomezyriesco.cl"
CUENTA_PERSONAL = "nmunos31@gmail.com"
DIAS_SEMANA = ["lunes", "martes", "miercoles", "jueves", "viernes", "sabado", "domingo"]


def _imprimir_json(datos) -> None:
    print(json.dumps(datos, ensure_ascii=False, default=str))


def cmd_diagnostico(args) -> int:
    resultado = gmail_client.diagnostico()
    _imprimir_json(resultado)
    if resultado["email"] != "nmunoz@gomezyriesco.cl":
        print(
            f"ADVERTENCIA: la cuenta autenticada es '{resultado['email']}', "
            "no 'nmunoz@gomezyriesco.cl'. Deten la tarea y revisa el token.",
            file=sys.stderr,
        )
        return 1
    return 0


def cmd_buscar_hilos(args) -> int:
    hilos = gmail_client.buscar_hilos(args.query, max_resultados=args.max_resultados)
    _imprimir_json({"hilos": hilos, "total": len(hilos)})
    return 0


def cmd_leer_hilo(args) -> int:
    hilo = gmail_client.obtener_hilo(args.thread_id)
    mensajes = []
    for mensaje_crudo in hilo.get("messages", []):
        headers = {h["name"].lower(): h["value"] for h in mensaje_crudo["payload"].get("headers", [])}
        mensajes.append({
            "id": mensaje_crudo["id"],
            "thread_id": mensaje_crudo["threadId"],
            "subject": headers.get("subject", ""),
            "sender": headers.get("from", ""),
            "to": headers.get("to", ""),
            "cc": headers.get("cc", ""),
            "date": headers.get("date", ""),
            "cuerpo_texto": gmail_client._extraer_texto_plano(mensaje_crudo["payload"]),
            "adjuntos": gmail_client._listar_adjuntos(mensaje_crudo["payload"]),
        })
    _imprimir_json({"thread_id": args.thread_id, "mensajes": mensajes})
    return 0


def cmd_guardar_adjunto(args) -> int:
    contenido = gmail_client.descargar_adjunto(args.message_id, args.attachment_id)
    if carpetas_mod.es_adjunto_firma(args.nombre_archivo, len(contenido)) and not args.forzar:
        _imprimir_json({"guardado": False, "motivo": "parece firma/logo, se omite"})
        return 0
    if args.dry_run:
        _imprimir_json({"simulado": True, "accion": "guardar-adjunto", "carpeta": args.carpeta, "nombre_archivo": args.nombre_archivo})
        return 0
    resultado = carpetas_mod.guardar_adjunto(Path(args.carpeta), args.nombre_archivo, contenido)
    _imprimir_json({"guardado": resultado["guardado"], "ruta": str(resultado["ruta"])})
    return 0


def cmd_etiquetar_empresa(args) -> int:
    color = gmail_client.COLOR_POR_EMPRESA.get(args.empresa)
    if color is None:
        print(f"Empresa sin color configurado: '{args.empresa}'", file=sys.stderr)
        return 1
    if args.dry_run:
        _imprimir_json({"simulado": True, "accion": "etiquetar-empresa", "thread_id": args.thread_id, "empresa": args.empresa})
        return 0
    label_id = gmail_client.obtener_o_crear_etiqueta(args.empresa, color=color)
    gmail_client.aplicar_etiqueta_a_hilo(args.thread_id, label_id)
    _imprimir_json({"thread_id": args.thread_id, "etiqueta": args.empresa, "label_id": label_id})
    return 0


def cmd_marcar_procesado(args) -> int:
    if args.dry_run:
        _imprimir_json({"simulado": True, "accion": "marcar-procesado", "thread_id": args.thread_id})
        return 0
    label_id = gmail_client.obtener_o_crear_etiqueta(gmail_client.ETIQUETA_PROCESADO)
    gmail_client.aplicar_etiqueta_a_hilo(args.thread_id, label_id)
    _imprimir_json({"thread_id": args.thread_id, "etiqueta": gmail_client.ETIQUETA_PROCESADO})
    return 0


def cmd_crear_carpeta(args) -> int:
    existente = carpetas_mod.buscar_carpeta_existente_por_rit(args.rit)
    if args.dry_run:
        destino = existente or carpetas_mod.ruta_carpeta_causa(args.apellido, args.empresa, args.rit)
        _imprimir_json({
            "simulado": True, "accion": "crear-carpeta", "carpeta": str(destino),
            "reusada": existente is not None,
        })
        return 0
    carpeta = carpetas_mod.crear_carpeta_causa(args.apellido, args.empresa, args.rit)
    _imprimir_json({"carpeta": str(carpeta), "reusada": existente is not None})
    return 0


def cmd_registrar_causa(args) -> int:
    with open(args.datos_json, "r", encoding="utf-8") as f:
        datos = json.load(f)
    if args.dry_run:
        _imprimir_json({"simulado": True, "accion": "registrar-causa", "rit": args.rit, "datos": datos})
        return 0
    entrada = registro_mod.registrar_causa(args.rit, datos)
    _imprimir_json(entrada)
    return 0


def cmd_causa_ya_registrada(args) -> int:
    existe = registro_mod.causa_ya_registrada(args.rit)
    _imprimir_json({"rit": args.rit, "ya_registrada": existe})
    return 0


def cmd_obtener_causa(args) -> int:
    entrada = registro_mod.obtener_causa(args.rit)
    _imprimir_json({"rit": args.rit, "causa": entrada})
    return 0


def cmd_bitacora(args) -> int:
    if args.dry_run:
        _imprimir_json({"simulado": True, "accion": "bitacora", "mensaje": args.mensaje})
        return 0
    bitacora_mod.registrar(args.mensaje, rit=args.rit)
    return 0


def _texto_a_lista_html(texto: str) -> str:
    """Convierte cada línea no vacía de `texto` en un ítem de una lista
    <ol><li> de HTML, quitando numeración manual al inicio ("1. ", "2) ")
    si la trae. Gmail muestra esto como una lista numerada nativa que se
    renumera sola al insertar o quitar ítems, a diferencia de números
    tipeados a mano en texto plano."""
    items = []
    for linea in texto.splitlines():
        linea = linea.strip()
        if not linea:
            continue
        linea = re.sub(r"^\d+[\.\)]\s*", "", linea)
        items.append(f"<li>{html.escape(linea)}</li>")
    return "<ol>" + "".join(items) + "</ol>"


def _texto_plano_a_html(texto: str) -> str:
    """Convierte cada salto de línea real de `texto` en un <br>, escapando
    HTML. Se usa para TODO borrador que no trae lista: Gmail reprocesa el
    texto plano que llega crudo por la API (drafts().create()) y reflowea
    líneas largas insertando saltos de línea nuevos donde no había ninguno,
    partiendo oraciones en dos párrafos sin que lo hayamos escrito así
    (confirmado en la práctica, agosto 2026 — no pasa si se escribe el
    correo a mano en Gmail, solo si llega por la API). Mandarlo como HTML
    con <br> explícitos evita que ese reflow del lado del servidor cambie la
    estructura del texto."""
    return "<br>".join(html.escape(linea) for linea in texto.splitlines())


def _cuerpo_con_lista(cuerpo_texto: str, items_texto: str) -> str:
    """Reemplaza el marcador "[[LISTA]]" (en su propia línea) dentro de
    `cuerpo_texto` por una lista HTML <ol><li> armada a partir de
    `items_texto` (una línea por ítem). A diferencia de _texto_a_lista_html
    (que convierte TODO el cuerpo en lista), esto sirve para el recordatorio
    de documentos pendientes (Fase 6), que tiene saludo antes y despedida
    después de la lista. El resto del cuerpo se escapa igual que la lista,
    para que Gmail lo reciba como HTML consistente."""
    partes = cuerpo_texto.split("[[LISTA]]")
    if len(partes) != 2:
        raise ValueError('El cuerpo debe contener exactamente un marcador "[[LISTA]]"')
    antes, despues = partes
    lista_html = _texto_a_lista_html(items_texto)
    antes_html = "<br>".join(html.escape(l) for l in antes.splitlines())
    despues_html = "<br>".join(html.escape(l) for l in despues.splitlines())
    return antes_html + lista_html + despues_html


def cmd_crear_borrador(args) -> int:
    if args.dry_run:
        _imprimir_json({
            "simulado": True, "accion": "crear-borrador",
            "destinatario": args.destinatario, "asunto": args.asunto, "thread_id": args.thread_id,
            "cc": args.cc,
        })
        return 0
    if args.thread_id:
        existentes = gmail_client.listar_borradores_de_hilo(args.thread_id)
        if existentes:
            _imprimir_json({"creado": False, "motivo": "ya existe un borrador en esta cadena, no se sobrescribe"})
            return 0
    else:
        # Sin thread_id (ej. el borrador de ofrecimiento de la Fase 4, que es
        # un correo nuevo): se busca duplicado por el asunto completo, que
        # siempre trae el RIT.
        existentes = gmail_client.buscar_borrador_por_asunto(args.asunto)
        if existentes:
            _imprimir_json({"creado": False, "motivo": "ya existe un borrador con este asunto, no se sobrescribe"})
            return 0
    with open(args.cuerpo_archivo, "r", encoding="utf-8") as f:
        cuerpo = f.read()
    if args.lista_archivo:
        with open(args.lista_archivo, "r", encoding="utf-8") as f:
            items_texto = f.read()
        cuerpo = _cuerpo_con_lista(cuerpo, items_texto)
    elif args.lista:
        cuerpo = _texto_a_lista_html(cuerpo)
    else:
        cuerpo = _texto_plano_a_html(cuerpo)
    borrador = gmail_client.crear_borrador(
        args.destinatario, args.asunto, cuerpo, thread_id=args.thread_id, html=True, cc=args.cc
    )
    _imprimir_json({"creado": True, "draft_id": borrador.get("id")})
    return 0


def cmd_verificar_borradores_pendientes(args) -> int:
    """Para cada causa con un borrador de documentos registrado (campo
    borrador_documentos_draft_id), consulta si ese borrador sigue existiendo
    en Gmail. Los que siguen ahí son borradores que Nico todavía no revisó ni
    envió — se devuelven en 'pendientes'. Los que ya no existen (Nico los
    envió o los borró a mano) se limpian del registro para no volver a
    chequearlos ('limpiados')."""
    causas = registro_mod.causas_con_borrador_pendiente()
    pendientes = []
    limpiados = []
    for causa in causas:
        draft_id = causa["borrador_documentos_draft_id"]
        if gmail_client.borrador_existe(draft_id):
            pendientes.append({
                "rit": causa.get("rit"),
                "empresa": causa.get("empresa"),
                "demandante": causa.get("demandante"),
                "draft_id": draft_id,
                "thread_id": causa.get("thread_id"),
            })
        else:
            limpiados.append(causa.get("rit"))
            if not args.dry_run:
                registro_mod.registrar_causa(causa["rit"], {"borrador_documentos_draft_id": None})
    _imprimir_json({"pendientes": pendientes, "limpiados": limpiados})
    return 0


def _mensajes_de_hilo(thread_id: str) -> list:
    """Trae y aplana los mensajes de un hilo al mismo formato que usa
    cmd_leer_hilo (con to/cc), para pasarlos a seguimiento.analizar_hilo."""
    hilo = gmail_client.obtener_hilo(thread_id)
    mensajes = []
    for mensaje_crudo in hilo.get("messages", []):
        headers = {h["name"].lower(): h["value"] for h in mensaje_crudo["payload"].get("headers", [])}
        mensajes.append({
            "id": mensaje_crudo["id"],
            "thread_id": mensaje_crudo["threadId"],
            "subject": headers.get("subject", ""),
            "sender": headers.get("from", ""),
            "to": headers.get("to", ""),
            "cc": headers.get("cc", ""),
            "date": headers.get("date", ""),
            "cuerpo_texto": gmail_client._extraer_texto_plano(mensaje_crudo["payload"]),
        })
    return mensajes


def cmd_hilos_sin_respuesta(args) -> int:
    """Fase 5/6: busca hilos con `--query` cuyo último mensaje propio
    (nmunoz@gomezyriesco.cl) sigue sin respuesta hace al menos `--horas`
    horas. Si se entrega `--responder-esperado`, exige que esa dirección
    puntual no haya contestado (no basta con que responda un tercero del
    hilo). Si se entrega `--iniciado-por`, descarta los hilos cuyo primer
    mensaje no venga de esa dirección."""
    perfil = gmail_client.diagnostico()
    direccion_propia = perfil["email"]

    hilos = gmail_client.buscar_hilos(args.query, max_resultados=args.max_hilos)
    ahora = datetime.datetime.now(datetime.timezone.utc)
    resultado = []
    for hilo in hilos:
        mensajes = _mensajes_de_hilo(hilo["id"])
        if not mensajes:
            continue
        if args.iniciado_por:
            if seguimiento_mod.extraer_direccion(mensajes[0]["sender"]) != args.iniciado_por.strip().lower():
                continue
        analisis = seguimiento_mod.analizar_hilo(
            mensajes, ahora, direccion_propia, responder_esperado=args.responder_esperado
        )
        if analisis["hay_respuesta_posterior"] is not False:
            continue  # sin mensaje propio, o ya hay respuesta: no aplica
        if analisis["horas_sin_respuesta"] < args.horas:
            continue

        ultimo_propio = analisis["ultimo_mensaje_propio"]
        asunto = ultimo_propio["subject"]
        asunto_normalizado = seguimiento_mod.normalizar_asunto(asunto)
        texto_para_detectar = asunto + " " + ultimo_propio["cuerpo_texto"]
        destinatarios = seguimiento_mod.destinatarios_de_ultimo_propio(ultimo_propio, direccion_propia)
        fecha_ultimo_propio = seguimiento_mod.parsear_fecha(ultimo_propio["date"]).date()
        dias_habiles_sin_respuesta = agenda_mod.dias_habiles_entre(fecha_ultimo_propio, ahora.date())

        resultado.append({
            "thread_id": hilo["id"],
            "asunto": asunto,
            "asunto_normalizado": asunto_normalizado,
            "rit": registro_mod.extraer_rit(texto_para_detectar),
            "empresa": calendar_client.detectar_empresa(texto_para_detectar),
            "iniciado_por": analisis["iniciado_por"],
            "horas_sin_respuesta": round(analisis["horas_sin_respuesta"], 1),
            "dias_habiles_sin_respuesta": dias_habiles_sin_respuesta,
            "ultimo_mensaje_propio": {
                "id": ultimo_propio["id"],
                "fecha": ultimo_propio["date"],
                "extracto": ultimo_propio["cuerpo_texto"][:400],
            },
            "destinatarios": destinatarios,
            "participantes": analisis["participantes"],
        })
    if args.dias_habiles is not None:
        resultado = [r for r in resultado if r["dias_habiles_sin_respuesta"] >= args.dias_habiles]
    _imprimir_json({"hilos": resultado, "total": len(resultado)})
    return 0


def cmd_puede_insistir(args) -> int:
    resultado = registro_mod.puede_insistir(args.thread_id, hoy=args.hoy)
    _imprimir_json({"thread_id": args.thread_id, **resultado})
    return 0


def cmd_registrar_aviso(args) -> int:
    if args.dry_run:
        _imprimir_json({"simulado": True, "accion": "registrar-aviso", "thread_id": args.thread_id, "tipo": args.tipo})
        return 0
    hoy = args.fecha or str(date.today())
    entrada = registro_mod.registrar_aviso(
        args.thread_id, args.tipo, hoy, rit=args.rit, draft_id=args.draft_id
    )
    _imprimir_json(entrada)
    return 0


def cmd_dias_habiles_entre(args) -> int:
    dias = agenda_mod.dias_habiles_entre(args.desde, args.hasta)
    _imprimir_json({"desde": args.desde, "hasta": args.hasta, "dias_habiles": dias})
    return 0


def cmd_buscar_eerr_reusable(args) -> int:
    reusable = registro_mod.buscar_eerr_reusable(
        args.ceco, args.fecha_despido, dias_tolerancia=args.dias_tolerancia
    )
    _imprimir_json({"reusable": reusable})
    return 0


def cmd_parece_eerr(args) -> int:
    _imprimir_json({"nombre_archivo": args.nombre_archivo, "parece_eerr": carpetas_mod.parece_eerr(args.nombre_archivo)})
    return 0


def cmd_registrar_eerr(args) -> int:
    if args.dry_run:
        _imprimir_json({"simulado": True, "accion": "registrar-eerr", "ceco": args.ceco, "rit": args.rit})
        return 0
    registro_mod.registrar_eerr_recibido(args.ceco, args.fecha_despido, args.rit)
    _imprimir_json({"registrado": True, "ceco": args.ceco, "rit": args.rit})
    return 0


def cmd_copiar_archivo(args) -> int:
    if args.dry_run:
        _imprimir_json({"simulado": True, "accion": "copiar-archivo", "carpeta_destino": args.carpeta_destino, "nombre_archivo": args.nombre_archivo})
        return 0
    resultado = carpetas_mod.copiar_archivo_local(Path(args.origen), Path(args.carpeta_destino), args.nombre_archivo)
    _imprimir_json({"copiado": resultado["copiado"], "ruta": str(resultado["ruta"])})
    return 0


def cmd_listar_carpeta(args) -> int:
    archivos = carpetas_mod.listar_archivos_carpeta(Path(args.carpeta))
    _imprimir_json({"carpeta": args.carpeta, "archivos": archivos})
    return 0


def cmd_causas_activas(args) -> int:
    causas = registro_mod.causas_para_goteo(dias_ventana_post_audiencia=args.dias_ventana)
    _imprimir_json({"causas": causas, "total": len(causas)})
    return 0


def cmd_dias_habiles_antes(args) -> int:
    fecha = agenda_mod.dias_habiles_antes(args.fecha, args.n)
    _imprimir_json({"fecha": str(fecha)})
    return 0


def cmd_dias_corridos_antes(args) -> int:
    fecha = agenda_mod.dias_corridos_antes(args.fecha, args.n)
    _imprimir_json({"fecha": str(fecha)})
    return 0


def cmd_diagnostico_calendario(args) -> int:
    resultado = calendar_client.diagnostico()
    _imprimir_json(resultado)
    if resultado["email"] != "nmunoz@gomezyriesco.cl":
        print(
            f"ADVERTENCIA: la cuenta autenticada es '{resultado['email']}', "
            "no 'nmunoz@gomezyriesco.cl'. Deten la tarea y revisa el token.",
            file=sys.stderr,
        )
        return 1
    return 0


def cmd_eventos_calendario(args) -> int:
    hoy = date.today()
    desde = hoy - timedelta(days=args.dias_atras)
    hasta = hoy + timedelta(days=args.dias_adelante)
    if args.desde_cache:
        eventos = calendar_client.eventos_empresas_interes_desde_cache(desde, hasta, args.desde_cache)
    else:
        eventos = calendar_client.eventos_empresas_interes(desde, hasta)
    _imprimir_json({"eventos": eventos, "total": len(eventos)})
    return 0


def cmd_cache_eventos_calendario(args) -> int:
    if args.dry_run:
        _imprimir_json({"simulado": True, "accion": "cache-eventos-calendario", "ruta": args.ruta})
        return 0
    resultado = calendar_client.guardar_cache_eventos(ruta=args.ruta, dias_adelante=args.dias_adelante)
    _imprimir_json(resultado)
    return 0


def cmd_buscar_audiencia_por_rit(args) -> int:
    if args.ics:
        eventos = ics_mod.buscar_audiencia_por_rit(args.ics, args.rit)
    elif args.desde_cache:
        eventos = calendar_client.buscar_audiencia_por_rit_desde_cache(args.rit, args.desde_cache)
    else:
        eventos = calendar_client.buscar_audiencia_por_rit(args.rit, dias_adelante=args.dias_adelante)
    _imprimir_json({"rit": args.rit, "eventos": eventos, "total": len(eventos)})
    return 0


def cmd_panel_html(args) -> int:
    if args.dry_run:
        _imprimir_json({"simulado": True, "accion": "panel-html", "salida": args.salida})
        return 0
    with open(args.resumen_json, "r", encoding="utf-8") as f:
        resumen = json.load(f)
    hoy = date.fromisoformat(args.hoy) if args.hoy else None
    ruta_registro = Path(args.ruta_registro) if args.ruta_registro else None
    contenido = panel_mod.generar_panel_html(resumen, hoy=hoy, ruta_registro=ruta_registro)
    Path(args.salida).write_text(contenido, encoding="utf-8")
    _imprimir_json({"escrito": True, "ruta": args.salida})
    return 0


def cmd_enviar_panel(args) -> int:
    contenido = Path(args.html_file).read_text(encoding="utf-8")
    if args.dry_run:
        _imprimir_json({"simulado": True, "accion": "enviar-panel", "asunto": args.asunto})
        return 0
    resultado = gmail_personal_client.enviar_panel_estado(args.asunto, contenido)
    _imprimir_json(resultado)
    return 0


def cmd_diagnostico_personal(args) -> int:
    resultado = gmail_personal_client.diagnostico()
    _imprimir_json(resultado)
    if resultado["email"] != "nmunos31@gmail.com":
        print(
            f"ADVERTENCIA: la cuenta autenticada es '{resultado['email']}', "
            "no 'nmunos31@gmail.com'. Deten la tarea y revisa el token.",
            file=sys.stderr,
        )
        return 1
    return 0


def _diagnosticar_token(diagnostico, email_esperado: str) -> dict:
    """Corre un `diagnostico()` de cliente sin permitir login interactivo y lo
    normaliza a {"ok", "email", "error"}. Nunca levanta: un token caido es un
    dato del contexto, no un crash de la corrida."""
    try:
        resultado = diagnostico(permitir_login=False)
    except Exception as e:  # red, token vencido, scope faltante, etc.
        return {"ok": False, "email": None, "error": f"{type(e).__name__}: {e}"}
    email = resultado.get("email")
    if email != email_esperado:
        return {
            "ok": False, "email": email,
            "error": f"el token esta atado a '{email}', no a '{email_esperado}'",
        }
    return {"ok": True, "email": email, "error": None}


def cmd_contexto_corrida(args) -> int:
    """Paso 0 del orquestador: resuelve de una vez lo que las 4 fases
    comparten, para que ninguna lo redescubra por su cuenta.

    - fecha de hoy / dia de la semana (evita que dos fases de una corrida que
      cruza la medianoche usen fechas distintas);
    - estado de los 3 tokens, SIN abrir el login interactivo (que en una tarea
      desatendida no vuelve nunca — ver obtener_credenciales(permitir_login));
    - el cache de eventos de calendario, una sola llamada a la API para toda la
      corrida, que despues consumen `goteo`, `agenda` y `calendario` con
      --desde-cache.

    Codigo de salida 1 si Gmail de trabajo o Calendar no estan disponibles (el
    orquestador aborta y manda el panel avisando). Un fallo del token personal
    no es motivo de salida 1: solo afecta el envio del panel al final.
    """
    hoy = date.today()
    contexto = {
        "generado_en": datetime.datetime.now().isoformat(),
        "fecha_hoy": str(hoy),
        "dia_semana": DIAS_SEMANA[hoy.weekday()],
        "es_lunes": hoy.weekday() == 0,
        "tokens": {},
        "cache_calendario": None,
    }

    if args.dry_run:
        _imprimir_json({"simulado": True, "accion": "contexto-corrida", "salida": args.salida})
        return 0

    contexto["tokens"]["gmail_trabajo"] = _diagnosticar_token(
        gmail_client.diagnostico, CUENTA_TRABAJO)
    contexto["tokens"]["calendar"] = _diagnosticar_token(
        calendar_client.diagnostico, CUENTA_TRABAJO)
    contexto["tokens"]["personal"] = _diagnosticar_token(
        gmail_personal_client.diagnostico, CUENTA_PERSONAL)

    if contexto["tokens"]["calendar"]["ok"]:
        try:
            contexto["cache_calendario"] = calendar_client.guardar_cache_eventos(
                ruta=args.ruta_cache, dias_adelante=args.dias_adelante)
        except Exception as e:
            contexto["tokens"]["calendar"] = {
                "ok": False,
                "email": contexto["tokens"]["calendar"]["email"],
                "error": f"el token sirve pero fallo al traer los eventos: {type(e).__name__}: {e}",
            }

    contexto["listo"] = (
        contexto["tokens"]["gmail_trabajo"]["ok"] and contexto["tokens"]["calendar"]["ok"]
    )

    Path(args.salida).write_text(
        json.dumps(contexto, ensure_ascii=False, indent=2), encoding="utf-8")
    _imprimir_json(contexto)
    return 0 if contexto["listo"] else 1


def construir_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--dry-run", action="store_true",
        help="No escribe nada (ni Gmail ni disco); solo informa qué haría",
    )
    sub = parser.add_subparsers(dest="comando", required=True)

    p = sub.add_parser("diagnostico", help="Verifica qué cuenta y scopes tiene el token guardado")
    p.set_defaults(func=cmd_diagnostico)

    p = sub.add_parser("buscar-hilos", help="Busca hilos con sintaxis de búsqueda de Gmail")
    p.add_argument("--query", required=True)
    p.add_argument("--max-resultados", type=int, default=50)
    p.set_defaults(func=cmd_buscar_hilos)

    p = sub.add_parser("leer-hilo", help="Trae todos los mensajes de un hilo, con cuerpo y adjuntos")
    p.add_argument("--thread-id", required=True)
    p.set_defaults(func=cmd_leer_hilo)

    p = sub.add_parser("guardar-adjunto", help="Descarga un adjunto y lo guarda en una carpeta (sin pisar)")
    p.add_argument("--message-id", required=True)
    p.add_argument("--attachment-id", required=True)
    p.add_argument("--carpeta", required=True)
    p.add_argument("--nombre-archivo", required=True)
    p.add_argument("--forzar", action="store_true", help="Guardar aunque parezca firma/logo")
    p.set_defaults(func=cmd_guardar_adjunto)

    p = sub.add_parser("etiquetar-empresa", help="Aplica la etiqueta de color de la empresa al hilo")
    p.add_argument("--thread-id", required=True)
    p.add_argument("--empresa", required=True, choices=sorted(gmail_client.COLOR_POR_EMPRESA))
    p.set_defaults(func=cmd_etiquetar_empresa)

    p = sub.add_parser("marcar-procesado", help=f"Aplica la etiqueta '{gmail_client.ETIQUETA_PROCESADO}' al hilo")
    p.add_argument("--thread-id", required=True)
    p.set_defaults(func=cmd_marcar_procesado)

    p = sub.add_parser("crear-carpeta", help="Crea (si no existe) la carpeta de la causa en Minutas")
    p.add_argument("--apellido", required=True)
    p.add_argument("--empresa", required=True)
    p.add_argument("--rit", required=True)
    p.set_defaults(func=cmd_crear_carpeta)

    p = sub.add_parser("registrar-causa", help="Da de alta o actualiza la causa en el registro local")
    p.add_argument("--rit", required=True)
    p.add_argument("--datos-json", required=True, help="Ruta a un JSON con los campos a guardar/actualizar")
    p.set_defaults(func=cmd_registrar_causa)

    p = sub.add_parser("causa-ya-registrada", help="Consulta si un RIT ya está en el registro")
    p.add_argument("--rit", required=True)
    p.set_defaults(func=cmd_causa_ya_registrada)

    p = sub.add_parser("obtener-causa", help="Trae los datos guardados de una causa (carpeta, ceco, thread_id, etc.)")
    p.add_argument("--rit", required=True)
    p.set_defaults(func=cmd_obtener_causa)

    p = sub.add_parser("bitacora", help="Agrega una línea a la bitácora")
    p.add_argument("--mensaje", required=True)
    p.add_argument("--rit", default=None)
    p.set_defaults(func=cmd_bitacora)

    p = sub.add_parser("crear-borrador", help="Crea un borrador (NUNCA lo envía). No sobrescribe uno ya existente en la cadena.")
    p.add_argument("--destinatario", required=True)
    p.add_argument("--asunto", required=True)
    p.add_argument("--cuerpo-archivo", required=True, help="Ruta a un .txt con el cuerpo del borrador")
    p.add_argument("--thread-id", default=None, help="Si se indica, el borrador queda como respuesta en esa cadena")
    p.add_argument(
        "--lista", action="store_true",
        help="Cada línea no vacía del cuerpo se envía como un ítem de una lista numerada HTML "
             "(<ol>), para que Gmail la renumere sola al insertar o quitar documentos",
    )
    p.add_argument("--cc", default=None, help="Direcciones en copia, separadas por coma")
    p.add_argument(
        "--lista-archivo", default=None,
        help="Ruta a un .txt (una línea por ítem); reemplaza el marcador [[LISTA]] del "
             "cuerpo por una lista numerada HTML, a diferencia de --lista que convierte "
             "todo el cuerpo (usar cuando el cuerpo tiene saludo/despedida además de la lista)",
    )
    p.set_defaults(func=cmd_crear_borrador)

    p = sub.add_parser(
        "hilos-sin-respuesta",
        help="Fase 5/6: busca hilos cuyo último mensaje propio sigue sin respuesta hace N horas",
    )
    p.add_argument("--query", required=True, help="Sintaxis de búsqueda de Gmail")
    p.add_argument("--horas", type=float, required=True)
    p.add_argument("--dias-habiles", type=int, default=None, help="Si se indica, filtra además por días hábiles mínimos sin respuesta")
    p.add_argument("--iniciado-por", default=None, help="Descarta hilos cuyo primer mensaje no venga de esta dirección")
    p.add_argument("--responder-esperado", default=None, help="Exige que esta dirección puntual no haya respondido (no basta con que responda un tercero)")
    p.add_argument("--max-hilos", type=int, default=50)
    p.set_defaults(func=cmd_hilos_sin_respuesta)

    p = sub.add_parser("puede-insistir", help="Fase 5/6: aplica la cadencia de insistencia (1er aviso siempre, 2do a los 2 dias habiles, despues nunca)")
    p.add_argument("--thread-id", required=True)
    p.add_argument("--hoy", default=None, help="AAAA-MM-DD, para tests; por defecto hoy")
    p.set_defaults(func=cmd_puede_insistir)

    p = sub.add_parser("registrar-aviso", help="Fase 5/6: anota que se creó un borrador de insistencia/recordatorio para este hilo")
    p.add_argument("--thread-id", required=True)
    p.add_argument("--tipo", required=True, choices=["acuerdo-daniela", "causa-laboral", "documentos"])
    p.add_argument("--rit", default=None)
    p.add_argument("--draft-id", default=None)
    p.add_argument("--fecha", default=None, help="AAAA-MM-DD, para tests; por defecto hoy")
    p.set_defaults(func=cmd_registrar_aviso)

    p = sub.add_parser("dias-habiles-entre", help="Fase 6: cuenta los dias habiles transcurridos entre dos fechas")
    p.add_argument("--desde", required=True, help="AAAA-MM-DD")
    p.add_argument("--hasta", required=True, help="AAAA-MM-DD")
    p.set_defaults(func=cmd_dias_habiles_entre)

    p = sub.add_parser(
        "verificar-borradores-pendientes",
        help="Revisa los borradores de documentos creados en corridas anteriores (guardados en "
             "el registro de causas) y avisa cuales siguen sin enviar",
    )
    p.set_defaults(func=cmd_verificar_borradores_pendientes)

    p = sub.add_parser("buscar-eerr-reusable", help="Fase 2: busca si ya hay un EERR recibido reusable para este CECO/fecha")
    p.add_argument("--ceco", required=True)
    p.add_argument("--fecha-despido", required=True, help="AAAA-MM-DD")
    p.add_argument("--dias-tolerancia", type=int, default=90)
    p.set_defaults(func=cmd_buscar_eerr_reusable)

    p = sub.add_parser("parece-eerr", help="Fase 3: heurística de nombre para saber si un archivo parece el Estado de Resultados")
    p.add_argument("--nombre-archivo", required=True)
    p.set_defaults(func=cmd_parece_eerr)

    p = sub.add_parser("registrar-eerr", help="Fase 3: anota que se recibió el EERR de un CECO para esta causa")
    p.add_argument("--ceco", required=True)
    p.add_argument("--fecha-despido", required=True, help="AAAA-MM-DD")
    p.add_argument("--rit", required=True)
    p.set_defaults(func=cmd_registrar_eerr)

    p = sub.add_parser("copiar-archivo", help="Fase 2: copia un archivo local (ej. EERR reusado) a la carpeta de otra causa, sin pisar")
    p.add_argument("--origen", required=True)
    p.add_argument("--carpeta-destino", required=True)
    p.add_argument("--nombre-archivo", required=True)
    p.set_defaults(func=cmd_copiar_archivo)

    p = sub.add_parser("listar-carpeta", help="Fase 3: lista los archivos que ya tiene guardados la carpeta de una causa")
    p.add_argument("--carpeta", required=True)
    p.set_defaults(func=cmd_listar_carpeta)

    p = sub.add_parser("causas-activas", help="Fase 3: causas a revisar por goteo de documentos (audiencia no muy pasada o sin fecha)")
    p.add_argument("--dias-ventana", type=int, default=60)
    p.set_defaults(func=cmd_causas_activas)

    p = sub.add_parser("dias-habiles-antes", help="Fase 4: fecha N días hábiles antes de una fecha (salta fin de semana y feriados)")
    p.add_argument("--fecha", required=True, help="AAAA-MM-DD")
    p.add_argument("--n", type=int, required=True)
    p.set_defaults(func=cmd_dias_habiles_antes)

    p = sub.add_parser("dias-corridos-antes", help="Fase 4: fecha N días corridos antes de una fecha")
    p.add_argument("--fecha", required=True, help="AAAA-MM-DD")
    p.add_argument("--n", type=int, required=True)
    p.set_defaults(func=cmd_dias_corridos_antes)

    p = sub.add_parser("diagnostico-calendario", help="Verifica qué cuenta tiene el token de Calendar guardado")
    p.set_defaults(func=cmd_diagnostico_calendario)

    p = sub.add_parser(
        "eventos-calendario",
        help="Fase 0: eventos del calendario que mencionan alguna de las 6 empresas de interés, con RIT detectado si aparece en el título",
    )
    p.add_argument("--dias-atras", type=int, default=0)
    p.add_argument("--dias-adelante", type=int, default=60)
    p.add_argument(
        "--desde-cache", default=None,
        help="Ruta a un cache generado por cache-eventos-calendario; filtra ese archivo en vez de llamar a la API (falla si el cache no cubre el rango pedido)",
    )
    p.set_defaults(func=cmd_eventos_calendario)

    p = sub.add_parser(
        "cache-eventos-calendario",
        help="Trae TODOS los eventos del calendario (rango de 200 dias) UNA vez y los guarda en un archivo, para que buscar-audiencia-por-rit --desde-cache no repita la llamada a la API por cada causa",
    )
    p.add_argument("--ruta", default=str(calendar_client.RUTA_CACHE_EVENTOS_CALENDARIO))
    p.add_argument("--dias-adelante", type=int, default=200)
    p.set_defaults(func=cmd_cache_eventos_calendario)

    p = sub.add_parser(
        "buscar-audiencia-por-rit",
        help="Fase 4: busca eventos que mencionan este RIT en el calendario de nmunoz@gomezyriesco.cl (API directa; --desde-cache usa un archivo generado por cache-eventos-calendario; --ics fuerza el modo antiguo por archivo exportado)",
    )
    p.add_argument("--rit", required=True)
    p.add_argument("--dias-adelante", type=int, default=200, help="Ventana de búsqueda hacia adelante desde hoy (API)")
    p.add_argument("--ics", default=None, help="Ruta a un .ics exportado a mano; si se indica, se usa en vez de la API")
    p.add_argument("--desde-cache", default=None, help="Ruta a un cache generado por cache-eventos-calendario; si se indica, filtra ese archivo en vez de llamar a la API")
    p.set_defaults(func=cmd_buscar_audiencia_por_rit)

    p = sub.add_parser(
        "panel-html",
        help="Arma el HTML del panel de estado del ciclo de causas y lo escribe a un archivo",
    )
    p.add_argument("--resumen-json", required=True, help='Ruta a un JSON: [{"fase":.., "resultado":.., "error":..}, ...]')
    p.add_argument("--salida", required=True, help="Ruta donde escribir el HTML generado")
    p.add_argument("--hoy", default=None, help="Fecha AAAA-MM-DD a usar como 'hoy' (pruebas); por defecto hoy")
    p.add_argument("--ruta-registro", default=None, help="Ruta alternativa al registro de causas (pruebas); por defecto el registro real")
    p.set_defaults(func=cmd_panel_html)

    p = sub.add_parser(
        "enviar-panel",
        help="Envia el panel de estado a nmunoz@gomezyriesco.cl desde la cuenta personal (nmunos31@gmail.com), la unica autorizada a enviar",
    )
    p.add_argument("--html-file", required=True)
    p.add_argument("--asunto", required=True)
    p.set_defaults(func=cmd_enviar_panel)

    p = sub.add_parser("diagnostico-personal", help="Verifica que el token de la cuenta personal (nmunos31@gmail.com) este autorizado")
    p.set_defaults(func=cmd_diagnostico_personal)

    p = sub.add_parser(
        "contexto-corrida",
        help="Paso 0 del orquestador: resuelve fecha de hoy, estado de los 3 tokens (sin login interactivo) y el cache de calendario, una sola vez para toda la corrida",
    )
    p.add_argument("--salida", default=str(RUTA_CONTEXTO_CORRIDA))
    p.add_argument("--ruta-cache", default=str(calendar_client.RUTA_CACHE_EVENTOS_CALENDARIO))
    p.add_argument("--dias-adelante", type=int, default=200, help="Ventana del cache de calendario")
    p.set_defaults(func=cmd_contexto_corrida)

    return parser


def main(argv=None) -> int:
    parser = construir_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except Exception as e:
        print(f"Error ({type(e).__name__}): {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
