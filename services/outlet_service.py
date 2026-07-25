import pandas as pd
import numpy as np
import pyodbc
import io
import warnings
from datetime import datetime
from config import settings


def _normalize_text_series(series: pd.Series) -> pd.Series:
    """Normaliza una serie de texto para cruces: string, sin espacios y en mayúsculas."""
    return series.astype(str).str.strip().str.upper()


def load_tc_inventory_sheets(tc_content: bytes):
    """Carga y valida las hojas Cargue y Requerido del Excel TC INVENTARIO."""
    tc_file = io.BytesIO(tc_content)
    try:
        cargue_df = pd.read_excel(tc_file, sheet_name='Cargue', header=8)
        requerido_df = pd.read_excel(tc_file, sheet_name='Requerido', header=7)
    except ValueError as exc:
        raise ValueError(f"El archivo TC INVENTARIO no tiene las hojas esperadas: {exc}") from exc

    required_cargue_columns = {'EQ_COD2', 'SABANA'}
    required_requerido_columns = {'EQ_COD2', 'GENERO', 'TIPO_DE_PRENDA', 'TALLA', 'Requerido', 'PRIORIDAD'}

    missing_cargue = required_cargue_columns - set(cargue_df.columns)
    missing_requerido = required_requerido_columns - set(requerido_df.columns)

    if missing_cargue or missing_requerido:
        details = []
        if missing_cargue:
            details.append(f"hoja Cargue: faltan columnas {sorted(missing_cargue)}")
        if missing_requerido:
            details.append(f"hoja Requerido: faltan columnas {sorted(missing_requerido)}")
        raise ValueError("Estructura inválida del archivo TC INVENTARIO: " + "; ".join(details))

    return cargue_df, requerido_df

warnings.filterwarnings("ignore")

# Rutas de red estáticas
RUTA_MAESTRA_DCTO = r"\\10.10.10.56\InteligenciaNegocios\INTELIGENCIA\Maestras\MAESTRA DE DESCUENTOS TEXTIL.xlsb"
RUTA_MATRIZ = r"\\10.10.10.56\InteligenciaNegocios\INTELIGENCIA\ANGEL\Proyecto Segmentacion\BD_Segmentacion.xlsx"
RUTA_CICLICIDAD = r"\\10.10.10.56\InteligenciaNegocios\INTELIGENCIA\ANGEL\Proyecto Segmentacion\Ciclicidad.xlsx"

