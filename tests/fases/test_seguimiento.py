import json
from datetime import datetime, timedelta
from email.utils import format_datetime

from gestion_causas import registro as registro_mod
from gestion_causas import seguimiento as seguimiento_mod
from gestion_causas.fases import seguimiento


def _rutas(tmp_path):
    return {
        "ruta_registro_pedidos": tmp_path / "registro_pedidos.json",
        "ruta_registro_causas": tmp_path / "registro_causas.json",
        "ruta_registro_seguimiento": tmp_path / "registro_seguimiento.json",
    }


def _registrar_pedido(tmp_path, thread_id="thread-1", **extra):
    rutas = _rutas(tmp_path)
    datos = {
        "rit": "M-1-2026", "tipo": "documentos", "fecha_envio": "2026-09-01",
        "destinatario": "contraparte@externo.cl", "items_pedidos": ["Contrato de trabajo"],
        "estado": "esperando", "origen": "manual", **extra,
    }
    registro_mod.registrar_pedido(thread_id, datos, ruta=rutas["ruta_registro_pedidos"])
    return rutas


def _mensaje(sender="contraparte@externo.cl", cuerpo="", fecha="Tue, 15 Sep 2026 10:00:00 -0400", subject="Causa laboral M-1-2026", **extra):
    return {
        "id": "msg-1", "thread_id": "thread-1", "subject": subject, "sender": sender,
        "to": "nmunoz@gomezyriesco.cl", "cc": "", "date": fecha, "cuerpo_texto": cuerpo,
        "adjuntos": [], **extra,
    }


class TestTipoAviso:
    def test_documentos_es_documentos(self):
        assert seguimiento._tipo_aviso({"tipo": "documentos"}) == "documentos"

    def test_acuerdo_daniela(self):
        pedido = {"tipo": "acuerdo", "destinatario": "dsanchezv@smu.cl"}
        assert seguimiento._tipo_aviso(pedido) == "acuerdo-daniela"

    def test_acuerdo_otro_destinatario_es_causa_laboral(self):
        pedido = {"tipo": "acuerdo", "destinatario": "otro@empresa.cl"}
        assert seguimiento._tipo_aviso(pedido) == "causa-laboral"


class TestNombreParaSaludo:
    def test_extrae_y_capitaliza_local_part(self):
        assert seguimiento._nombre_para_saludo("cristina.gil@empresa.cl") == "Cristina.gil"

    def test_vacio_si_no_hay_destinatario(self):
        assert seguimiento._nombre_para_saludo("") == ""


class TestMensajesPosteriores:
    def test_filtra_por_fecha_y_agrega_otros_hilos_del_mismo_rit(self):
        mensajes_hilo = [_mensaje(fecha="Mon, 31 Aug 2026 10:00:00 -0400"), _mensaje(fecha="Wed, 16 Sep 2026 10:00:00 -0400")]
        mapa_hilos = {
            "rit_a_hilos": {"M-1-2026": ["thread-1", "thread-2"]},
            "hilos": {"thread-2": [_mensaje(fecha="Thu, 17 Sep 2026 10:00:00 -0400")]},
        }
        resultado = seguimiento._mensajes_posteriores(
            "thread-1", mensajes_hilo, seguimiento_mod.momento_desde_fecha("2026-09-01"), "M-1-2026", mapa_hilos
        )
        assert len(resultado) == 2

    def test_sin_rit_no_busca_otros_hilos(self):
        mensajes_hilo = [_mensaje(fecha="Wed, 16 Sep 2026 10:00:00 -0400")]
        resultado = seguimiento._mensajes_posteriores(
            "thread-1", mensajes_hilo, seguimiento_mod.momento_desde_fecha("2026-09-01"), None, {}
        )
        assert len(resultado) == 1

    def test_respuesta_del_mismo_dia_cuenta(self):
        momento_envio = datetime.fromisoformat("2026-09-15T09:00:00-04:00")
        mensajes_hilo = [_mensaje(fecha="Tue, 15 Sep 2026 15:00:00 -0400")]
        resultado = seguimiento._mensajes_posteriores("thread-1", mensajes_hilo, momento_envio, None, {})
        assert len(resultado) == 1

    def test_excluye_borradores_y_mensajes_propios(self):
        momento_envio = datetime.fromisoformat("2026-09-15T09:00:00-04:00")
        mensajes_hilo = [
            _mensaje(sender="nmunoz@gomezyriesco.cl", fecha="Tue, 15 Sep 2026 10:00:00 -0400"),
            _mensaje(sender="nmunoz@gomezyriesco.cl", fecha="Tue, 15 Sep 2026 11:00:00 -0400", es_borrador=True),
            _mensaje(sender="contraparte@externo.cl", fecha="Tue, 15 Sep 2026 12:00:00 -0400"),
        ]
        resultado = seguimiento._mensajes_posteriores("thread-1", mensajes_hilo, momento_envio, None, {})
        assert [m["sender"] for m in resultado] == ["contraparte@externo.cl"]

    def test_momento_envio_pedido_legado_sin_message_id(self):
        pedido = {"fecha_envio": "2026-09-15"}
        assert seguimiento._momento_envio(pedido, []) == seguimiento_mod.momento_desde_fecha("2026-09-15")

    def test_momento_envio_usa_el_message_id_del_pedido(self):
        mensajes_hilo = [_mensaje(fecha="Tue, 15 Sep 2026 10:30:00 -0400")]
        mensajes_hilo[0]["id"] = "msg-envio"
        pedido = {"fecha_envio": "2026-09-15", "message_id": "msg-envio"}
        momento = seguimiento._momento_envio(pedido, mensajes_hilo)
        assert momento == datetime.fromisoformat("2026-09-15T10:30:00-04:00")


