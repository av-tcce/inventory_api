import pandas as pd
import pyodbc
from config import settings


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


def get_referencias_matriculadas(fecha=None, codigo_tienda=None, pais="Colombia"):
    conn = None
    try:
        conn = pyodbc.connect(settings.get_connection_string())
        columns = _get_table_columns(conn, "tblAgotados")

        referencia_col = _find_column(columns, "REFERENCIA")
        grupo_col = _find_column(columns, "GRUPO")
        personaje_col = _find_column(columns, "PERSONAJE")
        tipo_prenda_col = _find_column(columns, "TIPO_DE_PRENDA", "TIPO PRENDA")
        minimo_col = _find_column(columns, "MINIMO")
        fecha_col = _find_column(columns, "FECHA")
        tienda_col = _find_column(columns, "CODALMACEN", "CODIGO_TIENDA", "TIENDA")
        tiendas_ii_col = _find_column(columns, "TIENDAS_II")
        clasificacion_procesada_col = _find_column(columns, "CLASIFICACION_PROCESADA", "CLASIFICACION PROCESADA")

        if not all([referencia_col, grupo_col, personaje_col, tipo_prenda_col, minimo_col, fecha_col, tienda_col]):
            missing = [name for name, present in {
                "REFERENCIA": referencia_col,
                "GRUPO": grupo_col,
                "PERSONAJE": personaje_col,
                "TIPO_DE_PRENDA": tipo_prenda_col,
                "MINIMO": minimo_col,
                "FECHA": fecha_col,
                "TIENDA": tienda_col,
            }.items() if not present]
            raise ValueError(f"No se encontraron columnas requeridas en tblAgotados: {missing}")

        tiendas_ii_select = (
            f"[{tiendas_ii_col}] AS TIENDAS_II"
            if tiendas_ii_col
            else "NULL AS TIENDAS_II"
        )
        clasificacion_select = (
            f"[{clasificacion_procesada_col}] AS CLASIFICACION_PROCESADA"
            if clasificacion_procesada_col
            else "NULL AS CLASIFICACION_PROCESADA"
        )

        query = f"""
            SELECT [{referencia_col}] AS REFERENCIA,
                   [{grupo_col}] AS GRUPO,
                   [{personaje_col}] AS PERSONAJE,
                   [{tipo_prenda_col}] AS TIPO_DE_PRENDA,
                   {tiendas_ii_select},
                   {clasificacion_select}
            FROM [dbo].[tblAgotados]
            WHERE 1=1
              AND [{minimo_col}] > 0
        """
        params = []

        if fecha:
            query += f" AND CAST([{fecha_col}] AS DATE) = ?"
            params.append(fecha)

        if codigo_tienda:
            query += f" AND [{tienda_col}] = ?"
            params.append(codigo_tienda)

        df = pd.read_sql(query, conn, params=params)
        return df
    except Exception as exc:
        raise RuntimeError(f"Error consultando referencias matriculadas: {exc}") from exc
    finally:
        if conn:
            conn.close()


def get_referencias_matriculadas_export(fecha=None, codigo_tienda=None, pais="Colombia"):
    conn = None
    try:
        conn = pyodbc.connect(settings.get_connection_string())
        columns = _get_table_columns(conn, "tblAgotados")

        minimo_col = _find_column(columns, "MINIMO")
        fecha_col = _find_column(columns, "FECHA")
        tienda_col = _find_column(columns, "CODALMACEN", "CODIGO_TIENDA", "TIENDA")

        if not all([minimo_col, fecha_col, tienda_col]):
            missing = [name for name, present in {
                "MINIMO": minimo_col,
                "FECHA": fecha_col,
                "TIENDA": tienda_col,
            }.items() if not present]
            raise ValueError(f"No se encontraron columnas requeridas en tblAgotados para exportar: {missing}")

        query = f"SELECT * FROM [dbo].[tblAgotados] WHERE [{minimo_col}] > 0"
        params = []

        if fecha:
            query += f" AND CAST([{fecha_col}] AS DATE) = ?"
            params.append(fecha)

        if codigo_tienda:
            query += f" AND [{tienda_col}] = ?"
            params.append(codigo_tienda)

        return pd.read_sql(query, conn, params=params)
    except Exception as exc:
        raise RuntimeError(f"Error exportando referencias matriculadas: {exc}") from exc
    finally:
        if conn:
            conn.close()


