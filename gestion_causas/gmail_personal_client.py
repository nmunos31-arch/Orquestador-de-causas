#!/usr/bin/env python3
"""
Cliente Gmail propio (OAuth de escritorio) para la casilla personal
nmunos31@gmail.com.

Existe con un único propósito: enviar el panel de estado del ciclo de
gestión de causas a nmunoz@gomezyriesco.cl. Política del usuario
(2026-08-27): nmunoz@gomezyriesco.cl (trabajo) NUNCA envía correo, solo deja
borradores (ver gmail_client.py); nmunos31@gmail.com (personal) es la ÚNICA
cuenta que el usuario autoriza a enviar. Este módulo es deliberadamente
mínimo: no lee correo, no etiqueta, no crea borradores — solo envía, y solo
a un destinatario fijo (ver GARANTÍA DE SEGURIDAD abajo).

Reutiliza el mismo client_secret.json (proyecto informe-semanal-501614) que
ya usan 'Automatizacion Informe Semanal/generar_informe_semanal.py' y
gmail_client.py, con un token.json propio (token_gmail_personal.json)
autorizado con la cuenta personal.

GARANTÍA DE SEGURIDAD (verificada por tests/test_gmail_personal_client.py):
Este módulo expone una única función capaz de enviar correo,
enviar_panel_estado(), que no acepta un destinatario distinto del hardcodeado
en PANEL_DESTINATARIO (no expone parámetro `destinatario`/`to`). El scope
pedido es únicamente gmail.send — no hay lectura, etiquetado ni borrado
posible con este token.
"""

import base64
import sys
from pathlib import Path

CLIENT_SECRET_PATH = str(
    Path(__file__).parent.parent.parent / "Automatizacion Informe Semanal" / "client_secret.json"
)
TOKEN_PATH = str(Path(__file__).parent / "token_gmail_personal.json")

# gmail.send es el único scope de Gmail: este módulo no lee, no etiqueta,
# no crea borradores — solo envía el panel de estado. userinfo.email se
# agrega aparte, no da acceso a Gmail: solo permite confirmar qué cuenta
# quedó autenticada antes de enviar (mismo criterio de verificación que ya
# usan gmail_client.diagnostico() y calendar_client.diagnostico()) — sin
# él, gmail.send por sí solo no autoriza leer el perfil (users.getProfile
# devuelve 403 insufficientPermissions con gmail.send únicamente).
SCOPES = [
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/userinfo.email",
]

# Único destinatario permitido de enviar_panel_estado() — ver esa función
# más abajo. No es un parámetro: la garantía de que este módulo no puede
# mandar correo a nadie más queda en el código, no en el llamador.
PANEL_DESTINATARIO = "nmunoz@gomezyriesco.cl"


def log(msg):
    print(f"[gmail_personal_client] {msg}", file=sys.stderr)


def obtener_credenciales():
    """Autentica contra la cuenta personal, reutilizando el token si es
    válido. Mismo patrón que gmail_client.obtener_credenciales() (incluye
    el manejo de refresh token inválido por app en modo Testing)."""
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
            log("Abriendo navegador para iniciar sesión — usa la cuenta nmunos31@gmail.com.")
            creds = flow.run_local_server(port=0)

        with open(TOKEN_PATH, "w") as f:
            f.write(creds.to_json())

    return creds


def construir_servicio(credenciales=None):
    from googleapiclient.discovery import build

    if credenciales is None:
        credenciales = obtener_credenciales()
    return build("gmail", "v1", credentials=credenciales)


def diagnostico(credenciales=None) -> dict:
    """Devuelve {"email": ..., "scopes": [...]} de la cuenta autenticada,
    para verificar ANTES de operar que el token quedó atado a la cuenta
    correcta (nmunos31@gmail.com) y no a la del trabajo.

    Usa el servicio "oauth2" (scope userinfo.email), no el de Gmail: el
    scope gmail.send por sí solo no autoriza leer el perfil de Gmail
    (users.getProfile devuelve 403 con gmail.send únicamente)."""
    from googleapiclient.discovery import build

    if credenciales is None:
        credenciales = obtener_credenciales()
    servicio_userinfo = build("oauth2", "v2", credentials=credenciales)
    perfil = servicio_userinfo.userinfo().get().execute()
    return {"email": perfil.get("email"), "scopes": SCOPES}


def enviar_panel_estado(asunto: str, html: str, servicio=None) -> dict:
    """Envía el panel de estado del ciclo de gestión de causas a
    PANEL_DESTINATARIO (nmunoz@gomezyriesco.cl).

    Única función de este módulo — no expone parámetro `destinatario`/`to`,
    verificado por tests/test_gmail_personal_client.py.
    """
    import email.mime.text

    if not html or not html.strip():
        raise ValueError("El panel no puede enviarse vacío")

    if servicio is None:
        servicio = construir_servicio()

    mensaje = email.mime.text.MIMEText(html, "html")
    mensaje["to"] = PANEL_DESTINATARIO
    mensaje["subject"] = asunto
    raw = base64.urlsafe_b64encode(mensaje.as_bytes()).decode("utf-8")

    return servicio.users().messages().send(userId="me", body={"raw": raw}).execute()
