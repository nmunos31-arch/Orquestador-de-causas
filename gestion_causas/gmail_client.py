#!/usr/bin/env python3
"""
Cliente Gmail propio (OAuth de escritorio) para la casilla del trabajo
nmunoz@gomezyriesco.cl.

Existe porque el conector de Gmail de Claude apunta solo a la cuenta personal
(nmunos31@gmail.com) y no tiene herramienta para descargar adjuntos, que es
imprescindible para archivar la demanda y los documentos de cada causa.

GARANTÍA DE SEGURIDAD (verificada por tests/test_gmail_client.py):
Este módulo NO expone ninguna función que envíe correos (messages.send,
drafts.send) ni que borre o mande a la papelera mensajes o hilos (messages/
threads .trash, .delete). Esa garantía es de CÓDIGO, no de scope: la API de
Gmail exige el scope gmail.modify para poder aplicar etiquetas a un hilo (no
existe un scope más angosto que permita "solo etiquetar" — gmail.labels
únicamente administra las etiquetas en sí, no su aplicación a mensajes), y
gmail.modify técnicamente también habilita mover correos a la papelera. Se
pidió igual porque es el único camino de la API para el etiquetado
automático que pidió el usuario — la garantía de que NUNCA se llama a
trash/delete/send queda en el código (ver funciones de este módulo) y se
verifica con un test que falla si alguna vez se agrega una llamada así. Ver
también el plan del proyecto: la automatización nunca debe enviar ni borrar
correos.

Política del usuario (2026-08-27): esta cuenta (nmunoz@gomezyriesco.cl) NUNCA
envía correo bajo ninguna circunstancia, ni siquiera auto-reportes — solo deja
borradores. El envío del panel de estado del ciclo de causas lo hace un
módulo aparte, gmail_personal_client.py, autenticado como nmunos31@gmail.com
(la única cuenta que el usuario autoriza a enviar).

Reutiliza el mismo client_secret.json (proyecto informe-semanal-501614) que
ya usa 'Automatizacion Informe Semanal/generar_informe_semanal.py' para
Sheets, pero con un token.json SEPARADO autorizado con la cuenta del trabajo
(token_gmail_trabajo.json), porque son cuentas distintas.
"""

import base64
import sys
from pathlib import Path

CLIENT_SECRET_PATH = str(
    Path(__file__).parent.parent.parent / "Automatizacion Informe Semanal" / "client_secret.json"
)
TOKEN_PATH = str(Path(__file__).parent / "token_gmail_trabajo.json")

# gmail.modify es necesario para threads().modify() / messages().modify()
# (aplicar la etiqueta de color y la de "procesado" a un hilo) — ver
# GARANTÍA DE SEGURIDAD arriba sobre por qué se pidió pese a ser más amplio
# de lo ideal. Se mantiene además gmail.labels (administración de las
# etiquetas en sí) y gmail.readonly/gmail.compose. Deliberadamente NO se
# pide gmail.send ni https://mail.google.com/ (acceso total) — esta cuenta
# nunca envía correo, ver GARANTÍA DE SEGURIDAD arriba.
SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.labels",
    "https://www.googleapis.com/auth/gmail.compose",
    "https://www.googleapis.com/auth/gmail.modify",
]

# Paleta cerrada de colores que acepta la API de Gmail para etiquetas
# (Gmail rechaza cualquier hex fuera de esta lista). Colores acordados con
# el usuario para cada empresa. Solo se usan si la etiqueta no existe
# todavía (obtener_o_crear_etiqueta reusa la existente e ignora el color si
# ya existe) — "Preunic" y "Salcobrand" ya existían en la casilla antes de
# esta automatización, así que estos colores son solo por si algún día hay
# que recrearlas; en la práctica siempre se reusan las que Nico ya tenía.
COLOR_POR_EMPRESA = {
    "Rendic Hermanos": {"backgroundColor": "#fb4c2f", "textColor": "#ffffff"},  # rojo
    "Alvi": {"backgroundColor": "#4a86e8", "textColor": "#ffffff"},  # azul
    "Super 10": {"backgroundColor": "#fad165", "textColor": "#000000"},  # amarillo
    "Servicios Logísticos Santiago": {"backgroundColor": "#16a766", "textColor": "#ffffff"},  # verde
    "Preunic": {"backgroundColor": "#ffad46", "textColor": "#633e04"},  # naranja (ya existía)
    "Salcobrand": {"backgroundColor": "#1e53b8", "textColor": "#ffffff"},  # azul oscuro (ya existía)
}

