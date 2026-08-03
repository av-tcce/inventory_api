import pandas as pd
import pyodbc
import io
import os
from config import settings
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

class AgotadosCompareService:
    def compare_agotados_data(self, fecha_1: str, fecha_2: str, formatos: list = None, grupos: list = None):
        """
        Compara agotados por SKU (CODALMACEN, REFERENCIA, TALLA) y retorna:
        - resumen general
        - lista de SKUs que se agotaron (con info extendida)
        """
        conn = None
        try:
            conn = pyodbc.connect(settings.get_connection_string())
            grupos_filtro = grupos if grupos and len(grupos) > 0 else ['TEXTIL']
            grupos_str = "', '".join(grupos_filtro)
            # Query base con los filtros solicitados por el usuario
            query = f"""
                SELECT CAST(FECHA AS DATE) as FECHA, REFERENCIA, DESCRIPCION, FORMATO, TALLA, COLOR, CODALMACEN, STOCK, MINIMO, CEROS, TIPO_DE_PRENDA AS TIPO_PRENDA
                FROM tblAgotados
                WHERE CAST(FECHA AS DATE) IN ('{fecha_1}', '{fecha_2}')
                  AND GRUPO IN ('{grupos_str}')
                  AND MINIMO > 0
                  AND ISNULL(Exclusiones, '') <> 'Excluir'
                  AND ISNULL(Aperturas, '') <> 'Excluir'
                  AND ESTADO = 'ACTIVA'
                  AND CLASIFICACION_PROCESADA IN ('MTA', 'MTA-C', 'MTA-O', 'MTO-M')
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
                    },
                    "resumen_formatos": pd.DataFrame(),
                    "detalle_referencias": pd.DataFrame(),
                    "agotados_por_categoria_general": [],
                    "agotados_por_categoria_formato": {}
                }
            # Normalizar valores de columnas
            for col in ['REFERENCIA','DESCRIPCION','FORMATO','TALLA','COLOR','CODALMACEN','ALMACEN','TIPO_PRENDA']:
                if col in df.columns:
                    df[col] = df[col].fillna("").astype(str).str.strip()
            df['STOCK'] = pd.to_numeric(df['STOCK'], errors='coerce').fillna(0).astype(int)
            df['MINIMO'] = pd.to_numeric(df['MINIMO'], errors='coerce').fillna(0).astype(int)
            df['CEROS'] = pd.to_numeric(df['CEROS'], errors='coerce').fillna(0).astype(int)
            df['FECHA'] = df['FECHA'].astype(str)
            # --- 1. Resumen General ---
            dia1 = df[df['FECHA'] == fecha_1]
            dia2 = df[df['FECHA'] == fecha_2]
            # Agotado se determina con la columna CEROS (CEROS = 1 -> SKU agotado)
            dia1['agotado'] = (dia1['CEROS'] == 1).astype(int)
            dia2['agotado'] = (dia2['CEROS'] == 1).astype(int)
            dia1_registros = int(dia1.shape[0])
            dia1_agotados = int(dia1['agotado'].sum())
            dia2_registros = int(dia2.shape[0])
            dia2_agotados = int(dia2['agotado'].sum())
            pct_dia1 = round((dia1_agotados / dia1_registros * 100), 1) if dia1_registros else 0.0
            pct_dia2 = round((dia2_agotados / dia2_registros * 100), 1) if dia2_registros else 0.0
            resumen_general = {
                "registros_dia1": dia1_registros,
                "agotados_dia1": dia1_agotados,
                "pct_agotado_dia1": pct_dia1,
                "registros_dia2": dia2_registros,
                "agotados_dia2": dia2_agotados,
                "pct_agotado_dia2": pct_dia2,
                "variacion_pct": round(pct_dia2 - pct_dia1, 1),
                "referencias_agotaron": 0,
                "skus_agotaron": 0
            }
            # --- 2. Análisis por SKU ---
            # Unir por clave SKU: CODALMACEN, REFERENCIA, TALLA
            sku_cols = ['CODALMACEN','REFERENCIA','TALLA']
            merge_cols = sku_cols + ['DESCRIPCION','FORMATO','COLOR','TIPO_PRENDA']
            dia1_sku = dia1[merge_cols + ['STOCK','CEROS']].rename(columns={'STOCK':'stock_dia1','CEROS':'ceros_dia1'})
            dia2_sku = dia2[merge_cols + ['STOCK','CEROS']].rename(columns={'STOCK':'stock_dia2','CEROS':'ceros_dia2'})
            sku_cmp = pd.merge(dia1_sku, dia2_sku, on=merge_cols, how='outer')
            sku_cmp[['stock_dia1','stock_dia2','ceros_dia1','ceros_dia2']] = sku_cmp[
                ['stock_dia1','stock_dia2','ceros_dia1','ceros_dia2']
            ].fillna(0)
            for col in merge_cols:
                sku_cmp[col] = sku_cmp[col].fillna("").astype(str).str.strip()
            sku_cmp['agotado_dia1'] = (sku_cmp['ceros_dia1'] == 1).astype(int)
            sku_cmp['agotado_dia2'] = (sku_cmp['ceros_dia2'] == 1).astype(int)
            # Se agotó: no estaba agotado en día 1 y sí en día 2
            sku_cmp['se_agoto'] = (sku_cmp['agotado_dia1'] == 0) & (sku_cmp['agotado_dia2'] == 1)
            referencias_agotadas = sku_cmp[sku_cmp['se_agoto']].copy()
            total_agotados = int(referencias_agotadas.shape[0])
            resumen_general['referencias_agotaron'] = total_agotados
            resumen_general['skus_agotaron'] = total_agotados

            # --- 3. Cruce con inventario de bodega (inv_bodegas) ---
            # Objetivo: saber si un SKU que se agotó en tienda tiene o no stock
            # disponible en bodega (PT100) para descartar que el agotado sea por
            # falta de despacho o por no haberse leído/registrado en bodega.
            SKU2_SEP = '|'
            referencias_agotadas['sku2'] = referencias_agotadas['REFERENCIA'] + SKU2_SEP + referencias_agotadas['TALLA']

            query_bodega = """
                SELECT Reference, Size, TotalStock
                FROM [INTELIGENCIA].[dbo].[inv_bodegas]
                WHERE CAST(FechaRegistro AS DATE) = ?
                  AND PAIS = 'COLOMBIA'
                  AND WarehouseCode = 'PT100'
            """
            df_bodega = pd.read_sql(query_bodega, conn, params=[fecha_1])
            if not df_bodega.empty:
                df_bodega['Reference'] = df_bodega['Reference'].fillna('').astype(str).str.strip()
                df_bodega['Size'] = df_bodega['Size'].fillna('').astype(str).str.strip()
                df_bodega['TotalStock'] = pd.to_numeric(df_bodega['TotalStock'], errors='coerce').fillna(0)
                df_bodega['sku2'] = df_bodega['Reference'] + SKU2_SEP + df_bodega['Size']
                stock_bodega = df_bodega.groupby('sku2', as_index=False)['TotalStock'].sum()
            else:
                stock_bodega = pd.DataFrame(columns=['sku2', 'TotalStock'])
            stock_bodega = stock_bodega.rename(columns={'TotalStock': 'stock_bodega'})

            referencias_agotadas = referencias_agotadas.merge(stock_bodega, on='sku2', how='left')

            def _estado_bodega(stock):
                if pd.isna(stock):
                    return 'No registrado en bodega'
                if stock > 0:
                    return 'Con stock en bodega'
                return 'Sin stock en bodega'

            referencias_agotadas['estado_bodega'] = referencias_agotadas['stock_bodega'].apply(_estado_bodega)
            referencias_agotadas['stock_bodega'] = referencias_agotadas['stock_bodega'].fillna(0).astype(int)

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
                lambda row: round((row['agotados_dia1'] / row['registros_dia1'] * 100), 1) if row['registros_dia1'] else 0.0,
                axis=1
            )
            resumen_formatos['pct_agotado_dia2'] = resumen_formatos.apply(
                lambda row: round((row['agotados_dia2'] / row['registros_dia2'] * 100), 1) if row['registros_dia2'] else 0.0,
                axis=1
            )
            resumen_formatos['variacion_pct'] = round(resumen_formatos['pct_agotado_dia2'] - resumen_formatos['pct_agotado_dia1'], 1)

            agotadas_por_formato = referencias_agotadas.groupby('FORMATO', dropna=False).size().rename('referencias_agotaron')
            resumen_formatos = resumen_formatos.merge(agotadas_por_formato, on='FORMATO', how='left')
            resumen_formatos['referencias_agotaron'] = resumen_formatos['referencias_agotaron'].fillna(0).astype(int)

            resumen_formatos = resumen_formatos.sort_values(by='FORMATO').reset_index(drop=True)

            # SKUs que se agotaron (día1 -> día2), agrupados por categoría (TIPO_PRENDA)
            categorias = referencias_agotadas.assign(
                TIPO_PRENDA=referencias_agotadas['TIPO_PRENDA'].replace('', 'SIN CATEGORÍA')
            )

            agotados_por_categoria_general = (
                categorias.groupby('TIPO_PRENDA', dropna=False)
                          .size()
                          .rename('count')
                          .reset_index()
                          .sort_values('count', ascending=False)
                          .to_dict(orient='records')
            )

            agotados_por_categoria_formato = {}
            for formato, grupo in categorias.groupby('FORMATO', dropna=False):
                agotados_por_categoria_formato[formato] = (
                    grupo.groupby('TIPO_PRENDA', dropna=False)
                         .size()
                         .rename('count')
                         .reset_index()
                         .sort_values('count', ascending=False)
                         .to_dict(orient='records')
                )

            detalle_referencias = referencias_agotadas.copy()
            detalle_referencias['se_agoto'] = detalle_referencias['se_agoto'].astype(bool)
            detalle_referencias = detalle_referencias[[
                'CODALMACEN', 'FORMATO', 'REFERENCIA', 'DESCRIPCION', 'TALLA', 'COLOR',
                'stock_dia1', 'stock_dia2', 'se_agoto', 'stock_bodega', 'estado_bodega'
            ]]

            return {
                "detalle_sku": sku_cmp,
                "referencias_agotadas": referencias_agotadas,
                "resumen_general": resumen_general,
                "resumen_formatos": resumen_formatos,
                "detalle_referencias": detalle_referencias,
                "agotados_por_categoria_general": agotados_por_categoria_general,
                "agotados_por_categoria_formato": agotados_por_categoria_formato
            }
        except Exception as e:
            print(f"Error en compare_agotados_data: {e}")
            raise e
        finally:
            if conn:
                conn.close()

    def generate_comparison_excel(
        self,
        df_fmt: pd.DataFrame,
        df_ref: pd.DataFrame,
        fecha_1: str,
        fecha_2: str,
        categoria_general: list = None,
        categoria_formato: dict = None
    ) -> io.BytesIO:
        """
        Genera un archivo Excel premium con el análisis comparativo usando openpyxl.
        """
        output = io.BytesIO()

        # Copias locales para no alterar originales
        fmt_copy = df_fmt.copy()
        ref_copy = df_ref.copy()

        # Resumen por categoría (Tipo de Prenda): general + por formato, en una sola tabla plana
        filas_categoria = []
        for item in (categoria_general or []):
            filas_categoria.append({
                'Formato': 'GENERAL (Todos)',
                'Categoría': item['TIPO_PRENDA'],
                'SKUs Agotados': item['count']
            })
        for formato, items in (categoria_formato or {}).items():
            for item in items:
                filas_categoria.append({
                    'Formato': formato or 'SIN FORMATO',
                    'Categoría': item['TIPO_PRENDA'],
                    'SKUs Agotados': item['count']
                })
        cat_copy = pd.DataFrame(filas_categoria, columns=['Formato', 'Categoría', 'SKUs Agotados'])

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
            'se_agoto_str': 'Se Agotó',
            'stock_bodega': f'Stock Bodega PT100 ({fecha_1})',
            'estado_bodega': 'Estado Bodega'
        }
        ref_copy = ref_copy.drop(columns=['se_agoto']).rename(columns=ref_cols_map)
        
        # Escribir con Pandas
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            fmt_copy.to_excel(writer, sheet_name="Resumen por Formato", index=False)
            cat_copy.to_excel(writer, sheet_name="Resumen por Categoría", index=False)
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
                
            # Pestaña 2: Resumen por Categoría
            ws_cat = writer.sheets["Resumen por Categoría"]
            ws_cat.views.sheetView[0].showGridLines = True

            # Cabecera
            for col in range(1, ws_cat.max_column + 1):
                cell = ws_cat.cell(row=1, column=col)
                cell.fill = fill_header
                cell.font = font_header
                cell.alignment = Alignment(horizontal="center", vertical="center")

            # Resaltar las filas del resumen GENERAL para distinguirlas de las de cada formato
            fill_general = PatternFill("solid", fgColor="DBEAFE")  # Azul suave
            for row in range(2, ws_cat.max_row + 1):
                formato_cell = ws_cat.cell(row=row, column=1)
                if formato_cell.value == 'GENERAL (Todos)':
                    for col in range(1, ws_cat.max_column + 1):
                        ws_cat.cell(row=row, column=col).fill = fill_general
                        ws_cat.cell(row=row, column=col).font = font_bold

            # Autoajustar columnas
            for col in ws_cat.columns:
                max_len = max((len(str(cell.value or "")) for cell in col), default=12)
                col_letter = get_column_letter(col[0].column)
                ws_cat.column_dimensions[col_letter].width = min(max_len + 4, 30)

            # Pestaña 3: Detalle de Referencias
            ws_ref = writer.sheets["Detalle de Referencias"]
            ws_ref.views.sheetView[0].showGridLines = True
            
            # Cabecera
            for col in range(1, ws_ref.max_column + 1):
                cell = ws_ref.cell(row=1, column=col)
                cell.fill = fill_header
                cell.font = font_header
                cell.alignment = Alignment(horizontal="center", vertical="center")
                
            # Mapear encabezados a índice de columna (no depender de posiciones fijas)
            headers_ref = {ws_ref.cell(row=1, column=c).value: c for c in range(1, ws_ref.max_column + 1)}
            col_se_agoto = headers_ref.get('Se Agotó')
            col_estado_bodega = headers_ref.get('Estado Bodega')
            fill_gray = PatternFill("solid", fgColor="E5E7EB")  # Gris suave

            # Formatear 'Se Agotó?' y 'Estado Bodega' del detalle de referencias
            for row in range(2, ws_ref.max_row + 1):
                if col_se_agoto:
                    se_agoto_cell = ws_ref.cell(row=row, column=col_se_agoto)
                    if se_agoto_cell.value == 'SÍ':
                        se_agoto_cell.fill = fill_red
                        se_agoto_cell.font = font_red
                    else:
                        se_agoto_cell.font = font_bold
                    se_agoto_cell.alignment = Alignment(horizontal="center")

                if col_estado_bodega:
                    estado_cell = ws_ref.cell(row=row, column=col_estado_bodega)
                    if estado_cell.value == 'Sin stock en bodega':
                        estado_cell.fill = fill_red
                        estado_cell.font = font_red
                    elif estado_cell.value == 'No registrado en bodega':
                        estado_cell.fill = fill_gray
                        estado_cell.font = font_bold
                    elif estado_cell.value == 'Con stock en bodega':
                        estado_cell.fill = fill_green
                        estado_cell.font = font_green
                    estado_cell.alignment = Alignment(horizontal="center")

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
