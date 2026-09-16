from gestion_causas.cuadro_resumen import CAMPOS_OBLIGATORIOS, cuadro_completo, extraer_campos_cuadro

CUERPO_EJEMPLO = """\
Estimado Nico:

Le remitimos el cuadro resumen de la nueva causa.

Rit: M-6-2026
Tribunal: Juzgado de Letras del Trabajo de Temuco
Demandante: LUIS ALFREDO SOTO SANDOVAL
Rut: 12.345.678-9
Fecha audiencia: 15 de octubre de 2026
Demandada: Rendic Hermanos S.A.
Cuantía: $1.414.468.-
Materia: Despido injustificado
Fecha de ingreso al Pjud: 01 de agosto de 2026
Conceptos demandados: Recargo legal del 30% (art. 168), Devolución de AFC

Hechos:
- Despido el 08 de enero de 2026 por necesidades de la empresa.
- El trabajador se desempeñaba como reponedor.

Saludos,
Equipo Legal SMU
"""


class TestExtraerCamposCuadro:
    def test_extrae_los_campos_de_una_linea(self):
        campos = extraer_campos_cuadro(CUERPO_EJEMPLO)
        assert campos["rit"] == "M-6-2026"
        assert campos["tribunal"] == "Juzgado de Letras del Trabajo de Temuco"
        assert campos["demandante"] == "LUIS ALFREDO SOTO SANDOVAL"
        assert campos["rut"] == "12.345.678-9"
        assert campos["fecha_audiencia"] == "15 de octubre de 2026"
        assert campos["demandada"] == "Rendic Hermanos S.A."
        assert campos["cuantia"] == "$1.414.468.-"
        assert campos["materia"] == "Despido injustificado"
        assert campos["fecha_ingreso_pjud"] == "01 de agosto de 2026"

    def test_no_confunde_texto_libre_con_un_campo(self):
        campos = extraer_campos_cuadro(CUERPO_EJEMPLO)
        assert "hechos" not in campos
        assert "saludos" not in campos

    def test_cuadro_sin_rit_no_esta_completo(self):
        cuerpo_incompleto = "Tribunal: Juzgado de Temuco\nCuantía: $100.000\n"
        campos = extraer_campos_cuadro(cuerpo_incompleto)
        assert not cuadro_completo(campos)

    def test_cuadro_con_los_3_obligatorios_esta_completo(self):
        campos = extraer_campos_cuadro(CUERPO_EJEMPLO)
        assert cuadro_completo(campos)
        assert CAMPOS_OBLIGATORIOS == ("rit", "tribunal", "cuantia")

    def test_campo_faltante_simplemente_no_aparece(self):
        cuerpo_sin_rut = CUERPO_EJEMPLO.replace("Rut: 12.345.678-9\n", "")
        campos = extraer_campos_cuadro(cuerpo_sin_rut)
        assert "rut" not in campos
        assert campos["rit"] == "M-6-2026"
