import pandas as pd
import os
from config import settings
from typing import List, Dict, Any

class ConsultaCurvasService:
    def __init__(self):
        self.excel_path = settings.CONSULTA_CURVAS_PATH

    def get_data(self) -> List[Dict[str, Any]]:
        """Lee el Excel de curvas y retorna una lista de diccionarios."""
        try:
            # Intentar leer el Excel. Si tiene varias hojas, tomamos la primera por defecto o 'Hoja1'
            try:
                df = pd.read_excel(self.excel_path, sheet_name='Hoja1')
            except:
                df = pd.read_excel(self.excel_path)
            
            # Normalizar nombres de columnas a mayúsculas y quitar espacios
            df.columns = [str(c).upper().strip() for c in df.columns]
            
            # Mapeo de columnas para consistencia en el frontend
            # Buscamos nombres comunes
            mapping = {}
            for col in df.columns:
                if 'TIPO' in col and 'PRENDA' in col:
                    mapping[col] = 'TIPO_PRENDA'
                elif 'GENERO' in col or 'GÉNERO' in col:
                    mapping[col] = 'GENERO'
                elif 'TALLA' in col:
                    mapping[col] = 'TALLA'
            
            df = df.rename(columns=mapping)
            
            # Asegurarnos de que las columnas clave existan (si no, las creamos vacías para no romper el front)
            for key in ['TIPO_PRENDA', 'GENERO', 'TALLA']:
                if key not in df.columns:
                    df[key] = ""

            # Rellenar nulos
            df = df.fillna("")
            
            # Convertir todo a string para facilitar el filtrado en el front si es necesario, 
            # o dejar los números si son clusters.
            # Vamos a intentar mantener los números de clusters como están.
            
            return df.to_dict(orient="records")
        except Exception as e:
            raise Exception(f"Error al leer el Excel de curvas: {str(e)}")

    def get_filters(self, df_data: List[Dict[str, Any]]) -> Dict[str, List[str]]:
        """Extrae los valores únicos para los filtros desde los datos ya cargados."""
        tipos = sorted(list(set(str(item.get('TIPO_PRENDA', '')) for item in df_data if item.get('TIPO_PRENDA'))))
        generos = sorted(list(set(str(item.get('GENERO', '')) for item in df_data if item.get('GENERO'))))
        return {
            "tipos": tipos,
            "generos": generos
        }

    def update_curve(self, tipo: str, genero: str, talla: str, cluster_data: Dict[str, Any]) -> bool:
        """Actualiza los valores de clusters para un tipo, género y talla específicos."""
        try:
            # Leer el Excel original para no perder datos de otras hojas o columnas
            try:
                df = pd.read_excel(self.excel_path, sheet_name='Hoja1')
            except:
                df = pd.read_excel(self.excel_path)
            
            orig_cols = df.columns.tolist()
            upper_cols = [str(c).upper().strip() for c in orig_cols]
            
            # Encontrar índices de columnas clave
            tipo_col = next((c for c in orig_cols if 'TIPO' in str(c).upper() and 'PRENDA' in str(c).upper()), None)
            genero_col = next((c for c in orig_cols if 'GENERO' in str(c).upper() or 'GÉNERO' in str(c).upper()), None)
            talla_col = next((c for c in orig_cols if 'TALLA' in str(c).upper()), None)
            
            if not all([tipo_col, genero_col, talla_col]):
                raise Exception("No se encontraron las columnas necesarias (Tipo, Género, Talla) en el Excel.")

            # Buscar la fila
            mask = (df[tipo_col].astype(str).str.upper().str.strip() == str(tipo).upper().strip()) & \
                   (df[genero_col].astype(str).str.upper().str.strip() == str(genero).upper().strip()) & \
                   (df[talla_col].astype(str).str.upper().str.strip() == str(talla).upper().strip())
            
            if not mask.any():
                raise Exception(f"No se encontró la fila para: {tipo}, {genero}, Talla {talla}")

            # Mapear columnas de clusters (buscando .2 o exacto)
            for cluster, value in cluster_data.items():
                target_col = None
                # Buscar cluster.2 primero (patrón observado en curve_service)
                col_2 = f"{cluster}.2"
                if col_2 in upper_cols:
                    target_col = orig_cols[upper_cols.index(col_2)]
                elif cluster in upper_cols:
                    target_col = orig_cols[upper_cols.index(cluster)]
                
                if target_col:
                    df.loc[mask, target_col] = value

            # Guardar de nuevo
            # Nota: openpyxl 'a' mode with 'replace' is the safest for preserved sheets
            with pd.ExcelWriter(self.excel_path, engine='openpyxl', mode='a', if_sheet_exists='replace') as writer:
                df.to_excel(writer, sheet_name='Hoja1' if 'Hoja1' in pd.ExcelFile(self.excel_path).sheet_names else writer.sheets.keys()[0], index=False)
            
            return True
        except Exception as e:
            raise Exception(f"Error al actualizar el Excel: {str(e)}")

consulta_curvas_service = ConsultaCurvasService()
