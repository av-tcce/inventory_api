import pandas as pd
import pyodbc
import io
from config import settings

from datetime import datetime

def get_clasificacion_data(fecha: str, referencia: str = None):
    """
    Retorna los datos y estadísticas de clasificación para la última carga de la semana
    correspondiente a la fecha proporcionada.
    """
    conn = None
    try:
        conn = pyodbc.connect(settings.get_connection_string(server="parametros"))
        
        # Convertir fecha a objeto datetime para obtener semana y año
        dt = datetime.strptime(fecha, '%Y-%m-%d')
        year, week, _ = dt.isocalendar()
        
        # Primero buscamos la última fecha cargada en esa semana específica
        query_date = f"""
            SELECT MAX([Fecha]) as UltimaFecha
            FROM [Parametros].[dbo].[Clasificacion]
            WHERE DATEPART(isowk, [Fecha]) = {week} AND YEAR([Fecha]) = {year}
        """
        df_date = pd.read_sql(query_date, conn)
        
        if df_date.empty or df_date['UltimaFecha'].iloc[0] is None:
            return pd.DataFrame(), {}
            
        ultima_fecha = df_date['UltimaFecha'].iloc[0]
        
        # Filtro de referencia opcional
        ref_filter = ""
        if referencia and referencia.strip():
            ref_filter = f"AND [CodRef] LIKE '%{referencia.strip()}%'"

        # Consultamos el set completo para la última fecha de esa semana
        query = f"""
            SELECT 
                [Fecha], [Semana], [CodRef], [MARCA], [GENERO], [TIPO], 
                [Macro_Micro], [ICONICA], [CLASIFICACION], [MES_POST], 
                [CICLO_HASTA], [MARCA2], [MES], [UltimoXMes]
            FROM [Parametros].[dbo].[Clasificacion]
            WHERE [Fecha] = '{ultima_fecha}'
            {ref_filter}
        """
        
        df = pd.read_sql(query, conn)
        
        if df.empty:
            return df, {}

        # Cálculo de Estadísticas Generales
        total = len(df)
        stats_general = df['CLASIFICACION'].value_counts(normalize=True).mul(100).round(1).to_dict()
        
        # Cálculo por Marca
        stats_marca = {}
        for marca, group in df.groupby('MARCA'):
            m_total = len(group)
            stats_marca[marca] = group['CLASIFICACION'].value_counts(normalize=True).mul(100).round(1).to_dict()

        full_stats = {
            "total": total,
            "ultima_fecha_semana": str(ultima_fecha),
            "general": stats_general,
            "por_marca": stats_marca
        }

        return df, full_stats

    except Exception as e:
        print(f"DEBUG SQL Error en Clasificación: {str(e)}")
        raise e
    finally:
        if conn:
            conn.close()

def generate_clasificacion_excel(df):
    """
    Genera un archivo Excel en memoria a partir del DataFrame de clasificación.
    """
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        df.to_excel(writer, sheet_name='Clasificación', index=False)
        
        # Ajustar anchos de columna básicos
        worksheet = writer.sheets['Clasificación']
        for i, col in enumerate(df.columns):
            if not df[col].empty:
                column_len = max(df[col].astype(str).str.len().max(), len(col)) + 2
                worksheet.set_column(i, i, min(column_len, 50))
            else:
                worksheet.set_column(i, i, len(col) + 2)
            
    output.seek(0)
    return output
