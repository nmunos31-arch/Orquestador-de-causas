from gestion_causas.empresas import EMPRESAS_VALIDAS, normalizar_empresa


class TestNormalizarEmpresa:
    def test_coincide_exacto(self):
        assert normalizar_empresa("Alvi") == "Alvi"

    def test_ignora_mayusculas_y_sufijo_sa(self):
        assert normalizar_empresa("RENDIC HERMANOS S.A.") == "Rendic Hermanos"
        assert normalizar_empresa("salcobrand s.a") == "Salcobrand"

    def test_ignora_tildes(self):
        assert normalizar_empresa("Servicios Logisticos Santiago") == "Servicios Logísticos Santiago"

    def test_empresa_no_valida_devuelve_none(self):
        assert normalizar_empresa("Falabella") is None

    def test_vacio_devuelve_none(self):
        assert normalizar_empresa("") is None
        assert normalizar_empresa(None) is None

    def test_las_6_empresas_estan_en_la_lista(self):
        assert len(EMPRESAS_VALIDAS) == 6
        assert "Preunic" in EMPRESAS_VALIDAS
        assert "Salcobrand" in EMPRESAS_VALIDAS
