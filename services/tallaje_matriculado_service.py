import pyodbc
import pandas as pd
from config import settings

DATASET_COLUMNS = ["TALLA", "REFERENCIA", "CODALMACEN", "TIPO_DE_PRENDA", "FORMATO", "GENERO"]

# Caché en memoria del proceso: una entrada por fecha ya consultada, así el cliente puede
# volver a cargar (o cambiar de fecha) sin repetir el trabajo si ya se consultó antes.
_dataset_cache: dict[str, pd.DataFrame] = {}
_columns_cache: dict | None = None


def _get_table_columns(conn, table_name: str):
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT COLUMN_NAME
        FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA = 'dbo' AND TABLE_NAME = ?
        """,
        table_name,
    )
    return [row[0] for row in cursor.fetchall()]


def _find_column(columns, *candidates):
    normalized = {col.upper(): col for col in columns}
    for candidate in candidates:
        if candidate.upper() in normalized:
            return normalized[candidate.upper()]
    return None


def _resolve_columns(conn):
    global _columns_cache
    if _columns_cache is not None:
        return _columns_cache

    columns = _get_table_columns(conn, "tblAgotados")

    resolved = {
        "TALLA": _find_column(columns, "TALLA"),
        "REFERENCIA": _find_column(columns, "REFERENCIA"),
        "CODALMACEN": _find_column(columns, "CODALMACEN", "CODIGO_TIENDA", "TIENDA"),
        "MINIMO": _find_column(columns, "MINIMO"),
        "FECHA": _find_column(columns, "FECHA"),
        "FORMATO": _find_column(columns, "FORMATO"),
        "GENERO": _find_column(columns, "GENERO"),
        "TIPO_DE_PRENDA": _find_column(columns, "TIPO_DE_PRENDA", "TIPO PRENDA", "TIPO_PRENDA"),
    }

    faltantes = [nombre for nombre, col in resolved.items() if not col]
    if faltantes:
        raise ValueError(f"No se encontraron columnas requeridas en tblAgotados: {faltantes}")

    _columns_cache = resolved
    return resolved


def _cargar_dataset(fecha: str = None) -> tuple[str | None, pd.DataFrame]:
    """
    Devuelve (fecha_str, dataframe) con TODAS las filas matriculadas (MINIMO > 0) de la fecha
    indicada (o la más reciente disponible si no se indica). Cachea el dataframe en memoria por
    fecha: si ya se consultó esa fecha antes, no vuelve a tocar la base de datos.
    """
    conn = pyodbc.connect(settings.get_connection_string())
    try:
        cols = _resolve_columns(conn)

        if fecha:
            fecha_str = fecha
        else:
            fecha_row = pd.read_sql(f"SELECT MAX(CAST([{cols['FECHA']}] AS DATE)) AS FECHA FROM [dbo].[tblAgotados]", conn)
            fecha_val = fecha_row["FECHA"].iloc[0]
            fecha_str = None if pd.isna(fecha_val) else str(fecha_val)

        if not fecha_str:
            return None, pd.DataFrame(columns=DATASET_COLUMNS)

        if fecha_str in _dataset_cache:
            return fecha_str, _dataset_cache[fecha_str]

        query = f"""
            SELECT
                [{cols['TALLA']}] AS TALLA,
                [{cols['REFERENCIA']}] AS REFERENCIA,
                [{cols['CODALMACEN']}] AS CODALMACEN,
                [{cols['TIPO_DE_PRENDA']}] AS TIPO_DE_PRENDA,
                [{cols['FORMATO']}] AS FORMATO,
                [{cols['GENERO']}] AS GENERO
            FROM [dbo].[tblAgotados]
            WHERE [{cols['MINIMO']}] > 0
              AND CAST([{cols['FECHA']}] AS DATE) = ?
        """
        df = pd.read_sql(query, conn, params=[fecha_str])
    finally:
        conn.close()

    for col in DATASET_COLUMNS:
        df[col] = df[col].astype(str).str.strip()

    _dataset_cache[fecha_str] = df
    return fecha_str, df


def get_dataset_tallaje(fecha: str = None) -> dict:
    """
    Carga (o reutiliza del caché) todo lo matriculado (MINIMO > 0) de una fecha y lo entrega
    completo al cliente, para que los filtros de Tipo de Prenda/Formato/Género/Referencia se
    apliquen después en el navegador sin volver a consultar la base de datos.
    """
    fecha = str(fecha).strip() if fecha else None
    fecha_str, dataset = _cargar_dataset(fecha)

    if not fecha_str or dataset.empty:
        return {"fecha": fecha_str, "total_filas": 0, "rows": []}

    return {
        "fecha": fecha_str,
        "total_filas": int(len(dataset)),
        "rows": [
            {
                "talla": row.TALLA,
                "referencia": row.REFERENCIA,
                "codalmacen": row.CODALMACEN,
                "tipo_prenda": row.TIPO_DE_PRENDA,
                "formato": row.FORMATO,
                "genero": row.GENERO,
            }
            for row in dataset.itertuples(index=False)
        ]
    }
