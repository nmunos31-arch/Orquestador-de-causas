"""Tests de gestion_causas.seguimiento: análisis puro de hilos (sin red),
para las Fases 5 y 6 (correos sin respuesta / documentos pendientes)."""

from datetime import timedelta

from gestion_causas import seguimiento


def _mensaje(sender, fecha, subject="Causa laboral X con Rendic M-1-2026", to="", cc="", cuerpo=""):
    return {
        "id": f"m-{fecha}",
        "subject": subject,
        "sender": sender,
        "to": to,
        "cc": cc,
        "date": fecha,
        "cuerpo_texto": cuerpo,
    }


NICO = "nmunoz@gomezyriesco.cl"
DANIELA = "dsanchezv@smu.cl"
ALEXIS = "acubillos@divisionlogistica.cl"


class TestExtraerDireccionYNombre:
    def test_extrae_direccion_de_nombre_y_correo(self):
        assert seguimiento.extraer_direccion("Daniela Paz Sanchez Vidal <dsanchezv@smu.cl>") == "dsanchezv@smu.cl"

    def test_extrae_direccion_normaliza_mayusculas(self):
        assert seguimiento.extraer_direccion("NMunoz@GomezYRiesco.cl") == "nmunoz@gomezyriesco.cl"

    def test_direccion_vacia_si_no_hay_nada(self):
        assert seguimiento.extraer_direccion("") == ""

    def test_extrae_nombre_de_pila(self):
        assert seguimiento.extraer_nombre_pila("Alexis Cubillos Arellano <acubillos@divisionlogistica.cl>") == "Alexis"

    def test_nombre_de_pila_cae_a_la_parte_antes_de_la_arroba(self):
        assert seguimiento.extraer_nombre_pila("dsanchezv@smu.cl") == "Dsanchezv"


class TestNormalizarAsunto:
    def test_quita_re_simple(self):
        assert seguimiento.normalizar_asunto("Re: Causa laboral Soto con Rendic") == "Causa laboral Soto con Rendic"

    def test_quita_prefijos_anidados(self):
        assert seguimiento.normalizar_asunto("Re: RV: Re: Causa laboral Soto con Rendic") == "Causa laboral Soto con Rendic"

    def test_sin_prefijo_no_cambia(self):
        assert seguimiento.normalizar_asunto("Causa laboral Soto con Rendic") == "Causa laboral Soto con Rendic"


class TestDestinatariosRespuesta:
    def test_arma_para_y_cc_sin_incluir_propia_direccion(self):
        mensaje = _mensaje(
            "Alexis Cubillos <acubillos@divisionlogistica.cl>", "Mon, 3 Aug 2026 18:55:08 +0000",
            to="Nicolas Munoz <nmunoz@gomezyriesco.cl>",
            cc="Daniela Paz Sanchez Vidal <dsanchezv@smu.cl>, Roman Gomez <rgomez@gomezyriesco.cl>",
        )
        resultado = seguimiento.destinatarios_respuesta(mensaje, NICO)
        assert resultado["para"] == ALEXIS
        assert set(resultado["cc"]) == {DANIELA, "rgomez@gomezyriesco.cl"}

    def test_no_duplica_direccion_que_aparece_en_to_y_cc(self):
        mensaje = _mensaje(
            "Alexis <acubillos@divisionlogistica.cl>", "Mon, 3 Aug 2026 18:55:08 +0000",
            to="Nicolas <nmunoz@gomezyriesco.cl>, Daniela <dsanchezv@smu.cl>",
            cc="Daniela <dsanchezv@smu.cl>",
        )
        resultado = seguimiento.destinatarios_respuesta(mensaje, NICO)
        assert resultado["cc"] == [DANIELA]


