import io
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.traslados_service import traslados_service


def create_transfer_excel_bytes():
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        pd.DataFrame(
            {
                "CODALMACEN": ["TIE001", "TIE002"],
                "REFERENCIA": ["SKU001", "SKU002"],
                "TALLA": ["M", "L"],
                "COLOR": ["AZUL", "ROJO"],
                "STOCK": [10, 5],
            }
        ).to_excel(writer, sheet_name="Sheet1", index=False)
    output.seek(0)
    return output.getvalue()


def test_parse_transfer_excel_accepts_required_columns():
    content = create_transfer_excel_bytes()
    df = traslados_service.parse_transfer_excel(content)

    assert list(df.columns) == ["CODALMACEN", "REFERENCIA", "TALLA", "COLOR", "STOCK"]
    assert len(df) == 2


def test_parse_transfer_excel_rejects_missing_columns():
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        pd.DataFrame(
            {
                "CODALMACEN": ["TIE001"],
                "REFERENCIA": ["SKU001"],
                "TALLA": ["M"],
                "STOCK": [10],
            }
        ).to_excel(writer, sheet_name="Sheet1", index=False)
    output.seek(0)

    try:
        traslados_service.parse_transfer_excel(output.getvalue())
    except ValueError as exc:
        assert "COLOR" in str(exc)
    else:
        raise AssertionError("Se esperaba un ValueError para columnas faltantes")
