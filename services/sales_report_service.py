import pandas as pd
import pyodbc
from config import settings

def get_sales_analytics(fecha_inicio: str, fecha_fin: str, formatos: list = None, grupos: list = None):
    """
    Consulta y agrupa las ventas de VentasColombia filtrando por fecha, formato y grupo.
    Retorna un resumen general y desgloses por formato y grupo.
    """
    conn = None
    try:
        conn = pyodbc.connect(settings.get_connection_string())
        
        # Construcción de filtros SQL
        filter_parts = []
        filter_parts.append(f"V.FECHA >= '{fecha_inicio}' AND V.FECHA <= '{fecha_fin}'")
        
        if formatos and len(formatos) > 0:
            formatos_clean = [f.strip() for f in formatos if f]
            if formatos_clean:
                formatos_str = "', '".join(formatos_clean)
                filter_parts.append(f"T.FORMATO IN ('{formatos_str}')")
        
        if grupos and len(grupos) > 0:
            grupos_clean = [g.strip() for g in grupos if g]
            if grupos_clean:
                grupos_str = "', '".join(grupos_clean)
                filter_parts.append(f"P.GRUPO IN ('{grupos_str}')")
        
        where_clause = " AND ".join(filter_parts)

        query = f"""
            SELECT 
                CAST(V.FECHA AS DATE) as FECHA,
                ISNULL(T.FORMATO, 'SIN FORMATO') as FORMATO,
                ISNULL(P.GRUPO, 'SIN GRUPO') as GRUPO,
                SUM(V.UNIDADES) as UNIDADES,
                SUM(V.VALOR) as TOTAL_VENTA
            FROM VentasColombia V
            LEFT JOIN MAESTRA_ALMACENES T ON V.CODALMACEN = T.EQ_COD2
            LEFT JOIN PARAMETRIZACION P ON V.REFERENCIA = P.REFERENCIA
            WHERE {where_clause}
            GROUP BY CAST(V.FECHA AS DATE), T.FORMATO, P.GRUPO
            ORDER BY FECHA ASC
        """
        
        df = pd.read_sql(query, conn)
        
        if df.empty:
            return {
                "summary": {"unidades": 0, "valor": 0},
                "by_day": [],
                "by_format": [],
                "by_group": []
            }

        # Resumen General
        summary = {
            "unidades": int(df['UNIDADES'].sum()),
            "valor": float(df['TOTAL_VENTA'].sum())
        }

        # Desglose por Día
        df_day = df.groupby('FECHA').agg({
            'UNIDADES': 'sum',
            'TOTAL_VENTA': 'sum'
        }).reset_index().sort_values('FECHA')
        df_day['FECHA'] = df_day['FECHA'].astype(str)
        by_day = df_day.to_dict(orient='records')

        # Desglose por Formato
        df_format = df.groupby('FORMATO').agg({
            'UNIDADES': 'sum',
            'TOTAL_VENTA': 'sum'
        }).reset_index().sort_values('TOTAL_VENTA', ascending=False)
        
        by_format = df_format.to_dict(orient='records')

        # Desglose por Grupo
        df_group = df.groupby('GRUPO').agg({
            'UNIDADES': 'sum',
            'TOTAL_VENTA': 'sum'
        }).reset_index().sort_values('TOTAL_VENTA', ascending=False)
        
        by_group = df_group.to_dict(orient='records')

        return {
            "summary": summary,
            "by_day": by_day,
            "by_format": by_format,
            "by_group": by_group
        }

    except Exception as e:
        print(f"DEBUG SQL Error en Análisis de Ventas: {str(e)}")
        raise e
    finally:
        if conn:
            conn.close()
