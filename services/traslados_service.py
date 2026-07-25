import io
import math
from typing import List, Dict, Any

import pandas as pd
import pyodbc

from config import settings


class TrasladosService:
    REQUIRED_COLUMNS = ["CODALMACEN", "REFERENCIA", "TALLA", "COLOR", "STOCK"]

    @staticmethod
    def _normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        df.columns = df.columns.str.upper().str.strip()
        return df

    @staticmethod
    def _parse_numeric(value: Any) -> float:
        if pd.isna(value):
            return None
        try:
            return float(str(value).replace(",", ".").strip())
        except Exception:
            return None

    @staticmethod
    def _haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
        # Distancia en kilómetros entre dos puntos geográficos
        if None in (lat1, lon1, lat2, lon2):
            return float("inf")

        radius = 6371.0
        dlat = math.radians(lat2 - lat1)
        dlon = math.radians(lon2 - lon1)
        a = (math.sin(dlat / 2) ** 2 +
             math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) *
             math.sin(dlon / 2) ** 2)
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
        return radius * c

    @staticmethod
    def _safe_value(value: Any, default: Any = None) -> Any:
        if pd.isna(value):
            return default
        if isinstance(value, float) and (math.isinf(value) or math.isnan(value)):
            return default
        return value

    def _safe_numeric(self, value: Any) -> Any:
        value = self._safe_value(value)
        if value is None:
            return None
        try:
            return float(value)
        except Exception:
            return None

    def _safe_str(self, value: Any) -> str:
        value = self._safe_value(value, default="")
        return str(value).strip()

    def parse_transfer_excel(self, file_bytes: bytes) -> pd.DataFrame:
        df = pd.read_excel(io.BytesIO(file_bytes), sheet_name=0, dtype=str)
        df = self._normalize_columns(df)

        missing = [c for c in self.REQUIRED_COLUMNS if c not in df.columns]
        if missing:
            raise ValueError(f"El archivo Excel debe contener las columnas: {', '.join(missing)}")

        df = df[self.REQUIRED_COLUMNS].copy()
        df = df.fillna("")
        df["CODALMACEN"] = df["CODALMACEN"].astype(str).str.strip()
        df["REFERENCIA"] = df["REFERENCIA"].astype(str).str.strip()
        df["TALLA"] = df["TALLA"].astype(str).str.strip()
        df["COLOR"] = df["COLOR"].astype(str).str.strip()
        df["STOCK"] = pd.to_numeric(df["STOCK"], errors="coerce").fillna(0).astype(int)

        df = df[df["CODALMACEN"] != ""]
        if df.empty:
            raise ValueError("El archivo Excel no contiene filas válidas en la hoja solicitada.")

        df = df.groupby(["CODALMACEN", "REFERENCIA", "TALLA", "COLOR"], as_index=False, dropna=False).agg({"STOCK": "sum"})
        return df

    def _load_almacenes(self) -> pd.DataFrame:
        conn = None
        try:
            conn = pyodbc.connect(settings.get_connection_string(server="default"))
            query = (
                "SELECT EQ_COD2 AS CODALMACEN, "
                "COALESCE(TIENDAS_II, ID, TIENDAS_INVENTARIO, CLIENTE, '') AS NOMBRE, "
                "COALESCE([DIRECCIÓN], '') AS DIRECCION, "
                "CIUDAD, ZONA, FORMATO, CLIMA, NEGOCIO, ESTADO, PAIS, LONGITUD, LATITUD "
                "FROM [dbo].[MAESTRA_ALMACENES] "
                "WHERE LONGITUD IS NOT NULL AND LATITUD IS NOT NULL"
            )
            df = pd.read_sql(query, conn)
            df["LONGITUD"] = df["LONGITUD"].apply(self._parse_numeric)
            df["LATITUD"] = df["LATITUD"].apply(self._parse_numeric)
            df = df.dropna(subset=["LONGITUD", "LATITUD"])
            return df
        finally:
            if conn:
                conn.close()

    def _load_origin_almacenes(self, codigos: List[str]) -> pd.DataFrame:
        if not codigos:
            return pd.DataFrame(columns=["CODALMACEN", "NOMBRE", "DIRECCION", "CIUDAD", "ZONA", "FORMATO", "CLIMA", "NEGOCIO", "ESTADO", "PAIS", "LONGITUD", "LATITUD"])

        conn = None
        try:
            conn = pyodbc.connect(settings.get_connection_string(server="default"))
            quoted = ",".join([f"'{str(c).strip()}'" for c in codigos if str(c).strip()])
            if not quoted:
                return pd.DataFrame(columns=["CODALMACEN", "NOMBRE", "DIRECCION", "CIUDAD", "ZONA", "FORMATO", "CLIMA", "NEGOCIO", "ESTADO", "PAIS", "LONGITUD", "LATITUD"])
            query = (
                "SELECT EQ_COD2 AS CODALMACEN, "
                "COALESCE(TIENDAS_II, ID, TIENDAS_INVENTARIO, CLIENTE, '') AS NOMBRE, "
                "COALESCE([DIRECCIÓN], '') AS DIRECCION, "
                "CIUDAD, ZONA, FORMATO, CLIMA, NEGOCIO, ESTADO, PAIS, LONGITUD, LATITUD "
                "FROM [dbo].[MAESTRA_ALMACENES] "
                f"WHERE EQ_COD2 IN ({quoted})"
            )
            df = pd.read_sql(query, conn)
            df["LONGITUD"] = df["LONGITUD"].apply(self._parse_numeric)
            df["LATITUD"] = df["LATITUD"].apply(self._parse_numeric)
            return df
        finally:
            if conn:
                conn.close()

    def get_opciones_destino(self) -> Dict[str, List[str]]:
        """Devuelve los negocios, formatos y climas disponibles en la maestra de almacenes."""
        conn = None
        try:
            conn = pyodbc.connect(settings.get_connection_string(server="default"))

            def distinct_values(column: str) -> List[str]:
                query = (
                    f"SELECT DISTINCT [{column}] FROM [dbo].[MAESTRA_ALMACENES] "
                    f"WHERE [{column}] IS NOT NULL AND LTRIM(RTRIM([{column}])) <> '' "
                    f"ORDER BY [{column}]"
                )
                df = pd.read_sql(query, conn)
                return [self._safe_str(v) for v in df[column].tolist()]

            return {
                "negocios": distinct_values("NEGOCIO"),
                "formatos": distinct_values("FORMATO"),
                "climas": distinct_values("CLIMA"),
            }
        finally:
            if conn:
                conn.close()

    def build_suggestions(self, file_bytes: bytes, top_n: int = 5, origen_negocio: str = None,
                           destino_negocio: str = None, formatos_destino: List[str] = None,
                           climas_destino: List[str] = None) -> Dict[str, Any]:
        df_items = self.parse_transfer_excel(file_bytes)
        origenes = df_items["CODALMACEN"].unique().tolist()

        df_all = self._load_almacenes()
        df_origins = self._load_origin_almacenes(origenes)

        found_codes = df_origins["CODALMACEN"].astype(str).str.strip().tolist()
        missing_codes = [c for c in origenes if c not in found_codes]

        suggestions = []
        origin_matches = []

        df_items = df_items.merge(df_origins, on="CODALMACEN", how="left", suffixes=("", "_STORE"))
        for _, row in df_items.iterrows():
            origin_code = row["CODALMACEN"]
            origin_lat = row.get("LATITUD")
            origin_lon = row.get("LONGITUD")
            origin_info = {
                "codalmacen": origin_code,
                "nombre": row.get("NOMBRE", ""),
                "direccion": row.get("DIRECCION", row.get("DIRECCIÓN", "")),
                "ciudad": row.get("CIUDAD", ""),
                "zona": row.get("ZONA", ""),
                "formato": row.get("FORMATO", ""),
                "clima": row.get("CLIMA", ""),
                "negocio": row.get("NEGOCIO", ""),
                "estado": row.get("ESTADO", ""),
                "pais": row.get("PAIS", ""),
                "longitud": origin_lon,
                "latitud": origin_lat,
            }

            item_sugerencias = []
            if pd.isna(origin_lat) or pd.isna(origin_lon):
                if origin_code not in missing_codes:
                    missing_codes.append(origin_code)
            else:
                if origen_negocio and origin_info.get("negocio") != origen_negocio:
                    # El origen no coincide con el tipo de negocio seleccionado
                    df_targets = pd.DataFrame()
                else:
                    df_targets = df_all[df_all["CODALMACEN"] != origin_code].copy()
                    if destino_negocio:
                        df_targets = df_targets[df_targets["NEGOCIO"] == destino_negocio].copy()
                    df_base = df_targets

                    # Si el usuario eligió formatos/climas específicos, esos valores tienen prioridad.
                    # Si no eligió nada, se exige el mismo formato/clima que la tienda de origen.
                    formato_explicito = bool(formatos_destino)
                    clima_explicito = bool(climas_destino)
                    formatos_validos = formatos_destino if formato_explicito else (
                        [origin_info["formato"]] if origin_info.get("formato") else None
                    )
                    climas_validos = climas_destino if clima_explicito else (
                        [origin_info["clima"]] if origin_info.get("clima") else None
                    )

                    def _filtrar(base: pd.DataFrame, formatos: List[str] = None, climas: List[str] = None) -> pd.DataFrame:
                        out = base
                        if formatos:
                            out = out[out["FORMATO"].isin(formatos)]
                        if climas:
                            out = out[out["CLIMA"].isin(climas)]
                        return out

                    df_targets = _filtrar(df_base, formatos_validos, climas_validos)

                    # Solo se relajan las dimensiones que quedaron en modo "igual al origen";
                    # una selección explícita del usuario nunca se ignora.
                    if df_targets.empty and not clima_explicito:
                        df_targets = _filtrar(df_base, formatos_validos, None)
                    if df_targets.empty and not formato_explicito:
                        df_targets = _filtrar(df_base, None, climas_validos if clima_explicito else None)
                    if df_targets.empty and not formato_explicito and not clima_explicito:
                        df_targets = df_base

                if not df_targets.empty:
                    df_targets["DISTANCIA_KM"] = df_targets.apply(
                        lambda r: self._haversine(origin_lat, origin_lon, r["LATITUD"], r["LONGITUD"]),
                        axis=1
                    )
                    df_targets = df_targets.sort_values(by="DISTANCIA_KM").head(top_n)
                    for rank, (_, target) in enumerate(df_targets.iterrows()):
                        prioridad = "Alta" if rank == 0 else "Media" if rank == 1 else "Baja"
                        item_sugerencias.append({
                            "codalmacen_origen": origin_code,
                            "nombre_origen": self._safe_str(origin_info["nombre"]),
                            "direccion_origen": self._safe_str(origin_info.get("direccion", "")),
                            "codalmacen_destino": target["CODALMACEN"],
                            "nombre_destino": target.get("NOMBRE", ""),
                            "direccion_destino": self._safe_str(target.get("DIRECCIÓN", target.get("DIRECCION", ""))),
                            "ciudad_destino": target.get("CIUDAD", ""),
                            "zona_destino": target.get("ZONA", ""),
                            "formato_destino": target.get("FORMATO", ""),
                            "clima_destino": target.get("CLIMA", ""),
                            "negocio_destino": target.get("NEGOCIO", ""),
                            "estado_destino": target.get("ESTADO", ""),
                            "pais_destino": target.get("PAIS", ""),
                            "distancia_km": round(float(target["DISTANCIA_KM"]), 2),
                            "prioridad": prioridad,
                        })

            suggestion_entry = {
                "codalmacen": self._safe_str(origin_code),
                "referencia": self._safe_str(row["REFERENCIA"]),
                "talla": self._safe_str(row["TALLA"]),
                "color": self._safe_str(row["COLOR"]),
                "stock": int(self._safe_value(row["STOCK"], 0)),
                "origen": {
                    "codalmacen": self._safe_str(origin_info["codalmacen"]),
                    "nombre": self._safe_str(origin_info["nombre"]),
                    "direccion": self._safe_str(origin_info.get("direccion", "")),
                    "ciudad": self._safe_str(origin_info["ciudad"]),
                    "zona": self._safe_str(origin_info["zona"]),
                    "formato": self._safe_str(origin_info["formato"]),
                    "clima": self._safe_str(origin_info["clima"]),
                    "negocio": self._safe_str(origin_info["negocio"]),
                    "estado": self._safe_str(origin_info["estado"]),
                    "pais": self._safe_str(origin_info["pais"]),
                    "longitud": self._safe_numeric(origin_info["longitud"]),
                    "latitud": self._safe_numeric(origin_info["latitud"]),
                },
                "sugerencias": [
                    {
                        "codalmacen_origen": self._safe_str(s["codalmacen_origen"]),
                        "codalmacen_destino": self._safe_str(s["codalmacen_destino"]),
                        "nombre_destino": self._safe_str(s["nombre_destino"]),
                        "direccion_destino": self._safe_str(s.get("direccion_destino", "")),
                        "ciudad_destino": self._safe_str(s["ciudad_destino"]),
                        "zona_destino": self._safe_str(s["zona_destino"]),
                        "formato_destino": self._safe_str(s["formato_destino"]),
                        "clima_destino": self._safe_str(s.get("clima_destino", "")),
                        "negocio_destino": self._safe_str(s.get("negocio_destino", "")),
                        "estado_destino": self._safe_str(s["estado_destino"]),
                        "pais_destino": self._safe_str(s["pais_destino"]),
                        "distancia_km": self._safe_numeric(s["distancia_km"]),
                        "prioridad": self._safe_str(s.get("prioridad", "")),
                    }
                    for s in item_sugerencias
                ],
            }
            suggestions.append(suggestion_entry)

        return {
            "items": suggestions,
            "almacenes_no_encontrados": [self._safe_str(c) for c in missing_codes],
            "total_items": len(suggestions),
            "total_origenes": len(origenes),
            "total_sugerencias_por_item": top_n,
        }

    def generate_excel(self, results: Dict[str, Any]) -> io.BytesIO:
        output = io.BytesIO()
        rows = []
        for item in results.get("items", []):
            if item.get("sugerencias"):
                for sugerencia in item.get("sugerencias", []):
                    rows.append({
                        "CODALMACEN_ORIGEN": item["codalmacen"],
                        "NOMBRE_ORIGEN": item["origen"]["nombre"],
                        "DIRECCION_ORIGEN": item["origen"]["direccion"],
                        "FORMATO_ORIGEN": item["origen"]["formato"],
                        "CLIMA_ORIGEN": item["origen"]["clima"],
                        "NEGOCIO_ORIGEN": item["origen"]["negocio"],
                        "REFERENCIA": item["referencia"],
                        "TALLA": item["talla"],
                        "COLOR": item["color"],
                        "STOCK": item["stock"],
                        "CODALMACEN_DESTINO": sugerencia["codalmacen_destino"],
                        "NOMBRE_DESTINO": sugerencia["nombre_destino"],
                        "DIRECCION_DESTINO": sugerencia["direccion_destino"],
                        "FORMATO_DESTINO": sugerencia["formato_destino"],
                        "CLIMA_DESTINO": sugerencia["clima_destino"],
                        "NEGOCIO_DESTINO": sugerencia["negocio_destino"],
                        "CIUDAD_DESTINO": sugerencia["ciudad_destino"],
                        "ZONA_DESTINO": sugerencia["zona_destino"],
                        "ESTADO_DESTINO": sugerencia["estado_destino"],
                        "PAIS_DESTINO": sugerencia["pais_destino"],
                        "DISTANCIA_KM": sugerencia["distancia_km"],
                        "PRIORIDAD": sugerencia["prioridad"],
                    })
            else:
                rows.append({
                    "CODALMACEN_ORIGEN": item["codalmacen"],
                    "NOMBRE_ORIGEN": item["origen"]["nombre"],
                    "DIRECCION_ORIGEN": item["origen"]["direccion"],
                    "FORMATO_ORIGEN": item["origen"]["formato"],
                    "CLIMA_ORIGEN": item["origen"]["clima"],
                    "NEGOCIO_ORIGEN": item["origen"]["negocio"],
                    "REFERENCIA": item["referencia"],
                    "TALLA": item["talla"],
                    "COLOR": item["color"],
                    "STOCK": item["stock"],
                    "CODALMACEN_DESTINO": "",
                    "NOMBRE_DESTINO": "SIN SUGERENCIAS",
                    "DIRECCION_DESTINO": "",
                    "FORMATO_DESTINO": "",
                    "CLIMA_DESTINO": "",
                    "NEGOCIO_DESTINO": "",
                    "CIUDAD_DESTINO": "",
                    "ZONA_DESTINO": "",
                    "ESTADO_DESTINO": "",
                    "PAIS_DESTINO": "",
                    "DISTANCIA_KM": None,
                    "PRIORIDAD": "",
                })

        df = pd.DataFrame(rows)
        with pd.ExcelWriter(output, engine="openpyxl") as writer:
            df.to_excel(writer, sheet_name="Sugerencias", index=False)
        output.seek(0)
        return output


traslados_service = TrasladosService()
