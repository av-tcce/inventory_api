import pandas as pd
from datetime import date
from config import settings

SHEET_ASIGNACIONES = "Control Principal"
SHEET_USUARIOS = "Usuarios"
SHEET_PRIORIDAD = "Prioridades"
SHEET_ESTADOS = "Estados"

COL_USUARIOS = "Nombre Usuario"
COL_PRIORIDAD = "Prioridades"
COL_ESTADOS = "Estados"

ASIGNACION_COLUMNS = [
    "ID", "Fecha Asignacion", "Usuario que asigna", "Actividad", "Prioridad",
    "Estado", "Usuario Responsable Asignado", "Descripción / Qué hacer",
    "Notas", "Fecha Updated", "Fecha limite de entrega", "Fecha de cierre"
]

ESTADO_COMPLETADO = "completado"

# Columnas calculadas por el backend: nunca se toman del payload que envía el cliente
COLUMNAS_CALCULADAS = ("ID", "Fecha Updated", "Fecha de cierre")

# Columnas que solo se pueden definir al crear: no se permiten modificar en una actualización
COLUMNAS_NO_EDITABLES = COLUMNAS_CALCULADAS + ("Usuario que asigna",)


def _excel_path() -> str:
    return settings.PLANNER_EXCEL_PATH


def _read_sheet(sheet_name: str) -> pd.DataFrame:
    df = pd.read_excel(_excel_path(), sheet_name=sheet_name)
    # Forzar dtype 'object' en todas las columnas: si Excel trae una columna de
    # fechas vacía, pandas la infiere como float64 y luego falla al asignarle
    # un string ("Invalid value ... for dtype 'float64'") al actualizar filas.
    return df.astype(object)


def _write_sheet(sheet_name: str, df: pd.DataFrame):
    with pd.ExcelWriter(_excel_path(), engine="openpyxl", mode="a", if_sheet_exists="replace") as writer:
        df.to_excel(writer, sheet_name=sheet_name, index=False)


def _read_lookup_column(sheet_name: str, column: str) -> list[str]:
    df = _read_sheet(sheet_name)
    if column not in df.columns:
        raise ValueError(f"No se encontró la columna '{column}' en la hoja '{sheet_name}'.")
    valores = df[column].dropna().astype(str).str.strip()
    valores = valores[valores != ""]
    return sorted(valores.unique().tolist())


def get_usuarios() -> list[str]:
    return _read_lookup_column(SHEET_USUARIOS, COL_USUARIOS)


def get_prioridades() -> list[str]:
    return _read_lookup_column(SHEET_PRIORIDAD, COL_PRIORIDAD)


def get_estados() -> list[str]:
    return _read_lookup_column(SHEET_ESTADOS, COL_ESTADOS)


def listar_asignaciones() -> list[dict]:
    df = _read_sheet(SHEET_ASIGNACIONES)
    df = df.fillna("")
    return df.to_dict(orient="records")


def crear_asignacion(data: dict) -> dict:
    df = _read_sheet(SHEET_ASIGNACIONES)

    if df.empty or "ID" not in df.columns:
        next_id = 1
    else:
        ids = pd.to_numeric(df["ID"], errors="coerce").dropna()
        next_id = int(ids.max()) + 1 if not ids.empty else 1

    nueva_fila = {col: data.get(col, "") for col in ASIGNACION_COLUMNS}
    nueva_fila["ID"] = next_id
    nueva_fila["Fecha Updated"] = date.today().isoformat()
    # La fecha de cierre nunca se define al crear: solo se calcula al marcar Completado
    nueva_fila["Fecha de cierre"] = ""
    if str(nueva_fila.get("Estado", "")).strip().lower() == ESTADO_COMPLETADO:
        nueva_fila["Fecha de cierre"] = date.today().isoformat()

    df = pd.concat([df, pd.DataFrame([nueva_fila])], ignore_index=True)
    _write_sheet(SHEET_ASIGNACIONES, df)

    return nueva_fila


