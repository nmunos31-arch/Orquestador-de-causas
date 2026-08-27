from datetime import date

import pytest

from gestion_causas.registro import (
    buscar_eerr_reusable,
    causa_ya_registrada,
    causas_con_borrador_pendiente,
    causas_para_goteo,
    extraer_rit,
    normalizar_rit,
    obtener_causa,
    obtener_seguimiento,
    puede_insistir,
    registrar_aviso,
    registrar_causa,
    registrar_eerr_recibido,
)


def _feriados_sin_feriados(tmp_path):
    import json

    ruta = tmp_path / "feriados.json"
    ruta.write_text(json.dumps({"2026": []}), encoding="utf-8")
    return ruta


class TestNormalizarRit:
    def test_quita_espacios_y_normaliza_guion(self):
        assert normalizar_rit(" O‑348‑2026 ") == "O-348-2026"

    def test_ignora_mayusculas(self):
        assert normalizar_rit("o-348-2026") == normalizar_rit("O-348-2026")


class TestExtraerRit:
    def test_encuentra_rit_en_texto_libre(self):
        assert extraer_rit('Audiencia única "Rebolledo con Salcobrand" M-637-2026') == "M-637-2026"

    def test_encuentra_rit_con_guion_no_separable(self):
        assert extraer_rit("Audiencia Unica RIT M‑643‑2026 Iturriaga con Rendic") == "M-643-2026"

    def test_devuelve_none_si_no_hay_rit(self):
        assert extraer_rit("Reunión equipo semanal") is None

    def test_normaliza_letra_a_mayuscula(self):
        assert extraer_rit("causa m-637-2026") == "M-637-2026"


class TestRegistrarCausa:
    def test_alta_causa_nueva(self, tmp_path):
        ruta = tmp_path / "registro_causas.json"
        assert not causa_ya_registrada("O-348-2026", ruta)

        registrar_causa("O-348-2026", {"empresa": "Servicios Logísticos Santiago"}, ruta)

        assert causa_ya_registrada("O-348-2026", ruta)
        entrada = obtener_causa("O-348-2026", ruta)
        assert entrada["empresa"] == "Servicios Logísticos Santiago"
        assert entrada["rit"] == "O-348-2026"

    def test_rit_duplicado_no_crea_dos_entradas(self, tmp_path):
        ruta = tmp_path / "registro_causas.json"
        registrar_causa("O-88-2026", {"empresa": "Rendic Hermanos"}, ruta)
        registrar_causa("o‑88‑2026", {"empresa": "Rendic Hermanos"}, ruta)

        import json

        contenido = json.loads(ruta.read_text(encoding="utf-8"))
        assert len(contenido) == 1

    def test_ceco_que_llega_tarde_actualiza_sin_perder_lo_anterior(self, tmp_path):
        ruta = tmp_path / "registro_causas.json"
        registrar_causa("M-6-2026", {"empresa": "Rendic Hermanos", "tiene_ceco": False}, ruta)
        registrar_causa("M-6-2026", {"ceco": "1234", "tiene_ceco": True}, ruta)

        entrada = obtener_causa("M-6-2026", ruta)
        assert entrada["empresa"] == "Rendic Hermanos"
        assert entrada["ceco"] == "1234"
        assert entrada["tiene_ceco"] is True

    def test_causa_inexistente_devuelve_none(self, tmp_path):
        ruta = tmp_path / "registro_causas.json"
        assert obtener_causa("M-9999-2026", ruta) is None


class TestCausasConBorradorPendiente:
    def test_incluye_causa_con_draft_id_seteado(self, tmp_path):
        ruta = tmp_path / "registro_causas.json"
        registrar_causa("M-1-2026", {"empresa": "Alvi", "borrador_documentos_draft_id": "d1"}, ruta)

        pendientes = causas_con_borrador_pendiente(ruta)

        assert len(pendientes) == 1
        assert pendientes[0]["rit"] == "M-1-2026"

    def test_excluye_causa_sin_draft_id(self, tmp_path):
        ruta = tmp_path / "registro_causas.json"
        registrar_causa("M-2-2026", {"empresa": "Alvi"}, ruta)

        assert causas_con_borrador_pendiente(ruta) == []

    def test_excluye_causa_con_draft_id_limpiado_a_none(self, tmp_path):
        ruta = tmp_path / "registro_causas.json"
        registrar_causa("M-3-2026", {"empresa": "Alvi", "borrador_documentos_draft_id": "d1"}, ruta)
        registrar_causa("M-3-2026", {"borrador_documentos_draft_id": None}, ruta)

        assert causas_con_borrador_pendiente(ruta) == []