# Empresas cuyas causas NO se registran en el Informe de Juicios Vigentes
# (ese Excel es solo para las causas de SMU: Rendic/Alvi/Super 10/SSLL).
# Preunic y Salcobrand pasan por las 4 fases igual, pero sin escribir fila.
EMPRESAS_SIN_EXCEL = {"Preunic", "Salcobrand"}

ETIQUETA_PROCESADO = "Procesado-GestionCausas"


def log(msg):
    print(f"[gmail_client] {msg}", file=sys.stderr)


def obtener_credenciales():
    """Autentica contra la cuenta del trabajo, reutilizando el token si es
    válido. Mismo patrón que obtener_credenciales_drive() en
    generar_informe_semanal.py (incluye el manejo de refresh token inválido
    por app en modo Testing)."""
    from google.auth.exceptions import RefreshError
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow

    creds = None
    if Path(TOKEN_PATH).exists():
        creds = Credentials.from_authorized_user_file(TOKEN_PATH, SCOPES)

    if not creds or not creds.valid:
        necesita_login = True
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
                necesita_login = False
            except RefreshError as e:
                log(f"El token guardado ya no sirve ({e}); pidiendo login de nuevo...")

        if necesita_login:
            if not Path(CLIENT_SECRET_PATH).exists():
                sys.exit(
                    f"Falta '{CLIENT_SECRET_PATH}'. Descárgalo desde Google Cloud "
                    f"Console (credenciales OAuth de tipo Aplicación de escritorio)."
                )
            flow = InstalledAppFlow.from_client_secrets_file(CLIENT_SECRET_PATH, SCOPES)
            log("Abriendo navegador para iniciar sesión — usa la cuenta nmunoz@gomezyriesco.cl.")
            creds = flow.run_local_server(port=0)

        with open(TOKEN_PATH, "w") as f:
            f.write(creds.to_json())

    return creds


def construir_servicio(credenciales=None):
    from googleapiclient.discovery import build

    if credenciales is None:
        credenciales = obtener_credenciales()
    return build("gmail", "v1", credentials=credenciales)


def diagnostico(servicio=None) -> dict:
    """Devuelve {"email": ..., "scopes": [...]} de la cuenta autenticada, para
    verificar ANTES de operar que el token quedó atado a la cuenta correcta
    (nmunoz@gomezyriesco.cl) y no a la personal."""
    if servicio is None:
        servicio = construir_servicio()
    perfil = servicio.users().getProfile(userId="me").execute()
    return {"email": perfil.get("emailAddress"), "scopes": SCOPES}


# ── Lectura ────────────────────────────────────────────────────────────────
def buscar_hilos(query: str, servicio=None, max_resultados: int = 50) -> list[dict]:
    """Busca hilos con la sintaxis de búsqueda de Gmail (misma que usa la UI:
    'from:', 'subject:', '-label:', etc). Devuelve la lista cruda de
    {"id", "snippet"} que entrega la API (sin los mensajes completos)."""
    if servicio is None:
        servicio = construir_servicio()

    hilos = []
    page_token = None
    while True:
        resultado = servicio.users().threads().list(
            userId="me", q=query, maxResults=min(max_resultados - len(hilos), 100),
            pageToken=page_token,
        ).execute()
        hilos.extend(resultado.get("threads", []))
        page_token = resultado.get("nextPageToken")
        if not page_token or len(hilos) >= max_resultados:
            break
    return hilos