def get_referencias_matriculadas_summary(fecha=None, codigo_tienda=None, pais="Colombia"):
    df = get_referencias_matriculadas(fecha=fecha, codigo_tienda=codigo_tienda, pais=pais)

    if df.empty:
        return {
            "total_referencias_matriculadas": 0,
            "tienda_nombre": "",
            "por_grupo": {},
            "por_personaje": {},
            "por_tipo_prenda": {},
            "por_clasificacion_procesada": {},
            "por_clasificacion_procesada_por_grupo": {
                "TEXTIL": {},
                "NO TEXTIL": {}
            },
            "filtros": {
                "fecha": fecha,
                "codigo_tienda": codigo_tienda,
                "pais": pais,
            },
        }

    normalized = df.copy()
    if "CLASIFICACION_PROCESADA" not in normalized.columns:
        normalized["CLASIFICACION_PROCESADA"] = "Sin dato"
    if "TIENDAS_II" not in normalized.columns:
        normalized["TIENDAS_II"] = ""

    normalized["GRUPO"] = normalized["GRUPO"].fillna("Sin dato").astype(str).str.strip().replace({"": "Sin dato"})
    normalized["PERSONAJE"] = normalized["PERSONAJE"].fillna("Sin dato").astype(str).str.strip().replace({"": "Sin dato"})
    normalized["TIPO_DE_PRENDA"] = normalized["TIPO_DE_PRENDA"].fillna("Sin dato").astype(str).str.strip().replace({"": "Sin dato"})
    normalized["CLASIFICACION_PROCESADA"] = normalized["CLASIFICACION_PROCESADA"].fillna("Sin dato").astype(str).str.strip().replace({"": "Sin dato"})
    normalized["TIENDAS_II"] = normalized["TIENDAS_II"].fillna("").astype(str).str.strip()
    normalized["REFERENCIA"] = normalized["REFERENCIA"].fillna("").astype(str).str.strip()

    dedup = normalized.drop_duplicates(subset=["REFERENCIA", "GRUPO", "PERSONAJE", "TIPO_DE_PRENDA", "CLASIFICACION_PROCESADA", "TIENDAS_II"])

    tienda_values = normalized["TIENDAS_II"].loc[normalized["TIENDAS_II"] != ""].unique().tolist()
    tienda_nombre = tienda_values[0] if len(tienda_values) == 1 else (", ".join(tienda_values[:3]) + ("..." if len(tienda_values) > 3 else ""))

    summary = {
        "total_referencias_matriculadas": int(dedup["REFERENCIA"].nunique()),
        "tienda_nombre": tienda_nombre,
        "por_grupo": {
            str(key): int(value)
            for key, value in dedup.groupby("GRUPO")["REFERENCIA"].nunique().sort_values(ascending=False).to_dict().items()
        },
        "por_personaje": {
            str(key): int(value)
            for key, value in dedup.groupby("PERSONAJE")["REFERENCIA"].nunique().sort_values(ascending=False).to_dict().items()
        },
        "por_tipo_prenda": {
            str(key): int(value)
            for key, value in dedup.groupby("TIPO_DE_PRENDA")["REFERENCIA"].nunique().sort_values(ascending=False).to_dict().items()
        },
        "por_clasificacion_procesada": {
            str(key): int(value)
            for key, value in dedup.groupby("CLASIFICACION_PROCESADA")["REFERENCIA"].nunique().sort_values(ascending=False).to_dict().items()
        },
        "por_clasificacion_procesada_por_grupo": {
            group: {
                str(key): int(value)
                for key, value in dedup.loc[dedup["GRUPO"].str.upper() == group].groupby("CLASIFICACION_PROCESADA")["REFERENCIA"].nunique().sort_values(ascending=False).to_dict().items()
            }
            for group in ["TEXTIL", "NO TEXTIL"]
        },
        "filtros": {
            "fecha": fecha,
            "codigo_tienda": codigo_tienda,
            "pais": pais,
        },
    }
    return summary
