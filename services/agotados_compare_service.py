import pandas as pd
import pyodbc
import io
import os
from config import settings
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

class AgotadosCompareService:
    def compare_agotados_data(self, fecha_1: str, fecha_2: str, formatos: list = None):
        """
        Compara agotados por SKU (CODALMACEN, REFERENCIA, TALLA) y retorna:
        - resumen general
        - lista de SKUs que se agotaron (con info extendida)
        """
        conn = None
        try:
            conn = pyodbc.connect(settings.get_connection_string())
            # Query base con los filtros solicitados por el usuario
            query = f"""
                SELECT CAST(FECHA AS DATE) as FECHA, REFERENCIA, DESCRIPCION, FORMATO, TALLA, COLOR, CODALMACEN, STOCK, MINIMO
                FROM tblAgotados
                WHERE CAST(FECHA AS DATE) IN ('{fecha_1}', '{fecha_2}')
                  AND GRUPO = 'TEXTIL'
                  AND MINIMO > 0
                  AND ISNULL(Exclusiones, '') <> 'Excluir'
                  AND ESTADO = 'ACTIVA'
                  AND CLASIFICACION_PROCESADA IN ('MTA', 'MTA-CM', 'MTA-O', 'MTO-M')
            """
            if formatos and len(formatos) > 0:
                formatos_str = "', '".join(formatos)
                query += f" AND FORMATO IN ('{formatos_str}')"
            df = pd.read_sql(query, conn)
            if df.empty:
                return {
                    "detalle_sku": pd.DataFrame(),
                    "referencias_agotadas": pd.DataFrame(),
                    "resumen_general": {
                        "registros_dia1": 0,
                        "agotados_dia1": 0,
                        "pct_agotado_dia1": 0.0,
                        "registros_dia2": 0,
                        "agotados_dia2": 0,
                        "pct_agotado_dia2": 0.0,
                        "variacion_pct": 0.0,
                        "referencias_agotaron": 0,
                        "skus_agotaron": 0
                    }
                }
            # Normalizar valores de columnas
            for col in ['REFERENCIA','DESCRIPCION','FORMATO','TALLA','COLOR','CODALMACEN','ALMACEN']:
                if col in df.columns:
                    df[col] = df[col].fillna("").astype(str).str.strip()
            df['STOCK'] = pd.to_numeric(df['STOCK'], errors='coerce').fillna(0).astype(int)
            df['MINIMO'] = pd.to_numeric(df['MINIMO'], errors='coerce').fillna(0).astype(int)
            df['FECHA'] = df['FECHA'].astype(str)
            # --- 1. Resumen General ---
            dia1 = df[df['FECHA'] == fecha_1]
            dia2 = df[df['FECHA'] == fecha_2]
            dia1['agotado'] = ((dia1['STOCK'] == 0) & (dia1['MINIMO'] > 0)).astype(int)
            dia2['agotado'] = ((dia2['STOCK'] == 0) & (dia2['MINIMO'] > 0)).astype(int)
            dia1_registros = int(dia1.shape[0])
            dia1_agotados = int(dia1['agotado'].sum())
            dia2_registros = int(dia2.shape[0])
            dia2_agotados = int(dia2['agotado'].sum())
            pct_dia1 = round((dia1_agotados / dia1_registros * 100), 2) if dia1_registros else 0.0
            pct_dia2 = round((dia2_agotados / dia2_registros * 100), 2) if dia2_registros else 0.0
            resumen_general = {
                "registros_dia1": dia1_registros,
                "agotados_dia1": dia1_agotados,
                "pct_agotado_dia1": pct_dia1,
                "registros_dia2": dia2_registros,
                "agotados_dia2": dia2_agotados,
                "pct_agotado_dia2": pct_dia2,
                "variacion_pct": round(pct_dia2 - pct_dia1, 2),
                "referencias_agotaron": 0,
                "skus_agotaron": 0
            }
            # --- 2. Análisis por SKU ---
            # Unir por clave SKU: CODALMACEN, REFERENCIA, TALLA
            sku_cols = ['CODALMACEN','REFERENCIA','TALLA']
            merge_cols = sku_cols + ['DESCRIPCION','FORMATO','COLOR']
            dia1_sku = dia1[merge_cols + ['STOCK']].rename(columns={'STOCK':'stock_dia1'})
            dia2_sku = dia2[merge_cols + ['STOCK']].rename(columns={'STOCK':'stock_dia2'})
            sku_cmp = pd.merge(dia1_sku, dia2_sku, on=merge_cols, how='outer')
            sku_cmp[['stock_dia1','stock_dia2']] = sku_cmp[['stock_dia1','stock_dia2']].fillna(0)
            for col in merge_cols:
                sku_cmp[col] = sku_cmp[col].fillna("").astype(str).str.strip()
            sku_cmp['agotado_dia1'] = (sku_cmp['stock_dia1'] == 0).astype(int)
            sku_cmp['agotado_dia2'] = (sku_cmp['stock_dia2'] == 0).astype(int)
            # Se agotó: no estaba agotado en día 1 y sí en día 2
            sku_cmp['se_agoto'] = (sku_cmp['agotado_dia1'] == 0) & (sku_cmp['agotado_dia2'] == 1)
            referencias_agotadas = sku_cmp[sku_cmp['se_agoto']].copy()
            total_agotados = int(referencias_agotadas.shape[0])
            resumen_general['referencias_agotaron'] = total_agotados
            resumen_general['skus_agotaron'] = total_agotados

            # Resumen por formato para el Excel de comparación
            formato_1 = dia1.groupby('FORMATO', dropna=False).agg(
                registros_dia1=('STOCK', 'count'),
                agotados_dia1=('agotado', 'sum')
            ).reset_index()
            formato_2 = dia2.groupby('FORMATO', dropna=False).agg(
                registros_dia2=('STOCK', 'count'),
                agotados_dia2=('agotado', 'sum')
            ).reset_index()
            resumen_formatos = pd.merge(formato_1, formato_2, on='FORMATO', how='outer').fillna(0)
            resumen_formatos['FORMATO'] = resumen_formatos['FORMATO'].fillna('').astype(str).str.strip()
            resumen_formatos[['registros_dia1','agotados_dia1','registros_dia2','agotados_dia2']] = resumen_formatos[
                ['registros_dia1','agotados_dia1','registros_dia2','agotados_dia2']
            ].astype(int)
            resumen_formatos['pct_agotado_dia1'] = resumen_formatos.apply(
                lambda row: round((row['agotados_dia1'] / row['registros_dia1'] * 100), 2) if row['registros_dia1'] else 0.0,
                axis=1
            )
            resumen_formatos['pct_agotado_dia2'] = resumen_formatos.apply(
                lambda row: round((row['agotados_dia2'] / row['registros_dia2'] * 100), 2) if row['registros_dia2'] else 0.0,
                axis=1
            )
            resumen_formatos['variacion_pct'] = round(resumen_formatos['pct_agotado_dia2'] - resumen_formatos['pct_agotado_dia1'], 2)
            resumen_formatos = resumen_formatos.sort_values(by='FORMATO').reset_index(drop=True)

            detalle_referencias = referencias_agotadas.copy()
            detalle_referencias['se_agoto'] = detalle_referencias['se_agoto'].astype(bool)
            detalle_referencias = detalle_referencias[[
                'CODALMACEN', 'FORMATO', 'REFERENCIA', 'DESCRIPCION', 'TALLA', 'COLOR',
                'stock_dia1', 'stock_dia2', 'se_agoto'
            ]]

            return {
                "detalle_sku": sku_cmp,
                "referencias_agotadas": referencias_agotadas,
                "resumen_general": resumen_general,
                "resumen_formatos": resumen_formatos,
                "detalle_referencias": detalle_referencias
            }
        except Exception as e:
            print(f"Error en compare_agotados_data: {e}")
            raise e
        finally:
            if conn:
                conn.close()

    def generate_comparison_excel(self, df_fmt: pd.DataFrame, df_ref: pd.DataFrame, fecha_1: str, fecha_2: str) -> io.BytesIO:
        """
        Genera un archivo Excel premium con el análisis comparativo usando openpyxl.
        """
        output = io.BytesIO()
        
        # Copias locales para no alterar originales
        fmt_copy = df_fmt.copy()
        ref_copy = df_ref.copy()
        
        # Mapear nombres legibles de columnas para la exportación
        fmt_cols_map = {
            'FORMATO': 'Formato',
            'registros_dia1': f'Registros ({fecha_1})',
            'agotados_dia1': f'Agotados ({fecha_1})',
            'pct_agotado_dia1': f'% Agotado ({fecha_1})',
            'registros_dia2': f'Registros ({fecha_2})',
            'agotados_dia2': f'Agotados ({fecha_2})',
            'pct_agotado_dia2': f'% Agotado ({fecha_2})',
            'variacion_pct': 'Variación Pct (p.p.)'
        }
        fmt_copy = fmt_copy.rename(columns=fmt_cols_map)
        
        # Mapear detalle de referencia para SKUs que se agotaron
        ref_copy['se_agoto_str'] = ref_copy['se_agoto'].map({True: 'SÍ', False: 'NO'})
        ref_cols_map = {
            'CODALMACEN': 'Cod Almacén',
            'FORMATO': 'Formato',
            'REFERENCIA': 'Referencia',
            'DESCRIPCION': 'Descripción',
            'TALLA': 'Talla',
            'COLOR': 'Color',
            'stock_dia1': f'Stock ({fecha_1})',
            'stock_dia2': f'Stock ({fecha_2})',
            'se_agoto_str': 'Se Agotó'
        }
        ref_copy = ref_copy.drop(columns=['se_agoto']).rename(columns=ref_cols_map)
        
        # Escribir con Pandas
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            fmt_copy.to_excel(writer, sheet_name="Resumen por Formato", index=False)
            ref_copy.to_excel(writer, sheet_name="Detalle de Referencias", index=False)
            
            # --- Diseño y Estilización ---
            fill_header = PatternFill("solid", fgColor="1E3A8A")  # Azul Rey oscuro
            font_header = Font(color="FFFFFF", bold=True, name="Calibri", size=11)
            
            fill_red = PatternFill("solid", fgColor="FEE2E2")    # Rojo suave
            font_red = Font(color="991B1B", bold=True, name="Calibri")
            
            fill_green = PatternFill("solid", fgColor="D1FAE5")  # Verde suave
            font_green = Font(color="065F46", bold=True, name="Calibri")
            
            font_bold = Font(bold=True, name="Calibri")
            
            # Pestaña 1: Resumen por Formato
            ws_fmt = writer.sheets["Resumen por Formato"]
            ws_fmt.views.sheetView[0].showGridLines = True
            
            # Dar formato de cabecera
            for col in range(1, ws_fmt.max_column + 1):
                cell = ws_fmt.cell(row=1, column=col)
                cell.fill = fill_header
                cell.font = font_header
                cell.alignment = Alignment(horizontal="center", vertical="center")
                
            # Formatear celdas de variación y porcentajes
            for row in range(2, ws_fmt.max_row + 1):
                # Variación Pct está en la columna H (8)
                var_cell = ws_fmt.cell(row=row, column=8)
                val = var_cell.value
                if val is not None:
                    var_cell.value = float(val) / 100.0  # Para usar formato de porcentaje de Excel
                    var_cell.number_format = '0.0%'
                    if val > 0:
                        var_cell.fill = fill_red
                        var_cell.font = font_red
                    elif val < 0:
                        var_cell.fill = fill_green
                        var_cell.font = font_green
                
                # Formato de porcentaje a las columnas de porcentaje: D (4) y G (7)
                for c_idx in [4, 7]:
                    cell = ws_fmt.cell(row=row, column=c_idx)
                    if cell.value is not None:
                        cell.value = float(cell.value) / 100.0
                        cell.number_format = '0.0%'
                        
            # Autoajustar columnas
            for col in ws_fmt.columns:
                max_len = max((len(str(cell.value or "")) for cell in col), default=12)
                col_letter = get_column_letter(col[0].column)
                ws_fmt.column_dimensions[col_letter].width = min(max_len + 4, 30)
                
            # Pestaña 2: Detalle de Referencias
            ws_ref = writer.sheets["Detalle de Referencias"]
            ws_ref.views.sheetView[0].showGridLines = True
            
            # Cabecera
            for col in range(1, ws_ref.max_column + 1):
                cell = ws_ref.cell(row=1, column=col)
                cell.fill = fill_header
                cell.font = font_header
                cell.alignment = Alignment(horizontal="center", vertical="center")
                
            # Formatear 'Se Agotó?' y estilo de filas del detalle de referencias
            for row in range(2, ws_ref.max_row + 1):
                se_agoto_cell = ws_ref.cell(row=row, column=ws_ref.max_column)
                if se_agoto_cell.value == 'SÍ':
                    se_agoto_cell.fill = fill_red
                    se_agoto_cell.font = font_red
                else:
                    se_agoto_cell.font = font_bold
                se_agoto_cell.alignment = Alignment(horizontal="center")

            # Autoajustar columnas
            for col in ws_ref.columns:
                max_len = max((len(str(cell.value or "")) for cell in col), default=12)
                col_letter = get_column_letter(col[0].column)
                ws_fmt_col_width = min(max_len + 4, 40)
                # La descripción es la columna B, queremos que sea un poco más ancha
                if col_letter == 'B':
                    ws_fmt_col_width = 35
                ws_ref.column_dimensions[col_letter].width = ws_fmt_col_width
                
        output.seek(0)
        return output

agotados_compare_service = AgotadosCompareService()
