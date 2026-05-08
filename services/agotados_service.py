import pandas as pd
import pyodbc
import io
from config import settings

def get_necesidad_data(fecha, formatos=None, grupos=None, tipo_reporte='necesidad'):
    """
    Obtiene los registros para una fecha específica según el tipo de reporte:
    - necesidad: NECESIDAD > 0
    - agotados: STOCK = 0
    - desmatriculados: MINIMO = 0
    - matriculados: MINIMO > 0
    """
    conn = None
    try:
        conn = pyodbc.connect(settings.get_connection_string())
        
        # Filtro base por tipo
        if tipo_reporte == 'agotados':
            filtro_tipo = "STOCK = 0 AND MINIMO > 0"
        elif tipo_reporte == 'desmatriculados':
            filtro_tipo = "MINIMO = 0"
        elif tipo_reporte == 'matriculados':
            filtro_tipo = "MINIMO > 0"
        else: # necesidad
            filtro_tipo = "NECESIDAD > 0"

        query = f"""
            SELECT FECHA, REFERENCIA, DESCRIPCION, TALLA, COLOR, CODALMACEN, 
                   STOCK, MINIMO, MAXIMO, TRANSITO, NECESIDAD, TIENDAS_II, 
                   FORMATO, CIUDAD, ZONA_VENTAS, GRUPO, GENERO
            FROM tblAgotados
            WHERE CAST(FECHA AS DATE) = '{fecha}' AND {filtro_tipo}
        """
        
        if formatos and len(formatos) > 0:
            formatos_str = "', '".join(formatos)
            query += f" AND FORMATO IN ('{formatos_str}')"
            
        if grupos and len(grupos) > 0:
            grupos_str = "', '".join(grupos)
            query += f" AND GRUPO IN ('{grupos_str}')"
            
        df = pd.read_sql(query, conn)
        return df
    except Exception as e:
        print(f"Error obteniendo datos de necesidad: {e}")
        raise e
    finally:
        if conn:
            conn.close()

def generate_agotados_excel(df):
    """
    Genera un archivo Excel en memoria a partir del DataFrame de agotados.
    """
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        df.to_excel(writer, sheet_name='Necesidad en Tiendas', index=False)
        
        # Ajustar anchos de columna básicos
        worksheet = writer.sheets['Necesidad en Tiendas']
        for i, col in enumerate(df.columns):
            if not df[col].empty:
                column_len = max(df[col].astype(str).str.len().max(), len(col)) + 2
                worksheet.set_column(i, i, min(column_len, 50))
            else:
                worksheet.set_column(i, i, len(col) + 2)
            
    output.seek(0)
    return output