def obtener_hilo(thread_id: str, servicio=None) -> dict:
    if servicio is None:
        servicio = construir_servicio()
    return servicio.users().threads().get(userId="me", id=thread_id, format="full").execute()


def cabeceras_respuesta_de_hilo(thread_id: str, servicio=None) -> dict:
    """Devuelve {"in_reply_to", "references"} a partir de los headers
    Message-ID/References del ÚLTIMO mensaje del hilo.

    El campo `threadId` de la API de Gmail solo agrupa el mensaje dentro de
    la propia cuenta de Gmail — es un puntero interno que nunca viaja en el
    correo. Para que un cliente ajeno (Outlook/Exchange corporativo, otro
    Gmail, etc.) reconozca un borrador como respuesta dentro de la
    conversación, el mensaje saliente necesita las cabeceras estándar
    In-Reply-To/References (RFC 5322) — sin ellas, el destinatario puede ver
    el correo como un mensaje suelto aunque en tu propia bandeja se vea
    encadenado (confirmado en la práctica: causa Tiznado/Salcobrand
    M-744-2026, agosto 2026)."""
    if servicio is None:
        servicio = construir_servicio()

    hilo = servicio.users().threads().get(
        userId="me", id=thread_id, format="metadata", metadataHeaders=["Message-ID", "References"]
    ).execute()
    mensajes = hilo.get("messages", [])
    if not mensajes:
        return {"in_reply_to": None, "references": None}

    # Los nombres de cabecera son case-insensitive por RFC 5322 — un mensaje
    # que pasó por otro cliente de correo (Apple Mail, Outlook) puede traer
    # "Message-Id" o "message-id" en vez de "Message-ID", y una búsqueda con
    # mayúsculas exactas falla en silencio (bug real encontrado en la
    # práctica: hilo "Consulta respecto a funcionario", agosto 2026).
    headers = {h["name"].lower(): h["value"] for h in mensajes[-1]["payload"].get("headers", [])}
    message_id = headers.get("message-id")
    referencias_previas = headers.get("references", "")
    referencias = (referencias_previas + " " + message_id).strip() if message_id else referencias_previas or None
    return {"in_reply_to": message_id, "references": referencias}


def _decodificar_base64url(datos: str) -> bytes:
    return base64.urlsafe_b64decode(datos.encode("utf-8"))


def _extraer_texto_plano(payload: dict) -> str:
    """Recorre las partes MIME de un mensaje y devuelve el primer cuerpo
    text/plain que encuentre; si no hay, intenta con text/html (sin quitar
    las etiquetas, mejor texto crudo que nada)."""
    candidatos = {"text/plain": None, "text/html": None}

    def recorrer(parte):
        mime = parte.get("mimeType", "")
        cuerpo = parte.get("body", {})
        datos = cuerpo.get("data")
        if mime in candidatos and candidatos[mime] is None and datos:
            candidatos[mime] = _decodificar_base64url(datos).decode("utf-8", errors="replace")
        for sub in parte.get("parts", []) or []:
            recorrer(sub)

    recorrer(payload)
    return candidatos["text/plain"] or candidatos["text/html"] or ""


def _listar_adjuntos(payload: dict) -> list[dict]:
    """Devuelve [{"filename", "attachment_id", "mime_type", "size"}] de todas
    las partes con filename y attachmentId (se excluyen partes inline sin
    nombre, como el cuerpo mismo)."""
    adjuntos = []

    def recorrer(parte):
        filename = parte.get("filename")
        cuerpo = parte.get("body", {})
        attachment_id = cuerpo.get("attachmentId")
        if filename and attachment_id:
            adjuntos.append({
                "filename": filename,
                "attachment_id": attachment_id,
                "mime_type": parte.get("mimeType", ""),
                "size": cuerpo.get("size", 0),
            })
        for sub in parte.get("parts", []) or []:
            recorrer(sub)

    recorrer(payload)
    return adjuntos


