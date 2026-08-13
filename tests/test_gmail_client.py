"""
Test de garantía: gmail_client.py nunca debe poder enviar ni borrar correos.

No hace llamadas de red (no requiere credenciales) — solo inspecciona el
módulo estáticamente: qué funciones expone y qué scopes de OAuth pide.
"""

import inspect

from gestion_causas import gmail_client


class TestNoExponeEnvioNiBorrado:
    def test_no_hay_funciones_de_envio(self):
        nombres = [n for n, _ in inspect.getmembers(gmail_client, inspect.isfunction)]
        prohibidos_envio = {"enviar", "send", "mandar", "responder", "reply"}
        for nombre in nombres:
            partes = set(nombre.lower().replace("_", " ").split())
            assert not (partes & prohibidos_envio), f"Función sospechosa de enviar: {nombre}"

    def test_no_hay_funciones_de_borrado(self):
        nombres = [n for n, _ in inspect.getmembers(gmail_client, inspect.isfunction)]
        prohibidos_borrado = {"borrar", "eliminar", "delete", "trash", "papelera"}
        for nombre in nombres:
            partes = set(nombre.lower().replace("_", " ").split())
            assert not (partes & prohibidos_borrado), f"Función sospechosa de borrar: {nombre}"

    def test_codigo_fuente_no_llama_a_drafts_send_ni_messages_send(self):
        fuente = inspect.getsource(gmail_client)
        assert "drafts().send" not in fuente
        assert "messages().send" not in fuente
        assert ".trash(" not in fuente
        assert "untrash" not in fuente

    def test_crear_borrador_usa_drafts_create_no_send(self):
        fuente = inspect.getsource(gmail_client.crear_borrador)
        assert "drafts().create" in fuente
        assert ".send(" not in fuente


class TestScopesMinimos:
    def test_pide_scope_modify_solo_para_etiquetar(self):
        # gmail.modify es necesario porque la API de Gmail no ofrece un scope
        # más angosto para aplicar etiquetas a un hilo/mensaje — la garantía
        # de que igual no se borra ni se envía nada queda en el código
        # (ver TestNoExponeEnvioNiBorrado), no en el scope.
        assert "https://www.googleapis.com/auth/gmail.modify" in gmail_client.SCOPES

    def test_no_pide_acceso_total(self):
        assert "https://mail.google.com/" not in gmail_client.SCOPES

    def test_scopes_son_los_esperados(self):
        esperados = {
            "https://www.googleapis.com/auth/gmail.readonly",
            "https://www.googleapis.com/auth/gmail.labels",
            "https://www.googleapis.com/auth/gmail.compose",
            "https://www.googleapis.com/auth/gmail.modify",
        }
        assert set(gmail_client.SCOPES) == esperados


class TestExtraccionDeTextoYAdjuntos:
    def test_extrae_texto_plano_de_payload_simple(self):
        import base64

        texto = "Hola, este es el cuerpo del correo."
        payload = {
            "mimeType": "text/plain",
            "body": {"data": base64.urlsafe_b64encode(texto.encode()).decode()},
        }
        assert gmail_client._extraer_texto_plano(payload) == texto

    def test_extrae_texto_plano_de_payload_multipart(self):
        import base64

        texto = "Cuerpo en la segunda parte."
        payload = {
            "mimeType": "multipart/mixed",
            "parts": [
                {"mimeType": "text/plain", "body": {"data": base64.urlsafe_b64encode(texto.encode()).decode()}},
                {"filename": "demanda.pdf", "mimeType": "application/pdf", "body": {"attachmentId": "abc", "size": 100}},
            ],
        }
        assert gmail_client._extraer_texto_plano(payload) == texto

    def test_lista_adjuntos_ignora_partes_sin_filename(self):
        payload = {
            "mimeType": "multipart/mixed",
            "parts": [
                {"mimeType": "text/plain", "body": {"data": "eA=="}},
                {"filename": "demanda.pdf", "mimeType": "application/pdf", "body": {"attachmentId": "abc123", "size": 5000}},
            ],
        }
        adjuntos = gmail_client._listar_adjuntos(payload)
        assert len(adjuntos) == 1
        assert adjuntos[0]["filename"] == "demanda.pdf"
        assert adjuntos[0]["attachment_id"] == "abc123"


class _ServicioDraftsFalso:
    """Stub mínimo que imita servicio.users().drafts().list()/.get()
    encadenado, para probar buscar_borrador_por_asunto sin red."""

    def __init__(self, borradores_por_id):
        self._borradores = borradores_por_id

    def users(self):
        return self

    def drafts(self):
        return self

    def list(self, userId):
        ids = list(self._borradores.keys())
        return _Ejecutable({"drafts": [{"id": i} for i in ids]})

    def get(self, userId, id):
        return _Ejecutable(self._borradores[id])


class _Ejecutable:
    def __init__(self, valor):
        self._valor = valor

    def execute(self):
        return self._valor


def _borrador_con_asunto(asunto: str, thread_id: str = "t1") -> dict:
    return {
        "message": {
            "threadId": thread_id,
            "payload": {"headers": [{"name": "Subject", "value": asunto}]},
        }
    }


class TestBuscarBorradorPorAsunto:
    def test_encuentra_por_fragmento_insensible_a_mayusculas(self):
        servicio = _ServicioDraftsFalso({
            "d1": _borrador_con_asunto("Demanda laboral Soto con Rendic Rit M-6-2026"),
        })
        encontrados = gmail_client.buscar_borrador_por_asunto("rit m-6-2026", servicio=servicio)
        assert len(encontrados) == 1

    def test_no_encuentra_si_no_coincide(self):
        servicio = _ServicioDraftsFalso({
            "d1": _borrador_con_asunto("Demanda laboral Soto con Rendic Rit M-6-2026"),
        })
        encontrados = gmail_client.buscar_borrador_por_asunto("Rit O-999-2026", servicio=servicio)
        assert encontrados == []


class TestEmpresasSinExcel:
    def test_preunic_y_salcobrand_no_van_al_excel(self):
        assert gmail_client.EMPRESAS_SIN_EXCEL == {"Preunic", "Salcobrand"}

    def test_las_4_empresas_smu_no_estan_en_sin_excel(self):
        empresas_smu = {"Rendic Hermanos", "Alvi", "Super 10", "Servicios Logísticos Santiago"}
        assert empresas_smu.isdisjoint(gmail_client.EMPRESAS_SIN_EXCEL)

    def test_las_6_empresas_tienen_color_configurado(self):
        esperadas = {
            "Rendic Hermanos", "Alvi", "Super 10", "Servicios Logísticos Santiago",
            "Preunic", "Salcobrand",
        }
        assert esperadas == set(gmail_client.COLOR_POR_EMPRESA)