class TestCuerpoConLista:
    def test_arma_lista_html_entre_antes_y_despues(self):
        cuerpo = seguimiento._cuerpo_con_lista("Antes\n\n[[LISTA]]\n\nDespues", ["Item A", "Item B"])
        assert "<ol><li>Item A</li><li>Item B</li></ol>" in cuerpo
        assert cuerpo.startswith("Antes")
        assert cuerpo.endswith("Despues")


class TestEvaluarInsistencia:
    def test_documentos_no_corresponde_antes_de_4_dias_habiles(self, tmp_path, monkeypatch):
        rutas = _registrar_pedido(tmp_path, fecha_envio="2026-09-15")
        llamadas = []
        monkeypatch.setattr(seguimiento.gmail_client, "listar_borradores_de_hilo", lambda *a, **k: llamadas.append(1))

        resultado = seguimiento._evaluar_insistencia(
            {"thread_id": "thread-1", "tipo": "documentos", "fecha_envio": "2026-09-15", "rit": "M-1-2026"},
            "2026-09-16", [], [], [],
            rutas["ruta_registro_pedidos"], rutas["ruta_registro_seguimiento"], rutas["ruta_registro_causas"],
        )

        assert resultado == "sin_novedad"
        assert llamadas == []

    def test_acuerdo_corresponde_despues_de_un_dia(self, tmp_path, monkeypatch):
        rutas = _registrar_pedido(tmp_path, tipo="acuerdo", fecha_envio="2026-09-15")
        monkeypatch.setattr(seguimiento.gmail_client, "listar_borradores_de_hilo", lambda *a, **k: [])
        monkeypatch.setattr(seguimiento.gmail_client, "crear_borrador", lambda *a, **k: {"id": "draft-1"})
        monkeypatch.setattr(seguimiento.bitacora_mod, "registrar", lambda *a, **k: None)

        acciones, items = [], []
        resultado = seguimiento._evaluar_insistencia(
            {"thread_id": "thread-1", "tipo": "acuerdo", "fecha_envio": "2026-09-15", "rit": "M-1-2026", "destinatario": "x@y.cl"},
            "2026-09-16", [], acciones, items,
            rutas["ruta_registro_pedidos"], rutas["ruta_registro_seguimiento"], rutas["ruta_registro_causas"],
        )

        assert resultado == "insistencia"
        assert len(items) == 1
        seguimiento_guardado = registro_mod.obtener_seguimiento("thread-1", ruta=rutas["ruta_registro_seguimiento"])
        assert seguimiento_guardado["avisos"] == []
        assert seguimiento_guardado["borrador_pendiente"] == {"fecha": "2026-09-16"}

    def test_no_duplica_si_ya_hay_borrador_en_la_cadena(self, tmp_path, monkeypatch):
        rutas = _registrar_pedido(tmp_path, tipo="acuerdo", fecha_envio="2026-09-15")
        llamadas_crear = []
        monkeypatch.setattr(seguimiento.gmail_client, "crear_borrador", lambda *a, **k: llamadas_crear.append(1))
        hilo = [_mensaje(sender=seguimiento.CUENTA_TRABAJO, fecha="Tue, 15 Sep 2026 12:00:00 -0400", id="draft-existente", es_borrador=True)]

        resultado = seguimiento._evaluar_insistencia(
            {"thread_id": "thread-1", "tipo": "acuerdo", "fecha_envio": "2026-09-15", "rit": "M-1-2026"},
            "2026-09-16", hilo, [], [],
            rutas["ruta_registro_pedidos"], rutas["ruta_registro_seguimiento"], rutas["ruta_registro_causas"],
        )

        assert resultado == "sin_novedad"
        assert llamadas_crear == []

    def test_pasa_a_gestion_manual_si_causa_no_tiene_audiencia_agendada(self, tmp_path, monkeypatch):
        rutas = _registrar_pedido(tmp_path, tipo="acuerdo", fecha_envio="2026-09-01")
        # 2 avisos enviados por Nico después del pedido -> el 3ro exige mirar fecha_audiencia
        hilo = [
            _mensaje(sender=seguimiento.CUENTA_TRABAJO, fecha="Tue, 01 Sep 2026 10:00:00 -0400", id="msg-pedido"),
            _mensaje(sender=seguimiento.CUENTA_TRABAJO, fecha="Sat, 05 Sep 2026 10:00:00 -0400", id="aviso-1"),
            _mensaje(sender=seguimiento.CUENTA_TRABAJO, fecha="Tue, 08 Sep 2026 10:00:00 -0400", id="aviso-2"),
        ]
        registro_mod.registrar_causa("M-1-2026", {}, ruta=rutas["ruta_registro_causas"])  # sin fecha_audiencia

        acciones = []
        resultado = seguimiento._evaluar_insistencia(
            {"thread_id": "thread-1", "tipo": "acuerdo", "fecha_envio": "2026-09-01", "rit": "M-1-2026", "message_id": "msg-pedido"},
            "2026-09-16", hilo, acciones, [],
            rutas["ruta_registro_pedidos"], rutas["ruta_registro_seguimiento"], rutas["ruta_registro_causas"],
        )

        assert resultado == "gestion_manual"
        assert len(acciones) == 1
        assert acciones[0]["urgencia"] == "alta"
        entrada = registro_mod.obtener_pedido("thread-1", ruta=rutas["ruta_registro_pedidos"])
        assert entrada["estado"] == "gestion_manual"


