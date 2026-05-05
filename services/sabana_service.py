import pandas as pd
import numpy as np
import pyodbc
import io
import warnings
from config import settings

warnings.filterwarnings("ignore")

def _read_robust_excel(content: bytes):
    """
    Lee un Excel buscando dinámicamente la fila de encabezados que contiene 'REFERENCIA'.
    """
    excel_file = pd.ExcelFile(io.BytesIO(content), engine='calamine')
    sheet_names = excel_file.sheet_names
    
    # Buscar 'BD' o similar, si no la primera
    target_sheet = next((s for s in sheet_names if s.strip().upper() == 'BD'), sheet_names[0])
    
    # Leer sin encabezados para buscar la fila correcta
    df_raw = pd.read_excel(excel_file, sheet_name=target_sheet, header=None, engine='calamine')
    
    header_idx = 0
    for i, row in df_raw.head(20).iterrows():
        row_str = [str(x).strip().upper() for x in row.values]
        if 'REFERENCIA' in row_str:
            header_idx = i
            break
            
    # Leer ahora sí con el encabezado correcto
    df = pd.read_excel(excel_file, sheet_name=target_sheet, header=header_idx, engine='calamine')
    df.columns = [str(c).strip().upper() for c in df.columns]
    
    # Mapeo flexible para columnas comunes
    col_map = {
        'COD ALMACEN': 'COID', 'COD_ALMACEN': 'COID', 'CODIGO': 'COID', 'COD ALM': 'COID',
        'UNIDADES': 'MINIMO', 'UNIDAD': 'MINIMO', 'CANTIDAD': 'MINIMO', 'CANT': 'MINIMO'
    }
    df = df.rename(columns=col_map)
    
    return df, target_sheet

