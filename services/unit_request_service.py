import pandas as pd
import numpy as np
import pyodbc
import io
import warnings
from datetime import datetime
from config import settings

warnings.filterwarnings("ignore")

import os

def generate_unit_request(
    solicitud_content: bytes,
    canal_filtro: str = 'Todos'
):
    """
    Logic ported from Solicitud_unidades 5.0.ipynb
    Now using static network paths for Matriz and Cargue as requested.
    """
    fecha_hoy = datetime.now().strftime("%d-%m-%Y")
    
    # Rutas UNC para evitar dependencia de letra de unidad Z:
    base_unc = r"\\10.10.10.56\InteligenciaNegocios"
    ruta_MATRIZ = os.path.join(base_unc, "INTELIGENCIA", "ANGEL", "Proyecto Segmentacion", "BD_Segmentacion.xlsx")
    Ruta_Cargue_Cadenas = os.path.join(base_unc, "INTELIGENCIA", "CADENAS 2025", "CARGUES CADENAS 2024.xlsx")
    # Ruta_destino (Escritorio)
    ruta_escritorio = os.path.join(os.path.expanduser("~"), "Desktop", "resultado.xlsx")

    # Definición de formatos por canal
    formatos_cadenas = "'EXITO','ÉXITO','JUMBO','SAO','E-COMMERCE'"
    formatos_tiendas = "'MIC','LITTLE MIC','MOVIES-W','OUTLET MIC','OUTLET LITTLE MIC','OUTLET MOVIES'"

    if canal_filtro == 'Cadenas':
        where_formato = f"FORMATO IN ({formatos_cadenas})"
    elif canal_filtro == 'Tiendas':
        where_formato = f"FORMATO IN ({formatos_tiendas})"
    else:
        where_formato = f"FORMATO IN ({formatos_tiendas}, {formatos_cadenas})"

    # 1. SQL: Maestra Almacenes
    conn_inte = pyodbc.connect(settings.get_connection_string())
    
    SQL_QUERY_ALM = f"""
    SELECT 
    EQ_COD2,
    FORMATO,
    ZONA_VENTAS,
    CLIMA,
    TIENDAS_II,
    TOP_VENTA,
    RANK_VTA,
    GENERO AS GENERO_TIENDA,
    NOTAS,
    ABRIGOS
    FROM MAESTRA_ALMACENES
    WHERE {where_formato}
      AND CLIMA IN ('INTERMEDIO','FRIO','CALIDO')
      AND ESTADO IN ('ACTIVA', 'APERTURA');
    """
    df_alm = pd.read_sql(SQL_QUERY_ALM, conn_inte)
    df_alm.rename(columns={
        'EQ_COD2': 'CODIGO',
        'FORMATO': 'CANAL',
        'TIENDAS_II': 'NOMBRE ALMACEN',
        'TOP_VENTA': 'TOP PDV',
        'ZONA_VENTAS': 'ZONA'
    }, inplace=True)

    # Nuevo registro para Aperturas
    nuevo_registro = pd.DataFrame({
        'CANAL': ['APERTURASC'], 
        'CODIGO': ['APERTURASC'],
        'NOMBRE ALMACEN': ['APERTURASC'],
        'ZONA': ['APERTURASC'],
        'CLIMA': ['APERTURASC'],
        'TOP PDV': ['AA'],
        'GENERO_TIENDA': ['BEBE-CDORES-KIDS-ADULTO']
    })
    df_alm = pd.concat([df_alm, nuevo_registro], ignore_index=True)

    # 2. Cargar Excels
    df2 = pd.read_excel(io.BytesIO(solicitud_content), sheet_name='DETALLE', header=0, dtype={'CDCDGO': str, 'CDTLLA': str})
    
    # Asegurarse de que existe la columna MUEBLE (si no existe, crearla con valor por defecto)
    if 'MUEBLE' not in df2.columns:
        df2['MUEBLE'] = '-'
    
    # Matriz de segmentación y Cargue (Rutas Estáticas)
    try:
        df4 = pd.read_excel(ruta_MATRIZ, sheet_name='Matriz', header=0)
        df_maestratp = pd.read_excel(ruta_MATRIZ, sheet_name='Genero Parametrizacion', header=0)
    except Exception as e:
        raise Exception(f"No se pudo leer la Matriz de Segmentación en {ruta_MATRIZ}. Verifique la conexión a la unidad Z:. Error: {str(e)}")

    try:
        df_cargue = pd.read_excel(Ruta_Cargue_Cadenas, sheet_name="CARGUE", header=0, usecols=['EQCOD','GENERO','TIPO DE PRENDA','MUEBLE','# REFERENCIAS'])
    except Exception as e:
        raise Exception(f"No se pudo leer el Cargue de Cadenas en {Ruta_Cargue_Cadenas}. Verifique la conexión a la unidad Z:. Error: {str(e)}")

    # 3. Procesamiento Inicial
    df3 = pd.merge(df2, df_alm, how='cross')

    def get_value(row):
        return row[row['TOP PDV']]

    df3['UNIDADES'] = df3.apply(get_value, axis=1)
    df3['UNIDADES'] = np.where(df3['CANAL'] == 'APERTURASC', df3['UNIDADES'] * 3, df3['UNIDADES'])

    df3 = pd.merge(df3, df4, on='GENERO_TIENDA', how='left')

    def get_genero(row):
        return row[row['GENERO']]

    df3['AplicaGenero'] = df3.apply(get_genero, axis=1)
    df3 = df3.loc[(df3['AplicaGenero'] == 1)]

    df3 = pd.merge(df3, df_maestratp, left_on=['GENERO','TIPOPRENDA'], right_on=['GENERO','TIPO DE PRENDA'], how='left')

    def get_tipo(row):
        if row['NOTAS'] in row.index:
            return row[row['NOTAS']]
        return 1

    df3['AplicaTipo'] = df3.apply(get_tipo, axis=1)
    df3 = df3.loc[(df3['AplicaTipo'] != 0)]

    df_cargue['MUEBLE'] = df_cargue['MUEBLE'].replace('MODA', '-')
    formatos_permitidos = ['ÉXITO', 'SAO','JUMBO']

    df_merge = df3[df3['CANAL'].isin(formatos_permitidos)].copy()
    df_no_merge = df3[~df3['CANAL'].isin(formatos_permitidos)].copy()

    if not df_merge.empty:
        df_merge = pd.merge(
            df_merge,
            df_cargue,
            left_on=['CODIGO', 'GENERO', 'TIPOPRENDA', 'MUEBLE'],
            right_on=['EQCOD', 'GENERO', 'TIPO DE PRENDA', 'MUEBLE'],
            how='left'
        )
    else:
        df_merge['# REFERENCIAS'] = np.nan

    df_no_merge['# REFERENCIAS'] = 1
    df3 = pd.concat([df_merge, df_no_merge], ignore_index=True)
    df3 = df3[~((df3['# REFERENCIAS'].isna()))]

    # 4. SQL: Ventas para Curvas
    df_Analizar = df3[['GENERO','TIPOPRENDA','CDTLLA']].drop_duplicates()

    SQL_QUERY_VENTAS = """
    SELECT 
        V.CODALMACEN, 
        TRIM(V.REFERENCIA) AS REFERENCIA, 
        V.COLOR, 
        TRIM(V.TALLA) AS TALLA, 
        V.UNIDADES, 
        V.FECHA,
        P.GENERO,
        P.TIPO_DE_PRENDA,
        P.SILUETA,
        P.GRUPO,
        P.PERSONAJE,
        T.FORMATO,
        T.CLIMA
    FROM VentasColombia V
    LEFT JOIN PARAMETRIZACION P
        ON V.REFERENCIA = P.REFERENCIA
    LEFT JOIN MAESTRA_ALMACENES T
        ON V.CODALMACEN = T.EQ_COD2
    WHERE 
        V.FECHA >= '2025-01-01'
        AND V.UNIDADES > 0
        AND P.GRUPO = 'TEXTIL'

    UNION ALL

    SELECT 
        VC.EQCOD AS CODALMACEN, 
        TRIM(VC.REFERENCIA) AS REFERENCIA, 
        VC.COLOR, 
        TRIM(VC.TALLA) AS TALLA, 
        VC.CANTIDAD AS UNIDADES, 
        VC.FECHA,
        P.GENERO,
        P.TIPO_DE_PRENDA,
        P.SILUETA,
        P.GRUPO,
        P.PERSONAJE,
        T.FORMATO,
        T.CLIMA
    FROM VentasCadenas VC
    LEFT JOIN PARAMETRIZACION P
        ON VC.REFERENCIA = P.REFERENCIA
    LEFT JOIN MAESTRA_ALMACENES T
        ON VC.EQCOD = T.EQ_COD2
    WHERE 
        VC.FECHA >= '2025-01-01'
        AND VC.CANTIDAD > 0
        AND P.GRUPO = 'TEXTIL'
    """
    df_ventas = pd.read_sql(SQL_QUERY_VENTAS, conn_inte)
    conn_inte.close()

    df_ventas = (
        df_ventas
        .drop(columns='FECHA')
        .groupby(['CODALMACEN', 'REFERENCIA', 'COLOR', 'TALLA', 
                  'GENERO', 'TIPO_DE_PRENDA', 'SILUETA', 'GRUPO', 
                  'PERSONAJE', 'FORMATO', 'CLIMA'], as_index=False)
        .agg({'UNIDADES': 'sum'})
    )

    df_ventas = pd.merge(df_ventas, df_Analizar, left_on=['GENERO','TIPO_DE_PRENDA','TALLA'], right_on=['GENERO','TIPOPRENDA','CDTLLA'], how='inner')

    df3['FORMATO'] = df3['CANAL']
    df3['TIPO_DE_PRENDA'] = df3['TIPOPRENDA']
    df3['TALLA'] = df3['CDTLLA']

    df3['FORMATO'] = df3['FORMATO'].replace({'OUTLET MIC': 'MIC', 'OUTLET MOVIES': 'MOVIES-W', 'OUTLET LITTLE MIC': 'LITTLE MIC'})

    # OJO Solo por lo de Demon Slayer (Portado tal cual del notebook)
    df_ventas['PERSONAJE'] = np.where(df_ventas['REFERENCIA'].isin(['93123846','931238479','93123848','93123849']), 'DEMON SLAYER', df_ventas['PERSONAJE'])

    # 5. Lógica de Jerarquía
    jerarquia = ['GENERO', 'TIPO_DE_PRENDA', 'FORMATO', 'CLIMA', 'SILUETA', 'PERSONAJE']
    df_resultado = df3.copy()

    for i in range(len(jerarquia), 1, -1):
        grupo = jerarquia[:i]
        nombre_columna = f'grupo{i}'

        df_ventas[nombre_columna] = df_ventas.groupby(grupo)['UNIDADES'].transform('sum')
        df_ventas[f'{nombre_columna}_TALLA'] = df_ventas.groupby(grupo + ['TALLA'])['UNIDADES'].transform('sum')

        columnas_merge = grupo + ['TALLA', nombre_columna, f'{nombre_columna}_TALLA']
        df_temp = df_ventas[columnas_merge].drop_duplicates()

        df_resultado = df_resultado.merge(df_temp, on=grupo + ['TALLA'], how='left')

    # Orden de tallas
    orden_tallas = ['0-3','3-6','6-9','9-12','12-18','18-24','2T','3T','4T','5T','6T','4','6','8','10','12','14','28', '30', '32', '34', '36', 'XS','S', 'M', 'L', 'XL']
    tallas_en_df = df_resultado['TALLA'].unique()
    tallas_extra = [t for t in tallas_en_df if t not in orden_tallas]
    orden_completo = orden_tallas + tallas_extra

    df_resultado['TALLA'] = pd.Categorical(df_resultado['TALLA'], categories=orden_completo, ordered=True)
    df_resultado = df_resultado.sort_values(by=['CODIGO', 'CDCDGO', 'TALLA'])

    # Rellenar grupos
    columnas_a_rellenar = [col for col in df_resultado.columns if col.startswith('grupo') and not col.endswith('_TALLA')]
    for col in columnas_a_rellenar:
        df_resultado[col] = df_resultado.groupby(['CODIGO', 'CDCDGO'])[col].transform(lambda x: x.bfill().ffill())

    columnas_talla = [col for col in df_resultado.columns if col.endswith('_TALLA')]
    df_resultado[columnas_talla] = df_resultado[columnas_talla].fillna(0)

    # Grupo mayor a 100 (Optimizado con fallback)
    grupos = [f'grupo{i}' for i in range(len(jerarquia), 1, -1)]
    def obtener_primer_grupo(row):
        # 1. Intentar encontrar el primer grupo que supere el umbral de 100 unidades (Jerarquía más específica)
        for nombre in grupos:
            if row[nombre] > 100:
                return nombre
        
        # 2. Fallback: Si ninguno llega a 100, buscar el que tenga el valor máximo (aunque sea pequeño)
        max_val = -1
        mejor_grupo = 'ninguno'
        for nombre in grupos:
            if row[nombre] > max_val and row[nombre] > 0:
                max_val = row[nombre]
                mejor_grupo = nombre
        
        return mejor_grupo

    df_resultado['GRUPO_MAYOR_100'] = df_resultado.apply(obtener_primer_grupo, axis=1)

    # Ratio
    def calcular_ratio(row):
        grupo = row['GRUPO_MAYOR_100']
        if grupo == 'ninguno':
            return np.nan
        base = row[grupo]
        talla = row[f'{grupo}_TALLA']
        return talla / base if base else np.nan

    df_resultado['PARTICIPACION_TALLA'] = df_resultado.apply(calcular_ratio, axis=1)
    
    # Fallback final: Si la categoría NO tiene ventas en absoluto (referencia muy nueva o nicho)
    # se asigna una distribución uniforme (1 / cantidad de tallas) para evitar blancos.
    df_resultado['PARTICIPACION_TALLA'] = df_resultado.groupby(['CODIGO', 'CDCDGO'])['PARTICIPACION_TALLA'].transform(
        lambda x: x.fillna(1.0 / len(x)) if x.isnull().all() else x
    )

    # Suavizado y rellenos
    df_resultado['PREV'] = df_resultado.groupby(['CODIGO', 'CDCDGO'])['PARTICIPACION_TALLA'].shift(1)
    df_resultado['NEXT'] = df_resultado.groupby(['CODIGO', 'CDCDGO'])['PARTICIPACION_TALLA'].shift(-1)
    df_resultado['REFERENCIA_CERCANA'] = df_resultado[['NEXT', 'PREV']].bfill(axis=1).ffill(axis=1).iloc[:, 0]
    
    condicion = df_resultado['PARTICIPACION_TALLA'] < 0.5 * df_resultado['REFERENCIA_CERCANA']
    df_resultado.loc[condicion, 'PARTICIPACION_TALLA'] = np.nan
    df_resultado.drop(['PREV', 'NEXT', 'REFERENCIA_CERCANA'], axis=1, inplace=True)

    df_resultado['PARTICIPACION_TALLA'] = df_resultado.groupby(['CODIGO', 'CDCDGO'])['PARTICIPACION_TALLA'].transform(lambda x: x.bfill().ffill())

    df_resultado['SUMATEMP'] = df_resultado.groupby(['CODIGO', 'CDCDGO'])['PARTICIPACION_TALLA'].transform('sum')
    df_resultado['NUEVA_PART'] = df_resultado['PARTICIPACION_TALLA'] / df_resultado['SUMATEMP']
    df_resultado['SUMAUNDS'] = df_resultado.groupby(['CODIGO', 'CDCDGO'])['UNIDADES'].transform('sum')

    df_resultado['NUEVA CURVA'] = np.where(df_resultado['SUMAUNDS'] < 8, 
                                           np.maximum((df_resultado['SUMAUNDS'] * df_resultado['NUEVA_PART']).round(0), 1),
                                           np.maximum((df_resultado['SUMAUNDS'] * df_resultado['NUEVA_PART']).round(0), 2))

    df_resultado['UNIDADES'] = df_resultado['NUEVA CURVA']
    df_solicitudUnds = df_resultado[['CANAL','CDCDGO','CDTLLA','CODIGO','NOMBRE ALMACEN','ZONA','CLIMA','UNIDADES','TOP PDV']]

    # 6. Exportar a buffer y Opcionalmente a Escritorio
    try:
        df_solicitudUnds.to_excel(ruta_escritorio, sheet_name='Hoja1', index=False)
        print(f"Copia guardada exitosamente en {ruta_escritorio}")
    except Exception as e:
        print(f"No se pudo guardar copia en escritorio: {e}")

    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        df_solicitudUnds.to_excel(writer, sheet_name='Hoja1', index=False)
    output.seek(0)
    
    return output