class TestDestinatariosDeUltimoPropio:
    def test_primer_destinatario_es_para_el_resto_cc(self):
        propio = _mensaje(
            NICO, "Mon, 10 Aug 2026 12:00:00 -0400",
            to="Alexis Cubillos <acubillos@divisionlogistica.cl>",
            cc="Daniela Paz Sanchez Vidal <dsanchezv@smu.cl>",
        )
        resultado = seguimiento.destinatarios_de_ultimo_propio(propio, NICO)
        assert resultado["para"] == ALEXIS
        assert resultado["cc"] == [DANIELA]

    def test_vacio_si_no_hay_destinatarios(self):
        propio = _mensaje(NICO, "Mon, 10 Aug 2026 12:00:00 -0400")
        resultado = seguimiento.destinatarios_de_ultimo_propio(propio, NICO)
        assert resultado == {"para": "", "cc": []}


class TestPareceCierreSinPedido:
    def test_detecta_acuse_de_recibo_corto(self):
        assert seguimiento.parece_cierre_sin_pedido("Estimada Daniela: Acuso recibo. Saludos cordiales.")

    def test_no_marca_pedido_de_documentos(self):
        texto = "Estimado Alexis: Junto con saludar, agradeceriamos que nos ayudes con los siguientes antecedentes: 1. Contrato"
        assert not seguimiento.parece_cierre_sin_pedido(texto)

    def test_texto_vacio_no_es_cierre(self):
        assert not seguimiento.parece_cierre_sin_pedido("")


class TestAnalizarHilo:
    def _ahora(self, fecha_str, horas_despues=0):
        base = seguimiento.parsear_fecha(fecha_str)
        return base + timedelta(hours=horas_despues)

    def test_sin_ningun_mensaje_propio_no_aplica(self):
        mensajes = [_mensaje(DANIELA, "Mon, 10 Aug 2026 12:00:00 -0400")]
        ahora = self._ahora("Mon, 10 Aug 2026 12:00:00 -0400", 48)
        analisis = seguimiento.analizar_hilo(mensajes, ahora, NICO)
        assert analisis["ultimo_mensaje_propio"] is None
        assert analisis["hay_respuesta_posterior"] is None
        assert analisis["horas_sin_respuesta"] is None

    def test_ultimo_mensaje_propio_sin_respuesta_de_nadie(self):
        mensajes = [
            _mensaje(DANIELA, "Mon, 10 Aug 2026 09:00:00 -0400"),
            _mensaje(NICO, "Mon, 10 Aug 2026 12:00:00 -0400"),
        ]
        ahora = self._ahora("Mon, 10 Aug 2026 12:00:00 -0400", 30)
        analisis = seguimiento.analizar_hilo(mensajes, ahora, NICO)
        assert analisis["hay_respuesta_posterior"] is False
        assert round(analisis["horas_sin_respuesta"], 1) == 30.0

    def test_hay_respuesta_de_cualquiera_despues_del_propio(self):
        mensajes = [
            _mensaje(NICO, "Mon, 10 Aug 2026 12:00:00 -0400"),
            _mensaje(ALEXIS, "Tue, 11 Aug 2026 09:00:00 -0400"),
        ]
        ahora = self._ahora("Tue, 11 Aug 2026 09:00:00 -0400", 30)
        analisis = seguimiento.analizar_hilo(mensajes, ahora, NICO)
        assert analisis["hay_respuesta_posterior"] is True
        assert analisis["horas_sin_respuesta"] is None

    def test_responder_esperado_no_se_conforma_con_tercero(self):
        # Caso real O-348-2026: Alexis contesto pero Daniela seguia sin
        # responder -- "sin respuesta" debe seguir siendo True.
        mensajes = [
            _mensaje(NICO, "Mon, 10 Aug 2026 09:08:00 -0400"),
            _mensaje(ALEXIS, "Mon, 10 Aug 2026 13:56:53 -0400"),
        ]
        ahora = self._ahora("Mon, 10 Aug 2026 13:56:53 -0400", 30)
        analisis = seguimiento.analizar_hilo(mensajes, ahora, NICO, responder_esperado=DANIELA)
        assert analisis["hay_respuesta_posterior"] is False
        assert analisis["horas_sin_respuesta"] is not None

    def test_responder_esperado_si_contesta_marca_con_respuesta(self):
        mensajes = [
            _mensaje(NICO, "Mon, 10 Aug 2026 09:08:00 -0400"),
            _mensaje(DANIELA, "Mon, 10 Aug 2026 16:34:50 -0400"),
        ]
        ahora = self._ahora("Mon, 10 Aug 2026 16:34:50 -0400", 5)
        analisis = seguimiento.analizar_hilo(mensajes, ahora, NICO, responder_esperado=DANIELA)
        assert analisis["hay_respuesta_posterior"] is True

    def test_participantes_son_unicos_y_en_orden_de_aparicion(self):
        mensajes = [
            _mensaje(DANIELA, "Mon, 10 Aug 2026 09:00:00 -0400"),
            _mensaje(NICO, "Mon, 10 Aug 2026 10:00:00 -0400"),
            _mensaje(DANIELA, "Mon, 10 Aug 2026 11:00:00 -0400"),
        ]
        ahora = self._ahora("Mon, 10 Aug 2026 11:00:00 -0400", 1)
        analisis = seguimiento.analizar_hilo(mensajes, ahora, NICO)
        assert analisis["participantes"] == [DANIELA, NICO]

    def test_iniciado_por_es_el_primer_remitente(self):
        mensajes = [
            _mensaje(DANIELA, "Mon, 10 Aug 2026 09:00:00 -0400"),
            _mensaje(NICO, "Mon, 10 Aug 2026 10:00:00 -0400"),
        ]
        ahora = self._ahora("Mon, 10 Aug 2026 10:00:00 -0400", 1)
        analisis = seguimiento.analizar_hilo(mensajes, ahora, NICO)
        assert analisis["iniciado_por"] == DANIELA


