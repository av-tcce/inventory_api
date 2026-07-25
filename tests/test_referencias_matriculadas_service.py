import unittest
from unittest.mock import patch
import pandas as pd

from services.referencias_matriculadas_service import get_referencias_matriculadas_summary


class ReferenciasMatriculadasServiceTests(unittest.TestCase):
    def test_summary_counts_unique_references_per_category(self):
        df = pd.DataFrame([
            {"REFERENCIA": "SKU001", "GRUPO": "Textil", "PERSONAJE": "Disney", "TIPO_DE_PRENDA": "Camiseta", "CLASIFICACION_PROCESADA": "MTA"},
            {"REFERENCIA": "SKU001", "GRUPO": "Textil", "PERSONAJE": "Disney", "TIPO_DE_PRENDA": "Camiseta", "CLASIFICACION_PROCESADA": "MTA"},
            {"REFERENCIA": "SKU002", "GRUPO": "Textil", "PERSONAJE": "Marvel", "TIPO_DE_PRENDA": "Pantalon", "CLASIFICACION_PROCESADA": "MTO"},
            {"REFERENCIA": "SKU003", "GRUPO": "Calzado", "PERSONAJE": "Disney", "TIPO_DE_PRENDA": "Zapato", "CLASIFICACION_PROCESADA": "MTA"},
        ])

        with patch("services.referencias_matriculadas_service.get_referencias_matriculadas", return_value=df):
            result = get_referencias_matriculadas_summary(fecha="2026-07-01", codigo_tienda="101", pais="Colombia")

        self.assertEqual(result["total_referencias_matriculadas"], 3)
        self.assertEqual(result["por_grupo"]["Textil"], 2)
        self.assertEqual(result["por_personaje"]["Disney"], 2)
        self.assertEqual(result["por_tipo_prenda"]["Camiseta"], 1)
        self.assertEqual(result["por_clasificacion_procesada"]["MTA"], 2)
        self.assertEqual(result["por_clasificacion_procesada"]["MTO"], 1)


if __name__ == "__main__":
    unittest.main()