class TestProcesarPedido:
    def test_sin_fecha_envio_no_hace_nada(self, tmp_path):
        rutas = _registrar_pedido(tmp_path, fecha_envio=None)
        resultado = seguimiento._procesar_pedido(
            {"thread_id": "thread-1", "tipo": "documentos", "fecha_envio": None, "rit": "M-1-2026"},
            "2026-09-16", {},
            rutas["ruta_registro_pedidos"], rutas["ruta_registro_seguimiento"], rutas["ruta_registro_causas"],
            [], [], {},
        )
        assert resultado == "sin_novedad"

    def test_marca_completo_cuando_claude_clasifica_completo(self, tmp_path, monkeypatch):
        rutas = _registrar_pedido(tmp_path, fecha_envio="2026-09-01", label_id="label-1")
        monkeypatch.setattr(
            seguimiento.gmail_client, "leer_hilo",
            lambda thread_id, **k: [_mensaje(fecha="Wed, 16 Sep 2026 10:00:00 -0400", cuerpo="Adjunto el contrato solicitado")],
        )
        monkeypatch.setattr(
            seguimiento.reasoning, "preguntar",
            lambda *a, **k: {"estado": "completo", "items_recibidos": ["Contrato de trabajo"], "motivo": "llegó todo"},
        )
        quitadas = []
        monkeypatch.setattr(seguimiento.gmail_client, "quitar_etiqueta_de_hilo", lambda *a, **k: quitadas.append(1))
        monkeypatch.setattr(seguimiento.bitacora_mod, "registrar", lambda *a, **k: None)

        resultado = seguimiento._procesar_pedido(
            {"thread_id": "thread-1", "tipo": "documentos", "fecha_envio": "2026-09-01", "rit": "M-1-2026",
             "items_pedidos": ["Contrato de trabajo"], "label_id": "label-1"},
            "2026-09-16", {},
            rutas["ruta_registro_pedidos"], rutas["ruta_registro_seguimiento"], rutas["ruta_registro_causas"],
            [], [], {},
        )

        assert resultado == "completo"
        assert quitadas == [1]
        entrada = registro_mod.obtener_pedido("thread-1", ruta=rutas["ruta_registro_pedidos"])
        assert entrada["estado"] == "completo"

    def test_crea_recordatorio_cuando_claude_clasifica_parcial(self, tmp_path, monkeypatch):
        rutas = _registrar_pedido(
            tmp_path, fecha_envio="2026-09-01", items_pedidos=["Contrato de trabajo", "Finiquito"],
        )
        monkeypatch.setattr(
            seguimiento.gmail_client, "leer_hilo",
            lambda thread_id, **k: [_mensaje(fecha="Wed, 16 Sep 2026 10:00:00 -0400", cuerpo="Adjunto el contrato")],
        )
        monkeypatch.setattr(
            seguimiento.reasoning, "preguntar",
            lambda *a, **k: {"estado": "parcial", "items_recibidos": ["Contrato de trabajo"], "motivo": "falta el finiquito"},
        )
        monkeypatch.setattr(seguimiento.gmail_client, "listar_borradores_de_hilo", lambda *a, **k: [])
        llamadas_crear = []
        monkeypatch.setattr(
            seguimiento.gmail_client, "crear_borrador",
            lambda destinatario, asunto, cuerpo, **k: llamadas_crear.append((destinatario, asunto, cuerpo)) or {"id": "draft-2"},
        )
        monkeypatch.setattr(seguimiento.bitacora_mod, "registrar", lambda *a, **k: None)

        items: list[dict] = []
        resultado = seguimiento._procesar_pedido(
            {"thread_id": "thread-1", "tipo": "documentos", "fecha_envio": "2026-09-01", "rit": "M-1-2026",
             "items_pedidos": ["Contrato de trabajo", "Finiquito"], "destinatario": "contraparte@externo.cl"},
            "2026-09-16", {},
            rutas["ruta_registro_pedidos"], rutas["ruta_registro_seguimiento"], rutas["ruta_registro_causas"],
            [], items, {},
        )

        assert resultado == "recordatorio"
        assert len(llamadas_crear) == 1
        _destinatario, _asunto, cuerpo = llamadas_crear[0]
        assert "Finiquito" in cuerpo
        assert "Contrato de trabajo" not in cuerpo
        entrada = registro_mod.obtener_pedido("thread-1", ruta=rutas["ruta_registro_pedidos"])
        assert entrada["estado"] == "parcial"
        assert entrada["items_recibidos"] == ["Contrato de trabajo"]

    def test_mensaje_solo_informativo_no_crea_insistencia_antes_de_tiempo(self, tmp_path, monkeypatch):
        """Si Claude clasifica el mensaje posterior como solo informativo
        (sin_respuesta_real), el pedido sigue el flujo mecánico de
        insistencia normal, sin insistir apenas llega cualquier mensaje."""
        rutas = _registrar_pedido(tmp_path, tipo="acuerdo", fecha_envio="2026-09-15")
        monkeypatch.setattr(
            seguimiento.gmail_client, "leer_hilo",
            lambda thread_id, **k: [_mensaje(fecha="Wed, 16 Sep 2026 10:00:00 -0400", cuerpo="Le informamos que recibimos su correo")],
        )
        monkeypatch.setattr(
            seguimiento.reasoning, "preguntar",
            lambda *a, **k: {"estado": "sin_respuesta_real", "items_recibidos": [], "motivo": "solo informativo"},
        )
        monkeypatch.setattr(seguimiento.gmail_client, "listar_borradores_de_hilo", lambda *a, **k: [])
        monkeypatch.setattr(seguimiento.gmail_client, "crear_borrador", lambda *a, **k: {"id": "draft-1"})
        monkeypatch.setattr(seguimiento.bitacora_mod, "registrar", lambda *a, **k: None)

        resultado = seguimiento._procesar_pedido(
            {"thread_id": "thread-1", "tipo": "acuerdo", "fecha_envio": "2026-09-15", "rit": "M-1-2026"},
            "2026-09-16", {},
            rutas["ruta_registro_pedidos"], rutas["ruta_registro_seguimiento"], rutas["ruta_registro_causas"],
            [], [], {},
        )

        # Todavía corresponde insistir (paso 24hs cumplido, el mensaje
        # posterior es solo informativo y no cuenta como respuesta real): se
        # sigue el flujo mecánico normal y crea la insistencia, en vez de
        # marcar el pedido como completo o con un recordatorio.
        assert resultado == "insistencia"

    def test_acuerdo_con_externo_ignora_respuestas_internas(self, tmp_path, monkeypatch):
        """Ofrecimiento hecho al abogado de la contraparte: un comentario
        interno del equipo en la misma cadena no es la respuesta — no se le
        pasa a Claude y se sigue el flujo de insistencia (caso M-875-2026)."""
        rutas = _registrar_pedido(tmp_path, tipo="acuerdo", fecha_envio="2026-09-22")
        monkeypatch.setattr(
            seguimiento.gmail_client, "leer_hilo",
            lambda thread_id, **k: [_mensaje(
                sender="Diego Brito <dbrito@gomezyriesco.cl>", fecha="Tue, 22 Sep 2026 17:01:56 -0300",
                cuerpo="[image: image.png]",
            ), _mensaje(sender="Diego Brito <dbrito@gomezyriesco.cl>", fecha="Wed, 23 Sep 2026 10:00:00 -0300", cuerpo="ok")],
        )
        llamadas_claude = []
        monkeypatch.setattr(seguimiento.reasoning, "preguntar", lambda *a, **k: llamadas_claude.append(1) or {"estado": "completo"})
        monkeypatch.setattr(seguimiento.gmail_client, "listar_borradores_de_hilo", lambda *a, **k: [])
        monkeypatch.setattr(seguimiento.gmail_client, "crear_borrador", lambda *a, **k: {"id": "draft-1"})
        monkeypatch.setattr(seguimiento.bitacora_mod, "registrar", lambda *a, **k: None)

        resultado = seguimiento._procesar_pedido(
            {"thread_id": "thread-1", "tipo": "acuerdo", "fecha_envio": "2026-09-22", "rit": "M-1-2026",
             "destinatario": "egon.schmidlin@cajbiobio.cl"},
            "2026-09-24", {},
            rutas["ruta_registro_pedidos"], rutas["ruta_registro_seguimiento"], rutas["ruta_registro_causas"],
            [], [], {},
        )

        assert llamadas_claude == []
        assert resultado == "insistencia"

    def test_acuerdo_con_externo_si_cuenta_la_respuesta_de_la_contraparte(self, tmp_path, monkeypatch):
        rutas = _registrar_pedido(tmp_path, tipo="acuerdo", fecha_envio="2026-09-22")
        monkeypatch.setattr(
            seguimiento.gmail_client, "leer_hilo",
            lambda thread_id, **k: [_mensaje(
                sender="Egon <egon.schmidlin@cajbiobio.cl>", fecha="Wed, 23 Sep 2026 10:00:00 -0300",
                cuerpo="Mi representada rechaza la propuesta",
            )],
        )
        monkeypatch.setattr(
            seguimiento.reasoning, "preguntar",
            lambda *a, **k: {"estado": "completo", "items_recibidos": [], "motivo": "rechaza"},
        )
        monkeypatch.setattr(seguimiento.bitacora_mod, "registrar", lambda *a, **k: None)

        resultado = seguimiento._procesar_pedido(
            {"thread_id": "thread-1", "tipo": "acuerdo", "fecha_envio": "2026-09-22", "rit": "M-1-2026",
             "destinatario": "egon.schmidlin@cajbiobio.cl"},
            "2026-09-24", {},
            rutas["ruta_registro_pedidos"], rutas["ruta_registro_seguimiento"], rutas["ruta_registro_causas"],
            [], [], {},
        )

        assert resultado == "completo"

    def test_anota_accion_si_claude_devuelve_error(self, tmp_path, monkeypatch):
        rutas = _registrar_pedido(tmp_path, fecha_envio="2026-09-01")
        monkeypatch.setattr(
            seguimiento.gmail_client, "leer_hilo",
            lambda thread_id, **k: [_mensaje(fecha="Wed, 16 Sep 2026 10:00:00 -0400", cuerpo="algo")],
        )
        monkeypatch.setattr(seguimiento.reasoning, "preguntar", lambda *a, **k: {"error": "no parseo"})

        acciones: list[dict] = []
        resultado = seguimiento._procesar_pedido(
            {"thread_id": "thread-1", "tipo": "documentos", "fecha_envio": "2026-09-01", "rit": "M-1-2026",
             "items_pedidos": ["Contrato de trabajo"]},
            "2026-09-16", {},
            rutas["ruta_registro_pedidos"], rutas["ruta_registro_seguimiento"], rutas["ruta_registro_causas"],
            acciones, [], {},
        )

        assert resultado == "sin_novedad"
        assert len(acciones) == 1
        assert "no parseo" in acciones[0]["que"]