class TestEsReporteConsolidado:
    def test_provisiones_demanda_laborales(self):
        assert seguimiento.es_reporte_consolidado("Provisiones demanda laborales Abril 2026")

    def test_informe_de_provision_con_tilde_y_mayusculas(self):
        assert seguimiento.es_reporte_consolidado("INFORME PROVISIÓN ABRIL 2026")

    def test_informe_de_provision_sin_tilde(self):
        assert seguimiento.es_reporte_consolidado("Informe de provision Marzo 2026")

    def test_risgo_causas_estado_sentencias_con_typo(self):
        assert seguimiento.es_reporte_consolidado("Risgo causas estado sentencias")

    def test_riesgo_causas_estado_sentencias_bien_escrito(self):
        assert seguimiento.es_reporte_consolidado("Riesgo causas estado sentencias")

    def test_ignora_prefijo_re_y_rv(self):
        # Bug de raiz confirmado el 2026-08-21: sin quitar el prefijo esto no calzaba.
        assert seguimiento.es_reporte_consolidado("RE: Risgo causas estado sentencias")
        assert seguimiento.es_reporte_consolidado("Re: RV: INFORME PROVISIÓN ABRIL 2026")

    def test_asunto_normal_no_es_reporte(self):
        assert not seguimiento.es_reporte_consolidado("Causa laboral Soto con Alvi M-1-2026")

    def test_hilo_es_reporte_consolidado_si_cualquier_mensaje_matchea(self):
        mensajes = [
            _mensaje("a@sb.cl", "2026-08-14"),
            {**_mensaje("b@sb.cl", "2026-08-15"), "subject": "Provisiones demanda laborales Agosto 2026"},
        ]
        assert seguimiento.hilo_es_reporte_consolidado(mensajes)

    def test_hilo_normal_no_es_reporte(self):
        mensajes = [_mensaje("a@sb.cl", "2026-08-14"), _mensaje("b@sb.cl", "2026-08-15")]
        assert not seguimiento.hilo_es_reporte_consolidado(mensajes)