def leer_mensaje(message_id: str, servicio=None) -> dict:
    """Trae un mensaje completo y lo resume en:
    {"id", "thread_id", "subject", "sender", "date", "cuerpo_texto", "adjuntos"}
    """
    if servicio is None:
        servicio = construir_servicio()

    mensaje = servicio.users().messages().get(
        userId="me", id=message_id, format="full"
    ).execute()

    headers = {h["name"].lower(): h["value"] for h in mensaje["payload"].get("headers", [])}
    return {
        "id": mensaje["id"],
        "thread_id": mensaje["threadId"],
        "subject": headers.get("subject", ""),
        "sender": headers.get("from", ""),
        "to": headers.get("to", ""),
        "cc": headers.get("cc", ""),
        "date": headers.get("date", ""),
        "cuerpo_texto": _extraer_texto_plano(mensaje["payload"]),
        "adjuntos": _listar_adjuntos(mensaje["payload"]),
    }


def descargar_adjunto(message_id: str, attachment_id: str, servicio=None) -> bytes:
    if servicio is None:
        servicio = construir_servicio()
    adjunto = servicio.users().messages().attachments().get(
        userId="me", messageId=message_id, id=attachment_id
    ).execute()
    return _decodificar_base64url(adjunto["data"])


# ── Etiquetas ──────────────────────────────────────────────────────────────
def listar_etiquetas(servicio=None) -> list[dict]:
    if servicio is None:
        servicio = construir_servicio()
    return servicio.users().labels().list(userId="me").execute().get("labels", [])


def obtener_o_crear_etiqueta(
    nombre: str, servicio=None, color: dict | None = None
) -> str:
    """Devuelve el labelId de `nombre`, creándola si no existe. Si `color` se
    entrega (dict con backgroundColor/textColor de la paleta de Gmail), se
    aplica al crearla."""
    if servicio is None:
        servicio = construir_servicio()

    for etiqueta in listar_etiquetas(servicio):
        if etiqueta["name"] == nombre:
            return etiqueta["id"]

    cuerpo = {
        "name": nombre,
        "labelListVisibility": "labelShow",
        "messageListVisibility": "show",
    }
    if color:
        cuerpo["color"] = color

    creada = servicio.users().labels().create(userId="me", body=cuerpo).execute()
    return creada["id"]


def aplicar_etiqueta_a_hilo(thread_id: str, label_id: str, servicio=None) -> None:
    if servicio is None:
        servicio = construir_servicio()
    servicio.users().threads().modify(
        userId="me", id=thread_id, body={"addLabelIds": [label_id]}
    ).execute()


def aplicar_etiqueta_a_mensaje(message_id: str, label_id: str, servicio=None) -> None:
    if servicio is None:
        servicio = construir_servicio()
    servicio.users().messages().modify(
        userId="me", id=message_id, body={"addLabelIds": [label_id]}
    ).execute()


# ── Borradores (NUNCA se envían desde este módulo) ──────────────────────────
def crear_borrador(
    destinatario: str,
    asunto: str,
    cuerpo_texto: str,
    thread_id: str | None = None,
    servicio=None,
    html: bool = False,
    cc: str | None = None,
) -> dict:
    """Crea un borrador. Si se entrega `thread_id`, el borrador queda como
    respuesta dentro de esa cadena; si no, es un correo nuevo.

    Si `html` es True, `cuerpo_texto` se envía como text/html (p. ej. una
    lista `<ol><li>` para que Gmail la renumere solo al editarla) en vez de
    texto plano.

    `cc` (opcional) es una cadena de direcciones separadas por coma, para el
    "responder a todos" del recordatorio de documentos pendientes (Fase 6).

    Si se entrega `thread_id`, además se agregan las cabeceras estándar
    In-Reply-To/References (leídas del último mensaje del hilo — ver
    cabeceras_respuesta_de_hilo) para que el destinatario reconozca el
    correo como respuesta aunque su cliente de correo no sea Gmail; el
    `threadId` de la API por sí solo solo agrupa el mensaje en TU propia
    cuenta, nunca viaja con el correo.

    Este módulo deliberadamente NO implementa drafts.send ni messages.send.
    Un borrador creado aquí requiere que un humano lo revise y lo envíe a
    mano desde Gmail.
    """
    if servicio is None:
        servicio = construir_servicio()

    in_reply_to = referencias = None
    if thread_id:
        cabeceras = cabeceras_respuesta_de_hilo(thread_id, servicio=servicio)
        in_reply_to = cabeceras["in_reply_to"]
        referencias = cabeceras["references"]

    cuerpo_mensaje = _construir_cuerpo_mensaje(
        destinatario, asunto, cuerpo_texto, thread_id, html, cc, in_reply_to, referencias
    )

    return servicio.users().drafts().create(
        userId="me", body={"message": cuerpo_mensaje}
    ).execute()


