import io
import pyodbc
import pandas as pd
from config import settings

REQUIRED_SOURCE_COLUMNS = ['CODALMACEN', 'REFERENCIA', 'TALLA', 'COLOR', 'CANTIDAD', 'TIPO', 'CEDI']
SKU_PARTS = ['CODALMACEN', 'REFERENCIA', 'TALLA', 'COLOR']
AGOTADOS_VALUE_COLS = ['STOCK', 'MINIMO', 'TRANSITO', 'STOCKTOTAL_INVENTARIO']


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


def _resolve_agotados_columns(conn):
    columns = _get_table_columns(conn, "tblAgotados")
    resolved = {
        "CODALMACEN": _find_column(columns, "CODALMACEN", "CODIGO_TIENDA", "TIENDA"),
        "REFERENCIA": _find_column(columns, "REFERENCIA"),
        "TALLA": _find_column(columns, "TALLA"),
        "COLOR": _find_column(columns, "COLOR"),
        "STOCK": _find_column(columns, "STOCK"),
        "MINIMO": _find_column(columns, "MINIMO"),
        "TRANSITO": _find_column(columns, "TRANSITO"),
        "STOCKTOTAL_INVENTARIO": _find_column(
            columns, "STOCKTOTAL_inventario", "STOCKTOTAL_INVENTARIO", "STOCKTOTAL", "STOCK_TOTAL_INVENTARIO", "STOCK_TOTAL"
        ),
        "FECHA": _find_column(columns, "FECHA"),
    }
    faltantes = [nombre for nombre, col in resolved.items() if not col]
    if faltantes:
        raise ValueError(f"No se encontraron columnas requeridas en tblAgotados: {faltantes}")
    return resolved


def _resolve_transito_cedi_columns(conn):
    columns = _get_table_columns(conn, "transito_cedi")
    resolved = {
        "TIENDA": _find_column(columns, "TIENDA", "CODALMACEN", "CODIGO_TIENDA"),
        "REFERENCIA": _find_column(columns, "REFERENCIA"),
        "TALLA": _find_column(columns, "TALLA"),
        "COLOR": _find_column(columns, "COLOR"),
        "CANTIDAD": _find_column(columns, "CANTIDAD"),
    }
    faltantes = [nombre for nombre, col in resolved.items() if not col]
    if faltantes:
        raise ValueError(f"No se encontraron columnas requeridas en transito_cedi: {faltantes}")
    return resolved


def _construir_sku(df: pd.DataFrame, columnas: list[str]) -> pd.Series:
    """SKU = concatenación (sin separador) de CODALMACEN+REFERENCIA+TALLA+COLOR, normalizado
    (mayúsculas, sin espacios) para que el cruce entre el archivo y tblAgotados sea confiable."""
    partes = [df[col].fillna('').astype(str).str.strip().str.upper() for col in columnas]
    sku = partes[0]
    for parte in partes[1:]:
        sku = sku + parte
    return sku


