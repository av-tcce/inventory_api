import io
import pyodbc
import pandas as pd
from config import settings


def _fetch_auditoria(
    referencias: list[str],
    fecha_desde: str = None,
    fecha_hasta: str = None,
    formatos: list[str] = None
) -> pd.DataFrame:
    """Audita en cuántas tiendas (CODALMACEN) está matriculada cada referencia (MINIMO > 0), por fecha y formato."""
    referencias = [str(r).strip() for r in (referencias or []) if r and str(r).strip()]
    if not referencias:
        raise ValueError("Debe proporcionar al menos una referencia.")

    conditions = ["MINIMO > 0"]
    params = []

    placeholders = ",".join("?" for _ in referencias)
    conditions.append(f"REFERENCIA IN ({placeholders})")
    params.extend(referencias)

    if fecha_desde:
        conditions.append("CAST(FECHA AS DATE) >= ?")
        params.append(str(fecha_desde).strip())

    if fecha_hasta:
        conditions.append("CAST(FECHA AS DATE) <= ?")
        params.append(str(fecha_hasta).strip())

    formatos = [str(f).strip() for f in (formatos or []) if f and str(f).strip()]
    if formatos:
        formatos_placeholders = ",".join("?" for _ in formatos)
        conditions.append(f"FORMATO IN ({formatos_placeholders})")
        params.extend(formatos)

    where_clause = " AND ".join(conditions)

    query = f"""
        SELECT
            CAST(FECHA AS DATE) AS FECHA,
            FORMATO,
            REFERENCIA,
            MAX(DESCRIPCION) AS DESCRIPCION,
            COUNT(DISTINCT CODALMACEN) AS TIENDAS_MATRICULADAS
        FROM tblAgotados
        WHERE {where_clause}
        GROUP BY CAST(FECHA AS DATE), FORMATO, REFERENCIA
        ORDER BY CAST(FECHA AS DATE), FORMATO, REFERENCIA
    """

    conn = pyodbc.connect(settings.get_connection_string())
    try:
        df = pd.read_sql(query, conn, params=params)
    finally:
        conn.close()

    if not df.empty:
        df['FECHA'] = df['FECHA'].astype(str)

    return df


def consultar_auditoria_min_max(
    referencias: list[str],
    fecha_desde: str = None,
    fecha_hasta: str = None,
    formatos: list[str] = None
) -> list[dict]:
    df = _fetch_auditoria(referencias, fecha_desde, fecha_hasta, formatos)
    return df.fillna("").to_dict(orient="records")


def exportar_auditoria_min_max(
    referencias: list[str],
    fecha_desde: str = None,
    fecha_hasta: str = None,
    formatos: list[str] = None
) -> io.BytesIO:
    df = _fetch_auditoria(referencias, fecha_desde, fecha_hasta, formatos)
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, sheet_name="Auditoria Min-Max", index=False)
    output.seek(0)
    return output
