import io
import pyodbc
import pandas as pd
from config import settings

# Mismos canales que maneja el módulo de Solicitud de Unidades (unit_request_service.py):
# tiendas propias + cadenas. Se excluyen formatos que no son puntos de venta reales
# (bodegas, buffers, e-commerce placeholder, etc.)
FORMATOS_TIENDAS = ['MIC', 'LITTLE MIC', 'MOVIES-W', 'OUTLET MIC', 'OUTLET LITTLE MIC', 'OUTLET MOVIES']
FORMATOS_CADENAS = ['EXITO', 'ÉXITO', 'JUMBO', 'SAO', 'E-COMMERCE']
FORMATOS_VALIDOS = FORMATOS_TIENDAS + FORMATOS_CADENAS


def _cargar_tiendas_activas() -> pd.DataFrame:
    """Tiendas activas (o en apertura) de MAESTRA_ALMACENES para los canales soportados."""
    conn = pyodbc.connect(settings.get_connection_string())
    try:
        placeholders = ",".join("?" for _ in FORMATOS_VALIDOS)
        query = f"""
            SELECT EQ_COD2 AS CODIGO, TIENDAS_II AS TIENDA, FORMATO, TOP_VENTA, CLIMA
            FROM MAESTRA_ALMACENES
            WHERE ESTADO IN ('ACTIVA', 'APERTURA')
              AND FORMATO IN ({placeholders})
        """
        df = pd.read_sql(query, conn, params=FORMATOS_VALIDOS)
    finally:
        conn.close()

    df['CODIGO'] = df['CODIGO'].astype(str).str.strip()
    df['FORMATO'] = df['FORMATO'].astype(str).str.strip()
    df['TIENDA'] = df['TIENDA'].fillna(df['CODIGO']).astype(str).str.strip()
    df['TOP_VENTA'] = df['TOP_VENTA'].fillna('SIN DATO').astype(str).str.strip().replace('', 'SIN DATO')
    df['CLIMA'] = df['CLIMA'].fillna('SIN DATO').astype(str).str.strip().replace('', 'SIN DATO')
    return df


def _cargar_solicitud(referencias: list[str]) -> pd.DataFrame:
    """Pares (REFERENCIA, CODIGO de tienda, SEGMENTACION) que ya existen en tblSolicitudUnidades."""
    conn = pyodbc.connect(settings.get_connection_string())
    try:
        placeholders = ",".join("?" for _ in referencias)
        query = f"""
            SELECT DISTINCT CDCDGO AS REFERENCIA, CODIGO, SEGMENTACION
            FROM [INTELIGENCIA].[dbo].[tblSolicitudUnidades]
            WHERE CDCDGO IN ({placeholders})
              AND CODIGO LIKE 'CO%'
        """
        df = pd.read_sql(query, conn, params=referencias)
    finally:
        conn.close()

    df['REFERENCIA'] = df['REFERENCIA'].astype(str).str.strip()
    df['CODIGO'] = df['CODIGO'].astype(str).str.strip()
    return df


def _segmentacion_por_referencia(solicitud: pd.DataFrame, referencias: list[str]) -> dict:
    """La Segmentación es un atributo de la referencia: toma el valor más frecuente
    (no nulo) registrado para esa referencia en tblSolicitudUnidades."""
    resultado = {ref: None for ref in referencias}
    con_dato = solicitud[solicitud['SEGMENTACION'].notna() & (solicitud['SEGMENTACION'].astype(str).str.strip() != '')]
    for referencia, grupo in con_dato.groupby('REFERENCIA'):
        moda = grupo['SEGMENTACION'].astype(str).str.strip().mode()
        if not moda.empty:
            resultado[referencia] = moda.iloc[0]
    return resultado


def _breakdown_por_columna(subset: pd.DataFrame, columna: str) -> dict:
    """Para un subconjunto de tiendas (ya de un formato/referencia), agrupa por TOP_VENTA o CLIMA
    y retorna {valor: {"con": n, "activas": n}}. Los valores sin ninguna tienda simplemente no aparecen."""
    agrupado = subset.groupby(columna).agg(ACTIVAS=('CODIGO', 'count'), CON=('TIENE_REFERENCIA', 'sum'))
    return {
        str(valor): {"con": int(fila['CON']), "activas": int(fila['ACTIVAS'])}
        for valor, fila in agrupado.iterrows()
    }