class TestReusoEerr:
    def test_reusa_dentro_de_3_meses(self, tmp_path):
        ruta = tmp_path / "registro_ceco.json"
        registrar_eerr_recibido("1234", date(2026, 1, 15), "M-8-2026", ruta)

        reusable = buscar_eerr_reusable("1234", date(2026, 3, 1), dias_tolerancia=90, ruta=ruta)
        assert reusable is not None
        assert reusable["rit_causa"] == "M-8-2026"

    def test_no_reusa_fuera_de_3_meses(self, tmp_path):
        ruta = tmp_path / "registro_ceco.json"
        registrar_eerr_recibido("1234", date(2026, 1, 1), "M-8-2026", ruta)

        reusable = buscar_eerr_reusable("1234", date(2026, 8, 1), dias_tolerancia=90, ruta=ruta)
        assert reusable is None

    def test_ceco_distinto_no_se_confunde(self, tmp_path):
        ruta = tmp_path / "registro_ceco.json"
        registrar_eerr_recibido("1234", date(2026, 1, 15), "M-8-2026", ruta)

        reusable = buscar_eerr_reusable("5678", date(2026, 1, 20), dias_tolerancia=90, ruta=ruta)
        assert reusable is None

    def test_ceco_sin_registro_devuelve_none(self, tmp_path):
        ruta = tmp_path / "registro_ceco.json"
        assert buscar_eerr_reusable(None, date(2026, 1, 1), ruta=ruta) is None

    def test_elige_el_mas_cercano_si_hay_varios(self, tmp_path):
        ruta = tmp_path / "registro_ceco.json"
        registrar_eerr_recibido("1234", date(2026, 1, 1), "M-1-2026", ruta)
        registrar_eerr_recibido("1234", date(2026, 3, 1), "M-2-2026", ruta)

        reusable = buscar_eerr_reusable("1234", date(2026, 3, 10), dias_tolerancia=90, ruta=ruta)
        assert reusable["rit_causa"] == "M-2-2026"


class TestCausasParaGoteo:
    def test_incluye_causa_sin_fecha_audiencia(self, tmp_path):
        ruta = tmp_path / "registro_causas.json"
        registrar_causa("M-1-2026", {"empresa": "Alvi"}, ruta)

        activas = causas_para_goteo(hoy=date(2026, 8, 12), ruta=ruta)
        assert len(activas) == 1
        assert activas[0]["rit"] == "M-1-2026"

    def test_incluye_causa_con_audiencia_futura(self, tmp_path):
        ruta = tmp_path / "registro_causas.json"
        registrar_causa("M-1-2026", {"fecha_audiencia": "2026-09-01"}, ruta)

        activas = causas_para_goteo(hoy=date(2026, 8, 12), ruta=ruta)
        assert len(activas) == 1

    def test_incluye_causa_con_audiencia_reciente_dentro_de_la_ventana(self, tmp_path):
        ruta = tmp_path / "registro_causas.json"
        registrar_causa("M-1-2026", {"fecha_audiencia": "2026-07-01"}, ruta)  # 42 días antes

        activas = causas_para_goteo(hoy=date(2026, 8, 12), dias_ventana_post_audiencia=60, ruta=ruta)
        assert len(activas) == 1

    def test_excluye_causa_con_audiencia_muy_antigua(self, tmp_path):
        ruta = tmp_path / "registro_causas.json"
        registrar_causa("M-1-2026", {"fecha_audiencia": "2026-01-01"}, ruta)  # muy pasada

        activas = causas_para_goteo(hoy=date(2026, 8, 12), dias_ventana_post_audiencia=60, ruta=ruta)
        assert len(activas) == 0

    def test_excluye_causa_cerrada_aunque_no_tenga_fecha_audiencia(self, tmp_path):
        ruta = tmp_path / "registro_causas.json"
        registrar_causa("M-1-2026", {"causa_cerrada": True}, ruta)

        activas = causas_para_goteo(hoy=date(2026, 8, 12), ruta=ruta)
        assert len(activas) == 0


