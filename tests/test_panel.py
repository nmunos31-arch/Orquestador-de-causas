import json
from datetime import date
from pathlib import Path

from gestion_causas.panel import estado_causas, generar_panel_html


def _escribir_registro(tmp_path, causas: dict) -> Path:
    ruta = tmp_path / "registro_causas.json"
    ruta.write_text(json.dumps(causas, ensure_ascii=False), encoding="utf-8")
    return ruta


class TestEstadoCausas:
    def test_causa_recien_registrada(self, tmp_path):
        ruta = _escribir_registro(tmp_path, {
            "M-1-2026": {
                "rit": "M-1-2026", "empresa": "Alvi", "demandante": "Soto",
                "ultima_actualizacion": "2026-08-27T10:00:00",
            }
        })
        filas = estado_causas(hoy=date(2026, 8, 27), ruta=ruta)
        assert filas == [{
            "rit": "M-1-2026", "empresa": "Alvi", "demandante": "Soto",
            "fase": "Recien registrada", "fecha_audiencia": "",
            "dias_sin_actualizar": 0, "alerta": False,
        }]

    def test_causa_con_demanda_guardada(self, tmp_path):
        ruta = _escribir_registro(tmp_path, {
            "M-2-2026": {
                "rit": "M-2-2026", "empresa": "Alvi", "demandante": "Soto",
                "tiene_demanda": True, "ultima_actualizacion": "2026-08-27T10:00:00",
            }
        })
        filas = estado_causas(hoy=date(2026, 8, 27), ruta=ruta)
        assert filas[0]["fase"] == "Demanda guardada, en curso"

    def test_causa_con_ofrecimiento(self, tmp_path):
        ruta = _escribir_registro(tmp_path, {
            "M-3-2026": {
                "rit": "M-3-2026", "empresa": "Alvi", "demandante": "Soto",
                "tiene_demanda": True, "oferta_borrador_creado": True,
                "ultima_actualizacion": "2026-08-27T10:00:00",
            }
        })
        filas = estado_causas(hoy=date(2026, 8, 27), ruta=ruta)
        assert filas[0]["fase"] == "Ofrecimiento enviado a Roman"

    def test_causa_con_minuta(self, tmp_path):
        ruta = _escribir_registro(tmp_path, {
            "M-4-2026": {
                "rit": "M-4-2026", "empresa": "Alvi", "demandante": "Soto",
                "tiene_demanda": True, "oferta_borrador_creado": True,
                "minuta_ejecutada": True, "ultima_actualizacion": "2026-08-27T10:00:00",
            }
        })
        filas = estado_causas(hoy=date(2026, 8, 27), ruta=ruta)
        assert filas[0]["fase"] == "Minuta generada"

    def test_causa_cerrada(self, tmp_path):
        ruta = _escribir_registro(tmp_path, {
            "M-5-2026": {
                "rit": "M-5-2026", "empresa": "Alvi", "demandante": "Soto",
                "causa_cerrada": True, "ultima_actualizacion": "2026-01-01T10:00:00",
            }
        })
        filas = estado_causas(hoy=date(2026, 8, 27), ruta=ruta)
        assert filas[0]["fase"] == "Cerrada"
        assert filas[0]["alerta"] is False

    def test_alerta_por_dias_sin_actualizar(self, tmp_path):
        ruta = _escribir_registro(tmp_path, {
            "M-6-2026": {
                "rit": "M-6-2026", "empresa": "Alvi", "demandante": "Soto",
                "tiene_demanda": True, "ultima_actualizacion": "2026-08-01T10:00:00",
            }
        })
        filas = estado_causas(hoy=date(2026, 8, 27), ruta=ruta)
        assert filas[0]["dias_sin_actualizar"] == 26
        assert filas[0]["alerta"] is True

    def test_sin_alerta_dentro_del_umbral(self, tmp_path):
        ruta = _escribir_registro(tmp_path, {
            "M-7-2026": {
                "rit": "M-7-2026", "empresa": "Alvi", "demandante": "Soto",
                "tiene_demanda": True, "ultima_actualizacion": "2026-08-22T10:00:00",
            }
        })
        filas = estado_causas(hoy=date(2026, 8, 27), ruta=ruta)
        assert filas[0]["dias_sin_actualizar"] == 5
        assert filas[0]["alerta"] is False

    def test_ordena_por_rit(self, tmp_path):
        ruta = _escribir_registro(tmp_path, {
            "M-9-2026": {"rit": "M-9-2026", "empresa": "Alvi", "demandante": "B"},
            "M-2-2026": {"rit": "M-2-2026", "empresa": "Alvi", "demandante": "A"},
        })
        filas = estado_causas(hoy=date(2026, 8, 27), ruta=ruta)
        assert [f["rit"] for f in filas] == ["M-2-2026", "M-9-2026"]


class TestGenerarPanelHtml:
    def test_incluye_resumen_de_fases(self, tmp_path):
        ruta = _escribir_registro(tmp_path, {})
        resumen = [
            {"fase": "calendario", "resultado": "No corresponde hoy", "error": None},
            {"fase": "smu", "resultado": "2 causas nuevas", "error": None},
        ]
        contenido = generar_panel_html(resumen, hoy=date(2026, 8, 27), ruta_registro=ruta)
        assert "calendario" in contenido
        assert "No corresponde hoy" in contenido
        assert "2 causas nuevas" in contenido

    def test_marca_errores_de_fase(self, tmp_path):
        ruta = _escribir_registro(tmp_path, {})
        resumen = [{"fase": "goteo", "resultado": None, "error": "token vencido"}]
        contenido = generar_panel_html(resumen, hoy=date(2026, 8, 27), ruta_registro=ruta)
        assert "ERROR" in contenido
        assert "token vencido" in contenido

    def test_escapa_html_de_los_datos(self, tmp_path):
        ruta = _escribir_registro(tmp_path, {
            "M-1-2026": {
                "rit": "M-1-2026", "empresa": "<script>alert(1)</script>",
                "demandante": "Soto", "ultima_actualizacion": "2026-08-27T10:00:00",
            }
        })
        contenido = generar_panel_html([], hoy=date(2026, 8, 27), ruta_registro=ruta)
        assert "<script>alert(1)</script>" not in contenido
        assert "&lt;script&gt;" in contenido

    def test_incluye_tabla_de_causas(self, tmp_path):
        ruta = _escribir_registro(tmp_path, {
            "M-1-2026": {
                "rit": "M-1-2026", "empresa": "Alvi", "demandante": "Soto",
                "fecha_audiencia": "2026-09-10", "ultima_actualizacion": "2026-08-27T10:00:00",
            }
        })
        contenido = generar_panel_html([], hoy=date(2026, 8, 27), ruta_registro=ruta)
        assert "M-1-2026" in contenido
        assert "2026-09-10" in contenido

    def test_sin_causas_activas_no_falla(self, tmp_path):
        ruta = _escribir_registro(tmp_path, {})
        contenido = generar_panel_html([], hoy=date(2026, 8, 27), ruta_registro=ruta)
        assert "Sin causas activas" in contenido
