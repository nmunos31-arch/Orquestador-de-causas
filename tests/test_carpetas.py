from gestion_causas.carpetas import (
    abreviar_empresa,
    buscar_carpeta_existente_por_rit,
    copiar_archivo_local,
    crear_carpeta_causa,
    es_adjunto_firma,
    guardar_adjunto,
    listar_archivos_carpeta,
    nombre_carpeta_causa,
    parece_eerr,
    ruta_carpeta_causa,
    sanear_nombre_windows,
)


class TestAbreviarEmpresa:
    def test_rendic_hermanos(self):
        assert abreviar_empresa("Rendic Hermanos S.A") == "Rendic"

    def test_alvi(self):
        assert abreviar_empresa("Alvi") == "Alvi"

    def test_super_10(self):
        assert abreviar_empresa("Super 10") == "Super 10"

    def test_servicios_logisticos_santiago(self):
        assert abreviar_empresa("Servicios Logísticos Santiago S.A.") == "SSLL"

    def test_empresa_desconocida_se_devuelve_tal_cual(self):
        assert abreviar_empresa("Otra Empresa SPA") == "Otra Empresa SPA"

    def test_preunic(self):
        assert abreviar_empresa("Preunic S.A") == "Preunic"

    def test_salcobrand(self):
        assert abreviar_empresa("Salcobrand") == "Salcobrand"


class TestSanearNombreWindows:
    def test_quita_caracteres_ilegales(self):
        assert sanear_nombre_windows('Peña con Rendic: "M-6-2026"') == "Peña con Rendic M-6-2026"

    def test_colapsa_espacios(self):
        assert sanear_nombre_windows("Peña   con    Rendic") == "Peña con Rendic"

    def test_no_termina_en_punto(self):
        assert sanear_nombre_windows("Peña con Rendic.") == "Peña con Rendic"


class TestNombreCarpetaCausa:
    def test_apellido_compuesto_y_tildes(self):
        nombre = nombre_carpeta_causa("Yáñez Gómez", "Servicios Logísticos Santiago", "O-348-2026")
        assert nombre == "Yáñez Gómez con SSLL O-348-2026"

    def test_alvi(self):
        nombre = nombre_carpeta_causa("Millahueque", "Alvi", "O-394-2026")
        assert nombre == "Millahueque con Alvi O-394-2026"


class TestCrearCarpetaCausa:
    def test_crea_carpeta_bajo_base(self, tmp_path):
        carpeta = crear_carpeta_causa("Soto", "Rendic Hermanos", "M-6-2026", base=tmp_path)
        assert carpeta.exists()
        assert carpeta.is_dir()
        assert carpeta.name == "Soto con Rendic M-6-2026"

    def test_idempotente(self, tmp_path):
        primera = crear_carpeta_causa("Soto", "Rendic Hermanos", "M-6-2026", base=tmp_path)
        (primera / "demanda.pdf").write_bytes(b"contenido")

        segunda = crear_carpeta_causa("Soto", "Rendic Hermanos", "M-6-2026", base=tmp_path)
        assert segunda == primera
        assert (segunda / "demanda.pdf").exists()


class TestBuscarCarpetaExistentePorRit:
    def test_encuentra_carpeta_vieja_por_rit_en_archivo_interno(self, tmp_path):
        carpeta = tmp_path / "Yañez con SSLL"
        carpeta.mkdir()
        (carpeta / "Minuta audiencia preparatoria O-348-2026.docx").write_bytes(b"x")

        encontrada = buscar_carpeta_existente_por_rit("O-348-2026", tmp_path)
        assert encontrada == carpeta

    def test_no_encuentra_si_ningun_archivo_tiene_el_rit(self, tmp_path):
        carpeta = tmp_path / "Yañez con SSLL"
        carpeta.mkdir()
        (carpeta / "demanda.pdf").write_bytes(b"x")

        assert buscar_carpeta_existente_por_rit("O-348-2026", tmp_path) is None

    def test_encuentra_carpeta_por_rit_en_el_nombre(self, tmp_path):
        (tmp_path / "Millahueque con Alvi O-394-2026").mkdir()
        encontrada = buscar_carpeta_existente_por_rit("O-394-2026", tmp_path)
        assert encontrada == tmp_path / "Millahueque con Alvi O-394-2026"

    def test_no_encuentra_si_no_hay_ninguna(self, tmp_path):
        assert buscar_carpeta_existente_por_rit("M-1-2026", tmp_path) is None

    def test_insensible_a_guion_y_mayusculas(self, tmp_path):
        (tmp_path / "Soto con Rendic m-6-2026").mkdir()
        encontrada = buscar_carpeta_existente_por_rit("M‑6‑2026", tmp_path)
        assert encontrada == tmp_path / "Soto con Rendic m-6-2026"