class TestCorrerSinPedidosAbiertos:
    def test_devuelve_resumen_sin_pedidos(self, tmp_path, monkeypatch):
        rutas = _rutas(tmp_path)
        monkeypatch.setattr(registro_mod, "causas_con_borrador_pendiente", lambda ruta=None: [])
        monkeypatch.setattr(seguimiento.gmail_client, "obtener_o_crear_etiqueta", lambda *a, **k: "label-1")
        monkeypatch.setattr(seguimiento.gmail_client, "buscar_hilos", lambda *a, **k: [])

        contexto = {"fecha_hoy": "2026-09-16"}
        resumen = seguimiento.correr(
            contexto,
            ruta_registro_pedidos=rutas["ruta_registro_pedidos"],
            ruta_registro_causas=rutas["ruta_registro_causas"],
            ruta_registro_seguimiento=rutas["ruta_registro_seguimiento"],
        )

        assert resumen["fase"] == "seguimiento"
        assert resumen["titular"] == "Sin pedidos abiertos para revisar"
        assert resumen["items"] == []


class TestCorrerDePuntaAPunta:
    def test_una_insistencia_de_acuerdo(self, tmp_path, monkeypatch):
        rutas = _registrar_pedido(tmp_path, tipo="acuerdo", fecha_envio="2026-09-01")
        registro_mod.registrar_causa("M-1-2026", {}, ruta=rutas["ruta_registro_causas"])

        monkeypatch.setattr(registro_mod, "causas_con_borrador_pendiente", lambda ruta=None: [])
        monkeypatch.setattr(seguimiento.gmail_client, "obtener_o_crear_etiqueta", lambda *a, **k: "label-1")
        monkeypatch.setattr(seguimiento.gmail_client, "buscar_hilos", lambda *a, **k: [])
        monkeypatch.setattr(seguimiento.gmail_client, "leer_hilo", lambda thread_id, **k: [_mensaje(fecha="Fri, 01 Sep 2026 09:00:00 -0400", sender="nmunoz@gomezyriesco.cl")])
        monkeypatch.setattr(seguimiento.gmail_client, "listar_borradores_de_hilo", lambda *a, **k: [])
        monkeypatch.setattr(seguimiento.gmail_client, "crear_borrador", lambda *a, **k: {"id": "draft-1"})
        monkeypatch.setattr(seguimiento.bitacora_mod, "registrar", lambda *a, **k: None)

        contexto = {"fecha_hoy": "2026-09-16"}
        resumen = seguimiento.correr(
            contexto,
            ruta_registro_pedidos=rutas["ruta_registro_pedidos"],
            ruta_registro_causas=rutas["ruta_registro_causas"],
            ruta_registro_seguimiento=rutas["ruta_registro_seguimiento"],
        )

        assert resumen["titular"] == "1 insistencia creada"
        metricas = {m["etiqueta"]: m["valor"] for m in resumen["metricas"]}
        assert metricas["Insistencias creadas"] == 1
        assert metricas["Pedidos abiertos revisados"] == 1


