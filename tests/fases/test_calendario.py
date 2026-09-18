import sys
import types
from datetime import date
from pathlib import Path

from gestion_causas import registro as registro_mod
from gestion_causas.fases import calendario


def _stub_fases_smu(monkeypatch, *, generar_resumen=None, agregar_causa=None):
    """`fases/smu.py` engancha `actualizar_informe_juicios.py` (repo aparte,
    no instalado en este entorno de tests) apenas se importa. `calendario.py`
    lo importa de forma diferida solo cuando de verdad va a escribir una fila
    del Excel — para testear ese camino sin esa dependencia externa, se
    registra un módulo falso en sys.modules con los símbolos que
    `_agregar_fila_excel` necesita."""
    modulo_falso = types.ModuleType("gestion_causas.fases.smu")
    modulo_falso.RUTA_EXCEL_JUICIOS = "excel-falso.xlsx"
    modulo_falso._generar_resumen_narrativo = generar_resumen or (lambda campos, cuerpo: {"resumen": "texto"})
    modulo_falso.agregar_causa = agregar_causa or (lambda ruta, datos: None)
    monkeypatch.setitem(sys.modules, "gestion_causas.fases.smu", modulo_falso)


def _evento(fecha=date(2026, 9, 21), resumen="Audiencia única M-1-2026 Perez con Alvi", rit="M-1-2026", empresa="Alvi"):
    return {"fecha": fecha, "resumen": resumen, "empresa_detectada": empresa, "rit_detectado": rit}


def _mensaje(sender="demandas@smu.cl", cuerpo="", fecha="Tue, 01 Sep 2026 10:00:00 -0400", subject="Causa laboral", adjuntos=None):
    return {
        "id": "msg-1", "thread_id": "thread-1", "subject": subject, "sender": sender,
        "to": "nmunoz@gomezyriesco.cl", "cc": "", "date": fecha, "cuerpo_texto": cuerpo,
        "adjuntos": adjuntos or [],
    }


class TestEsLunes:
    def test_usa_es_lunes_del_contexto_si_esta_presente(self):
        assert calendario._es_lunes({"es_lunes": True}) is True
        assert calendario._es_lunes({"es_lunes": False}) is False

    def test_calcula_solo_si_falta_en_el_contexto(self, monkeypatch):
        import gestion_causas.fases.calendario as mod
        monkeypatch.setattr(mod, "date", type("D", (), {"today": staticmethod(lambda: date(2026, 9, 21))}))
        assert mod._es_lunes({}) is True  # 2026-09-21 es lunes


class TestCorrerFueraDeLunes:
    def test_devuelve_mensaje_corto_sin_ejecutar_nada(self, monkeypatch):
        llamado = []
        monkeypatch.setattr(calendario, "_eventos_candidatos", lambda ctx: llamado.append(1))

        resumen = calendario.correr({"es_lunes": False})

        assert resumen == {
            "fase": "calendario",
            "resultado": "No corresponde hoy (Fase 0 solo corre los lunes).",
            "error": None,
        }
        assert llamado == []


class TestEventosCandidatos:
    def test_usa_cache_cuando_esta_disponible(self, tmp_path, monkeypatch):
        llamadas = []
        monkeypatch.setattr(
            calendario.calendar_client, "eventos_empresas_interes_desde_cache",
            lambda desde, hasta, ruta: llamadas.append(ruta) or [_evento()],
        )
        eventos = calendario._eventos_candidatos({"cache_calendario": {"ruta": str(tmp_path / "cache.json")}})
        assert len(eventos) == 1
        assert llamadas == [str(tmp_path / "cache.json")]

    def test_cae_a_la_api_en_vivo_si_el_cache_falla(self, monkeypatch):
        monkeypatch.setattr(
            calendario.calendar_client, "eventos_empresas_interes_desde_cache",
            lambda *a, **k: (_ for _ in ()).throw(ValueError("no alcanza")),
        )
        monkeypatch.setattr(calendario.calendar_client, "eventos_empresas_interes", lambda desde, hasta: [_evento()])
        eventos = calendario._eventos_candidatos({"cache_calendario": {"ruta": "algo.json"}})
        assert len(eventos) == 1

    def test_sin_contexto_llama_a_la_api_en_vivo(self, monkeypatch):
        monkeypatch.setattr(calendario.calendar_client, "eventos_empresas_interes", lambda desde, hasta: [_evento()])
        eventos = calendario._eventos_candidatos({})
        assert len(eventos) == 1