class TestRegistrarAviso:
    def test_primer_aviso_crea_entrada_con_un_aviso(self, tmp_path):
        ruta = tmp_path / "registro_seguimiento.json"
        entrada = registrar_aviso("t1", "acuerdo-daniela", "2026-08-19", rit="O-348-2026", draft_id="d1", ruta=ruta)

        assert entrada["tipo"] == "acuerdo-daniela"
        assert entrada["rit"] == "O-348-2026"
        assert len(entrada["avisos"]) == 1
        assert entrada["avisos"][0] == {"n": 1, "fecha": "2026-08-19", "draft_id": "d1"}

    def test_segundo_aviso_se_acumula_sin_perder_el_primero(self, tmp_path):
        ruta = tmp_path / "registro_seguimiento.json"
        registrar_aviso("t1", "documentos", "2026-08-19", ruta=ruta)
        entrada = registrar_aviso("t1", "documentos", "2026-08-21", draft_id="d2", ruta=ruta)

        assert len(entrada["avisos"]) == 2
        assert entrada["avisos"][1] == {"n": 2, "fecha": "2026-08-21", "draft_id": "d2"}

    def test_obtener_seguimiento_de_hilo_inexistente_es_none(self, tmp_path):
        ruta = tmp_path / "registro_seguimiento.json"
        assert obtener_seguimiento("no-existe", ruta) is None


class TestPuedeInsistir:
    def test_sin_avisos_previos_siempre_puede(self, tmp_path):
        ruta = tmp_path / "registro_seguimiento.json"
        resultado = puede_insistir("t1", hoy=date(2026, 8, 19), ruta=ruta)
        assert resultado == {"puede": True, "n_aviso": 1, "motivo": "sin avisos previos"}

    def test_segundo_aviso_bloqueado_antes_de_2_dias_habiles(self, tmp_path):
        ruta = tmp_path / "registro_seguimiento.json"
        ruta_feriados = _feriados_sin_feriados(tmp_path)
        registrar_aviso("t1", "documentos", "2026-08-19", ruta=ruta)  # miércoles

        resultado = puede_insistir("t1", hoy=date(2026, 8, 20), ruta=ruta, ruta_feriados=ruta_feriados)
        assert resultado["puede"] is False
        assert resultado["n_aviso"] == 2

    def test_segundo_aviso_permitido_a_los_2_dias_habiles(self, tmp_path):
        ruta = tmp_path / "registro_seguimiento.json"
        ruta_feriados = _feriados_sin_feriados(tmp_path)
        registrar_aviso("t1", "documentos", "2026-08-19", ruta=ruta)  # miércoles

        resultado = puede_insistir("t1", hoy=date(2026, 8, 21), ruta=ruta, ruta_feriados=ruta_feriados)  # viernes: 2 hábiles después
        assert resultado["puede"] is True
        assert resultado["n_aviso"] == 2

    def test_tercer_aviso_nunca_procede(self, tmp_path):
        ruta = tmp_path / "registro_seguimiento.json"
        ruta_feriados = _feriados_sin_feriados(tmp_path)
        registrar_aviso("t1", "documentos", "2026-08-19", ruta=ruta)
        registrar_aviso("t1", "documentos", "2026-08-21", ruta=ruta)

        resultado = puede_insistir("t1", hoy=date(2026, 9, 1), ruta=ruta, ruta_feriados=ruta_feriados)
        assert resultado["puede"] is False
        assert resultado["n_aviso"] == 3
        assert "gestion manual" in resultado["motivo"]