class TestAvisosDesdeLoEnviado:
    NICO = "nmunoz@gomezyriesco.cl"

    def _evaluar(self, tmp_path, monkeypatch, hilo, hoy, fecha_envio="2026-09-15", extra_pedido=None):
        rutas = _registrar_pedido(tmp_path, tipo="acuerdo", fecha_envio=fecha_envio)
        monkeypatch.setattr(seguimiento.gmail_client, "crear_borrador", lambda *a, **k: {"id": "draft-1"})
        monkeypatch.setattr(seguimiento.bitacora_mod, "registrar", lambda *a, **k: None)
        pedido = {
            "thread_id": "thread-1", "tipo": "acuerdo", "fecha_envio": fecha_envio,
            "rit": "M-1-2026", "destinatario": "x@y.cl", "message_id": "msg-pedido", **(extra_pedido or {}),
        }
        acciones, items = [], []
        resultado = seguimiento._evaluar_insistencia(
            pedido, hoy, hilo, acciones, items,
            rutas["ruta_registro_pedidos"], rutas["ruta_registro_seguimiento"], rutas["ruta_registro_causas"],
        )
        return resultado, rutas, acciones

    def test_borrador_borrado_no_cuenta_como_aviso(self, tmp_path, monkeypatch):
        rutas = _registrar_pedido(tmp_path, tipo="acuerdo", fecha_envio="2026-09-15")
        registro_mod.registrar_aviso("thread-1", "causa-laboral", "2026-09-15", rit="M-1-2026", draft_id="borrador-viejo", ruta=rutas["ruta_registro_seguimiento"])
        hilo = [_mensaje(sender=self.NICO, fecha="Tue, 15 Sep 2026 10:00:00 -0400", id="msg-pedido")]

        resultado, rutas, _ = self._evaluar(tmp_path, monkeypatch, hilo, "2026-09-16")

        assert resultado == "insistencia"
        assert registro_mod.obtener_seguimiento("thread-1", ruta=rutas["ruta_registro_seguimiento"])["avisos"] == []

    def test_insistencia_manual_cuenta_como_aviso(self, tmp_path, monkeypatch):
        hilo = [
            _mensaje(sender=self.NICO, fecha="Tue, 15 Sep 2026 10:00:00 -0400", id="msg-pedido"),
            _mensaje(sender=self.NICO, fecha="Tue, 15 Sep 2026 18:00:00 -0400", id="msg-manual"),
        ]

        resultado, rutas, _ = self._evaluar(tmp_path, monkeypatch, hilo, "2026-09-16")

        assert resultado == "sin_novedad"
        avisos = registro_mod.obtener_seguimiento("thread-1", ruta=rutas["ruta_registro_seguimiento"])["avisos"]
        assert [a["message_id"] for a in avisos] == ["msg-manual"]

    def test_avisos_inflados_se_recalculan(self, tmp_path, monkeypatch):
        rutas = _registrar_pedido(tmp_path, tipo="acuerdo", fecha_envio="2026-09-15")
        for dia in ["2026-09-15", "2026-09-16", "2026-09-17", "2026-09-18", "2026-09-21"]:
            registro_mod.registrar_aviso("thread-1", "causa-laboral", dia, rit="M-1-2026", draft_id="d-" + dia, ruta=rutas["ruta_registro_seguimiento"])
        hilo = [
            _mensaje(sender=self.NICO, fecha="Tue, 15 Sep 2026 10:00:00 -0400", id="msg-pedido"),
            _mensaje(sender=self.NICO, fecha="Wed, 16 Sep 2026 10:00:00 -0400", id="a1"),
            _mensaje(sender=self.NICO, fecha="Thu, 17 Sep 2026 10:00:00 -0400", id="a2"),
        ]

        self._evaluar(tmp_path, monkeypatch, hilo, "2026-10-30")

        avisos = registro_mod.obtener_seguimiento("thread-1", ruta=rutas["ruta_registro_seguimiento"])["avisos"]
        assert len(avisos) == 2

    def test_borrador_pendiente_genera_accion_y_no_duplica(self, tmp_path, monkeypatch):
        rutas = _registrar_pedido(tmp_path, tipo="acuerdo", fecha_envio="2026-09-10")
        registro_mod.sincronizar_avisos("thread-1", [], "causa-laboral", "M-1-2026", {"fecha": "2026-09-10"}, ruta=rutas["ruta_registro_seguimiento"])
        hilo = [
            _mensaje(sender=self.NICO, fecha="Thu, 10 Sep 2026 10:00:00 -0400", id="msg-pedido"),
            _mensaje(sender=self.NICO, fecha="Thu, 10 Sep 2026 12:00:00 -0400", id="draft-msg", es_borrador=True),
        ]
        llamadas_crear = []
        monkeypatch.setattr(seguimiento.gmail_client, "crear_borrador", lambda *a, **k: llamadas_crear.append(1))

        resultado, _, acciones = self._evaluar(tmp_path, monkeypatch, hilo, "2026-09-15", fecha_envio="2026-09-10")

        assert resultado == "sin_novedad"
        assert llamadas_crear == []
        assert len(acciones) == 1
        assert "pendiente de enviar" in acciones[0]["que"]
        assert acciones[0]["urgencia"] == "media"