class TestProcesarEvento:
    def test_causa_ya_registrada_no_hace_nada(self, tmp_path):
        ruta = tmp_path / "registro_causas.json"
        registro_mod.registrar_causa("M-1-2026", {"empresa": "Alvi"}, ruta=ruta)
        resultado = calendario._procesar_evento("M-1-2026", _evento(), ruta, [], [])
        assert resultado is None

    def test_evento_no_es_audiencia_se_anota_en_notas(self, tmp_path):
        ruta = tmp_path / "registro_causas.json"
        notas = []
        evento = _evento(resumen="Vence plazo para contestar M-1-2026")
        resultado = calendario._procesar_evento("M-1-2026", evento, ruta, [], notas)
        assert resultado is None
        assert len(notas) == 1
        assert notas[0]["tipo"] == "evento_no_es_audiencia"

    def test_evento_ambiguo_se_anota_en_notas(self, tmp_path):
        ruta = tmp_path / "registro_causas.json"
        notas = []
        evento = _evento(resumen="Reunion con cliente M-1-2026")
        resultado = calendario._procesar_evento("M-1-2026", evento, ruta, [], notas)
        assert resultado is None
        assert len(notas) == 1

    def test_audiencia_unica_crea_carpeta_y_guarda_demanda(self, tmp_path, monkeypatch):
        ruta = tmp_path / "registro_causas.json"
        carpeta_destino = tmp_path / "Perez con Alvi M-1-2026"

        monkeypatch.setattr(calendario.gmail_client, "buscar_hilos", lambda rit, **k: [{"id": "thread-1"}])
        monkeypatch.setattr(
            calendario.gmail_client, "leer_hilo",
            lambda thread_id, **k: [_mensaje(cuerpo="Rit: M-1-2026\nTribunal: X\nCuantia: $100\nDemandante: Juan Perez",
                                              adjuntos=[{"filename": "demanda.pdf", "attachment_id": "a1"}])],
        )
        monkeypatch.setattr(calendario.gmail_client, "descargar_adjunto", lambda *a, **k: b"%PDF-1.4 contenido")
        monkeypatch.setattr(calendario.carpetas_mod, "es_adjunto_firma", lambda *a, **k: False)
        monkeypatch.setattr(calendario.carpetas_mod, "buscar_carpeta_existente_por_rit", lambda rit: None)
        monkeypatch.setattr(calendario.carpetas_mod, "crear_carpeta_causa", lambda apellido, empresa, rit: carpeta_destino)
        monkeypatch.setattr(calendario.carpetas_mod, "guardar_adjunto", lambda carpeta, nombre, contenido: {"guardado": True, "ruta": str(carpeta / nombre)})
        monkeypatch.setattr(calendario.gmail_client, "obtener_o_crear_etiqueta", lambda *a, **k: "label-1")
        monkeypatch.setattr(calendario.gmail_client, "aplicar_etiqueta_a_hilo", lambda *a, **k: None)
        monkeypatch.setattr(calendario.bitacora_mod, "registrar", lambda *a, **k: None)
        # Preunic no tiene fila de Excel (EMPRESAS_SIN_EXCEL) -> no debería
        # intentar importar fases.smu para este caso.
        evento = _evento(empresa="Preunic")

        resultado = calendario._procesar_evento("M-1-2026", evento, ruta, [], [])

        assert resultado is not None
        assert "Audiencia Única" in resultado["detalle"]
        assert "demanda guardada" in resultado["detalle"]
        assert "Excel no aplica" in resultado["detalle"]
        entrada = registro_mod.obtener_causa("M-1-2026", ruta=ruta)
        assert entrada["carpeta"] == str(carpeta_destino)
        assert entrada["tiene_demanda"] is True
        assert entrada["thread_id"] == "thread-1"

    def test_audiencia_de_juicio_no_crea_carpeta(self, tmp_path, monkeypatch):
        ruta = tmp_path / "registro_causas.json"
        monkeypatch.setattr(calendario.gmail_client, "buscar_hilos", lambda rit, **k: [])
        monkeypatch.setattr(calendario.bitacora_mod, "registrar", lambda *a, **k: None)
        llamadas_carpeta = []
        monkeypatch.setattr(calendario.carpetas_mod, "crear_carpeta_causa", lambda *a, **k: llamadas_carpeta.append(1))

        evento = _evento(resumen="Audiencia de Juicio M-1-2026", empresa="Preunic")
        resultado = calendario._procesar_evento("M-1-2026", evento, ruta, [], [])

        assert resultado is not None
        assert "falta demanda" not in resultado["detalle"]  # Juicio ni siquiera intenta la carpeta
        assert llamadas_carpeta == []
        entrada = registro_mod.obtener_causa("M-1-2026", ruta=ruta)
        assert entrada["carpeta"] is None

    def test_sin_hilo_de_origen_registra_causa_igual_y_anota_nota(self, tmp_path, monkeypatch):
        ruta = tmp_path / "registro_causas.json"
        monkeypatch.setattr(calendario.gmail_client, "buscar_hilos", lambda rit, **k: [])
        monkeypatch.setattr(calendario.carpetas_mod, "buscar_carpeta_existente_por_rit", lambda rit: None)
        monkeypatch.setattr(calendario.carpetas_mod, "crear_carpeta_causa", lambda apellido, empresa, rit: tmp_path / "X")
        monkeypatch.setattr(calendario.bitacora_mod, "registrar", lambda *a, **k: None)

        notas = []
        evento = _evento(empresa="Preunic")
        resultado = calendario._procesar_evento("M-1-2026", evento, ruta, [], notas)

        assert resultado is not None
        assert any(n["tipo"] == "sin_hilo_origen" for n in notas)
        entrada = registro_mod.obtener_causa("M-1-2026", ruta=ruta)
        assert entrada["thread_id"] is None

    def test_excel_se_actualiza_cuando_aplica_y_hay_datos_suficientes(self, tmp_path, monkeypatch):
        ruta = tmp_path / "registro_causas.json"
        monkeypatch.setattr(calendario.gmail_client, "buscar_hilos", lambda rit, **k: [{"id": "thread-1"}])
        monkeypatch.setattr(
            calendario.gmail_client, "leer_hilo",
            lambda thread_id, **k: [_mensaje(cuerpo="Rit: M-1-2026\nTribunal: X\nCuantia: $100\nDemandante: Juan Perez")],
        )
        monkeypatch.setattr(calendario.carpetas_mod, "buscar_carpeta_existente_por_rit", lambda rit: None)
        monkeypatch.setattr(calendario.carpetas_mod, "crear_carpeta_causa", lambda apellido, empresa, rit: tmp_path / "X")
        monkeypatch.setattr(calendario.gmail_client, "obtener_o_crear_etiqueta", lambda *a, **k: "label-1")
        monkeypatch.setattr(calendario.gmail_client, "aplicar_etiqueta_a_hilo", lambda *a, **k: None)
        monkeypatch.setattr(calendario.bitacora_mod, "registrar", lambda *a, **k: None)

        llamadas_excel = []
        _stub_fases_smu(monkeypatch, agregar_causa=lambda ruta, datos: llamadas_excel.append(datos))

        evento = _evento(empresa="Alvi")  # Alvi sí tiene fila de Excel
        resultado = calendario._procesar_evento("M-1-2026", evento, ruta, [], [])

        assert len(llamadas_excel) == 1
        assert llamadas_excel[0]["causa"] == "M-1-2026"
        assert "Excel actualizado" in resultado["detalle"]

    def test_excel_permission_error_anota_accion_urgente(self, tmp_path, monkeypatch):
        ruta = tmp_path / "registro_causas.json"
        monkeypatch.setattr(calendario.gmail_client, "buscar_hilos", lambda rit, **k: [{"id": "thread-1"}])
        monkeypatch.setattr(
            calendario.gmail_client, "leer_hilo",
            lambda thread_id, **k: [_mensaje(cuerpo="Rit: M-1-2026\nTribunal: X\nCuantia: $100\nDemandante: Juan Perez")],
        )
        monkeypatch.setattr(calendario.carpetas_mod, "buscar_carpeta_existente_por_rit", lambda rit: None)
        monkeypatch.setattr(calendario.carpetas_mod, "crear_carpeta_causa", lambda apellido, empresa, rit: tmp_path / "X")
        monkeypatch.setattr(calendario.gmail_client, "obtener_o_crear_etiqueta", lambda *a, **k: "label-1")
        monkeypatch.setattr(calendario.gmail_client, "aplicar_etiqueta_a_hilo", lambda *a, **k: None)
        monkeypatch.setattr(calendario.bitacora_mod, "registrar", lambda *a, **k: None)

        def falla(*a, **k):
            raise PermissionError()
        _stub_fases_smu(monkeypatch, agregar_causa=falla)

        acciones: list[dict] = []
        evento = _evento(empresa="Alvi")
        resultado = calendario._procesar_evento("M-1-2026", evento, ruta, acciones, [])

        assert len(acciones) == 1
        assert acciones[0]["urgencia"] == "alta"
        assert "Excel pendiente" in resultado["detalle"]

    def test_no_intenta_excel_si_cuadro_incompleto(self, tmp_path, monkeypatch):
        ruta = tmp_path / "registro_causas.json"
        monkeypatch.setattr(calendario.gmail_client, "buscar_hilos", lambda rit, **k: [{"id": "thread-1"}])
        monkeypatch.setattr(
            calendario.gmail_client, "leer_hilo",
            lambda thread_id, **k: [_mensaje(cuerpo="Sin campos reconocibles")],
        )
        monkeypatch.setattr(calendario.carpetas_mod, "buscar_carpeta_existente_por_rit", lambda rit: None)
        monkeypatch.setattr(calendario.carpetas_mod, "crear_carpeta_causa", lambda apellido, empresa, rit: tmp_path / "X")
        monkeypatch.setattr(calendario.gmail_client, "obtener_o_crear_etiqueta", lambda *a, **k: "label-1")
        monkeypatch.setattr(calendario.gmail_client, "aplicar_etiqueta_a_hilo", lambda *a, **k: None)
        monkeypatch.setattr(calendario.bitacora_mod, "registrar", lambda *a, **k: None)

        evento = _evento(empresa="Alvi")
        resultado = calendario._procesar_evento("M-1-2026", evento, ruta, [], [])

        assert "Excel pendiente" in resultado["detalle"]


