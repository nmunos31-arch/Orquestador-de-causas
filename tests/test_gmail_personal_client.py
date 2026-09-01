"""
Test de garantía: gmail_personal_client.py solo puede enviar el panel de
estado a un destinatario fijo, y no expone ninguna otra capacidad (lectura,
etiquetado, borrado).

No hace llamadas de red (no requiere credenciales) — solo inspecciona el
módulo estáticamente: qué funciones expone, qué scopes de OAuth pide, y la
firma/comportamiento de enviar_panel_estado.
"""

import inspect

import pytest

from gestion_causas import gmail_personal_client


class TestScopeMinimo:
    def test_pide_solo_send_userinfo_email_y_openid(self):
        # userinfo.email/openid no dan acceso a Gmail: solo permiten que
        # diagnostico() confirme la cuenta autenticada (gmail.send solo no
        # alcanza para leer el perfil vía la API de Gmail). "openid" se
        # pide explícito porque Google lo agrega solo junto a
        # userinfo.email (ver comentario en gmail_personal_client.py).
        assert set(gmail_personal_client.SCOPES) == {
            "https://www.googleapis.com/auth/gmail.send",
            "https://www.googleapis.com/auth/userinfo.email",
            "openid",
        }

    def test_no_pide_acceso_total(self):
        assert "https://mail.google.com/" not in gmail_personal_client.SCOPES


class TestNoExponeOtrasCapacidades:
    def test_no_hay_funciones_de_lectura_ni_borrado(self):
        permitidas = {
            "enviar_panel_estado",
            "obtener_credenciales",
            "construir_servicio",
            "diagnostico",
            "log",
        }
        nombres = [n for n, _ in inspect.getmembers(gmail_personal_client, inspect.isfunction)]
        prohibidas = {"borrar", "eliminar", "delete", "trash", "papelera", "leer", "buscar", "etiquetar"}
        for nombre in nombres:
            if nombre in permitidas:
                continue
            partes = set(nombre.lower().replace("_", " ").split())
            assert not (partes & prohibidas), f"Función inesperada en un módulo de solo-envío: {nombre}"

    def test_codigo_fuente_no_llama_a_drafts(self):
        fuente = inspect.getsource(gmail_personal_client)
        assert "drafts()" not in fuente
        assert ".trash(" not in fuente


class TestEnvioAcotadoDelPanel:
    def test_enviar_panel_estado_llama_a_messages_send(self):
        fuente = inspect.getsource(gmail_personal_client.enviar_panel_estado)
        assert "messages().send" in fuente

    def test_enviar_panel_estado_no_acepta_destinatario_arbitrario(self):
        parametros = inspect.signature(gmail_personal_client.enviar_panel_estado).parameters
        assert "destinatario" not in parametros
        assert "to" not in parametros

    def test_enviar_panel_estado_usa_destinatario_fijo(self):
        assert gmail_personal_client.PANEL_DESTINATARIO == "nmunoz@gomezyriesco.cl"

    def test_enviar_panel_estado_rechaza_html_vacio(self):
        with pytest.raises(ValueError):
            gmail_personal_client.enviar_panel_estado("Asunto de prueba", "")

    def test_enviar_panel_estado_rechaza_html_solo_espacios(self):
        with pytest.raises(ValueError):
            gmail_personal_client.enviar_panel_estado("Asunto de prueba", "   ")


class TestLoginNoInteractivo:
    """En una corrida desatendida (contexto-corrida) el flujo de OAuth abre un
    navegador y nunca vuelve. Con permitir_login=False se falla rápido en vez
    de colgar la tarea programada."""

    def test_sin_token_valido_levanta_en_vez_de_abrir_el_navegador(self, tmp_path, monkeypatch):
        import pytest

        monkeypatch.setattr(gmail_personal_client, "TOKEN_PATH", str(tmp_path / "no-existe.json"))
        with pytest.raises(RuntimeError, match="diagnostico-personal"):
            gmail_personal_client.obtener_credenciales(permitir_login=False)
