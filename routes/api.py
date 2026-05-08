from fastapi import APIRouter, HTTPException, status, UploadFile, File, Form
from fastapi.responses import Response, StreamingResponse, FileResponse
from models.schemas import RequestDistribucion, ResponseDistribucion
from services.algorithm import distribuir_inventario
from services.sabana_service import generate_sabana_mto
from services.unit_request_service import generate_unit_request
from services.outlet_service import generate_sabana_outlet
from services.devolucion_outlets import procesar_devolucion
from services.devolucion_outlets import procesar_devolucion
from services.agotados_service import get_necesidad_data, generate_agotados_excel
from services.clasificacion_service import get_clasificacion_data, generate_clasificacion_excel
from services.sales_report_service import get_sales_analytics
import pandas as pd
import io
import os
from datetime import datetime

router = APIRouter()

@router.get("/health", tags=["Health"])
def health_check():
    """
    Endpoint para verificar el estado de salud del servicio.
    """
    return {"status": "ok", "message": "Inventory Distribution API is running"}

@router.get("/template", tags=["Template"])
def download_template():
    """
    Descarga un archivo Excel de plantilla con las 5 hojas requeridas y datos de ejemplo.
    Úsalo como guía para construir tu propio archivo y subirlo al endpoint /distribute/excel.
    """
    # ── Hoja 1: Origen ─────────────────────────────────────────────────────────
    # La tienda que cierra / cede el inventario para redistribuir.
    df_origen = pd.DataFrame([
        {"Tienda": "TIENDA_ORIGEN", "SKU": "SKU001", "Genero": "HOMBRE", "Talla": "M",  "Color": "NEGRO", "Unidades": 50},
        {"Tienda": "TIENDA_ORIGEN", "SKU": "SKU002", "Genero": "MUJER",  "Talla": "38", "Color": "ROJO",  "Unidades": 30},
    ])

    # ── Hoja 2: Destino ────────────────────────────────────────────────────────
    # Stock que cada tienda destino YA tiene en piso (para evitar sobrestock).
    df_destino = pd.DataFrame([
        {"Tienda": "MALL_SUR",   "SKU": "SKU001", "Genero": "HOMBRE", "Talla": "M",  "Color": "NEGRO", "Unidades Actuales": 2},
        {"Tienda": "MALL_SUR",   "SKU": "SKU002", "Genero": "MUJER",  "Talla": "38", "Color": "ROJO",  "Unidades Actuales": 0},
        {"Tienda": "MALL_NORTE", "SKU": "SKU001", "Genero": "HOMBRE", "Talla": "M",  "Color": "NEGRO", "Unidades Actuales": 0},
        {"Tienda": "MALL_NORTE", "SKU": "SKU002", "Genero": "MUJER",  "Talla": "38", "Color": "ROJO",  "Unidades Actuales": 4},
        {"Tienda": "CENTRO",     "SKU": "SKU001", "Genero": "HOMBRE", "Talla": "M",  "Color": "NEGRO", "Unidades Actuales": 1},
        {"Tienda": "CENTRO",     "SKU": "SKU002", "Genero": "MUJER",  "Talla": "38", "Color": "ROJO",  "Unidades Actuales": 0},
    ])

    # ── Hoja 3: Ventas ─────────────────────────────────────────────────────────
    # Ventas históricas por (Tienda, SKU). Misma clave que Destino.
    # Si una tienda no vendió un SKU, ponla con Unidades Vendidas = 0.
    df_ventas = pd.DataFrame([
        {"Tienda": "MALL_SUR",   "SKU": "SKU001", "Genero": "HOMBRE", "Talla": "M",  "Color": "NEGRO", "Unidades Vendidas": 10},
        {"Tienda": "MALL_SUR",   "SKU": "SKU002", "Genero": "MUJER",  "Talla": "38", "Color": "ROJO",  "Unidades Vendidas": 8},
        {"Tienda": "MALL_NORTE", "SKU": "SKU001", "Genero": "HOMBRE", "Talla": "M",  "Color": "NEGRO", "Unidades Vendidas": 15},
        {"Tienda": "MALL_NORTE", "SKU": "SKU002", "Genero": "MUJER",  "Talla": "38", "Color": "ROJO",  "Unidades Vendidas": 12},
        {"Tienda": "CENTRO",     "SKU": "SKU001", "Genero": "HOMBRE", "Talla": "M",  "Color": "NEGRO", "Unidades Vendidas": 0},
        {"Tienda": "CENTRO",     "SKU": "SKU002", "Genero": "MUJER",  "Talla": "38", "Color": "ROJO",  "Unidades Vendidas": 5},
    ])

    # ── Hoja 4: Porcentajes ────────────────────────────────────────────────────
    # Peso base de distribución por tienda. La suma de Porcentaje DEBE ser 100.
    df_porcentajes = pd.DataFrame([
        {"Tienda": "MALL_SUR",   "Nombre": "Mall del Sur",   "Porcentaje": 30.0},
        {"Tienda": "MALL_NORTE", "Nombre": "Mall del Norte", "Porcentaje": 50.0},
        {"Tienda": "CENTRO",     "Nombre": "Tienda Centro",  "Porcentaje": 20.0},
    ])

    # ── Hoja 5: Excepciones ────────────────────────────────────────────────────
    # ASIGNAR_FIJO → enviar exactamente N unidades de ese SKU a esa tienda.
    # NO_ASIGNAR   → no enviar nada de ese SKU a esa tienda.
    # Si no tienes excepciones, deja la hoja con solo los encabezados.
    df_excepciones = pd.DataFrame([
        {"Tienda": "MALL_SUR", "SKU": "SKU001", "Genero": "HOMBRE", "Talla": "M",  "Color": "NEGRO", "Tipo": "ASIGNAR_FIJO", "Cantidad": 5,  "Motivo": "Pedido especial cliente VIP"},
        {"Tienda": "CENTRO",   "SKU": "SKU001", "Genero": "HOMBRE", "Talla": "M",  "Color": "NEGRO", "Tipo": "NO_ASIGNAR",   "Cantidad": "", "Motivo": "Local en remodelación"},
    ])

    # ── Escribir todo en un buffer de memoria ───────────────────────────────────
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df_origen.to_excel(writer,      sheet_name="Origen",      index=False)
        df_destino.to_excel(writer,     sheet_name="Destino",     index=False)
        df_ventas.to_excel(writer,      sheet_name="Ventas",      index=False)
        df_porcentajes.to_excel(writer, sheet_name="Porcentajes", index=False)
        df_excepciones.to_excel(writer, sheet_name="Excepciones", index=False)

    # Preparamos el buffer para lectura
    output.seek(0)
    
    headers = {
        'Content-Disposition': 'attachment; filename="plantilla_distribucion.xlsx"'
    }
    
    return StreamingResponse(
        output,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers=headers
    )