def generate_sabana_outlet(tc_content: bytes):
    """
    Replica la lógica del notebook Sabanas_outlet.ipynb integrándola al proyecto.
    """
    
    # 1. Conexiones a Bases de Datos
    conn_bod = pyodbc.connect(settings.get_connection_string("bodega"))
    conn_inte = pyodbc.connect(settings.get_connection_string("default"))
    conn_abast = pyodbc.connect(settings.get_connection_string("parametros"))
    conn_inv = pyodbc.connect(settings.get_connection_string("stocks"))

    # 2. Extracción de Datos SQL
    
    # Compromisos (Servidor 36)
    SQL_QUERY_COMP = """
    SELECT
        TRIM(f440_id_ubicacion_ent) AS ID,
        TRIM(i.f120_referencia) AS REFERENCIA,
        TRIM(ext.f121_id_ext2_detalle) AS TALLA,
        TRIM(ext.f121_id_ext1_detalle) AS COLOR,
        mov.f441_cant1_comprometida AS COMPROMISO
    FROM dbo.t440_docto_req_int AS doc
    INNER JOIN dbo.t441_movto_req_int AS mov ON doc.f440_rowid = mov.f441_rowid_docto_req_int AND mov.f441_cant1_comprometida > 0
    LEFT JOIN dbo.t121_mc_items_extensiones AS ext ON mov.f441_rowid_item_ext = ext.f121_rowid
    LEFT JOIN dbo.t120_mc_items AS i ON ext.f121_rowid_item = i.f120_rowid
    WHERE doc.f440_fecha_ts_creacion > '2025-11-01';
    """
    df_COMP = pd.read_sql(SQL_QUERY_COMP, conn_bod)
    df_COMP['ID'] = df_COMP['ID'].str.replace(r'^T', 'CO', regex=True)
    # Agrupar para evitar duplicidad
    df_COMP = df_COMP.groupby(['ID', 'REFERENCIA', 'TALLA', 'COLOR'])['COMPROMISO'].sum().reset_index()

    # Inventario Tiendas (Servidor 26)
    SQL_QUERY_INV_TIENDAS = '''
    SELECT A.REFPROVEEDOR, [TALLA], [COLOR], [CODALMACEN], (STOCK + ENTRANSITO) INV_TOTAL
    FROM STOCKS S
    LEFT JOIN [dbo].[ARTICULOS] A ON S.[CODARTICULO] = A.[CODARTICULO]
    WHERE STOCK > 0 OR ENTRANSITO > 0
    '''
    df_inv = pd.read_sql(SQL_QUERY_INV_TIENDAS, conn_inv)
    df_inv = df_inv.groupby(['REFPROVEEDOR', 'TALLA', 'COLOR', 'CODALMACEN'])['INV_TOTAL'].sum().reset_index()
    conn_inv.close()

    # Inventario Bodega 100 (Servidor 36)
    SQL_QUERY_INV100 = """
    SELECT RTRIM(R.f120_referencia) AS Referencia, RTRIM(P.f121_id_ext2_detalle) AS Talla, 
           RTRIM(P.f121_id_ext1_detalle) AS Color, B.f150_id AS Bodega,
           CAST(SUM(E.f400_cant_existencia_1) AS INT) Existencia,
           CAST(SUM(E.f400_cant_existencia_1)-SUM(E.f400_cant_comprometida_1) AS INT) Disponible,
           CAST(SUM(E.f400_cant_comprometida_1) AS INT) Compromiso
    FROM t121_mc_items_extensiones P
    INNER JOIN t120_mc_items R ON P.f121_rowid_item = R.f120_rowid
    INNER JOIN t400_cm_existencia E ON P.f121_rowid = E.f400_rowid_item_ext
    INNER JOIN t150_mc_bodegas B ON E.f400_rowid_bodega = B.f150_rowid
    WHERE E.f400_cant_existencia_1 > 0 AND B.f150_id IN ('PT100')
    GROUP BY R.f120_referencia, P.f121_id_ext2_detalle, P.f121_id_ext1_detalle, B.f150_id;
    """
    df_inv100 = pd.read_sql(SQL_QUERY_INV100, conn_bod)
    conn_bod.close()

    # Parametrización y Tiendas (Servidor 1)
    df_parametrizacion = pd.read_sql("SELECT REFERENCIA, GRUPO, TIPO_DE_PRENDA, GENERO, PERSONAJE FROM PARAMETRIZACION", conn_inte)
    df_clasi = pd.read_sql("SELECT CodRef, CLASIFICACION FROM Clasificacion WHERE FECHA = (SELECT MAX(FECHA) FROM Clasificacion)", conn_abast)
    conn_abast.close()
    
    SQL_QUERY_TIENDAS = """
    SELECT EQ_COD2, FORMATO, ZONA_VENTAS, CLIMA, TIENDAS_II, TOP_VENTA, RANK_VTA, GENERO AS GENERO_TIENDA, NOTAS
    FROM MAESTRA_ALMACENES
    WHERE FORMATO IN ('MIC','LITTLE MIC','MOVIES-W','OUTLET MIC','OUTLET LITTLE MIC','OUTLET MOVIES') 
      AND CLIMA IN ('INTERMEDIO','FRIO','CALIDO') AND ESTADO IN ('ACTIVA', 'APERTURA');
    """
    df_tiendas_master = pd.read_sql(SQL_QUERY_TIENDAS, conn_inte)
    
    # Ventas 31 días (Servidor 1)
    SQL_QUERY_VENTAS = """
    SELECT CODALMACEN, REFERENCIA, COLOR, TALLA, UNIDADES
    FROM VentasColombia
    WHERE FECHA BETWEEN DATEADD(DAY, -31, CAST(GETDATE() AS DATE)) AND CAST(GETDATE() AS DATE)
    """
    df_ventas = pd.read_sql(SQL_QUERY_VENTAS, conn_inte)
    conn_inte.close()
    
    df_ventas = df_ventas.groupby(["CODALMACEN", "REFERENCIA", "TALLA", "COLOR"])["UNIDADES"].sum().reset_index()
    for col in ['CODALMACEN', 'REFERENCIA', 'TALLA', 'COLOR']:
        df_ventas[col] = df_ventas[col].str.replace(' ', '')

    # 3. Procesamiento de Lógica (Merges y Filtros)
    df_sabana = pd.merge(df_inv100, df_parametrizacion, left_on='Referencia', right_on='REFERENCIA', how='left')
    df_sabana = df_sabana[(df_sabana['GRUPO']=='TEXTIL') & (df_sabana['Disponible']>0) & (df_sabana['Talla']!='U')]
    df_sabana.drop('REFERENCIA', axis=1, inplace=True)

    df_maestra_dcto = pd.read_excel(RUTA_MAESTRA_DCTO, sheet_name='Maestra', header=2, usecols=['REF','OBS','CLASI ESTELARES','PROMOCIONAL ESCALA OUTLET'], engine='pyxlsb')
    df_sabana = pd.merge(df_sabana, df_maestra_dcto, left_on='Referencia', right_on='REF', how='left')
    df_sabana.drop('REF', axis=1, inplace=True)

    df_sabana = pd.merge(df_sabana, df_clasi, left_on='Referencia', right_on='CodRef', how='left')
    df_sabana['CLASIFICACION'].fillna(df_sabana['CLASI ESTELARES'], inplace=True)
    df_sabana['CLASIFICACION'] = np.where((df_sabana['CLASIFICACION']=='MTA') & (df_sabana['PROMOCIONAL ESCALA OUTLET']!="-"), "MTA-R", df_sabana['CLASIFICACION'])
    df_sabana.drop('CodRef', axis=1, inplace=True)

    clasificaciones_validas = ['MTA-CA', 'MTA-R', 'MTA-RD','MTA-O','MTA-OS']
    exclusiones = ['HALLOMIC 2022','HALLOMIC 2023','HALLOWEEN 2024','HALLOMIC 2021','UNIFORME DE NANAS','HALLOMIC 2020','HALLOWEEN 2025']
    df_sabana = df_sabana[df_sabana['CLASIFICACION'].isin(clasificaciones_validas)]
    df_sabana = df_sabana[~df_sabana['OBS'].isin(exclusiones)]

    # 4. Cargar TC INVENTARIO (desde el contenido subido)
    cargue_df, requerido_df = load_tc_inventory_sheets(tc_content)
    df_necesidad_tienda = cargue_df[['EQ_COD2', 'SABANA']].copy()
    df_necesidad_tienda = df_necesidad_tienda[df_necesidad_tienda['SABANA'].notna()]
    if df_necesidad_tienda.empty:
        raise ValueError("La hoja Cargue no tiene valores válidos en la columna SABANA.")

    df = pd.merge(df_sabana, df_necesidad_tienda, how='cross')
    df.rename(columns={'EQ_COD2': 'ID'}, inplace=True)
    df = df[df['SABANA'] > 0]

    # Tiendas Master y Segmentación
    df = pd.merge(df, df_tiendas_master, left_on='ID', right_on='EQ_COD2', how='left')
    df['ORDEN'] = df['RANK_VTA'].fillna(999).astype(int)
    df['ORDEN'] = np.where(df['ID']=="CO571", 1, df['ORDEN'])

    df_matriz = pd.read_excel(RUTA_MATRIZ, sheet_name='Matriz', header=0)
    df = pd.merge(df, df_matriz, on='GENERO_TIENDA', how='left')
    
    def get_genero(row):
        return row[row['GENERO']]
    df['AplicaGenero'] = df.apply(get_genero, axis=1)
    df = df[df['AplicaGenero'] == 1]

    df_requerido = requerido_df[['EQ_COD2', 'GENERO', 'TIPO_DE_PRENDA', 'TALLA', 'Requerido', 'PRIORIDAD']].copy()
    
    # Normalización de claves para asegurar el cruce
    for col in ['GENERO', 'TIPO_DE_PRENDA']:
        df[col] = _normalize_text_series(df[col])
        df_requerido[col] = _normalize_text_series(df_requerido[col])

    df['Talla_Norm'] = _normalize_text_series(df['Talla'])
    df_requerido['Talla_Norm'] = _normalize_text_series(df_requerido['TALLA'])

    df = pd.merge(df, df_requerido, left_on=['ID', 'GENERO', 'TIPO_DE_PRENDA', 'Talla_Norm'], right_on=['EQ_COD2', 'GENERO', 'TIPO_DE_PRENDA', 'Talla_Norm'], how='left')
    df.drop(['EQ_COD2', 'TALLA'], axis=1, inplace=True, errors='ignore')
    if df['Requerido'].isna().all():
        raise ValueError(
            "No se encontraron requerimientos válidos en la hoja Requerido del TC INVENTARIO. Revise que EQ_COD2, GENERO, TIPO_DE_PRENDA y TALLA coincidan con los datos del archivo."
        )
    df = df.sort_values(by=['ORDEN', 'PRIORIDAD'], ascending=[True, False])

    # 5. Merges de Inventario Tienda, Ventas y Compromisos
    # Normalización para los cruces de ventas e inventario
    for df_tmp in [df_ventas, df_inv, df_COMP]:
        for col in df_tmp.columns:
            if col in ['CODALMACEN', 'REFERENCIA', 'TALLA', 'COLOR', 'REFPROVEEDOR', 'ID']:
                df_tmp[col] = df_tmp[col].astype(str).str.strip().str.upper()

    df['Ref_Norm'] = df['Referencia'].astype(str).str.strip().str.upper()
    df['Color_Norm'] = df['Color'].astype(str).str.strip().str.upper()
    # Talla_Norm ya fue creada arriba

    df = pd.merge(df, df_ventas, left_on=['ID','Ref_Norm','Talla_Norm','Color_Norm'], right_on=['CODALMACEN','REFERENCIA','TALLA','COLOR'], how='left')
    df.drop(['CODALMACEN','REFERENCIA','TALLA','COLOR'], axis=1, inplace=True, errors='ignore')
    df['UNIDADES'] = df['UNIDADES'].fillna(0).astype(int)
    
    df_inv['CODALMACEN_FULL'] = "CO" + df_inv['CODALMACEN'].astype(str)
    df = pd.merge(df, df_inv, left_on=['ID','Ref_Norm','Talla_Norm','Color_Norm'], right_on=['CODALMACEN_FULL','REFPROVEEDOR','TALLA','COLOR'], how='left')
    df.drop(['CODALMACEN','CODALMACEN_FULL','REFPROVEEDOR','TALLA','COLOR'], axis=1, inplace=True, errors='ignore')
    df['INV_TOTAL'] = df['INV_TOTAL'].fillna(0).astype(int)
    
    df = pd.merge(df, df_COMP, left_on=['ID','Ref_Norm','Talla_Norm','Color_Norm'], right_on=['ID','REFERENCIA','TALLA','COLOR'], how='left')
    df['COMPROMISO'] = df['COMPROMISO'].fillna(0).astype(int)
    
    df.drop(['REFERENCIA','TALLA','COLOR','Ref_Norm','Color_Norm','Talla_Norm'], axis=1, inplace=True, errors='ignore')
    
    # Columna de Auditoría
    df['Ya_Tenia_Stock'] = np.where(df['INV_TOTAL'] > 0, 'SI', 'NO')

    # Ciclicidad
    df_ciclicidad = pd.read_excel(RUTA_CICLICIDAD, sheet_name='Sheet1', usecols=['GENERO','TIPO_DE_PRENDA','FACTOR','FACTOR SABANA'])
    df_ciclicidad = df_ciclicidad.drop_duplicates()
    df = pd.merge(df, df_ciclicidad, on=['GENERO','TIPO_DE_PRENDA'], how='left')

    # 6. Cálculo de NECESIDAD
    tiendas_especiales = ["CO570", "CO571", "CO574", "CO584", "CO746", "CO889", "CO903", "CO105", "CO108", "CO111", "CO112", "CO117", "CO153", "CO423", "CO710", "CO744", "CO754", "CO890"]
    curva_std, curva_especial = 5, 10
    
    df['NECESIDAD'] = np.where(
        df['ID'].isin(tiendas_especiales),
        np.maximum(df['UNIDADES'] + curva_especial - df['INV_TOTAL'] - df['COMPROMISO'], 0),
        np.maximum(df['UNIDADES'] + curva_std - df['INV_TOTAL'] - df['COMPROMISO'], 0)
    )
    df['NECESIDAD'] = np.where(df['Requerido'] <= 0, 0, df['NECESIDAD'])
    df['NECESIDAD'] = np.where((df['TIPO_DE_PRENDA']=='CHAQUETA') & (df['CLIMA']!='FRIO'), 0, df['NECESIDAD'])
    df['NECESIDAD'] = np.where((df['ID']=='CO766') & (df['CLASIFICACION'].isin(['MTA-O','MTA-OS'])), 0, df['NECESIDAD'])

    # 7. Algoritmo de Asignación (Loop)
    df['SabanaFinal'] = 0
    df['Disponible2'] = df['Disponible']
    tiendas_list = df['ID'].unique().tolist()

    for tid in tiendas_list:
        df['NECESIDAD2'] = np.where(df['ID'] == tid, df['NECESIDAD'], 0)
        df['AcumuladoNec'] = df.groupby(['Referencia', 'Talla','Color'])['NECESIDAD2'].cumsum()
        df['Asignado'] = np.where(df['AcumuladoNec'] <= df['Disponible'], df['NECESIDAD2'], np.maximum(df['Disponible']-(df['AcumuladoNec']-df['NECESIDAD2']), 0))
        
        df['AcumuladoReq'] = df.groupby(['GENERO', 'TIPO_DE_PRENDA','Talla','ID'])['Asignado'].cumsum()
        df['Sabana'] = np.where(df['AcumuladoReq'] <= df['Requerido'].fillna(0), df['Asignado'], np.maximum(round(df['Requerido'].fillna(0), 0)-(df['AcumuladoReq']-df['Asignado']), 0))
        
        df['AcumuladoTech'] = df.groupby(['ID'])['Sabana'].cumsum()
        df['SabanaFinal'] = np.where(df['ID'] == tid, np.where(df['AcumuladoTech'] <= df['SABANA'], df['Sabana'], np.maximum(round(df['SABANA'], 0)-(df['AcumuladoTech']-df['Sabana']), 0)), df['SabanaFinal'])
        
        df['Gastado'] = df.groupby(['Referencia', 'Talla','Color'])['SabanaFinal'].transform('sum')
        df['Disponible'] = df['Disponible2'] - df['Gastado']

    df['SabanaFinal'] = df['SabanaFinal'].fillna(0).astype(int)
    
    # 8. Exportar resultado
    output = io.BytesIO()
    df.to_excel(output, sheet_name='Hoja1', index=False)
    output.seek(0)
    
    return output
