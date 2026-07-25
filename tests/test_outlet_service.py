import io
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.outlet_service import load_tc_inventory_sheets


def create_tc_excel_bytes():
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        pd.DataFrame({"EQ_COD2": ["CO100"], "SABANA": [10]}).to_excel(
            writer,
            sheet_name="Cargue",
            index=False,
            startrow=8,
        )
        pd.DataFrame(
            {
                "EQ_COD2": ["CO100"],
                "GENERO": ["Mujer"],
                "TIPO_DE_PRENDA": ["Camiseta"],
                "TALLA": ["M"],
                "Requerido": [5],
                "PRIORIDAD": [1],
            }
        ).to_excel(
            writer,
            sheet_name="Requerido",
            index=False,
            startrow=7,
        )
    output.seek(0)
    return output.getvalue()


def test_load_tc_inventory_sheets_reads_expected_structure():
    content = create_tc_excel_bytes()

    cargue_df, requerido_df = load_tc_inventory_sheets(content)

    assert list(cargue_df.columns) == ["EQ_COD2", "SABANA"]
    assert list(requerido_df.columns) == [
        "EQ_COD2",
        "GENERO",
        "TIPO_DE_PRENDA",
        "TALLA",
        "Requerido",
        "PRIORIDAD",
    ]


def test_load_tc_inventory_sheets_rejects_missing_columns():
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        pd.DataFrame({"EQ_COD2": ["CO100"]}).to_excel(
            writer,
            sheet_name="Cargue",
            index=False,
            startrow=8,
        )
        pd.DataFrame({"EQ_COD2": ["CO100"]}).to_excel(
            writer,
            sheet_name="Requerido",
            index=False,
            startrow=7,
        )
    output.seek(0)

    try:
        load_tc_inventory_sheets(output.getvalue())
    except ValueError as exc:
        assert "SABANA" in str(exc)
    else:
        raise AssertionError("Se esperaba un ValueError para columnas faltantes")
