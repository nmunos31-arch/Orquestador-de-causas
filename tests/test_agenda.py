import json

from gestion_causas.agenda import (
    cargar_feriados,
    dias_corridos_antes,
    dias_habiles_antes,
    es_dia_habil,
)


def _feriados_prueba(tmp_path, fechas_2026):
    ruta = tmp_path / "feriados.json"
    ruta.write_text(json.dumps({"2026": fechas_2026}), encoding="utf-8")
    return ruta


class TestCargarFeriados:
    def test_carga_fechas_de_todos_los_anios(self, tmp_path):
        ruta = tmp_path / "feriados.json"
        ruta.write_text(
            json.dumps({"2026": ["2026-01-01"], "2027": ["2027-01-01"]}), encoding="utf-8"
        )
        feriados = cargar_feriados(ruta)
        assert len(feriados) == 2

    def test_ignora_claves_de_comentario(self, tmp_path):
        ruta = tmp_path / "feriados.json"
        ruta.write_text(
            json.dumps({"_comentario": "nota", "2026": ["2026-01-01"]}), encoding="utf-8"
        )
        feriados = cargar_feriados(ruta)
        assert len(feriados) == 1


class TestEsDiaHabil:
    def test_sabado_no_es_habil(self, tmp_path):
        ruta = _feriados_prueba(tmp_path, [])
        assert es_dia_habil("2026-08-08", cargar_feriados(ruta)) is False

    def test_domingo_no_es_habil(self, tmp_path):
        ruta = _feriados_prueba(tmp_path, [])
        assert es_dia_habil("2026-08-09", cargar_feriados(ruta)) is False

    def test_feriado_entre_semana_no_es_habil(self, tmp_path):
        ruta = _feriados_prueba(tmp_path, ["2026-09-18"])
        assert es_dia_habil("2026-09-18", cargar_feriados(ruta)) is False

    def test_dia_normal_es_habil(self, tmp_path):
        ruta = _feriados_prueba(tmp_path, [])
        assert es_dia_habil("2026-08-11", cargar_feriados(ruta)) is True


class TestDiasHabilesAntes:
    def test_cruza_un_fin_de_semana(self, tmp_path):
        # Audiencia martes 2026-08-11. 4 hábiles antes, sin feriados:
        # lun 10, (sáb 8/dom 9 saltados), vie 7, jue 6, mié 5.
        ruta = _feriados_prueba(tmp_path, [])
        resultado = dias_habiles_antes("2026-08-11", 4, ruta)
        assert str(resultado) == "2026-08-05"

    def test_cruza_fin_de_semana_y_feriado_viernes(self, tmp_path):
        # Audiencia lunes 2026-09-21. Feriado viernes 2026-09-18 (más el
        # sábado 19 que ya es fin de semana). 4 hábiles antes:
        # dom 20 y sáb 19 (finde), vie 18 (feriado) -> jue 17, mié 16,
        # mar 15, lun 14.
        ruta = _feriados_prueba(tmp_path, ["2026-09-18", "2026-09-19"])
        resultado = dias_habiles_antes("2026-09-21", 4, ruta)
        assert str(resultado) == "2026-09-14"

    def test_un_dia_habil_antes_de_un_lunes_es_el_viernes(self, tmp_path):
        ruta = _feriados_prueba(tmp_path, [])
        resultado = dias_habiles_antes("2026-08-10", 1, ruta)
        assert str(resultado) == "2026-08-07"


class TestDiasCorridosAntes:
    def test_resta_dias_corridos_sin_excluir_nada(self):
        resultado = dias_corridos_antes("2026-08-25", 14)
        assert str(resultado) == "2026-08-11"