@router.post("/distribute", response_model=ResponseDistribucion, tags=["Distribucion"])
def distribute_inventory(request: RequestDistribucion):
    """
    Recibe el estado actual del inventario via JSON crudo y devuelve asignaciones en JSON.
    """
    try:
        asignaciones, _ = distribuir_inventario(request)   # el algoritmo devuelve (asignaciones, auditoria)
        return ResponseDistribucion(asignaciones=asignaciones)
    except ValueError as ve:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(ve))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Error interno: {str(e)}")


@router.post("/distribute/excel", response_model=ResponseDistribucion, tags=["Distribucion Excel"])
async def distribute_inventory_excel(
    factor_cobertura: float = Form(2.5, description="Factor multiplicador de cobertura (ej: 2.5)"),
    file: UploadFile = File(..., description="Documento Excel con las 5 tablas necesarias")
):
    """
    Recibe un archivo excel y extrae la información de sus hojas.
    Utiliza el helper _parse_excel_request para asegurar consistencia.
    """
    if not (file.filename.endswith('.xlsx') or file.filename.endswith('.xls')):
        raise HTTPException(status_code=400, detail="Debes subir un archivo Excel (.xlsx o .xls)")
        
    contents = await file.read()
    
    try:
        request = _parse_excel_request(contents, factor_cobertura)
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Error parseando Excel: {str(e)}")

    try:
        asignaciones, _ = distribuir_inventario(request)
        return ResponseDistribucion(asignaciones=asignaciones)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error interno en algoritmo: {str(e)}")