class TestAgruparCausasParaBarrido:
    def test_separa_ya_revisadas_de_primera_revision(self):
        causas = [
            {"rit": "M-1-2026", "goteo_ultima_revision": "2026-08-28"},
            {"rit": "M-2-2026", "goteo_ultima_revision": "2026-08-30"},
            {"rit": "M-3-2026", "thread_id": "t3"},
        ]
        grupos = seguimiento.agrupar_causas_para_barrido(causas)
        assert grupos["ya_revisadas"]["rits"] == ["M-1-2026", "M-2-2026"]
        assert grupos["ya_revisadas"]["fecha_corte"] == "2026-08-27"  # min - 1 dia colchon
        assert grupos["primera_revision"]["rits"] == ["M-3-2026"]
        assert grupos["thread_por_rit"] == {"M-3-2026": "t3"}

    def test_thread_por_rit_incluye_causas_ya_revisadas_no_solo_primera_revision(self):
        # Bug confirmado el 2026-09-03 con T-26-2026: una causa ya revisada
        # (con goteo_ultima_revision) tambien puede tener thread_id
        # registrado, y antes esa red de seguridad solo cubria
        # "primera_revision" — quedaba fuera para siempre si su hilo
        # original nunca mencionaba el RIT como texto.
        causas = [
            {"rit": "T-26-2026", "goteo_ultima_revision": "2026-08-13", "thread_id": "torig"},
            {"rit": "M-3-2026", "thread_id": "t3"},
        ]
        grupos = seguimiento.agrupar_causas_para_barrido(causas)
        assert grupos["thread_por_rit"] == {"T-26-2026": "torig", "M-3-2026": "t3"}

    def test_grupo_vacio_si_no_hay_causas_de_ese_tipo(self):
        grupos = seguimiento.agrupar_causas_para_barrido([{"rit": "M-1-2026", "goteo_ultima_revision": "2026-08-28"}])
        assert grupos["primera_revision"]["rits"] == []
        assert grupos["thread_por_rit"] == {}

    def test_causa_sin_rit_se_ignora(self):
        grupos = seguimiento.agrupar_causas_para_barrido([{"rit": None, "thread_id": "t1"}])
        assert grupos["ya_revisadas"]["rits"] == []
        assert grupos["primera_revision"]["rits"] == []
        assert grupos["thread_por_rit"] == {}


class TestConstruirQueryOrRits:
    def test_sin_fecha_corte(self):
        query = seguimiento.construir_query_or_rits(["M-1-2026", "O-2-2026"])
        assert query == '("M-1-2026" OR "O-2-2026")'

    def test_con_fecha_corte_convierte_guiones_a_barras(self):
        query = seguimiento.construir_query_or_rits(["M-1-2026"], fecha_corte="2026-08-27")
        assert query == 'after:2026/08/27 ("M-1-2026")'


class TestClasificarRitsDeHilo:
    def test_encuentra_rit_en_asunto_normalizado(self):
        mensajes = [_mensaje("a@sb.cl", "2026-08-14", subject="RE: Causa laboral Soto con Alvi M-1-2026")]
        assert seguimiento.clasificar_rits_de_hilo(["M-1-2026", "M-2-2026"], mensajes) == ["M-1-2026"]

    def test_no_matchea_rit_ausente(self):
        mensajes = [_mensaje("a@sb.cl", "2026-08-14", subject="Causa laboral Soto con Alvi M-1-2026")]
        assert seguimiento.clasificar_rits_de_hilo(["M-9-2026"], mensajes) == []

    def test_matchea_por_cualquier_mensaje_del_hilo(self):
        mensajes = [
            _mensaje("a@sb.cl", "2026-08-14", subject="Antecedentes"),
            _mensaje("b@sb.cl", "2026-08-15", subject="RV: Causa laboral Soto con Alvi M-1-2026"),
        ]
        assert seguimiento.clasificar_rits_de_hilo(["M-1-2026"], mensajes) == ["M-1-2026"]
