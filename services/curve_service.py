import pandas as pd
import os
from config import settings
from typing import List, Dict, Any

class CurveService:
    def __init__(self):
        self.excel_path = settings.CURVAS_EXCEL_PATH

    def get_all_curves(self) -> List[Dict[str, Any]]:
        """Lee el Excel de curvas (Hoja1) y retorna una lista de diccionarios."""
        try:
            # Leer específicamente Hoja1
            df = pd.read_excel(self.excel_path, sheet_name='Hoja1')
            
            # Normalizar nombres de columnas
            df.columns = [str(c).upper().strip() for c in df.columns]
            
            # El usuario indica que quiere los números enteros. 
            # Según dtypes, estos están en AA.2, A.2, B.2, C.2 o similares.
            # Vamos a mapear los que tengan .2 o los originales convertidos a int
            mapping = {
                'TIPO PRENDA': 'Tipo de Prenda',
                'GENERO': 'Genero',
                'TALLA': 'Talla'
            }
            
            # Mapear clusters buscando la versión entera (.2) si existe
            for cluster in ['AA', 'A', 'B', 'C']:
                col_name = f"{cluster}.2"
                if col_name in df.columns:
                    mapping[col_name] = cluster
                elif cluster in df.columns:
                    mapping[cluster] = cluster
                    df[cluster] = df[cluster].fillna(0).astype(int)

            df = df.rename(columns=mapping)
            
            # Seleccionar solo las columnas necesarias para limpiar el ruido del Excel
            cols_to_keep = ['Tipo de Prenda', 'Genero', 'Talla', 'AA', 'A', 'B', 'C']
            df = df[cols_to_keep]
            
            df = df.fillna(0)
            return df.to_dict(orient="records")
        except Exception as e:
            raise Exception(f"No se pudo acceder a 'Hoja1' en {self.excel_path}: {str(e)}")

    def get_filters(self) -> Dict[str, List[str]]:
        """Retorna los valores únicos para filtros desde Hoja1."""
        try:
            df = pd.read_excel(self.excel_path, sheet_name='Hoja1')
            df.columns = [str(c).upper().strip() for c in df.columns]
            return {
                "tipos": sorted(df['TIPO PRENDA'].unique().astype(str).tolist()),
                "generos": sorted(df['GENERO'].unique().astype(str).tolist()),
                "clusters": ["AA", "A", "B", "C"]
            }
        except Exception as e:
            return {"tipos": [], "generos": [], "clusters": ["AA", "A", "B", "C"]}

    def update_curve(self, tipo: str, genero: str, new_data: List[Dict[str, Any]]):
        """Actualiza los valores (AA, A, B, C) para un tipo y género específico en Hoja1."""
        df = pd.read_excel(self.excel_path, sheet_name='Hoja1')
        orig_cols = df.columns.tolist()
        
        # Mapeo inverso para saber qué columna del Excel actualizar
        # Buscamos las columnas originales que corresponden a cada cluster
        excel_col_mapping = {}
        upper_cols = [str(c).upper().strip() for c in orig_cols]
        
        for cluster in ["AA", "A", "B", "C"]:
            col_2 = f"{cluster}.2"
            if col_2 in upper_cols:
                # Encontrar el nombre original con casing exacto
                idx = upper_cols.index(col_2)
                excel_col_mapping[cluster] = orig_cols[idx]
            elif cluster in upper_cols:
                idx = upper_cols.index(cluster)
                excel_col_mapping[cluster] = orig_cols[idx]

        # Normalizar para búsqueda
        df_search = df.copy()
        df_search.columns = upper_cols
        
        for item in new_data:
            talla = item.get("talla")
            mask = (df_search['TIPO PRENDA'] == tipo) & (df_search['GENERO'] == genero) & (df_search['TALLA'].astype(str) == str(talla))
            
            if mask.any():
                for cluster, excel_col in excel_col_mapping.items():
                    if cluster in item:
                        df.loc[mask, excel_col] = item[cluster]
        
        # Guardar de nuevo en Excel preservando Hoja1
        with pd.ExcelWriter(self.excel_path, engine='openpyxl', mode='a', if_sheet_exists='replace') as writer:
            df.to_excel(writer, sheet_name='Hoja1', index=False)
        return True

curve_service = CurveService()