class TestCrearCarpetaCausaReusaExistente:
    def test_reusa_carpeta_ya_creada_con_el_rit_en_el_nombre(self, tmp_path):
        vieja = tmp_path / "Peña con Rendic M-6-2026"
        vieja.mkdir()
        (vieja / "demanda.pdf").write_bytes(b"ya estaba")

        resultado = crear_carpeta_causa("Peña", "Rendic Hermanos", "M-6-2026", base=tmp_path)
        assert resultado == vieja
        assert (resultado / "demanda.pdf").exists()
        # no se creó una segunda carpeta con el nombre canónico
        assert not (tmp_path / "Peña con Rendic M-6-2026 M-6-2026").exists()


class TestEsAdjuntoFirma:
    def test_imagen_chica_es_firma(self):
        assert es_adjunto_firma("Outlook-PIE-DE-FIR.png", 15_000) is True

    def test_imagen_grande_no_es_firma(self):
        assert es_adjunto_firma("escaneo.png", 500_000) is False

    def test_pdf_nunca_es_firma(self):
        assert es_adjunto_firma("demanda.pdf", 10_000) is False


class TestGuardarAdjunto:
    def test_guarda_archivo_nuevo(self, tmp_path):
        resultado = guardar_adjunto(tmp_path, "demanda.pdf", b"contenido-demanda")
        assert resultado["guardado"] is True
        assert resultado["ruta"].read_bytes() == b"contenido-demanda"

    def test_no_pisa_archivo_existente(self, tmp_path):
        primero = guardar_adjunto(tmp_path, "demanda.pdf", b"version-1")
        assert primero["guardado"] is True

        segundo = guardar_adjunto(tmp_path, "demanda.pdf", b"version-2-distinta")
        assert segundo["guardado"] is False
        assert segundo["ruta"].read_bytes() == b"version-1"  # no se pisó

    def test_sanea_nombre_del_adjunto(self, tmp_path):
        resultado = guardar_adjunto(tmp_path, 'demanda: "final".pdf', b"x")
        assert resultado["ruta"].name == "demanda final.pdf"


class TestCopiarArchivoLocal:
    def test_copia_archivo_nuevo(self, tmp_path):
        origen = tmp_path / "eerr_viejo.pdf"
        origen.write_bytes(b"contenido-eerr")
        destino_carpeta = tmp_path / "causa_nueva"

        resultado = copiar_archivo_local(origen, destino_carpeta, "EERR 2026.pdf")
        assert resultado["copiado"] is True
        assert resultado["ruta"].read_bytes() == b"contenido-eerr"

    def test_no_pisa_archivo_existente_en_destino(self, tmp_path):
        origen = tmp_path / "eerr_viejo.pdf"
        origen.write_bytes(b"version-nueva")
        destino_carpeta = tmp_path / "causa_nueva"
        destino_carpeta.mkdir()
        (destino_carpeta / "EERR 2026.pdf").write_bytes(b"version-que-ya-estaba")

        resultado = copiar_archivo_local(origen, destino_carpeta, "EERR 2026.pdf")
        assert resultado["copiado"] is False
        assert resultado["ruta"].read_bytes() == b"version-que-ya-estaba"


class TestPareceEerr:
    def test_reconoce_eerr_explicito(self):
        assert parece_eerr("EERR 2026.pdf") is True

    def test_reconoce_ifrs(self):
        assert parece_eerr("Ec1223_Rendic_IFRS_individual.pdf") is True

    def test_reconoce_estado_de_resultados(self):
        assert parece_eerr("Estado de Resultados Local Temuco.pdf") is True

    def test_documento_normal_no_es_eerr(self):
        assert parece_eerr("Finiquito ratificado.pdf") is False


class TestListarArchivosCarpeta:
    def test_lista_archivos_existentes(self, tmp_path):
        (tmp_path / "demanda.pdf").write_bytes(b"x")
        (tmp_path / "contrato.pdf").write_bytes(b"x")
        (tmp_path / "subcarpeta").mkdir()

        archivos = listar_archivos_carpeta(tmp_path)
        assert archivos == ["contrato.pdf", "demanda.pdf"]

    def test_carpeta_inexistente_devuelve_lista_vacia(self, tmp_path):
        assert listar_archivos_carpeta(tmp_path / "no_existe") == []