def generate_sabana_mto(portafolio_content: bytes, sabana_ant_content: bytes, 
                        extra1_content: bytes = None, extra2_content: bytes = None):
    """
    Genera el consolidado en cascada: Sabana Anterior > Extra 1 > Extra 2.
    """
    
    # 1. Cargar Portafolio
    df_portafolio = pd.read_excel(io.BytesIO(portafolio_content), sheet_name='Portafolio', header=0, engine='calamine')
    df_portafolio.columns = [str(c).strip() for c in df_portafolio.columns]
    
    col_map_port = {
        'Género': 'GENERO', 'Genero': 'GENERO',
        'Tipo Prenda': 'TIPO DE PRENDA', 'Tipo de Prenda': 'TIPO DE PRENDA',
        'Licencia': 'LICENCIA',
        'Segmentación': 'SEG', 'Segmentacion': 'SEG',
        'Mes postura': 'MES POSTURA', 'Mes Postura': 'MES POSTURA'
    }
    df_portafolio = df_portafolio.rename(columns=col_map_port)

    # 2. Conexión SQL y MaxMin
    conn = pyodbc.connect(settings.get_connection_string())
    SQL_QUERY_MAXMIN = """
        SELECT FECHA, REFERENCIA, TALLA, COLOR, CODALMACEN, MINIMO
        FROM tblAgotados
        WHERE CAST(FECHA AS DATE) = CAST(GETDATE() AS DATE) AND MINIMO > 0 AND GRUPO = 'TEXTIL';
    """
    df_MaxMin = pd.read_sql(SQL_QUERY_MAXMIN, conn)

    df_consolidado = pd.merge(df_MaxMin, df_portafolio, left_on='REFERENCIA', right_on='Referencia', how='left')
    df_consolidado = df_consolidado[df_consolidado['Referencia'].notna()]
    df_consolidado['COID'] = df_consolidado['CODALMACEN']
    
    col_outlet = 'OUTLET' if 'OUTLET' in df_consolidado.columns else ('LINEA OUTLET UNICOS' if 'LINEA OUTLET UNICOS' in df_consolidado.columns else None)
    sel_cols = ['REFERENCIA', 'TALLA', 'COLOR', 'COID', 'MINIMO','Categoría','GENERO','TIPO DE PRENDA','Silueta',
                'LICENCIA','Estrategia','CLASIFICACIÓN LINE PLAN','SEG','MES POSTURA']
    if col_outlet: sel_cols.insert(13, col_outlet)

    df_consolidado = df_consolidado[sel_cols]
    df_consolidado['DATO'] = 'MAXMIN'

    # 3. Procesamiento en CASCADA (Sabana > Extra 1 > Extra 2)
    sources = [
        {'content': sabana_ant_content, 'label': 'SABANA MTO'},
        {'content': extra1_content, 'label': 'EXTRA 1'},
        {'content': extra2_content, 'label': 'EXTRA 2'}
    ]

    for src in sources:
        if src['content'] is not None and len(src['content']) > 0:
            try:
                df_src, sheet_name = _read_robust_excel(src['content'])
                
                required = ['REFERENCIA', 'TALLA', 'COLOR', 'COID', 'MINIMO']
                # Normalizar nombres de columnas de entrada para el mapeo
                df_src.columns = [str(c).strip().upper() for c in df_src.columns]
                
                missing = [c for c in required if c not in df_src.columns]
                if missing:
                    continue

                # Limpiar y Merge
                df_src['REFERENCIA'] = df_src['REFERENCIA'].astype(str)
                df_src = pd.merge(df_src[required], df_portafolio, left_on='REFERENCIA', right_on='Referencia', how='left')
                df_src = df_src[df_src['Referencia'].notna()]
                df_src = df_src[sel_cols]
                
                # FILTRO: Solo referencias que NO estén ya en el consolidado
                df_src = df_src[~df_src['REFERENCIA'].isin(df_consolidado['REFERENCIA'])]
                df_src['DATO'] = src['label']
                
                df_consolidado = pd.concat([df_consolidado, df_src], ignore_index=True)
            except Exception:
                continue # Si un archivo extra falla, seguimos con el proceso

    # 4. Distribución (tblSolicitudUnidades)
    # ... (mismo código de SQL Query Dist) ...
    cursor = conn.cursor()
    cursor.execute("SELECT TOP 0 * FROM [INTELIGENCIA].[dbo].[tblSolicitudUnidades]")
    columnas_solicitud = [column[0] for column in cursor.description]
    columna_color = "CDCLOR" if "CDCLOR" in columnas_solicitud else "'UNICO'"

    SQL_QUERY_DIST = f"""
        SELECT CDCDGO AS REFERENCIA, CDTLLA AS TALLA, {columna_color} AS COLOR, CODIGO AS COID, UNIDADES AS MINIMO
        FROM [INTELIGENCIA].[dbo].[tblSolicitudUnidades]
        WHERE CANAL IN ('MIC','LITTLE MIC','MOVIES-W','OUTLET MIC','OUTLET LITTLE MIC','OUTLET MOVIES') 
    """
    df_distribucion = pd.read_sql(SQL_QUERY_DIST, conn)
    
    df_distribucion = pd.merge(df_distribucion, df_portafolio, left_on='REFERENCIA', right_on='Referencia', how='left')
    df_distribucion = df_distribucion[df_distribucion['Referencia'].notna()]
    df_distribucion = df_distribucion[sel_cols]
    df_distribucion['DATO'] = ' SABANA DISTRIBUCION'
    df_distribucion = df_distribucion[~df_distribucion['REFERENCIA'].isin(df_consolidado['REFERENCIA'])]

    df_consolidado = pd.concat([df_consolidado, df_distribucion], ignore_index=True)

    # 5. Maestra Almacenes y Estados
    SQL_QUERY_ALM = """
        SELECT EQ_COD2 AS COID, TIENDAS_II, FORMATO, ESTADO, ZONA_VENTAS, GENERO AS GENERO_TIENDA,
               CLIMA, TOP_VENTA, MUEBLES, OBSER
        FROM MAESTRA_ALMACENES
        WHERE FORMATO IN ('MIC','LITTLE MIC','MOVIES-W','OUTLET MIC','OUTLET LITTLE MIC','OUTLET MOVIES') 
          AND ESTADO IN ('ACTIVA', 'APERTURA','INACTIVA','CERRADA');
    """
    df_almacenes = pd.read_sql(SQL_QUERY_ALM, conn)
    conn.close()

    df_Estado_Obs = df_almacenes[['COID','ESTADO','OBSER']]
    df_consolidado = pd.merge(df_consolidado, df_Estado_Obs, on='COID', how='left')
    
    df_consolidado['COID'] = np.where(df_consolidado['ESTADO'] == 'INACTIVA', 
                                      'CO' + df_consolidado['OBSER'].str[-3:], 
                                      df_consolidado['COID'])
    
    df_consolidado.drop(['ESTADO','OBSER'], axis=1, inplace=True)
    df_consolidado = pd.merge(df_consolidado, df_almacenes, on='COID', how='left')
    df_consolidado = df_consolidado[df_consolidado['ESTADO'].isin(['ACTIVA', 'APERTURA'])]
    df_consolidado['ID'] = df_consolidado['COID'].str.replace('CO', '', regex=False)

    # 6. Cálculo de Faltantes (Pendientes)
    df_faltantes = df_portafolio[~df_portafolio['Referencia'].isin(df_consolidado['REFERENCIA'])]
    
    # Filtros de negocio para faltantes (según script original)
    if 'Estado' in df_faltantes.columns:
        df_faltantes = df_faltantes[~df_faltantes['Estado'].isin(['POR PEDIDO', 'DISEÑO', 'DESARROLLO'])]
    if 'CLASIFICACIÓN ABASTECIMIENTO' in df_faltantes.columns:
        df_faltantes = df_faltantes[~df_faltantes['CLASIFICACIÓN ABASTECIMIENTO'].isin(['MTA-R', 'MTA-RD'])]

    # 7. Reordenar y Generar Excel
    final_cols = ['DATO','REFERENCIA','TALLA','COLOR','COID','ID','MINIMO','TIENDAS_II','FORMATO','ESTADO','ZONA_VENTAS','GENERO_TIENDA',
                  'CLIMA','TOP_VENTA','MUEBLES','Categoría','GENERO','TIPO DE PRENDA','Silueta','LICENCIA',
                  'Estrategia','CLASIFICACIÓN LINE PLAN','SEG','MES POSTURA']
    if col_outlet: final_cols.insert(23, col_outlet)
    
    df_consolidado = df_consolidado[final_cols]
    
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
        df_consolidado.to_excel(writer, sheet_name='BD', index=False)
        df_faltantes.to_excel(writer, sheet_name='Faltantes_Portafolio', index=False)
    output.seek(0)
    
    return output
