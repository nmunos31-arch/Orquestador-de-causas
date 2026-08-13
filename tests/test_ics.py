from datetime import date

from gestion_causas.ics import (
    buscar_audiencia_por_rit,
    buscar_eventos_por_rit,
    parsear_eventos,
)

_ICS_EJEMPLO = """BEGIN:VCALENDAR
VERSION:2.0
BEGIN:VEVENT
DTSTART;TZID=America/Santiago:20260821T104000
DTEND;TZID=America/Santiago:20260821T113000
SUMMARY:Audiencia Unica RIT M-643-2026 Iturriaga con Rendic
LOCATION:JLT Concepcion
END:VEVENT
BEGIN:VEVENT
DTSTART;VALUE=DATE:20260918
SUMMARY:Vence plazo contestacion O-1411-2026
END:VEVENT
BEGIN:VEVENT
DTSTART;TZID=America/Santiago:20260930T090000
SUMMARY:Reunion equipo semanal
DESCRIPTION:Sin relacion con causas
END:VEVENT
BEGIN:VEVENT
DTSTART;TZID=America/Santiago:20261015T150000
SUMMARY:Audiencia preparatoria O-1411-2026\\, Preunic
END:VEVENT
END:VCALENDAR
"""


def _escribir_ics(tmp_path, contenido=_ICS_EJEMPLO):
    ruta = tmp_path / "calendario.ics"
    ruta.write_text(contenido, encoding="utf-8")
    return ruta


class TestParsearEventos:
    def test_extrae_fecha_y_resumen_de_cada_evento(self, tmp_path):
        ruta = _escribir_ics(tmp_path)
        eventos = parsear_eventos(ruta)
        assert len(eventos) == 4
        assert eventos[0]["fecha"] == date(2026, 8, 21)
        assert "M-643-2026" in eventos[0]["resumen"]

    def test_soporta_dtstart_value_date_sin_hora(self, tmp_path):
        ruta = _escribir_ics(tmp_path)
        eventos = parsear_eventos(ruta)
        vence_plazo = next(e for e in eventos if "Vence plazo" in e["resumen"])
        assert vence_plazo["fecha"] == date(2026, 9, 18)

    def test_desescapa_comas_en_el_resumen(self, tmp_path):
        ruta = _escribir_ics(tmp_path)
        eventos = parsear_eventos(ruta)
        preparatoria = next(e for e in eventos if "preparatoria" in e["resumen"].lower())
        assert preparatoria["resumen"] == "Audiencia preparatoria O-1411-2026, Preunic"


class TestBuscarEventosPorRit:
    def test_encuentra_por_rit_exacto(self, tmp_path):
        eventos = parsear_eventos(_escribir_ics(tmp_path))
        encontrados = buscar_eventos_por_rit(eventos, "M-643-2026")
        assert len(encontrados) == 1
        assert encontrados[0]["fecha"] == date(2026, 8, 21)

    def test_rit_con_guion_no_separable_igual_matchea(self, tmp_path):
        eventos = parsear_eventos(_escribir_ics(tmp_path))
        encontrados = buscar_eventos_por_rit(eventos, "M‑643‑2026")
        assert len(encontrados) == 1

    def test_un_rit_puede_aparecer_en_mas_de_un_evento(self, tmp_path):
        eventos = parsear_eventos(_escribir_ics(tmp_path))
        encontrados = buscar_eventos_por_rit(eventos, "O-1411-2026")
        assert len(encontrados) == 2

    def test_rit_sin_coincidencias(self, tmp_path):
        eventos = parsear_eventos(_escribir_ics(tmp_path))
        assert buscar_eventos_por_rit(eventos, "T-999-2026") == []


class TestBuscarAudienciaPorRit:
    def test_devuelve_ordenado_por_fecha_ascendente(self, tmp_path):
        ruta = _escribir_ics(tmp_path)
        encontrados = buscar_audiencia_por_rit(ruta, "O-1411-2026")
        assert len(encontrados) == 2
        assert encontrados[0]["fecha"] < encontrados[1]["fecha"]
