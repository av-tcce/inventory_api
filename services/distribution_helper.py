import pandas as pd
import pyodbc
import os
import io
from datetime import datetime
from dateutil.relativedelta import relativedelta
from dotenv import load_dotenv
from config import settings
from models.schemas import VentasDestinoItem, PorcentajeDistribucionItem, InventarioOrigenItem, InventarioDestinoItem

load_dotenv()

class DistributionHelper:
    def fetch_sales_from_sql(self, skus, tiendas, periodo="ultimos_30_dias"):
        """
        Consulta las ventas históricas de SQL Server para los SKUs y Tiendas especificados.
        """
        if not skus or not tiendas:
            return []

        # ── 1. Variables de conexión ──────────────────────────────────────────────
        conn_str = settings.get_connection_string(server="default")

        # ── 2. Calcular el rango de fechas ────────────────────────────────────────
        hoy = datetime.now()
        if periodo == "ultimos_30_dias":
            sql_date_filter = "FECHA >= DATEADD(DAY, -30, CAST(GETDATE() AS DATE)) AND FECHA < CAST(GETDATE() AS DATE)"
        elif periodo == "ultimos_60_dias":
            sql_date_filter = "FECHA >= DATEADD(DAY, -60, CAST(GETDATE() AS DATE)) AND FECHA < CAST(GETDATE() AS DATE)"
        else: # mes_anterior
            sql_date_filter = "FECHA >= DATEADD(MONTH, DATEDIFF(MONTH,0,GETDATE())-1,0) AND FECHA < DATEADD(MONTH, DATEDIFF(MONTH,0,GETDATE()),0)"

        # Preparar listas para la query
        skus_str = ", ".join([f"'{s}'" for s in skus[:2000]])
        tiendas_str = ", ".join([f"'{t}'" for t in tiendas[:1000]])

        sql_query = f"""
        SELECT CODALMACEN as tienda, REFERENCIA as sku, SUM(UNIDADES) AS unidades_vendidas
        FROM [INTELIGENCIA].[dbo].[VentasColombia]
        WHERE {sql_date_filter}
        AND REFERENCIA IN ({skus_str})
        AND CODALMACEN IN ({tiendas_str})
        GROUP BY CODALMACEN, REFERENCIA
        """

        try:
            conn = pyodbc.connect(conn_str)
            ventas_df = pd.read_sql(sql_query, conn)
            conn.close()
        except Exception as e:
            print(f"Error consultando ventas SQL: {str(e)}")
            return []

        # Convertir a objetos VentasDestinoItem
        ventas_items = []
        for _, row in ventas_df.iterrows():
            ventas_items.append(VentasDestinoItem(
                tienda=str(row['tienda']).strip(),
                sku=str(row['sku']).strip(),
                unidades_vendidas=int(row['unidades_vendidas'])
            ))
        return ventas_items

    def segment_inventory(self, df_inventario, df_parametros):
        """
        Separa el inventario consolidado en Origen y Destino basándose en Parámetros.
        df_parametros debe tener columnas: Tienda, Rol (Origen/Destino), Porcentaje, Tipo_Aceptado
        """
        # Normalizar columnas
        df_inventario.columns = [c.upper().strip() for c in df_inventario.columns]
        df_parametros.columns = [c.upper().strip() for c in df_parametros.columns]

        # Identificar Origen y Destinos
        df_ori_cfg = df_parametros[df_parametros['ROL'].str.contains('ORIGEN', case=False, na=False)]
        if df_ori_cfg.empty:
            raise ValueError("No se definió una tienda ORIGEN en la hoja de Parámetros.")
            
        id_origen = df_ori_cfg['TIENDA'].iloc[0]
        ids_destino = df_parametros[df_parametros['ROL'].str.contains('DESTINO', case=False, na=False)]['TIENDA'].tolist()

        # Filtrar inventario
        tienda_col = next((c for c in df_inventario.columns if c in ['ID', 'CODALMACEN', 'TIENDA']), df_inventario.columns[0])
        
        df_origen_raw = df_inventario[df_inventario[tienda_col].astype(str).str.strip() == str(id_origen).strip()]
        df_destino_raw = df_inventario[df_inventario[tienda_col].astype(str).str.strip().isin([str(i).strip() for i in ids_destino])]

        # Mapear a modelos
        inventario_origen = []
        for _, row in df_origen_raw.iterrows():
            # Usar la columna LINEA_OUTLET directamente como indica el usuario
            tipo_p = str(row.get('LINEA_OUTLET', 'LINEA')).strip().capitalize()
            if tipo_p not in ["Linea", "Outlet"]: tipo_p = "Linea"
            
            inventario_origen.append(InventarioOrigenItem(
                tienda=str(row[tienda_col]).strip(),
                sku=str(row.get('REFERENCIA', row.get('SKU', ''))).strip(),
                genero=str(row.get('GENERO', '')),
                talla=str(row.get('TALLA', '')),
                color=str(row.get('COLOR', '')),
                unidades=int(pd.to_numeric(row.get('STOCK', row.get('STOCKTOTAL', 0)), errors='coerce') or 0),
                tipo_producto=tipo_p
            ))

        inventario_destino = []
        for _, row in df_destino_raw.iterrows():
            inventario_destino.append(InventarioDestinoItem(
                tienda=str(row[tienda_col]).strip(),
                sku=str(row.get('REFERENCIA', row.get('SKU', ''))).strip(),
                genero=str(row.get('GENERO', '')),
                talla=str(row.get('TALLA', '')),
                color=str(row.get('COLOR', '')),
                unidades_actuales=int(pd.to_numeric(row.get('STOCK', row.get('STOCKTOTAL', 0)), errors='coerce') or 0)
            ))

        # Mapear porcentajes y reglas de aceptación
        porcentajes = []
        for _, row in df_parametros[df_parametros['ROL'].str.contains('DESTINO', case=False, na=False)].iterrows():
            porcentajes.append(PorcentajeDistribucionItem(
                tienda=str(row['TIENDA']).strip(),
                porcentaje=float(pd.to_numeric(row.get('PORCENTAJE', 0), errors='coerce') or 0),
                tipo_aceptado=str(row.get('TIPO_ACEPTADO', 'Ambos')).strip()
            ))

        return inventario_origen, inventario_destino, porcentajes, id_origen

    def get_zone_suggestions(self, id_origen, tiendas_actuales):
        """
        Encuentra tiendas en la misma zona que el origen que no estén en la lista actual.
        """
        conn_str = settings.get_connection_string(server="default")
        try:
            conn = pyodbc.connect(conn_str)
            # Buscar zona del origen
            query_zona = f"SELECT ZONA FROM [dbo].[MAESTRA_ALMACENES] WHERE [CODALMACEN] = '{id_origen}'"
            res_zona = pd.read_sql(query_zona, conn)
            
            if res_zona.empty:
                conn.close()
                return []
            
            zona = res_zona['ZONA'].iloc[0]
            
            # Buscar otras tiendas en la misma zona
            query_sug = f"SELECT CODALMACEN, NOMBRE, FORMATO FROM [dbo].[MAESTRA_ALMACENES] WHERE [ZONA] = '{zona}' AND [ESTADO] = 'ACTIVO'"
            df_sug = pd.read_sql(query_sug, conn)
            conn.close()
            
            # Filtrar las que ya están participando
            tiendas_actuales_str = [str(t).strip() for t in tiendas_actuales]
            df_sug = df_sug[~df_sug['CODALMACEN'].astype(str).str.strip().isin(tiendas_actuales_str)]
            df_sug = df_sug[df_sug['CODALMACEN'].astype(str).str.strip() != str(id_origen).strip()]
            
            return df_sug.to_dict(orient="records")
        except Exception as e:
            print(f"Error buscando sugerencias por zona: {str(e)}")
            return []

distribution_helper = DistributionHelper()