def _parse_excel_request(contents: bytes, factor_cobertura: float) -> RequestDistribucion:
    """
    Helper reutilizable: lee el Excel en memoria y devuelve un RequestDistribucion validado.
    Limpia los valores nulos (NaN) para evitar errores de validación en Pydantic.
    """
    xls = pd.read_excel(io.BytesIO(contents), sheet_name=None, dtype=str)
    
    # Limpiar filas completamente vacías
    for sheet in xls:
        xls[sheet] = xls[sheet].dropna(how='all')

    def get_sheet(names):
        for name in names:
            if name in xls:
                # Retornamos una copia para no afectar el dict original si se requiere re-uso
                return xls[name].copy()
        raise ValueError(f"No se encontró la hoja '{names[0]}'. Hojas disponibles: {list(xls.keys())}")

    # Cargar hojas con nombres posibles (robusto a variaciones)
    df_origen      = get_sheet(["Origen", "Inventario_Origen", "inventario origen"])
    df_destino     = get_sheet(["Destino", "Inventario_Destino", "inventario destino"])
    df_ventas      = get_sheet(["Ventas", "Ventas_Destino", "ventas destino"])
    df_porcentajes = get_sheet(["Porcentajes", "porcentaje ventas", "porcentaje de ventas"])
    
    df_excepciones = pd.DataFrame()
    try:
        df_excepciones = get_sheet(["Excepciones", "tabla de excepciones", "excepciones"])
    except ValueError:
        pass

    def parse_col_numeric(df, col_name, as_float=False):
        """Busca columnas numéricas por nombre y las convierte, manejando nulos."""
        for col in df.columns:
            if col_name.lower() in col.lower():
                if as_float:
                    df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0.0)
                else:
                    df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0).astype(int)

    # 1. Convertir columnas numéricas primero
    parse_col_numeric(df_origen,      "unidades")
    parse_col_numeric(df_destino,     "unidades")
    parse_col_numeric(df_ventas,      "unidades")
    parse_col_numeric(df_porcentajes, "porcentaje", as_float=True)
    if not df_excepciones.empty:
        parse_col_numeric(df_excepciones, "cantidad") or parse_col_numeric(df_excepciones, "unidades")

    def sanitize_cols(df):
        """Normaliza los nombres de las columnas para que coincidan con los modelos de Pydantic."""
        mapper = {}
        for c in df.columns:
            c_low = str(c).lower().strip()
            if "tienda" in c_low or "codigo" in c_low:
                mapper[c] = "tienda"
            elif "sku" in c_low:
                mapper[c] = "sku"
            elif c_low in ("genero", "género", "gender", "sexo"):
                mapper[c] = "genero"
            elif c_low in ("talla", "talle", "size", "medida"):
                mapper[c] = "talla"
            elif c_low in ("color", "colour", "tono"):
                mapper[c] = "color"
            elif "actual" in c_low:
                mapper[c] = "unidades_actuales"
            elif "vendida" in c_low:
                mapper[c] = "unidades_vendidas"
            elif "cantidad" in c_low:
                mapper[c] = "unidades"
            elif "unidades" in c_low and "unidades_actuales" not in mapper.values() and "unidades_vendidas" not in mapper.values():
                mapper[c] = "unidades"
            elif c_low in ("%",) or "porcentaje" in c_low:
                mapper[c] = "porcentaje"
            elif "nombre" in c_low:
                mapper[c] = "nombre"
            elif "tipo" in c_low:
                mapper[c] = "tipo"
            elif "motivo" in c_low:
                mapper[c] = "motivo"
        return df.rename(columns=mapper)

    # 2. Sanitizar nombres de columnas
    df_origen      = sanitize_cols(df_origen)
    df_destino     = sanitize_cols(df_destino)
    df_ventas      = sanitize_cols(df_ventas)
    df_porcentajes = sanitize_cols(df_porcentajes)

    # 3. CRUCIAL: Reemplazar cualquier NaN restante con string vacío
    # Esto soluciona los errores de validación de Pydantic para Genero, Talla, Color, etc.
    df_origen      = df_origen.fillna("")
    df_destino     = df_destino.fillna("")
    df_ventas      = df_ventas.fillna("")
    df_porcentajes = df_porcentajes.fillna("")

    excepciones_list = []
    if not df_excepciones.empty:
        df_excepciones = sanitize_cols(df_excepciones)
        df_excepciones = df_excepciones.fillna("")
        if "tipo" not in df_excepciones.columns:
            df_excepciones["tipo"] = "ASIGNAR_FIJO"
        # Asegurar que si tipo es ASIGNAR_FIJO la columna 'unidades' exista (mapeada de cantidad)
        if "unidades" not in df_excepciones.columns and "cantidad" in df_excepciones.columns:
             df_excepciones = df_excepciones.rename(columns={"cantidad": "unidades"})
        
        excepciones_list = df_excepciones.to_dict(orient="records")

    return RequestDistribucion(**{
        "inventario_origen":       df_origen.to_dict(orient="records"),
        "inventario_destino":      df_destino.to_dict(orient="records"),
        "ventas_destino":          df_ventas.to_dict(orient="records"),
        "porcentaje_distribucion": df_porcentajes.to_dict(orient="records"),
        "excepciones":             excepciones_list,
        "factor_cobertura":        factor_cobertura,
    })


