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


REQUIRED_COBERTURA_COLUMNS = ['CLIENTE', 'REFERENCIA', 'ARCHIVO ORIGEN']


def generar_reporte_cobertura_archivo(source_content: bytes) -> io.BytesIO:
    """
    A partir de un Excel con columnas CLIENTE (=CANAL en tblSolicitudUnidades), REFERENCIA y
    ARCHIVO ORIGEN, genera un reporte con dos hojas:
      - Cargado: dónde (tienda/código) ya está cargada cada combinación Cliente+Referencia en
        tblSolicitudUnidades.
      - No_Cargado: tiendas ACTIVAS de Maestra_Almacenes para ese mismo canal (FORMATO) donde la
        referencia todavía NO aparece cargada.
    """
    df_source = pd.read_excel(io.BytesIO(source_content), sheet_name=0, header=0, dtype={'REFERENCIA': str})
    df_source.columns = [str(c).strip().upper() for c in df_source.columns]

    faltantes_cols = [c for c in REQUIRED_COBERTURA_COLUMNS if c not in df_source.columns]
    if faltantes_cols:
        raise ValueError(f"Al archivo le faltan columnas requeridas: {faltantes_cols}")

    df_source['CLIENTE'] = df_source['CLIENTE'].astype(str).str.strip()
    df_source['REFERENCIA'] = df_source['REFERENCIA'].astype(str).str.strip()
    df_source['ARCHIVO ORIGEN'] = df_source['ARCHIVO ORIGEN'].astype(str).str.strip()
    df_source = df_source[
        (df_source['CLIENTE'] != '') & (df_source['CLIENTE'].str.lower() != 'nan') &
        (df_source['REFERENCIA'] != '') & (df_source['REFERENCIA'].str.lower() != 'nan')
    ]
    if df_source.empty:
        raise ValueError("El archivo no tiene filas válidas con CLIENTE y REFERENCIA.")

    clientes = sorted(df_source['CLIENTE'].unique().tolist())
    referencias = sorted(df_source['REFERENCIA'].unique().tolist())

    conn = pyodbc.connect(settings.get_connection_string())
    try:
        placeholders_canal = ",".join("?" for _ in clientes)
        placeholders_ref = ",".join("?" for _ in referencias)

        query_cargado = f"""
            SELECT
                s.CANAL,
                s.CDCDGO AS REFERENCIA,
                s.CODIGO,
                COALESCE(m.TIENDAS_II, s.CODIGO) AS TIENDA,
                COALESCE(m.ZONA, 'SIN ZONA') AS ZONA,
                MAX(s.SEGMENTACION) AS SEGMENTACION,
                MAX(s.USUARIO_INSERCION) AS USUARIO_INSERCION,
                MAX(s.FECHA_INSERCION) AS FECHA_INSERCION,
                SUM(s.UNIDADES) AS TOTAL_UNIDADES
            FROM [INTELIGENCIA].[dbo].[tblSolicitudUnidades] s
            LEFT JOIN MAESTRA_ALMACENES m ON s.CODIGO = m.EQ_COD2
            WHERE s.CANAL IN ({placeholders_canal})
              AND s.CDCDGO IN ({placeholders_ref})
              AND s.CODIGO LIKE 'CO%'
            GROUP BY s.CANAL, s.CDCDGO, s.CODIGO, COALESCE(m.TIENDAS_II, s.CODIGO), COALESCE(m.ZONA, 'SIN ZONA')
        """
        df_cargado = pd.read_sql(query_cargado, conn, params=clientes + referencias)

        query_activas = f"""
            SELECT EQ_COD2 AS CODIGO, TIENDAS_II AS TIENDA, FORMATO, CLIMA
            FROM MAESTRA_ALMACENES
            WHERE ESTADO IN ('ACTIVA', 'APERTURA')
              AND FORMATO IN ({placeholders_canal})
        """
        df_activas = pd.read_sql(query_activas, conn, params=clientes)
    finally:
        conn.close()

    for col in ['CANAL', 'REFERENCIA', 'CODIGO']:
        df_cargado[col] = df_cargado[col].astype(str).str.strip()
    if 'FECHA_INSERCION' in df_cargado.columns:
        df_cargado['FECHA_INSERCION'] = pd.to_datetime(df_cargado['FECHA_INSERCION'], errors='coerce')
    df_activas['CODIGO'] = df_activas['CODIGO'].astype(str).str.strip()
    df_activas['FORMATO'] = df_activas['FORMATO'].astype(str).str.strip()
    df_activas['TIENDA'] = df_activas['TIENDA'].fillna(df_activas['CODIGO']).astype(str).str.strip()
    df_activas['CLIMA'] = df_activas['CLIMA'].fillna('SIN DATO').astype(str).str.strip().replace('', 'SIN DATO')

    filas_cargado = []
    filas_no_cargado = []
    filas_cruce = []  # una fila por (tienda activa x referencia consultada), para el dashboard "Resumen"

    for _, fuente in df_source.iterrows():
        cliente = fuente['CLIENTE']
        referencia = fuente['REFERENCIA']
        archivo_origen = fuente['ARCHIVO ORIGEN']

        cargado_par = df_cargado[(df_cargado['CANAL'] == cliente) & (df_cargado['REFERENCIA'] == referencia)]
        for row in cargado_par.itertuples(index=False):
            filas_cargado.append({
                'CLIENTE': cliente,
                'REFERENCIA': referencia,
                'ARCHIVO_ORIGEN': archivo_origen,
                'CODIGO': row.CODIGO,
                'TIENDA': row.TIENDA,
                'ZONA': row.ZONA,
                'SEGMENTACION': row.SEGMENTACION,
                'USUARIO_INSERCION': row.USUARIO_INSERCION,
                'FECHA_INSERCION': row.FECHA_INSERCION,
                'UNIDADES': int(row.TOTAL_UNIDADES)
            })

        activas_canal = df_activas[df_activas['FORMATO'] == cliente]
        codigos_cargados = set(cargado_par['CODIGO'])
        total_activas = len(activas_canal)
        total_cargadas_activas = int(activas_canal['CODIGO'].isin(codigos_cargados).sum())
        total_faltantes = total_activas - total_cargadas_activas

        for row in activas_canal.itertuples(index=False):
            filas_cruce.append({
                'FORMATO': cliente,
                'CLIMA': row.CLIMA,
                'CARGADA': row.CODIGO in codigos_cargados
            })

        if total_cargadas_activas == 0:
            nota = f"No está cargada en ninguna tienda del formato {cliente} (0/{total_activas})."
        else:
            nota = (
                f"Cargada parcialmente en el formato {cliente}: {total_cargadas_activas} de {total_activas} "
                f"tiendas activas la tienen cargada, faltan {total_faltantes}."
            )

        faltantes_canal = activas_canal[~activas_canal['CODIGO'].isin(codigos_cargados)]
        for row in faltantes_canal.itertuples(index=False):
            filas_no_cargado.append({
                'CLIENTE': cliente,
                'REFERENCIA': referencia,
                'ARCHIVO_ORIGEN': archivo_origen,
                'EQ_COD': row.CODIGO,
                'TIENDAS_II': row.TIENDA,
                'FORMATO': row.FORMATO,
                'NOTAS': nota
            })

    df_out_cargado = pd.DataFrame(filas_cargado, columns=[
        'CLIENTE', 'REFERENCIA', 'ARCHIVO_ORIGEN', 'CODIGO', 'TIENDA', 'ZONA',
        'SEGMENTACION', 'USUARIO_INSERCION', 'FECHA_INSERCION', 'UNIDADES'
    ])
    df_out_no_cargado = pd.DataFrame(filas_no_cargado, columns=['CLIENTE', 'REFERENCIA', 'ARCHIVO_ORIGEN', 'EQ_COD', 'TIENDAS_II', 'FORMATO', 'NOTAS'])

    # --- Dashboard "Resumen" ---
    df_cruce = pd.DataFrame(filas_cruce, columns=['FORMATO', 'CLIMA', 'CARGADA'])

    total_referencias_distintas = int(df_source['REFERENCIA'].nunique())
    total_combinaciones = int(len(df_source))
    total_evaluadas = int(len(df_cruce))
    total_cargadas = int(df_cruce['CARGADA'].sum()) if total_evaluadas else 0
    total_faltantes_global = total_evaluadas - total_cargadas
    pct_global = round(total_cargadas / total_evaluadas * 100, 1) if total_evaluadas else 0.0

    def _resumen_cobertura(agrupado_por: list[str]) -> pd.DataFrame:
        if df_cruce.empty:
            return pd.DataFrame(columns=agrupado_por + ['Tiendas Evaluadas', 'Cargadas', 'Faltantes', '% Cobertura'])
        resumen = (
            df_cruce.groupby(agrupado_por)
                    .agg(**{'Tiendas Evaluadas': ('CARGADA', 'count'), 'Cargadas': ('CARGADA', 'sum')})
                    .reset_index()
        )
        resumen['Cargadas'] = resumen['Cargadas'].astype(int)
        resumen['Faltantes'] = resumen['Tiendas Evaluadas'] - resumen['Cargadas']
        resumen['% Cobertura'] = (resumen['Cargadas'] / resumen['Tiendas Evaluadas'] * 100).round(1)
        return resumen.sort_values(agrupado_por)

    resumen_formato = _resumen_cobertura(['FORMATO'])
    resumen_formato_clima = _resumen_cobertura(['FORMATO', 'CLIMA'])

    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        workbook = writer.book
        titulo_fmt = workbook.add_format({'bold': True, 'font_size': 14})
        etiqueta_fmt = workbook.add_format({'bold': True})
        subtitulo_fmt = workbook.add_format({'bold': True, 'font_size': 12, 'bg_color': '#EEF2FF'})

        ws = workbook.add_worksheet('Resumen')
        writer.sheets['Resumen'] = ws
        ws.set_column(0, 0, 26)
        ws.set_column(1, 5, 16)

        ws.write(0, 0, 'Resumen de Cobertura - Solicitud de Unidades', titulo_fmt)

        kpis = [
            ('Referencias distintas consultadas', total_referencias_distintas),
            ('Combinaciones Cliente + Referencia', total_combinaciones),
            ('Tiendas evaluadas (tienda x referencia)', total_evaluadas),
            ('Cargadas', total_cargadas),
            ('Faltantes', total_faltantes_global),
            ('% Cobertura global', f"{pct_global}%"),
        ]
        fila = 2
        for etiqueta, valor in kpis:
            ws.write(fila, 0, etiqueta, etiqueta_fmt)
            ws.write(fila, 1, valor)
            fila += 1

        fila += 1
        ws.write(fila, 0, 'Cobertura por Formato', subtitulo_fmt)
        fila += 1
        resumen_formato.to_excel(writer, sheet_name='Resumen', startrow=fila, index=False)
        fila += len(resumen_formato) + 3

        ws.write(fila, 0, 'Cobertura por Formato y Clima', subtitulo_fmt)
        fila += 1
        resumen_formato_clima.to_excel(writer, sheet_name='Resumen', startrow=fila, index=False)

        df_out_cargado.to_excel(writer, sheet_name='Cargado', index=False)
        df_out_no_cargado.to_excel(writer, sheet_name='No_Cargado', index=False)
    output.seek(0)
    return output
