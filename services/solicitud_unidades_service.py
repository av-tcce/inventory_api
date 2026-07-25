import io
import pyodbc
import pandas as pd
from config import settings


def get_solicitud_unidades_dataframe(cdcdgo: str) -> pd.DataFrame:
    """Devuelve un DataFrame con los registros de tblSolicitudUnidades para un CDCDGO."""
    if not cdcdgo or not str(cdcdgo).strip():
        raise ValueError("El campo CDCDGO no puede estar vacío.")

    query = """
    SELECT *
    FROM [INTELIGENCIA].[dbo].[tblSolicitudUnidades]
    WHERE CDCDGO = ?
      AND CODIGO LIKE 'CO%'
    """

    conn = pyodbc.connect(settings.get_connection_string())
    try:
        df = pd.read_sql(query, conn, params=[str(cdcdgo).strip()])
    finally:
        conn.close()

    return df


def consultar_solicitud_unidades(cdcdgo: str) -> list[dict]:
    """Consulta la tabla tblSolicitudUnidades en la base INTELIGENCIA por CDCDGO."""
    df = get_solicitud_unidades_dataframe(cdcdgo)
    return df.fillna("").to_dict(orient="records")


def resumen_solicitud_unidades(codigo_prefix: str = "CO") -> dict:
    """Retorna resumen de unidades cargadas en tblSolicitudUnidades por tienda y zona."""
    conn = pyodbc.connect(settings.get_connection_string())
    try:
        query = """
        SELECT
            s.CODIGO,
            COALESCE(m.TIENDAS_II, s.CODIGO) AS TIENDA,
            COALESCE(m.ZONA, 'SIN ZONA') AS ZONA,
            SUM(s.UNIDADES) AS TOTAL_UNIDADES,
            COUNT(*) AS REGISTROS
        FROM [INTELIGENCIA].[dbo].[tblSolicitudUnidades] s
        LEFT JOIN MAESTRA_ALMACENES m ON s.CODIGO = m.EQ_COD2
        WHERE s.CODIGO LIKE ?
        GROUP BY s.CODIGO, COALESCE(m.TIENDAS_II, s.CODIGO), COALESCE(m.ZONA, 'SIN ZONA')
        """
        df = pd.read_sql(query, conn, params=[f"{codigo_prefix}%"])
    finally:
        conn.close()

    if df.empty:
        return {
            "summary": {
                "total_unidades": 0,
                "total_registros": 0,
                "total_tiendas": 0,
                "total_zonas": 0
            },
            "by_store": [],
            "by_zone": []
        }

    summary = {
        "total_unidades": int(df["TOTAL_UNIDADES"].sum()),
        "total_registros": int(df["REGISTROS"].sum()),
        "total_tiendas": int(df["TIENDA"].nunique()),
        "total_zonas": int(df["ZONA"].nunique())
    }

    by_store = (
        df.sort_values("TOTAL_UNIDADES", ascending=False)
          .loc[:, ["CODIGO", "TIENDA", "ZONA", "TOTAL_UNIDADES", "REGISTROS"]]
          .to_dict(orient="records")
    )

    by_zone = (
        df.groupby("ZONA", as_index=False)
          .agg({"TOTAL_UNIDADES": "sum", "REGISTROS": "sum"})
          .sort_values("TOTAL_UNIDADES", ascending=False)
          .to_dict(orient="records")
    )

    return {
        "summary": summary,
        "by_store": by_store,
        "by_zone": by_zone
    }


def resumen_solicitud_unidades_por_referencia(cdcdgo: str) -> dict:
    """Retorna resumen de unidades para una referencia específica (CDCDGO)."""
    if not cdcdgo or not str(cdcdgo).strip():
        raise ValueError("El campo CDCDGO no puede estar vacío.")
    
    conn = pyodbc.connect(settings.get_connection_string())
    try:
        query = """
        SELECT
            s.CODIGO,
            COALESCE(m.TIENDAS_II, s.CODIGO) AS TIENDA,
            COALESCE(m.ZONA, 'SIN ZONA') AS ZONA,
            SUM(s.UNIDADES) AS TOTAL_UNIDADES,
            COUNT(*) AS REGISTROS
        FROM [INTELIGENCIA].[dbo].[tblSolicitudUnidades] s
        LEFT JOIN MAESTRA_ALMACENES m ON s.CODIGO = m.EQ_COD2
        WHERE s.CDCDGO = ?
        GROUP BY s.CODIGO, COALESCE(m.TIENDAS_II, s.CODIGO), COALESCE(m.ZONA, 'SIN ZONA')
        """
        df = pd.read_sql(query, conn, params=[str(cdcdgo).strip()])
    finally:
        conn.close()

    if df.empty:
        return {
            "cdcdgo": cdcdgo,
            "summary": {
                "total_unidades": 0,
                "total_registros": 0,
                "total_tiendas": 0,
                "total_zonas": 0
            },
            "by_store": [],
            "by_zone": []
        }

    summary = {
        "total_unidades": int(df["TOTAL_UNIDADES"].sum()),
        "total_registros": int(df["REGISTROS"].sum()),
        "total_tiendas": int(df["TIENDA"].nunique()),
        "total_zonas": int(df["ZONA"].nunique())
    }

    by_store = (
        df.sort_values("TOTAL_UNIDADES", ascending=False)
          .loc[:, ["CODIGO", "TIENDA", "ZONA", "TOTAL_UNIDADES", "REGISTROS"]]
          .to_dict(orient="records")
    )

    by_zone = (
        df.groupby("ZONA", as_index=False)
          .agg({"TOTAL_UNIDADES": "sum", "REGISTROS": "sum"})
          .sort_values("TOTAL_UNIDADES", ascending=False)
          .to_dict(orient="records")
    )

    return {
        "cdcdgo": cdcdgo,
        "summary": summary,
        "by_store": by_store,
        "by_zone": by_zone
    }