class TestBorradorIntegradoACadena:
    def test_cc_sale_solo_del_ultimo_enviado_propio(self):
        hilo = [
            _mensaje(sender="nmunoz@gomezyriesco.cl", fecha="Thu, 10 Sep 2026 10:00:00 -0400",
                     to="viejo@otro.cl, a@x.cl", id="m1"),
            _mensaje(sender="nmunoz@gomezyriesco.cl", fecha="Mon, 14 Sep 2026 10:00:00 -0400",
                     to="Daniela <d@smu.cl>", cc="cc@smu.cl", id="m2"),
            _mensaje(sender="contraparte@externo.cl", fecha="Tue, 15 Sep 2026 10:00:00 -0400", id="m3"),
        ]
        destinatarios = seguimiento._destinatarios_pedido({"destinatario": "d@smu.cl"}, hilo)
        assert destinatarios["para"] == "d@smu.cl"
        assert destinatarios["cc"] == "cc@smu.cl"

    def test_saludo_usa_nombre_visible_del_ultimo_envio(self):
        hilo = [_mensaje(sender="nmunoz@gomezyriesco.cl", fecha="Mon, 14 Sep 2026 10:00:00 -0400",
                         to="Daniela Sánchez <dsanchezv@smu.cl>", id="m2")]
        assert seguimiento._nombre_para_saludo_desde_hilo("dsanchezv@smu.cl", hilo) == "Daniela"

    def test_borrador_de_insistencia_incluye_bloque_citado(self, monkeypatch):
        capturados = []
        monkeypatch.setattr(seguimiento.gmail_client, "crear_borrador", lambda *a, **k: capturados.append(a) or {"id": "d1"})
        hilo = [
            _mensaje(sender="nmunoz@gomezyriesco.cl", fecha="Mon, 14 Sep 2026 10:00:00 -0400", to="d@smu.cl", id="m2"),
            _mensaje(sender="d@smu.cl", fecha="Tue, 15 Sep 2026 10:00:00 -0400", cuerpo="Recibido", id="m3"),
        ]
        seguimiento._crear_insistencia({"thread_id": "thread-1", "destinatario": "d@smu.cl"}, "documentos", hilo)
        assert "gmail_quote" in capturados[0][2]