def actualizar_asignacion(asignacion_id: int, data: dict) -> dict:
    df = _read_sheet(SHEET_ASIGNACIONES)

    mask = pd.to_numeric(df["ID"], errors="coerce") == asignacion_id
    if not mask.any():
        raise ValueError(f"No se encontró la asignación con ID {asignacion_id}.")

    estado_anterior = str(df.loc[mask, "Estado"].iloc[0] or "").strip().lower()

    for col in ASIGNACION_COLUMNS:
        if col in COLUMNAS_NO_EDITABLES:
            continue
        if col in data:
            df.loc[mask, col] = data[col]

    df.loc[mask, "Fecha Updated"] = date.today().isoformat()

    estado_nuevo = str(df.loc[mask, "Estado"].iloc[0] or "").strip().lower()
    if estado_nuevo == ESTADO_COMPLETADO and estado_anterior != ESTADO_COMPLETADO:
        # Se acaba de marcar como Completado: registrar la fecha de cierre
        df.loc[mask, "Fecha de cierre"] = date.today().isoformat()
    elif estado_nuevo != ESTADO_COMPLETADO and estado_anterior == ESTADO_COMPLETADO:
        # Se reabrió la actividad: limpiar la fecha de cierre
        df.loc[mask, "Fecha de cierre"] = ""

    _write_sheet(SHEET_ASIGNACIONES, df)

    fila = df.loc[mask].fillna("").iloc[0].to_dict()
    return fila


def eliminar_asignacion(asignacion_id: int) -> bool:
    df = _read_sheet(SHEET_ASIGNACIONES)

    mask = pd.to_numeric(df["ID"], errors="coerce") == asignacion_id
    if not mask.any():
        raise ValueError(f"No se encontró la asignación con ID {asignacion_id}.")

    df = df.loc[~mask].reset_index(drop=True)
    _write_sheet(SHEET_ASIGNACIONES, df)
    return True


def _parse_fecha(value):
    if value is None or value == "":
        return None
    parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed):
        return None
    return parsed.date()


def obtener_reporte() -> dict:
    """Resumen para el submódulo de Gráficos: totales, por estado, por responsable y cumplimiento de fechas."""
    df = _read_sheet(SHEET_ASIGNACIONES)
    df = df.fillna("")

    total_registros = int(len(df))

    por_estado = (
        df.assign(Estado=df["Estado"].astype(str).str.strip().replace("", "Sin Estado"))
          .groupby("Estado", as_index=False)
          .size()
          .rename(columns={"size": "count"})
          .sort_values("count", ascending=False)
          .to_dict(orient="records")
    )

    por_responsable = (
        df.assign(Responsable=df["Usuario Responsable Asignado"].astype(str).str.strip().replace("", "Sin Asignar"))
          .groupby("Responsable", as_index=False)
          .size()
          .rename(columns={"size": "count"})
          .sort_values("count", ascending=False)
          .to_dict(orient="records")
    )

    completadas = df[df["Estado"].astype(str).str.strip().str.lower() == ESTADO_COMPLETADO]

    a_tiempo = 0
    fuera_de_tiempo = 0
    sin_fecha_limite = 0
    for _, row in completadas.iterrows():
        cierre = _parse_fecha(row.get("Fecha de cierre"))
        limite = _parse_fecha(row.get("Fecha limite de entrega"))
        if not cierre or not limite:
            sin_fecha_limite += 1
        elif cierre <= limite:
            a_tiempo += 1
        else:
            fuera_de_tiempo += 1

    return {
        "total_registros": total_registros,
        "por_estado": por_estado,
        "por_responsable": por_responsable,
        "cumplimiento": {
            "total_completadas": int(len(completadas)),
            "a_tiempo": a_tiempo,
            "fuera_de_tiempo": fuera_de_tiempo,
            "sin_fecha_limite": sin_fecha_limite
        }
    }