def _construir_cuerpo_mensaje(
    destinatario: str, asunto: str, cuerpo_texto: str, thread_id: str | None, html: bool, cc: str | None,
    in_reply_to: str | None = None, referencias: str | None = None,
) -> dict:
    import email.mime.text

    mensaje = email.mime.text.MIMEText(cuerpo_texto, "html" if html else "plain")
    mensaje["to"] = destinatario
    if in_reply_to:
        mensaje["In-Reply-To"] = in_reply_to
    if referencias:
        mensaje["References"] = referencias
    if cc:
        mensaje["cc"] = cc
    mensaje["subject"] = asunto
    raw = base64.urlsafe_b64encode(mensaje.as_bytes()).decode("utf-8")

    cuerpo_mensaje = {"raw": raw}
    if thread_id:
        cuerpo_mensaje["threadId"] = thread_id
    return cuerpo_mensaje


def listar_borradores_de_hilo(thread_id: str, servicio=None) -> list[dict]:
    """Usado antes de crear_borrador() para no duplicar un borrador ya
    existente en la cadena (regla del usuario: si ya hay un borrador, no se
    sobrescribe)."""
    if servicio is None:
        servicio = construir_servicio()
    todos = servicio.users().drafts().list(userId="me").execute().get("drafts", [])
    resultado = []
    for borrador in todos:
        detalle = servicio.users().drafts().get(userId="me", id=borrador["id"]).execute()
        if detalle.get("message", {}).get("threadId") == thread_id:
            resultado.append(detalle)
    return resultado


def buscar_borrador_por_asunto(fragmento_asunto: str, servicio=None) -> list[dict]:
    """Busca borradores cuyo asunto contenga `fragmento_asunto` (comparación
    simple, insensible a mayúsculas). Existe para la Fase 4: el borrador de
    ofrecimiento a Román es un correo NUEVO, no una respuesta dentro de una
    cadena existente, así que listar_borradores_de_hilo() no sirve para
    evitar duplicarlo — se busca por el RIT en el asunto en su lugar (el
    asunto siempre incluye el RIT: 'Demanda laboral ... Rit [RIT]')."""
    if servicio is None:
        servicio = construir_servicio()
    todos = servicio.users().drafts().list(userId="me").execute().get("drafts", [])
    objetivo = fragmento_asunto.lower()
    resultado = []
    for borrador in todos:
        detalle = servicio.users().drafts().get(userId="me", id=borrador["id"]).execute()
        headers = detalle.get("message", {}).get("payload", {}).get("headers", [])
        asunto = next((h["value"] for h in headers if h["name"].lower() == "subject"), "")
        if objetivo in asunto.lower():
            resultado.append(detalle)
    return resultado


def borrador_existe(draft_id: str, servicio=None) -> bool:
    """True si `draft_id` sigue existiendo como borrador. Una vez que Nico
    envía un borrador, Gmail lo convierte en mensaje enviado y el draft_id
    deja de existir (drafts().get devuelve 404) — así se detecta que un
    borrador de una corrida anterior ya fue revisado y enviado."""
    from googleapiclient.errors import HttpError

    if servicio is None:
        servicio = construir_servicio()
    try:
        servicio.users().drafts().get(userId="me", id=draft_id).execute()
        return True
    except HttpError as e:
        if getattr(e, "status_code", None) == 404 or e.resp.status == 404:
            return False
        raise
