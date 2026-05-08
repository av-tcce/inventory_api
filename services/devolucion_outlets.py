import pandas as pd
import pyodbc
import os
import io
from datetime import datetime
from dateutil.relativedelta import relativedelta
from dotenv import load_dotenv

load_dotenv()


def procesar_devolucion(archivo_excel_bytes, formatos_seleccionados, grupos_seleccionados, periodo="mes_anterior"):
    """
    Procesa el archivo Excel de inventario, lo filtra por FORMATO y GRUPO, 
    lo cruza con las ventas del periodo seleccionado y clasifica qué devolver.
    Mantiene todas las columnas originales del inventario en el resultado.
    """
    # ── 1. Leer Excel con pandas ───────────────────────────────────────────────
    df = pd.read_excel(io.BytesIO(archivo_excel_bytes), dtype=str)
    
    # Guardamos los nombres originales de las columnas para el paso final
    columnas_originales = list(df.columns)

    # Normalizar nombres de columnas a mayúsculas para lógica interna
    df.rename(columns={c: str(c).upper().strip() for c in df.columns}, inplace=True)

    # Si la columna viene como CODALMACEN, la tratamos como ID
    if 'CODALMACEN' in df.columns and 'ID' not in df.columns:
        df.rename(columns={'CODALMACEN': 'ID'}, inplace=True)

    # Validar columnas mínimas necesarias para el cruce
    for col in ['ID', 'REFERENCIA', 'TALLA']:
        if col not in df.columns:
            raise ValueError(f"El archivo Excel no contiene la columna obligatoria para el cruce: {col}")

    # ── 2. Filtrar por formatos y grupos seleccionados ─────────────────────────
    if formatos_seleccionados and 'FORMATO' in df.columns:
        df = df[df['FORMATO'].isin(formatos_seleccionados)]

    if grupos_seleccionados and 'GRUPO' in df.columns:
        df = df[df['GRUPO'].isin(grupos_seleccionados)]

    if df.empty:
        raise ValueError("El archivo Excel está vacío o no hay datos para los filtros seleccionados.")

    # Convertir STOCKTOTAL a numérico para la clasificación
    if 'STOCKTOTAL' in df.columns:
        df['STOCKTOTAL'] = pd.to_numeric(df['STOCKTOTAL'], errors='coerce').fillna(0).astype(int)
    else:
        df['STOCKTOTAL'] = 0

    # ── 3. Variables de conexión SQL Server ────────────────────────────────────
    server   = os.getenv('DB_SERVER',   '10.10.10.1')
    database = os.getenv('DB_DATABASE', 'INTELIGENCIA')
    username = os.getenv('DB_USERNAME', 'consulta_inteligencia')
    password = os.getenv('DB_PASSWORD', '1nt3l1g3nc1a')
    driver   = os.getenv('DB_DRIVER',   '{ODBC Driver 17 for SQL Server}')

    conn_str = f"DRIVER={driver};SERVER={server};DATABASE={database};UID={username};PWD={password}"

    # ── 4. Calcular el rango de fechas y Query SQL según el periodo ──────────────
    hoy = datetime.now()
    
    if periodo == "ultimos_30_dias":
        mes_ventas_label = "ÚLTIMOS 30 DÍAS"
        fecha_inicio_dt = hoy - relativedelta(days=30)
        fecha_fin_dt = hoy
        
        sql_query = """
        SELECT CODALMACEN, REFERENCIA, TALLA, SUM(UNIDADES) AS UNIDADES_VENDIDAS
        FROM [INTELIGENCIA].[dbo].[VentasColombia]
        WHERE FECHA >= DATEADD(DAY, -30, CAST(GETDATE() AS DATE))
        AND FECHA < CAST(GETDATE() AS DATE)
        GROUP BY CODALMACEN, REFERENCIA, TALLA
        """
    elif periodo == "ultimos_60_dias":
        mes_ventas_label = "ÚLTIMOS 60 DÍAS"
        fecha_inicio_dt = hoy - relativedelta(days=60)
        fecha_fin_dt = hoy
        
        sql_query = """
        SELECT CODALMACEN, REFERENCIA, TALLA, SUM(UNIDADES) AS UNIDADES_VENDIDAS
        FROM [INTELIGENCIA].[dbo].[VentasColombia]
        WHERE FECHA >= DATEADD(DAY, -60, CAST(GETDATE() AS DATE))
        AND FECHA < CAST(GETDATE() AS DATE)
        GROUP BY CODALMACEN, REFERENCIA, TALLA
        """
    else: # mes_anterior
        inicio_mes_anterior = hoy.replace(day=1) - relativedelta(months=1)
        fin_mes_anterior    = hoy.replace(day=1)
        mes_ventas_label    = inicio_mes_anterior.strftime("%B %Y").upper()
        fecha_inicio_dt    = inicio_mes_anterior
        fecha_fin_dt       = fin_mes_anterior - relativedelta(days=1)
        
        sql_query = """
        SELECT CODALMACEN, REFERENCIA, TALLA, SUM(UNIDADES) AS UNIDADES_VENDIDAS
        FROM [INTELIGENCIA].[dbo].[VentasColombia]
        WHERE FECHA >= DATEADD(MONTH, DATEDIFF(MONTH,0,GETDATE())-1,0)
        AND FECHA < DATEADD(MONTH, DATEDIFF(MONTH,0,GETDATE()),0)
        GROUP BY CODALMACEN, REFERENCIA, TALLA
        """

    fecha_inicio_str = fecha_inicio_dt.strftime("%Y-%m-%d")
    fecha_fin_str    = fecha_fin_dt.strftime("%Y-%m-%d")

    # ── 5. Consulta SQL ────────────────────────────────────────────────────────
    try:
        conn = pyodbc.connect(conn_str)
        ventas_df = pd.read_sql(sql_query, conn)
        conn.close()
    except Exception as e:
        raise ConnectionError(f"Error al conectar con SQL Server: {str(e)}. Verifica conexión VPN/Red.")

    # Normalizar strings para el cruce
    ventas_df['CODALMACEN'] = ventas_df['CODALMACEN'].astype(str).str.strip()
    ventas_df['REFERENCIA'] = ventas_df['REFERENCIA'].astype(str).str.strip()
    ventas_df['TALLA']      = ventas_df['TALLA'].astype(str).str.strip()

    df['ID']         = df['ID'].astype(str).str.strip()
    df['REFERENCIA'] = df['REFERENCIA'].astype(str).str.strip()
    df['TALLA']      = df['TALLA'].astype(str).str.strip()

    # ── 6. Merge inventario vs ventas (left join) ──────────────────────────────
    merged_df = pd.merge(
        df,
        ventas_df,
        left_on=['ID', 'REFERENCIA', 'TALLA'],
        right_on=['CODALMACEN', 'REFERENCIA', 'TALLA'],
        how='left'
    )

    merged_df['UNIDADES_VENDIDAS'] = merged_df['UNIDADES_VENDIDAS'].fillna(0).astype(int)

    # ── 7. Clasificar por fila ─────────────────────────────────────────────────
    def clasificar(row):
        uv    = row['UNIDADES_VENDIDAS']
        stock = row['STOCKTOTAL']
        if uv <= 0:
            return "DEVOLVER"
        elif stock > uv * 3:
            return "REVISAR"
        else:
            return "OK"

    merged_df['CLASIFICACION'] = merged_df.apply(clasificar, axis=1)

    # ── 7b. Calcular columnas por grupo (ID + REFERENCIA) ────────────────────────
    # Agrupar por ID y REFERENCIA para calcular estadísticas
    grupos_stats = merged_df.groupby(['ID', 'REFERENCIA']).agg(
        TOTAL_TALLAS=('CLASIFICACION', 'count'),
        TALLAS_DEVOLVER=('CLASIFICACION', lambda x: (x == 'DEVOLVER').sum()),
        TALLAS_REVISAR=('CLASIFICACION', lambda x: (x == 'REVISAR').sum()),
    ).reset_index()
    
    # Calcular porcentajes
    grupos_stats['PCT_DEVOLVER'] = grupos_stats['TALLAS_DEVOLVER'] / grupos_stats['TOTAL_TALLAS']
    grupos_stats['PCT_COMPROMETIDAS'] = (grupos_stats['TALLAS_DEVOLVER'] + grupos_stats['TALLAS_REVISAR']) / grupos_stats['TOTAL_TALLAS']
    
    # Calcular ESTADO_REFERENCIA
    def determinar_estado(row):
        if row['PCT_DEVOLVER'] >= 0.60:
            return "DEVOLVER REFERENCIA COMPLETA"
        elif row['PCT_COMPROMETIDAS'] >= 0.60:
            return "ALERTA: CURVA EN RIESGO"
        else:
            return "OK"
            
    grupos_stats['ESTADO_REFERENCIA'] = grupos_stats.apply(determinar_estado, axis=1)
    
    # Calcular DESCUENTO_SUGERIDO por referencia
    def calcular_descuento(row):
        pct = row['PCT_DEVOLVER']
        if pct > 0.60:
            return "70%"
        elif pct >= 0.50:
            return "60%"
        else:
            return "50%"
            
    grupos_stats['DESCUENTO_SUGERIDO'] = grupos_stats.apply(calcular_descuento, axis=1)
    
    # Hacer merge left para agregar estas columnas a cada fila
    merged_df = pd.merge(
        merged_df,
        grupos_stats[['ID', 'REFERENCIA', 'TOTAL_TALLAS', 'TALLAS_DEVOLVER', 'TALLAS_REVISAR', 'PCT_DEVOLVER', 'PCT_COMPROMETIDAS', 'ESTADO_REFERENCIA', 'DESCUENTO_SUGERIDO']],
        on=['ID', 'REFERENCIA'],
        how='left'
    )
    
    # Convertir porcentajes a formato texto con % (manejando NaNs)
    merged_df['PCT_DEVOLVER_STR'] = (merged_df['PCT_DEVOLVER'].fillna(0) * 100).round(1).astype(str) + '%'
    merged_df['PCT_COMPROMETIDAS_STR'] = (merged_df['PCT_COMPROMETIDAS'].fillna(0) * 100).round(1).astype(str) + '%'
    
    # Eliminar las columnas numéricas de porcentaje (usaremos las de texto)
    merged_df = merged_df.drop(columns=['PCT_DEVOLVER', 'PCT_COMPROMETIDAS'])

    # Re-mapear columnas finales: Todas las originales + Ventas + Clasificación + Nuevas calculadas
    # Para no perder los nombres originales de las columnas, usamos el dataframe original mapeado
    # Pero como merged_df ya tiene los datos, simplemente seleccionamos todas y añadimos las nuevas
    columnas_finales = columnas_originales + ['UNIDADES_VENDIDAS', 'CLASIFICACION', 'TOTAL_TALLAS', 'TALLAS_DEVOLVER', 'TALLAS_REVISAR', 'PCT_DEVOLVER_STR', 'PCT_COMPROMETIDAS_STR', 'ESTADO_REFERENCIA', 'DESCUENTO_SUGERIDO']
    
    # Aseguramos que CODALMACEN (si vino de SQL) no se repita si ya estaba en originales
    merged_df = merged_df.loc[:, ~merged_df.columns.duplicated()]
    
    # Seleccionamos las columnas deseadas. 
    # Usamos los nombres normalizados para asegurar que encontramos UNIDADES_VENDIDAS y CLASIFICACION
    # pero intentamos mantener el orden original.
    res_cols = []
    for c in columnas_originales:
        res_cols.append(c)
    res_cols.append('UNIDADES_VENDIDAS')
    res_cols.append('CLASIFICACION')
    res_cols.append('TOTAL_TALLAS')
    res_cols.append('TALLAS_DEVOLVER')
    res_cols.append('TALLAS_REVISAR')
    res_cols.append('PCT_DEVOLVER_STR')
    res_cols.append('PCT_COMPROMETIDAS_STR')
    res_cols.append('ESTADO_REFERENCIA')
    res_cols.append('DESCUENTO_SUGERIDO')
    
    # Creamos el dataframe final con los nombres reales
    # Para esto, necesitamos saber qué nombre de columna de merged_df corresponde a cada c de res_cols
    # merged_df tiene las columnas en MAYUSCULAS por el rename inicial.
    final_df = merged_df.copy()
    
    # ── 8. Construir hoja RESUMEN ──────────────────────────────────────────────
    formatos_label = ", ".join(formatos_seleccionados) if formatos_seleccionados else "Todos"
    grupos_label   = ", ".join(grupos_seleccionados) if grupos_seleccionados else "Todos"
    n_devolver     = int((final_df['CLASIFICACION'] == 'DEVOLVER').sum())
    n_revisar      = int((final_df['CLASIFICACION'] == 'REVISAR').sum())
    n_ok           = int((final_df['CLASIFICACION'] == 'OK').sum())
    n_ref_devolver_completa = int((final_df['ESTADO_REFERENCIA'] == 'DEVOLVER REFERENCIA COMPLETA').sum())
    n_ref_alerta = int((final_df['ESTADO_REFERENCIA'] == 'ALERTA: CURVA EN RIESGO').sum())
    n_ref_ok = int((final_df['ESTADO_REFERENCIA'] == 'OK').sum())
    total_rows     = len(final_df)

    resumen_data = [
        ("INFORMACIÓN DEL PROCESO",            ""),
        ("Fecha de generación",                hoy.strftime("%Y-%m-%d %H:%M:%S")),
        ("Módulo",                             "Devolución Outlets"),
        ("",                                   ""),
        ("FUENTE DE DATOS — VENTAS",           ""),
        ("Servidor SQL",                       server),
        ("Base de datos",                      database),
        ("Tabla consultada",                   "[INTELIGENCIA].[dbo].[VentasColombia]"),
        ("Periodo seleccionado",               "Últimos 30 días" if periodo == "ultimos_30_dias" else "Mes Anterior Completo"),
        ("Etiqueta del periodo",               mes_ventas_label),
        ("Rango de fechas",                    f"{fecha_inicio_str}  →  {fecha_fin_str}"),
        ("",                                   ""),
        ("FILTROS APLICADOS",                  ""),
        ("Formatos seleccionados",             formatos_label),
        ("Grupos seleccionados",               grupos_label),
        ("",                                   ""),
        ("RESUMEN DE CLASIFICACIÓN (por SKU)", ""),
        ("Total de registros procesados",      total_rows),
        ("DEVOLVER  (sin ventas en el periodo)", n_devolver),
        ("REVISAR   (stock > 3× ventas)",      n_revisar),
        ("OK        (rotación sana)",          n_ok),
        ("",                                   ""),
        ("RESUMEN DE ESTADO POR REFERENCIA",   ""),
        ("DEVOLVER REFERENCIA COMPLETA",       n_ref_devolver_completa),
        ("ALERTA: CURVA EN RIESGO",           n_ref_alerta),
        ("OK",                                 n_ref_ok),
        ("",                                   ""),
        ("REGLAS DE CLASIFICACIÓN (SKU)",      ""),
        ("DEVOLVER",                           "Unidades vendidas en el periodo == 0"),
        ("REVISAR",                            "Stock total > Unidades vendidas × 3"),
        ("OK",                                 "Resto de los casos"),
        ("",                                   ""),
        ("REGLAS DE ESTADO POR REFERENCIA",    ""),
        ("DEVOLVER REFERENCIA COMPLETA",       "% DEVOLVER >= 60%"),
        ("ALERTA: CURVA EN RIESGO",           "% COMPROMETIDAS >= 60% (pero % DEVOLVER < 60%)"),
        ("OK",                                 "Resto de los casos"),
    ]

    df_resumen = pd.DataFrame(resumen_data, columns=["Concepto", "Valor"])

    # ── 9. Exportar Excel con dos hojas formateadas ────────────────────────────
    from openpyxl.styles import Font, PatternFill

    ruta_excel = "resultado_devolucion.xlsx"

    with pd.ExcelWriter(ruta_excel, engine='openpyxl') as writer:
        df_resumen.to_excel(writer, sheet_name="Resumen", index=False)
        final_df.to_excel(writer,  sheet_name="Detalle", index=False)

        # ── Formato hoja Resumen ───────────────────────────────────────────────
        ws_res = writer.sheets["Resumen"]
        ws_res.column_dimensions['A'].width = 38
        ws_res.column_dimensions['B'].width = 50

        fill_header   = PatternFill("solid", fgColor="1E3A8A")
        font_header   = Font(color="FFFFFF", bold=True, size=11)
        fill_devolver = PatternFill("solid", fgColor="FEE2E2")
        fill_revisar  = PatternFill("solid", fgColor="FEF3C7")
        fill_ok       = PatternFill("solid", fgColor="D1FAE5")
        font_bold     = Font(bold=True)

        for row in ws_res.iter_rows(min_row=1):
            concepto = str(row[0].value or "").strip()
            valor    = str(row[1].value or "").strip()

            if valor == "" and concepto not in ("", "None"):
                for cell in row:
                    cell.fill = fill_header
                    cell.font = font_header
            elif concepto.startswith("DEVOLVER"):
                for cell in row:
                    cell.fill = fill_devolver
                row[0].font = font_bold
            elif concepto.startswith("REVISAR"):
                for cell in row:
                    cell.fill = fill_revisar
                row[0].font = font_bold
            elif concepto.startswith("OK"):
                for cell in row:
                    cell.fill = fill_ok
                row[0].font = font_bold

        # ── Formato hoja Detalle ───────────────────────────────────────────────
        ws_det = writer.sheets["Detalle"]
        for col in ws_det.columns:
            max_len = max((len(str(cell.value or "")) for cell in col), default=10)
            ws_det.column_dimensions[col[0].column_letter].width = min(max_len + 4, 40)

        # Colorear celdas CLASIFICACION y ESTADO_REFERENCIA por valor
        try:
            clasi_idx = list(final_df.columns).index('CLASIFICACION') + 1 
            for row in ws_det.iter_rows(min_row=2):
                cell = row[clasi_idx - 1]
                val  = str(cell.value or "")
                if val == "DEVOLVER":
                    cell.fill = fill_devolver
                    cell.font = Font(bold=True, color="991B1B")
                elif val == "REVISAR":
                    cell.fill = fill_revisar
                    cell.font = Font(bold=True, color="92400E")
                elif val == "OK":
                    cell.fill = fill_ok
                    cell.font = Font(bold=True, color="065F46")
        except (ValueError, IndexError):
            pass
        
        # Colorear celdas ESTADO_REFERENCIA por valor
        try:
            estado_idx = list(final_df.columns).index('ESTADO_REFERENCIA') + 1
            fill_alerta = PatternFill("solid", fgColor="FCA5A5")  # Rojo más oscuro para alerta
            for row in ws_det.iter_rows(min_row=2):
                cell = row[estado_idx - 1]
                val  = str(cell.value or "")
                if val == "DEVOLVER REFERENCIA COMPLETA":
                    cell.fill = fill_devolver
                    cell.font = Font(bold=True, color="991B1B")
                elif val == "ALERTA: CURVA EN RIESGO":
                    cell.fill = fill_alerta
                    cell.font = Font(bold=True, color="7C2D12")
                elif val == "OK":
                    cell.fill = fill_ok
                    cell.font = Font(bold=True, color="065F46")
        except (ValueError, IndexError):
            pass

    # ── 10. Retornar JSON (usamos nombres normalizados para la tabla web) ────────
    # Limpiar NaNs e infinitos para que sea compatible con JSON (evita el error 'Out of range float values')
    final_df = final_df.replace([float('inf'), float('-inf')], None).fillna("")
    json_data = final_df.to_dict(orient="records")

    return {
        "resultados": json_data,
        "ruta_descarga": "/descargar-devolucion"
    }
