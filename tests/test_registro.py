from datetime import date

import pytest

from gestion_causas.registro import (
    buscar_eerr_reusable,
    causa_ya_registrada,
    causas_para_goteo,
    normalizar_rit,
    obtener_causa,
    registrar_causa,
    registrar_eerr_recibido,
)


class TestNormalizarRit:
    def test_quita_espacios_y_normaliza_guion(self):
        assert normalizar_rit(" O‑348‑2026 ") == "O-348-2026"

    def test_ignora_mayusculas(self):
        assert normalizar_rit("o-348-2026") == normalizar_rit("O-348-2026")


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