class TestCorrerDePuntaAPunta:
    def test_sin_eventos(self, monkeypatch):
        monkeypatch.setattr(calendario, "_eventos_candidatos", lambda ctx: [])
        resumen = calendario.correr({"es_lunes": True})
        assert resumen["titular"] == "Sin eventos nuevos de las empresas de interés"
        assert resumen["metricas"][0] == {"etiqueta": "Eventos revisados", "valor": 0}

    def test_evento_sin_rit_se_cuenta_y_anota(self, monkeypatch, tmp_path):
        evento_sin_rit = _evento(rit=None, resumen="Audiencia única sin RIT reconocible")
        monkeypatch.setattr(calendario, "_eventos_candidatos", lambda ctx: [evento_sin_rit])

        resumen = calendario.correr({"es_lunes": True}, ruta_registro_causas=tmp_path / "registro_causas.json")

        assert resumen["metricas"][2] == {"etiqueta": "Eventos sin RIT reconocible", "valor": 1}
        assert len(resumen["notas"]) == 1
        assert resumen["items"] == []

    def test_una_causa_nueva_de_alta(self, monkeypatch, tmp_path):
        ruta = tmp_path / "registro_causas.json"
        monkeypatch.setattr(calendario, "_eventos_candidatos", lambda ctx: [_evento(empresa="Preunic")])
        monkeypatch.setattr(calendario.gmail_client, "buscar_hilos", lambda rit, **k: [])
        monkeypatch.setattr(calendario.carpetas_mod, "buscar_carpeta_existente_por_rit", lambda rit: None)
        monkeypatch.setattr(calendario.carpetas_mod, "crear_carpeta_causa", lambda apellido, empresa, rit: tmp_path / "X")
        monkeypatch.setattr(calendario.bitacora_mod, "registrar", lambda *a, **k: None)

        resumen = calendario.correr({"es_lunes": True}, ruta_registro_causas=ruta)

        assert resumen["metricas"][1] == {"etiqueta": "Causas nuevas dadas de alta", "valor": 1}
        # No se encontró hilo de origen (buscar_hilos devuelve []), así que
        # no hay "demandante" en los campos extraídos del cuadro-resumen.
        assert resumen["titular"] == "1 causa nueva detectada por calendario (con Preunic)"