def generar_validacion_compromisos(source_content: bytes, fecha: str) -> io.BytesIO:
    """
    A partir de un Excel de compromisos (CODALMACEN, REFERENCIA, TALLA, COLOR, CANTIDAD, TIPO, CEDI)
    y una fecha, arma el SKU (CODALMACEN+REFERENCIA+TALLA+COLOR) y lo cruza contra:
      - tblAgotados (mismo SKU, para esa fecha): STOCK, MINIMO, TRANSITO, STOCKTOTAL_inventario.
      - transito_cedi (mismo SKU vía TIENDA+REFERENCIA+TALLA+COLOR, sin filtro de fecha): CANTIDAD
        comprometida pero aún no despachada, sumada por SKU en COMPROMETIDO_TRANSITO_CEDI.
    Calcula NECESIDAD, NECESIDAD CON TRANSITO, CUBRIMIENTO (%) y CUBRIMIENTO CON TRANSITO (%).
    """
    fecha = str(fecha).strip() if fecha else None
    if not fecha:
        raise ValueError("Debe indicar una fecha para filtrar tblAgotados.")

    df_source = pd.read_excel(
        io.BytesIO(source_content), sheet_name=0, header=0,
        dtype={'CODALMACEN': str, 'REFERENCIA': str, 'TALLA': str, 'COLOR': str}
    )
    df_source.columns = [str(c).strip().upper() for c in df_source.columns]

    faltantes_cols = [c for c in REQUIRED_SOURCE_COLUMNS if c not in df_source.columns]
    if faltantes_cols:
        raise ValueError(f"Al archivo le faltan columnas requeridas: {faltantes_cols}")

    for col in SKU_PARTS:
        df_source[col] = df_source[col].fillna('').astype(str).str.strip()
    df_source['SKU'] = _construir_sku(df_source, SKU_PARTS)
    df_source = df_source[df_source['CODALMACEN'] != '']
    if df_source.empty:
        raise ValueError("El archivo no tiene filas válidas con CODALMACEN.")

    codalmacenes = sorted(v for v in df_source['CODALMACEN'].str.upper().unique().tolist() if v)
    referencias = sorted(v for v in df_source['REFERENCIA'].str.upper().unique().tolist() if v)
    if not codalmacenes or not referencias:
        raise ValueError("El archivo no tiene filas válidas con CODALMACEN y REFERENCIA.")

    conn = pyodbc.connect(settings.get_connection_string())
    try:
        cols = _resolve_agotados_columns(conn)

        placeholders_alm = ",".join("?" for _ in codalmacenes)
        placeholders_ref = ",".join("?" for _ in referencias)

        query = f"""
            SELECT
                [{cols['CODALMACEN']}] AS CODALMACEN,
                [{cols['REFERENCIA']}] AS REFERENCIA,
                [{cols['TALLA']}] AS TALLA,
                [{cols['COLOR']}] AS COLOR,
                [{cols['STOCK']}] AS STOCK,
                [{cols['MINIMO']}] AS MINIMO,
                [{cols['TRANSITO']}] AS TRANSITO,
                [{cols['STOCKTOTAL_INVENTARIO']}] AS STOCKTOTAL_INVENTARIO
            FROM [dbo].[tblAgotados]
            WHERE CAST([{cols['FECHA']}] AS DATE) = ?
              AND [{cols['CODALMACEN']}] IN ({placeholders_alm})
              AND [{cols['REFERENCIA']}] IN ({placeholders_ref})
        """
        params = [fecha] + codalmacenes + referencias
        df_agotados = pd.read_sql(query, conn, params=params)

        cols_cedi = _resolve_transito_cedi_columns(conn)
        query_cedi = f"""
            SELECT
                [{cols_cedi['TIENDA']}] AS TIENDA,
                [{cols_cedi['REFERENCIA']}] AS REFERENCIA,
                [{cols_cedi['TALLA']}] AS TALLA,
                [{cols_cedi['COLOR']}] AS COLOR,
                [{cols_cedi['CANTIDAD']}] AS CANTIDAD
            FROM [dbo].[transito_cedi]
            WHERE [{cols_cedi['TIENDA']}] IN ({placeholders_alm})
              AND [{cols_cedi['REFERENCIA']}] IN ({placeholders_ref})
        """
        df_transito_cedi = pd.read_sql(query_cedi, conn, params=codalmacenes + referencias)
    finally:
        conn.close()

    if not df_agotados.empty:
        for col in SKU_PARTS:
            df_agotados[col] = df_agotados[col].fillna('').astype(str).str.strip()
        df_agotados['SKU'] = _construir_sku(df_agotados, SKU_PARTS)
        df_agotados = df_agotados.drop_duplicates(subset=['SKU'], keep='first')
        df_cruce = df_agotados[['SKU'] + AGOTADOS_VALUE_COLS]
    else:
        df_cruce = pd.DataFrame(columns=['SKU'] + AGOTADOS_VALUE_COLS)

    df_resultado = pd.merge(df_source, df_cruce, on='SKU', how='left')

    for col in AGOTADOS_VALUE_COLS:
        df_resultado[col] = pd.to_numeric(df_resultado[col], errors='coerce')

    # transito_cedi: lo comprometido (no despachado) por SKU. Puede haber varias filas por SKU
    # (varios despachos pendientes), así que se suman antes de cruzar.
    if not df_transito_cedi.empty:
        transito_cols = ['TIENDA', 'REFERENCIA', 'TALLA', 'COLOR']
        for col in transito_cols:
            df_transito_cedi[col] = df_transito_cedi[col].fillna('').astype(str).str.strip()
        df_transito_cedi['SKU'] = _construir_sku(df_transito_cedi, transito_cols)
        df_transito_cedi['CANTIDAD'] = pd.to_numeric(df_transito_cedi['CANTIDAD'], errors='coerce').fillna(0)
        df_transito_agrupado = (
            df_transito_cedi.groupby('SKU', as_index=False)['CANTIDAD']
            .sum()
            .rename(columns={'CANTIDAD': 'COMPROMETIDO_TRANSITO_CEDI'})
        )
    else:
        df_transito_agrupado = pd.DataFrame(columns=['SKU', 'COMPROMETIDO_TRANSITO_CEDI'])

    df_resultado = pd.merge(df_resultado, df_transito_agrupado, on='SKU', how='left')
    df_resultado['COMPROMETIDO_TRANSITO_CEDI'] = df_resultado['COMPROMETIDO_TRANSITO_CEDI'].fillna(0)

    df_resultado['NECESIDAD'] = df_resultado['MINIMO'] - df_resultado['STOCK']
    df_resultado['NECESIDAD_CON_TRANSITO'] = df_resultado['MINIMO'] - df_resultado['STOCKTOTAL_INVENTARIO']

    minimo_valido = df_resultado['MINIMO'] > 0
    df_resultado['CUBRIMIENTO'] = pd.NA
    df_resultado.loc[minimo_valido, 'CUBRIMIENTO'] = (
        df_resultado.loc[minimo_valido, 'STOCK'] / df_resultado.loc[minimo_valido, 'MINIMO'] * 100
    ).round(1)
    df_resultado['CUBRIMIENTO_CON_TRANSITO'] = pd.NA
    df_resultado.loc[minimo_valido, 'CUBRIMIENTO_CON_TRANSITO'] = (
        df_resultado.loc[minimo_valido, 'STOCKTOTAL_INVENTARIO'] / df_resultado.loc[minimo_valido, 'MINIMO'] * 100
    ).round(1)

    # STOCK_CON_COMPROMISO = STOCK + TRANSITO + COMPROMETIDO_TRANSITO_CEDI (todo lo que hay o va a
    # haber disponible: lo físico, lo en tránsito de tblAgotados y lo comprometido aún no despachado).
    df_resultado['STOCK_CON_COMPROMISO'] = (
        df_resultado['STOCK'].fillna(0) + df_resultado['TRANSITO'].fillna(0) + df_resultado['COMPROMETIDO_TRANSITO_CEDI'].fillna(0)
    )
    df_resultado['CUBRIMIENTO_CON_COMPROMISO'] = pd.NA
    df_resultado.loc[minimo_valido, 'CUBRIMIENTO_CON_COMPROMISO'] = (
        df_resultado.loc[minimo_valido, 'STOCK_CON_COMPROMISO'] / df_resultado.loc[minimo_valido, 'MINIMO'] * 100
    ).round(1)

    columnas_finales = REQUIRED_SOURCE_COLUMNS + ['SKU', 'COMPROMETIDO_TRANSITO_CEDI'] + AGOTADOS_VALUE_COLS + [
        'NECESIDAD', 'NECESIDAD_CON_TRANSITO', 'CUBRIMIENTO', 'CUBRIMIENTO_CON_TRANSITO',
        'STOCK_CON_COMPROMISO', 'CUBRIMIENTO_CON_COMPROMISO'
    ]
    df_resultado = df_resultado[[c for c in columnas_finales if c in df_resultado.columns]]

    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        df_resultado.to_excel(writer, sheet_name='Validacion_Compromisos', index=False)
    output.seek(0)
    return output
