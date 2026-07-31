import io
import pyodbc
import pandas as pd
from config import settings


def get_solicitud_unidades_dataframe(cdcdgos: list[str]) -> pd.DataFrame:
    """Devuelve un DataFrame con los registros de tblSolicitudUnidades para una o varias referencias CDCDGO."""
    cdcdgos = [str(c).strip() for c in (cdcdgos or []) if c and str(c).strip()]
    if not cdcdgos:
        raise ValueError("Debe proporcionar al menos una referencia CDCDGO.")

    placeholders = ",".join("?" for _ in cdcdgos)
    query = f"""
    SELECT *
    FROM [INTELIGENCIA].[dbo].[tblSolicitudUnidades]
    WHERE CDCDGO IN ({placeholders})
      AND CODIGO LIKE 'CO%'
    """

    conn = pyodbc.connect(settings.get_connection_string())
    try:
        df = pd.read_sql(query, conn, params=cdcdgos)
    finally:
        conn.close()

    return df


def consultar_solicitud_unidades(cdcdgos: list[str]) -> list[dict]:
    """Consulta la tabla tblSolicitudUnidades en la base INTELIGENCIA por una o varias referencias CDCDGO."""
    df = get_solicitud_unidades_dataframe(cdcdgos)
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


def resumen_solicitud_unidades_por_referencia(cdcdgos: list[str]) -> dict:
    """Retorna resumen de unidades para una o varias referencias (CDCDGO)."""
    cdcdgos = [str(c).strip() for c in (cdcdgos or []) if c and str(c).strip()]
    if not cdcdgos:
        raise ValueError("Debe proporcionar al menos una referencia CDCDGO.")

    conn = pyodbc.connect(settings.get_connection_string())
    try:
        placeholders = ",".join("?" for _ in cdcdgos)
        query = f"""
        SELECT
            s.CDCDGO,
            s.CODIGO,
            COALESCE(m.TIENDAS_II, s.CODIGO) AS TIENDA,
            COALESCE(m.ZONA, 'SIN ZONA') AS ZONA,
            SUM(s.UNIDADES) AS TOTAL_UNIDADES,
            COUNT(*) AS REGISTROS
        FROM [INTELIGENCIA].[dbo].[tblSolicitudUnidades] s
        LEFT JOIN MAESTRA_ALMACENES m ON s.CODIGO = m.EQ_COD2
        WHERE s.CDCDGO IN ({placeholders})
        GROUP BY s.CDCDGO, s.CODIGO, COALESCE(m.TIENDAS_II, s.CODIGO), COALESCE(m.ZONA, 'SIN ZONA')
        """
        df = pd.read_sql(query, conn, params=cdcdgos)
    finally:
        conn.close()

    if df.empty:
        return {
            "cdcdgos": cdcdgos,
            "summary": {
                "total_unidades": 0,
                "total_registros": 0,
                "total_tiendas": 0,
                "total_zonas": 0
            },
            "by_store": [],
            "by_zone": [],
            "by_reference": []
        }

    summary = {
        "total_unidades": int(df["TOTAL_UNIDADES"].sum()),
        "total_registros": int(df["REGISTROS"].sum()),
        "total_tiendas": int(df["TIENDA"].nunique()),
        "total_zonas": int(df["ZONA"].nunique())
    }

    by_store = (
        df.sort_values("TOTAL_UNIDADES", ascending=False)
          .loc[:, ["CDCDGO", "CODIGO", "TIENDA", "ZONA", "TOTAL_UNIDADES", "REGISTROS"]]
          .to_dict(orient="records")
    )

    by_zone = (
        df.groupby("ZONA", as_index=False)
          .agg({"TOTAL_UNIDADES": "sum", "REGISTROS": "sum"})
          .sort_values("TOTAL_UNIDADES", ascending=False)
          .to_dict(orient="records")
    )

    by_reference = (
        df.groupby("CDCDGO", as_index=False)
          .agg({"TOTAL_UNIDADES": "sum", "REGISTROS": "sum"})
          .sort_values("TOTAL_UNIDADES", ascending=False)
          .to_dict(orient="records")
    )

    return {
        "cdcdgos": cdcdgos,
        "summary": summary,
        "by_store": by_store,
        "by_zone": by_zone,
        "by_reference": by_reference
    }