class TestBorradorDocumentosBorradoOReescrito:
    NICO = "nmunoz@gomezyriesco.cl"
    CREADO = datetime.now(seguimiento_mod.ZONA_NEGOCIO) - timedelta(days=2)

    def _verificar(self, tmp_path, monkeypatch, causa_extra, hilo, buscar=None, leer=None):
        ruta_causas = tmp_path / "registro_causas.json"
        ruta_pedidos = tmp_path / "registro_pedidos.json"
        registro_mod.registrar_causa(
            "M-1-2026",
            {"thread_id": "thread-1", "borrador_documentos_draft_id": "draft-1",
             "documentos_solicitados": ["Contrato"], **causa_extra},
            ruta=ruta_causas,
        )
        monkeypatch.setattr(seguimiento.gmail_client, "borrador_existe", lambda draft_id: False)
        monkeypatch.setattr(seguimiento.gmail_client, "buscar_hilos", buscar or (lambda *a, **k: []))
        if leer:
            monkeypatch.setattr(seguimiento.gmail_client, "leer_hilo", leer)
        acciones = []
        resultado = seguimiento._verificar_borradores_pendientes(ruta_causas, ruta_pedidos, {"thread-1": hilo}, acciones)
        return resultado, ruta_causas, ruta_pedidos, acciones

    def test_mensaje_propio_anterior_al_borrador_no_cuenta_como_envio(self, tmp_path, monkeypatch):
        antes = format_datetime(self.CREADO - timedelta(days=1))
        hilo = [_mensaje(sender=self.NICO, fecha=antes, id="viejo")]

        resultado, ruta_causas, ruta_pedidos, acciones = self._verificar(
            tmp_path, monkeypatch, {"borrador_documentos_creado": self.CREADO.isoformat()}, hilo,
        )

        assert resultado["enviados"] == []
        assert registro_mod.obtener_pedido("thread-1", ruta=ruta_pedidos) is None
        causa = registro_mod.obtener_causa("M-1-2026", ruta=ruta_causas)
        assert causa["borrador_documentos_buscar_envio_desde"] == self.CREADO.isoformat()
        assert len(acciones) == 1
        assert acciones[0]["urgencia"] == "media"

    def test_reescrito_como_correo_nuevo_se_detecta(self, tmp_path, monkeypatch):
        antes = format_datetime(self.CREADO - timedelta(days=1))
        despues = format_datetime(self.CREADO + timedelta(days=1))
        hilo = [_mensaje(sender=self.NICO, fecha=antes, id="viejo")]
        otro_hilo = [_mensaje(sender=self.NICO, fecha=despues, id="nuevo", subject="Consulta documentos")]

        resultado, _, ruta_pedidos, _ = self._verificar(
            tmp_path, monkeypatch, {"borrador_documentos_creado": self.CREADO.isoformat()}, hilo,
            buscar=lambda *a, **k: [{"id": "thread-otro"}],
            leer=lambda thread_id, **k: otro_hilo,
        )

        assert resultado["enviados"][0]["thread_id"] == "thread-otro"
        pedido = registro_mod.obtener_pedido("thread-otro", ruta=ruta_pedidos)
        assert pedido["origen"] == "borrador_enviado"
        assert pedido["items_pedidos"] == ["Contrato"]

    def test_sin_envio_detectado_avisa_y_queda_pendiente_de_busqueda(self, tmp_path, monkeypatch):
        hilo = []

        resultado, ruta_causas, _, acciones = self._verificar(
            tmp_path, monkeypatch, {"borrador_documentos_creado": self.CREADO.isoformat()}, hilo,
        )

        assert resultado["enviados"] == []
        assert "no se detectó el envío" in acciones[0]["que"]
        assert registro_mod.causas_buscando_envio_borrador(ruta=ruta_causas)[0]["rit"] == "M-1-2026"

    def test_causa_legada_sin_fecha_de_borrador_no_rompe(self, tmp_path, monkeypatch):
        hilo = [_mensaje(sender=self.NICO, fecha=format_datetime(self.CREADO - timedelta(days=1)), id="viejo")]

        resultado, _, _, acciones = self._verificar(tmp_path, monkeypatch, {}, hilo)

        assert resultado["enviados"] == []
        assert len(acciones) == 1