def validar_pedidos(referencias: list[str]) -> dict:
    """
    Para cada referencia, valida -por Formato- en cuántas tiendas activas de MAESTRA_ALMACENES
    ya existe un registro en tblSolicitudUnidades y en cuántas falta. Cada fila de Formato incluye
    además un desglose de esa misma cobertura por Top de Venta y por Clima.
    """
    referencias = [str(r).strip() for r in (referencias or []) if r and str(r).strip()]
    if not referencias:
        raise ValueError("Debe proporcionar al menos una referencia.")

    tiendas = _cargar_tiendas_activas()
    if tiendas.empty:
        raise ValueError("No se encontraron tiendas activas para los formatos soportados en MAESTRA_ALMACENES.")

    solicitud = _cargar_solicitud(referencias)
    segmentacion_por_ref = _segmentacion_por_referencia(solicitud, referencias)

    resumen = []
    detalle = []

    for referencia in referencias:
        segmentacion = segmentacion_por_ref.get(referencia)
        codigos_con_referencia = set(solicitud.loc[solicitud['REFERENCIA'] == referencia, 'CODIGO'])

        cruce = tiendas.copy()
        cruce['TIENE_REFERENCIA'] = cruce['CODIGO'].isin(codigos_con_referencia)

        for row in cruce.itertuples(index=False):
            detalle.append({
                "referencia": referencia,
                "segmentacion": segmentacion,
                "formato": row.FORMATO,
                "top_venta": row.TOP_VENTA,
                "clima": row.CLIMA,
                "codigo": row.CODIGO,
                "tienda": row.TIENDA,
                "tiene_referencia": bool(row.TIENE_REFERENCIA)
            })

        for formato, subset in cruce.groupby('FORMATO'):
            activas = len(subset)
            con = int(subset['TIENE_REFERENCIA'].sum())
            resumen.append({
                "referencia": referencia,
                "segmentacion": segmentacion,
                "formato": formato,
                "tiendas_activas": activas,
                "tiendas_con": con,
                "tiendas_sin": activas - con,
                "pct_cobertura": round(con / activas * 100, 1) if activas else 0.0,
                "top_venta": _breakdown_por_columna(subset, 'TOP_VENTA'),
                "clima": _breakdown_por_columna(subset, 'CLIMA')
            })

    return {
        "referencias": referencias,
        "formatos_validados": sorted(tiendas['FORMATO'].unique().tolist()),
        "top_ventas_validados": sorted(tiendas['TOP_VENTA'].unique().tolist()),
        "climas_validados": sorted(tiendas['CLIMA'].unique().tolist()),
        "resumen": resumen,
        "detalle": detalle
    }


def generar_excel_validacion(data: dict) -> io.BytesIO:
    """Genera un Excel con la hoja Resumen (Formato + columnas por Top de Venta/Clima) y Detalle."""
    top_ventas = data.get('top_ventas_validados', [])
    climas = data.get('climas_validados', [])

    filas_resumen = []
    for fila in data.get('resumen', []):
        plano = {
            "referencia": fila["referencia"],
            "segmentacion": fila["segmentacion"],
            "formato": fila["formato"],
            "tiendas_activas": fila["tiendas_activas"],
            "tiendas_con": fila["tiendas_con"],
            "tiendas_sin": fila["tiendas_sin"],
            "pct_cobertura": fila["pct_cobertura"],
        }
        for valor in top_ventas:
            datos = fila["top_venta"].get(valor, {"con": 0, "activas": 0})
            plano[f"TopVenta {valor} - Con"] = datos["con"]
            plano[f"TopVenta {valor} - Activas"] = datos["activas"]
        for valor in climas:
            datos = fila["clima"].get(valor, {"con": 0, "activas": 0})
            plano[f"Clima {valor} - Con"] = datos["con"]
            plano[f"Clima {valor} - Activas"] = datos["activas"]
        filas_resumen.append(plano)

    df_resumen = pd.DataFrame(filas_resumen)
    df_detalle = pd.DataFrame(data.get('detalle', []))

    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        df_resumen.to_excel(writer, sheet_name='Resumen', index=False)
        df_detalle.to_excel(writer, sheet_name='Detalle', index=False)
    output.seek(0)
    return output
