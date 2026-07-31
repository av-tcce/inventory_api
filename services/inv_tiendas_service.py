import pyodbc
import pandas as pd
from config import settings


def _fetch_inventario_tiendas(fecha: str, warehouse_codes: list[str] = None, referencias: list[str] = None) -> pd.DataFrame:
    """Consulta inv_tiendas unida con PARAMETRIZACION y MAESTRA_ALMACENES para una fecha de inventario."""
    if not fecha or not str(fecha).strip():
        raise ValueError("Debe indicar la fecha de inventario a consultar.")

    conditions = ["CAST(i.FechaRegistro AS DATE) = ?", "i.PAIS = ?"]
    params = [str(fecha).strip(), "COLOMBIA"]

    warehouse_codes = [str(c).strip() for c in (warehouse_codes or []) if c and str(c).strip()]
    if warehouse_codes:
        placeholders = ",".join("?" for _ in warehouse_codes)
        conditions.append(f"i.WarehouseCode IN ({placeholders})")
        params.extend(warehouse_codes)

    referencias = [str(r).strip() for r in (referencias or []) if r and str(r).strip()]
    if referencias:
        placeholders = ",".join("?" for _ in referencias)
        conditions.append(f"i.Reference IN ({placeholders})")
        params.extend(referencias)

    where_clause = " AND ".join(conditions)

    query = f"""
    SELECT
        i.Id,
        i.FechaRegistro,
        i.PAIS,
        i.Reference,
        i.Size,
        i.Colour,
        i.WarehouseCode,
        i.ExistenceQuantity,
        i.InitialStock,
        i.TransitStock,
        i.TotalStock,
        p.DESCRIPCION,
        p.GRUPO,
        p.GENERO AS GENERO_PRODUCTO,
        p.TIPO_DE_PRENDA,
        p.PRENDA,
        p.MARCA,
        p.[COLECCIÓN],
        p.MUNDO,
        m.TIENDAS_II,
        m.FORMATO,
        m.CIUDAD,
        m.ZONA,
        m.ZONA_VENTAS,
        m.CLIMA,
        m.ESTADO
    FROM [INTELIGENCIA].[dbo].[inv_tiendas] i
    LEFT JOIN [INTELIGENCIA].[dbo].[PARAMETRIZACION] p ON i.Reference = p.REFERENCIA
    LEFT JOIN [INTELIGENCIA].[dbo].[MAESTRA_ALMACENES] m ON i.WarehouseCode = m.EQ_COD2
    WHERE {where_clause}
    """

    conn = pyodbc.connect(settings.get_connection_string())
    try:
        df = pd.read_sql(query, conn, params=params)
    finally:
        conn.close()

    return df


def resumen_inventario_tiendas(fecha: str, warehouse_codes: list[str] = None, referencias: list[str] = None) -> dict:
    """Retorna un resumen general y por formato del inventario de tiendas para una fecha dada."""
    df = _fetch_inventario_tiendas(fecha, warehouse_codes, referencias)

    if df.empty:
        return {
            "fecha": fecha,
            "summary": {
                "total_existencia": 0,
                "total_stock": 0,
                "total_inicial": 0,
                "total_transito": 0,
                "total_tiendas": 0,
                "total_referencias": 0,
                "total_registros": 0
            },
            "by_format": [],
            "by_group": []
        }

    df["ExistenceQuantity"] = df["ExistenceQuantity"].fillna(0)
    df["InitialStock"] = df["InitialStock"].fillna(0)
    df["TransitStock"] = df["TransitStock"].fillna(0)
    df["TotalStock"] = df["TotalStock"].fillna(0)

    summary = {
        "total_existencia": int(df["ExistenceQuantity"].sum()),
        "total_stock": int(df["TotalStock"].sum()),
        "total_inicial": int(df["InitialStock"].sum()),
        "total_transito": int(df["TransitStock"].sum()),
        "total_tiendas": int(df["WarehouseCode"].nunique()),
        "total_referencias": int(df["Reference"].nunique()),
        "total_registros": int(len(df))
    }

    by_format = (
        df.assign(FORMATO=df["FORMATO"].fillna("SIN FORMATO"))
          .groupby("FORMATO", as_index=False)
          .agg(
              TOTAL_EXISTENCIA=("ExistenceQuantity", "sum"),
              TOTAL_STOCK=("TotalStock", "sum"),
              TOTAL_TIENDAS=("WarehouseCode", "nunique"),
              REGISTROS=("Id", "count")
          )
          .sort_values("TOTAL_STOCK", ascending=False)
          .to_dict(orient="records")
    )

    by_group = (
        df.assign(GRUPO=df["GRUPO"].fillna("SIN GRUPO"))
          .groupby("GRUPO", as_index=False)
          .agg(
              TOTAL_EXISTENCIA=("ExistenceQuantity", "sum"),
              TOTAL_STOCK=("TotalStock", "sum"),
              TOTAL_REFERENCIAS=("Reference", "nunique"),
              REGISTROS=("Id", "count")
          )
          .sort_values("TOTAL_STOCK", ascending=False)
          .to_dict(orient="records")
    )

    return {
        "fecha": fecha,
        "summary": summary,
        "by_format": by_format,
        "by_group": by_group
    }


def exportar_inventario_tiendas(fecha: str, warehouse_codes: list[str] = None, referencias: list[str] = None) -> pd.DataFrame:
    """Devuelve la sábana completa (detalle) de inventario de tiendas para exportar a Excel."""
    return _fetch_inventario_tiendas(fecha, warehouse_codes, referencias)