@router.post("/distribute/excel/resultado", tags=["Distribucion Excel"])
async def distribute_excel_resultado(
    factor_cobertura: float = Form(2.5, description="Factor multiplicador de cobertura (ej: 2.5)"),
    file: UploadFile = File(..., description="Archivo Excel con las 5 hojas requeridas")
):
    """
    Procesa el Excel y devuelve un Excel de resultado con dos hojas:
    - 'Distribucion': asignaciones por tienda y SKU.
    - 'Explicacion': detalle del razonamiento del algoritmo por cada fila.
    """
    if not (file.filename.endswith('.xlsx') or file.filename.endswith('.xls')):
        raise HTTPException(status_code=400, detail="El archivo debe ser .xlsx o .xls")

    contents = await file.read()

    try:
        request = _parse_excel_request(contents, factor_cobertura)
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Error leyendo Excel: {str(e)}")

    try:
        asignaciones, auditoria = distribuir_inventario(request)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error en algoritmo: {str(e)}")

    # ── Hoja 1: Distribución ────────────────────────────────────────────────
    df_dist = pd.DataFrame([
        {
            "Tienda":             a.tienda,
            "SKU":               a.sku,
            "Genero":            a.genero,
            "Talla":             a.talla,
            "Color":             a.color,
            "Unidades Asignadas": a.unidades_asignadas,
            "Tipo Asignacion":   a.tipo_asignacion,
        }
        for a in asignaciones
    ])

    # ── Hoja 2: Explicación ───────────────────────────────────────────────
    df_exp = pd.DataFrame([
        {
            "SKU":                     a.sku,
            "Tienda":                  a.tienda,
            "Genero":                  a.genero,
            "Talla":                   a.talla,
            "Color":                   a.color,
            "Tipo de Decision":        a.decision,
            "Ventas Historicas (uds)": a.ventas,
            "Capacidad Maxima (uds)":  a.capacidad_max,
            "Stock Actual Destino":    a.stock_actual,
            "Unidades Asignadas":      a.unidades_asignadas,
            "Razon / Explicacion":     a.razon,
        }
        for a in auditoria
    ])

    # ── Generar Excel en memoria ───────────────────────────────────────────────
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df_dist.to_excel(writer, sheet_name="Distribucion", index=False)
        df_exp.to_excel(writer,  sheet_name="Explicacion",  index=False)

    # Preparamos el buffer para lectura
    output.seek(0)
    
    headers = {
        'Content-Disposition': 'attachment; filename="resultado_distribucion.xlsx"'
    }
    
    return StreamingResponse(
        output,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers=headers
    )


