from gestion_causas.cuadro_resumen import (
    CAMPOS_OBLIGATORIOS,
    buscar_ceco_en_mensajes,
    cuadro_completo,
    dominios_citados,
    extraer_campos_cuadro,
    texto_citado,
)

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

    def test_normaliza_espacios_internos_de_la_etiqueta(self):
        cuerpo = "Fecha  audiencia:   15 de octubre de 2026\n"
        campos = extraer_campos_cuadro(cuerpo)
        assert campos["fecha_audiencia"] == "15 de octubre de 2026"

    def test_extrae_valor_que_contiene_dos_puntos(self):
        cuerpo = "Fecha audiencia: 15:30 hrs, 15 de octubre de 2026\n"
        campos = extraer_campos_cuadro(cuerpo)
        assert campos["fecha_audiencia"] == "15:30 hrs, 15 de octubre de 2026"

    def test_extrae_cuadro_en_formato_tabla_sin_dos_puntos(self):
        """SMU casi siempre manda el cuadro como una tabla: la etiqueta
        queda sola en una línea y el valor en la siguiente, sin ":" (hilo
        Rit M-417-2026, 2026-09-07)."""
        cuerpo = (
            "Rit\n"
            "M-417-2026\n"
            "Tribunal\n"
            "Juzgado de Letras del Trabajo de Los Ángeles\n"
            "Demandante\n"
            "Leticia Andrea Zapata Rodríguez\n"
            "Cuantía\n"
            "$4.380.371\n"
        )
        campos = extraer_campos_cuadro(cuerpo)
        assert campos["rit"] == "M-417-2026"
        assert campos["tribunal"] == "Juzgado de Letras del Trabajo de Los Ángeles"
        assert campos["demandante"] == "Leticia Andrea Zapata Rodríguez"
        assert campos["cuantia"] == "$4.380.371"
        assert cuadro_completo(campos)

    def test_extrae_cuadro_en_formato_tabla_con_lineas_en_blanco(self):
        """Algunos correos dejan líneas en blanco entre la celda de
        etiqueta y la de valor (hilo Rit M-21-2025, 2025-06-06)."""
        cuerpo = (
            "RIT\n"
            "M-21-2025\n"
            "\n"
            "\n"
            "Tribunal\n"
            "Juzgado de Letras de Yungay\n"
            "\n"
            "\n"
            "Cuantía\n"
            "$3.789.798.-\n"
        )
        campos = extraer_campos_cuadro(cuerpo)
        assert campos["rit"] == "M-21-2025"
        assert campos["tribunal"] == "Juzgado de Letras de Yungay"
        assert campos["cuantia"] == "$3.789.798.-"
        assert cuadro_completo(campos)


class TestTextoCitado:
    def test_sin_marcador_de_cita_devuelve_vacio(self):
        assert texto_citado("Román, ¿cómo contestamos esta?") == ""

    def test_corta_desde_el_primer_marcador_y_quita_el_prefijo_de_cita(self):
        cuerpo = "Te reenvío esto.\n\n> Rit: M-1-2026\n> Tribunal: Temuco"
        assert texto_citado(cuerpo) == "Rit: M-1-2026\nTribunal: Temuco"

    def test_corta_desde_mensaje_original(self):
        cuerpo = (
            "Román, te paso esto.\n\n"
            "---------- Mensaje original ----------\n"
            "De: Persona <persona@smu.cl>\n"
            "Rit: M-1-2026\n"
        )
        citado = texto_citado(cuerpo)
        assert citado.startswith("---------- Mensaje original ----------")

    def test_usa_el_marcador_que_aparece_primero(self):
        cuerpo = "> cita temprana\n\nDe: x\nEnviado: y"
        assert texto_citado(cuerpo).startswith("cita temprana")


class TestDominiosCitados:
    def test_encuentra_dominio_de_una_direccion(self):
        assert dominios_citados("De: Persona <persona@smu.cl>") == {"smu.cl"}

    def test_varias_direcciones_de_distintos_dominios(self):
        texto = "De: a@smu.cl\nPara: b@gomezyriesco.cl"
        assert dominios_citados(texto) == {"smu.cl", "gomezyriesco.cl"}

    def test_sin_direcciones_devuelve_vacio(self):
        assert dominios_citados("sin ningún correo acá") == set()


class TestBuscarCecoEnMensajes:
    def test_encuentra_ceco_en_el_primer_mensaje(self):
        mensajes = [{"cuerpo_texto": "Les confirmamos el CECO: T-4521 para esta causa."}]
        assert buscar_ceco_en_mensajes(mensajes) == "T-4521"

    def test_encuentra_ceco_en_un_mensaje_posterior(self):
        mensajes = [
            {"cuerpo_texto": "Estimados, queda pendiente el CECO."},
            {"cuerpo_texto": "El CECO es 8890."},
        ]
        assert buscar_ceco_en_mensajes(mensajes) == "8890"

    def test_sin_ceco_en_ningun_mensaje_devuelve_none(self):
        mensajes = [{"cuerpo_texto": "No hay CECO mencionado acá."}]
        assert buscar_ceco_en_mensajes(mensajes) is None