class TestPedidosSinItemsYReapertura:
    NICO = "nmunoz@gomezyriesco.cl"

    def test_alta_por_etiqueta_extrae_los_items_de_la_lista(self, tmp_path, monkeypatch):
        ruta_pedidos = tmp_path / "registro_pedidos.json"
        hilo = [_mensaje(sender=self.NICO, fecha="Tue, 01 Sep 2026 10:00:00 -0400", cuerpo="1. Contrato\n2. Finiquito", id="p1")]
        monkeypatch.setattr(seguimiento.gmail_client, "obtener_o_crear_etiqueta", lambda *a, **k: "label-1")
        monkeypatch.setattr(seguimiento.gmail_client, "buscar_hilos", lambda *a, **k: [{"id": "thread-1"}])
        monkeypatch.setattr(seguimiento.gmail_client, "leer_hilo", lambda thread_id, **k: hilo)

        resultado = seguimiento._pedidos_desde_etiqueta(ruta_pedidos)

        assert resultado["creados"][0]["items_pedidos"] == ["Contrato", "Finiquito"]
        assert registro_mod.obtener_pedido("thread-1", ruta=ruta_pedidos)["items_pedidos"] == ["Contrato", "Finiquito"]

    def test_parcial_sin_items_no_cierra_ni_recuerda(self, tmp_path, monkeypatch):
        rutas = _registrar_pedido(tmp_path, items_pedidos=[], message_id="msg-pedido")
        hilo = [
            _mensaje(sender=self.NICO, fecha="Tue, 01 Sep 2026 10:00:00 -0400", id="msg-pedido"),
            _mensaje(sender="contraparte@externo.cl", fecha="Wed, 02 Sep 2026 10:00:00 -0400", id="resp"),
        ]
        monkeypatch.setattr(seguimiento, "_clasificar_pedido", lambda pedido, posteriores: {"estado": "parcial", "items_recibidos": [], "motivo": ""})
        llamadas_crear = []
        monkeypatch.setattr(seguimiento.gmail_client, "crear_borrador", lambda *a, **k: llamadas_crear.append(1))
        pedido = registro_mod.obtener_pedido("thread-1", ruta=rutas["ruta_registro_pedidos"])
        acciones, items = [], []

        resultado = seguimiento._procesar_pedido(
            pedido, "2026-09-03", {}, rutas["ruta_registro_pedidos"], rutas["ruta_registro_seguimiento"],
            rutas["ruta_registro_causas"], acciones, items, {"thread-1": hilo},
        )

        assert resultado == "sin_novedad"
        assert llamadas_crear == []
        assert "sin lista de documentos" in acciones[0]["que"]
        assert registro_mod.obtener_pedido("thread-1", ruta=rutas["ruta_registro_pedidos"])["estado"] == "esperando"

    def test_reetiquetado_reabre_pedido_cerrado_con_envio_nuevo(self, tmp_path, monkeypatch):
        ruta_pedidos = tmp_path / "registro_pedidos.json"
        registro_mod.registrar_pedido("thread-1", {
            "rit": "M-1-2026", "tipo": "documentos", "message_id": "msg-viejo", "fecha_envio": "2026-09-01",
            "momento_envio": "2026-09-01T10:00:00-04:00", "estado": "completo", "items_recibidos": ["Contrato"],
            "origen": "etiqueta",
        }, ruta=ruta_pedidos)
        hilo = [
            _mensaje(sender=self.NICO, fecha="Tue, 01 Sep 2026 10:00:00 -0400", cuerpo="1. Contrato", id="msg-viejo"),
            _mensaje(sender=self.NICO, fecha="Thu, 10 Sep 2026 10:00:00 -0400", cuerpo="1. Liquidaciones", id="msg-nuevo"),
        ]
        monkeypatch.setattr(seguimiento.gmail_client, "obtener_o_crear_etiqueta", lambda *a, **k: "label-1")
        monkeypatch.setattr(seguimiento.gmail_client, "buscar_hilos", lambda *a, **k: [{"id": "thread-1"}])
        monkeypatch.setattr(seguimiento.gmail_client, "leer_hilo", lambda thread_id, **k: hilo)

        seguimiento._pedidos_desde_etiqueta(ruta_pedidos)

        pedido = registro_mod.obtener_pedido("thread-1", ruta=ruta_pedidos)
        assert pedido["estado"] == "esperando"
        assert pedido["message_id"] == "msg-nuevo"
        assert pedido["items_recibidos"] == []
        assert pedido["items_pedidos"] == ["Liquidaciones"]
