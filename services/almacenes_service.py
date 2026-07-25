import pandas as pd
import pyodbc
import io
from config import settings

class AlmacenesService:
    def get_maestra_almacenes(self, filters: dict = None):
        """
        Consulta la tabla MAESTRA_ALMACENES con filtros opcionales.
        """
        conn = None
        try:
            # Usamos el servidor 1 (Default: INTELIGENCIA)
            conn = pyodbc.connect(settings.get_connection_string(server="default"))
            
            query = "SELECT * FROM [dbo].[MAESTRA_ALMACENES]"
            
            # Construir cláusula WHERE si hay filtros
            where_clauses = []
            if filters:
                for key, value in filters.items():
                    if value:
                        if isinstance(value, list):
                            # Filtrar valores vacíos o "Todos"
                            clean_values = [v.strip() for v in value if v and v.strip() and v != "Todos"]
                            if clean_values:
                                vals_str = ", ".join([f"'{v}'" for v in clean_values])
                                where_clauses.append(f"[{key.upper()}] IN ({vals_str})")
                        elif value.strip() and value != "Todos":
                            where_clauses.append(f"[{key.upper()}] = '{value.strip()}'")
            
            if where_clauses:
                query += " WHERE " + " AND ".join(where_clauses)

            df = pd.read_sql(query, conn)
            # NaN/NaT no son JSON-compliant (FastAPI/Starlette serializan con allow_nan=False).
            # astype(object) es necesario porque .where() por sí solo revierte None a NaN
            # en columnas float64 para preservar el dtype numérico.
            df = df.astype(object).where(df.notnull(), None)
            return df
        except Exception as e:
            print(f"Error en AlmacenesService (Get Data): {str(e)}")
            raise e
        finally:
            if conn:
                conn.close()

    def get_filter_options(self):
        """
        Obtiene los valores únicos para los filtros requeridos.
        """
        conn = None
        try:
            conn = pyodbc.connect(settings.get_connection_string(server="default"))
            
            filter_cols = ['TIENDAS_II', 'FORMATO', 'ZONA', 'ESTADO', 'CIUDAD', 'ZONA_VENTAS', 'PAIS', 'GENERO']
            options = {}
            
            for col in filter_cols:
                try:
                    query = f"SELECT DISTINCT [{col}] FROM [dbo].[MAESTRA_ALMACENES] WHERE [{col}] IS NOT NULL AND [{col}] != '' ORDER BY [{col}]"
                    df = pd.read_sql(query, conn)
                    options[col.lower()] = df[col].tolist()
                except Exception as col_err:
                    print(f"Advertencia: No se pudo cargar filtro para {col}: {str(col_err)}")
                    options[col.lower()] = []
                
            return options
        except Exception as e:
            print(f"Error en AlmacenesService (Filters): {str(e)}")
            raise e
        finally:
            if conn:
                conn.close()

    def generate_excel(self, df):
        """
        Genera un archivo Excel en memoria.
        """
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
            df.to_excel(writer, sheet_name='Maestra_Almacenes', index=False)
            worksheet = writer.sheets['Maestra_Almacenes']
            
            # Formato de cabecera
            header_format = writer.book.add_format({
                'bold': True,
                'bg_color': '#1e3a8a',
                'font_color': 'white',
                'border': 1
            })
            
            for i, col in enumerate(df.columns):
                worksheet.write(0, i, col, header_format)
                if not df[col].empty:
                    column_len = max(df[col].astype(str).str.len().max(), len(col)) + 2
                    worksheet.set_column(i, i, min(column_len, 50))
                else:
                    worksheet.set_column(i, i, len(col) + 2)
                    
        output.seek(0)
        return output

almacenes_service = AlmacenesService()