@router.post("/sabana-mto/generate", tags=["Sabana MTO"])
async def generate_sabana_mto_endpoint(
    portafolio: UploadFile = File(..., description="Archivo Excel del Portafolio Activo"),
    sabana_anterior: UploadFile = File(..., description="Archivo Excel de la Sabana MTO del mes anterior"),
    extra1: UploadFile = File(None, description="Archivo adicional 1 (Opcional)"),
    extra2: UploadFile = File(None, description="Archivo adicional 2 (Opcional)")
):
    """
    Genera el consolidado de la Sabana MTO en cascada: Portafolio + Sabana Anterior + Extras + SQL.
    """
    if not (portafolio.filename.endswith('.xlsx') or portafolio.filename.endswith('.xls')):
        raise HTTPException(status_code=400, detail="El Portafolio debe ser un archivo Excel.")
    
    try:
        portafolio_content = await portafolio.read()
        sabana_ant_content = await sabana_anterior.read()
        
        # Leer contenidos extras si existen
        extra1_content = await extra1.read() if extra1 else None
        extra2_content = await extra2.read() if extra2 else None
        
        output = generate_sabana_mto(
            portafolio_content, 
            sabana_ant_content,
            extra1_content,
            extra2_content
        )
        
        headers = {
            'Content-Disposition': 'attachment; filename="Sabana_MTO_Consolidada.xlsx"'
        }
        
        return StreamingResponse(
            output,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers=headers
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error generando Sabana MTO: {str(e)}")


@router.post("/unit-request/generate", tags=["Solicitud de Unidades"])
async def generate_unit_request_endpoint(
    solicitud: UploadFile = File(..., description="Archivo Excel de Solicitud de Unidades (Hoja DETALLE)"),
    canal: str = Form("Todos", description="Filtrar por canal: Todos, Cadenas o Tiendas")
):
    """
    Genera la solicitud de unidades calculando la nueva curva basada en históricos de ventas y jerarquías.
    Utiliza rutas maestras estáticas configuradas en el servidor.
    """
    if not (solicitud.filename.endswith('.xlsx') or solicitud.filename.endswith('.xls')):
        raise HTTPException(status_code=400, detail="El archivo de solicitud debe ser un Excel.")
    
    try:
        solicitud_content = await solicitud.read()
        
        output = generate_unit_request(solicitud_content, canal)
        
        fecha_hoy = datetime.now().strftime("%d-%m-%Y")
        filename = f"solicitud_unidades_{fecha_hoy}.xlsx"
        
        headers = {
            'Content-Disposition': f'attachment; filename="{filename}"'
        }
        
        return StreamingResponse(
            output,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers=headers
        )
    except Exception as e:
        import traceback
        print(traceback.format_exc())
        raise HTTPException(status_code=500, detail=f"Error generando Solicitud de Unidades: {str(e)}")

@router.post("/sabana-outlet/generate", tags=["Sabana Outlet"])
async def generate_sabana_outlet_endpoint(
    tc_inventario: UploadFile = File(..., description="Archivo Excel TC INVENTARIO (Hojas Cargue y Requerido)")
):
    """
    Genera el reporte de distribución Sabana Outlet.
    Requiere el archivo TC INVENTARIO y utiliza maestras estáticas del servidor.
    """
    if not (tc_inventario.filename.endswith('.xlsx') or tc_inventario.filename.endswith('.xls')):
        raise HTTPException(status_code=400, detail="El archivo TC INVENTARIO debe ser un Excel.")
    
    try:
        tc_content = await tc_inventario.read()
        
        output = generate_sabana_outlet(tc_content)
        
        fecha_hoy = datetime.now().strftime("%d-%m-%Y")
        filename = f"Sabanas_Outlet_{fecha_hoy}.xlsx"
        
        headers = {
            'Content-Disposition': f'attachment; filename="{filename}"'
        }
        
        return StreamingResponse(
            output,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers=headers
        )
    except Exception as e:
        import traceback
        print(traceback.format_exc())
        raise HTTPException(status_code=500, detail=f"Error generando Sabana Outlet: {str(e)}")


@router.post("/procesar-devolucion", tags=["Devolucion Outlets"])
async def procesar_devolucion_endpoint(
    file: UploadFile = File(..., description="Archivo Excel de inventario"),
    formatos: str = Form("[]", description="Lista de formatos seleccionados en formato JSON"),
    grupos: str = Form("[]", description="Lista de grupos seleccionados en formato JSON"),
    periodo: str = Form("mes_anterior", description="Periodo de ventas: mes_anterior o ultimos_30_dias")
):
    import json
    if not (file.filename.endswith('.xlsx') or file.filename.endswith('.xls')):
        raise HTTPException(status_code=400, detail="El archivo debe ser un Excel (.xlsx o .xls)")
    
    try:
        formatos_list = json.loads(formatos)
    except Exception:
        formatos_list = []

    try:
        grupos_list = json.loads(grupos)
    except Exception:
        grupos_list = []

    try:
        content = await file.read()
        resultado = procesar_devolucion(content, formatos_list, grupos_list, periodo)
        return resultado
    except ValueError as e:
        import traceback
        print(traceback.format_exc())
        raise HTTPException(status_code=400, detail=str(e))
    except ConnectionError as e:
        import traceback
        print(traceback.format_exc())
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        import traceback
        print(traceback.format_exc())
        raise HTTPException(status_code=500, detail=f"Error procesando devolución: {str(e)}")


@router.get("/descargar-devolucion", tags=["Devolucion Outlets"])
async def descargar_devolucion_endpoint():
    file_path = "resultado_devolucion.xlsx"
    if os.path.exists(file_path):
        return FileResponse(
            path=file_path,
            filename="resultado_devolucion.xlsx",
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
    raise HTTPException(status_code=404, detail="Archivo no encontrado.")


@router.get("/agotados/report", tags=["Buscador de Agotados"])
def get_agotados_report(fecha: str, formatos: str = None, grupos: str = None, tipo: str = 'necesidad'):
    """
    Retorna los datos de necesidad, agotados o desmatriculados para una fecha y filtros.
    Limitado a los primeros 1000 registros para la vista previa.
    """
    import json
    try:
        formatos_list = json.loads(formatos) if formatos else None
        grupos_list = json.loads(grupos) if grupos else None
        
        df = get_necesidad_data(fecha, formatos_list, grupos_list, tipo)
        # Convertimos fechas a string para JSON
        if not df.empty and 'FECHA' in df.columns:
            df['FECHA'] = df['FECHA'].astype(str)
        
        # Retornamos un subset para la tabla y el total de filas
        total_rows = len(df)
        data = df.head(1000).to_dict(orient="records")
        
        return {
            "total": total_rows,
            "data": data
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/agotados/export", tags=["Buscador de Agotados"])
def export_agotados(fecha: str, formatos: str = None, grupos: str = None, tipo: str = 'necesidad'):
    """
    Genera y descarga el archivo Excel completo según el tipo de reporte.
    """
    import json
    try:
        formatos_list = json.loads(formatos) if formatos else None
        grupos_list = json.loads(grupos) if grupos else None
        
        df = get_necesidad_data(fecha, formatos_list, grupos_list, tipo)
        if df.empty:
            raise HTTPException(status_code=404, detail="No se encontraron datos para la fecha seleccionada.")
            
        output = generate_agotados_excel(df)
        
        filename = f"Necesidad_Tiendas_{fecha}.xlsx"
        headers = {
            'Content-Disposition': f'attachment; filename="{filename}"'
        }
        
        return StreamingResponse(
            output,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers=headers
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/clasificacion/report", tags=["Clasificación"])
def get_clasificacion_report(fecha: str, referencia: str = None):
    """
    Retorna los datos de clasificación y estadísticas para la última carga de la semana de la fecha.
    """
    try:
        df, stats = get_clasificacion_data(fecha, referencia)
        
        # Convertimos fechas a string para JSON si existen
        for col in df.columns:
            if pd.api.types.is_datetime64_any_dtype(df[col]):
                df[col] = df[col].astype(str)
                
        return {
            "total": stats.get("total", 0),
            "stats": stats,
            "data": df.head(1000).to_dict(orient='records')
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/clasificacion/export", tags=["Clasificación"])
def export_clasificacion(fecha: str, referencia: str = None):
    """
    Genera y descarga el archivo Excel completo de clasificación (semana/referencia).
    """
    try:
        df, stats = get_clasificacion_data(fecha, referencia)
        if df.empty:
            raise HTTPException(status_code=404, detail="No se encontraron datos para los filtros seleccionados.")
            
        output = generate_clasificacion_excel(df)
        
        # Usar la fecha real de carga encontrada si es posible
        display_date = stats.get("ultima_fecha_semana", fecha)
        filename = f"Clasificacion_{display_date}.xlsx"
        if referencia:
            filename = f"Clasificacion_{display_date}_{referencia}.xlsx"
            
        headers = {'Content-Disposition': f'attachment; filename="{filename}"'}
        return StreamingResponse(output, media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', headers=headers)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/sales/analytics", tags=["Análisis de Ventas"])
def get_sales_report(inicio: str, fin: str, formatos: str = None, grupos: str = None):
    """
    Retorna el reporte analítico de ventas por formato y grupo para un rango de fechas.
    """
    import json
    try:
        formatos_list = json.loads(formatos) if formatos else None
        grupos_list = json.loads(grupos) if grupos else None
        
        result = get_sales_analytics(inicio, fin, formatos_list, grupos_list)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

