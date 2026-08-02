from fastapi import APIRouter, HTTPException, status, UploadFile, File, Form, Query, Body
from typing import List, Dict, Any
from fastapi.responses import Response, StreamingResponse, FileResponse
from models.schemas import (
    RequestDistribucion, ResponseDistribucion, CurveUpdate, 
    ConsultaCurvaUpdate, ResumenDestino, ResumenDistribucion
)
from services.algorithm import distribuir_inventario
from services.sabana_service import generate_sabana_mto
from services.unit_request_service import generate_unit_request
from services.solicitud_unidades_service import consultar_solicitud_unidades, get_solicitud_unidades_dataframe, resumen_solicitud_unidades, resumen_solicitud_unidades_por_referencia
from services.inv_tiendas_service import resumen_inventario_tiendas, exportar_inventario_tiendas
from services import planner_service
from services.outlet_service import generate_sabana_outlet
from services.devolucion_outlets import procesar_devolucion
from services.devolucion_outlets import procesar_devolucion
from services.agotados_service import get_necesidad_data, generate_agotados_excel
from services.agotados_compare_service import agotados_compare_service
from services.clasificacion_service import get_clasificacion_data, generate_clasificacion_excel
from services.referencias_matriculadas_service import get_referencias_matriculadas, get_referencias_matriculadas_export, get_referencias_matriculadas_summary
from services.sales_report_service import get_sales_analytics
from services.curve_service import curve_service
from services.consulta_curvas_service import consulta_curvas_service
from services.almacenes_service import almacenes_service
from services.distribution_helper import distribution_helper
from services.traslados_service import traslados_service
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
    # ── Hoja 1: Inventario ─────────────────────────────────────────────────────
    # Listado completo de inventario con las columnas exactas solicitadas.
    df_inventario = pd.DataFrame([
        {
            "ID": "101", "ALMACEN": "TIENDA_ORIGEN", "FORMATO": "MIC", "ZONA": "CENTRO", 
            "FORMATO 2": "MIC", "REFERENCIA": "SKU001", "DESCRIPCION": "CAMISETA EJEMPLO",
            "TALLA": "M", "COLOR": "NEGRO", "STOCK": 50, "TRANSITO": 0, "STOCKTOTAL": 50,
            "MES": "5", "AÑO": "2026", "GRUPO": "TEXTIL", "SUBLINEA EXITO": "",
            "GENERO": "HOMBRE", "PERSONAJE": "DISNEY", "SILUETA": "BASICA",
            "TIPO PRENDA": "CAMISETA", "PRENDA": "SUPERIOR", "ROPERO": "HOMBRE",
            "CLASIFICACION_PROCESADA": "Línea", "LINEA_OUTLET": "LINEA"
        },
        {
            "ID": "202", "ALMACEN": "MALL_SUR", "FORMATO": "OUTLET MIC", "ZONA": "SUR", 
            "FORMATO 2": "OUTLET", "REFERENCIA": "SKU001", "DESCRIPCION": "CAMISETA EJEMPLO",
            "TALLA": "M", "COLOR": "NEGRO", "STOCK": 2, "TRANSITO": 0, "STOCKTOTAL": 2,
            "MES": "5", "AÑO": "2026", "GRUPO": "TEXTIL", "SUBLINEA EXITO": "",
            "GENERO": "HOMBRE", "PERSONAJE": "DISNEY", "SILUETA": "BASICA",
            "TIPO PRENDA": "CAMISETA", "PRENDA": "SUPERIOR", "ROPERO": "HOMBRE",
            "CLASIFICACION_PROCESADA": "Outlet", "LINEA_OUTLET": "OUTLET"
        },
    ])

    # ── Hoja 2: Parametros ─────────────────────────────────────────────────────
    # Configuración de roles y reglas por tienda.
    df_parametros = pd.DataFrame([
        {"Tienda": "101", "Rol": "ORIGEN",  "Porcentaje": 0,    "Tipo_Aceptado": "Ambos"},
        {"Tienda": "202", "Rol": "DESTINO", "Porcentaje": 60.0, "Tipo_Aceptado": "Linea"},
        {"Tienda": "303", "Rol": "DESTINO", "Porcentaje": 40.0, "Tipo_Aceptado": "Outlet"},
    ])

    # ── Hoja 3: Excepciones ────────────────────────────────────────────────────
    df_excepciones = pd.DataFrame([
        {"Tienda": "202", "SKU": "SKU001", "Genero": "HOMBRE", "Talla": "M",  "Color": "NEGRO", "Tipo": "ASIGNAR_FIJO", "Cantidad": 5,  "Motivo": "Pedido especial"},
    ])

    # ── Escribir todo en un buffer de memoria ───────────────────────────────────
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df_inventario.to_excel(writer,  sheet_name="Inventario",  index=False)
        df_parametros.to_excel(writer,  sheet_name="Parametros",  index=False)
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
    periodo: str = Form("ultimos_30_dias"),
    formatos: str = Form("[]"),
    grupos: str = Form("[]"),
    file: UploadFile = File(..., description="Documento Excel con Inventario y Parametros")
):
    """
    Recibe un archivo excel y extrae la información de sus hojas.
    Utiliza el helper _parse_excel_request para asegurar consistencia.
    """
    import json
    if not (file.filename.endswith('.xlsx') or file.filename.endswith('.xls')):
        raise HTTPException(status_code=400, detail="Debes subir un archivo Excel (.xlsx o .xls)")
        
    contents = await file.read()
    
    try:
        formatos_list = json.loads(formatos)
        grupos_list = json.loads(grupos)
        request, _ = await _parse_excel_request(contents, factor_cobertura, periodo, formatos_list, grupos_list)
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        import traceback
        print(traceback.format_exc())
        raise HTTPException(status_code=400, detail=f"Error parseando Excel: {str(e)}")

    try:
        asignaciones, auditoria = distribuir_inventario(request)
        
        # Calcular Resumen para el UI
        total_origen = sum(o.unidades for o in request.inventario_origen)
        total_dist = sum(a.unidades_asignadas for a in asignaciones)
        
        resumen_destinos = []
        # Agrupar por tienda
        dest_map = {}
        for a in asignaciones:
            dest_map[a.tienda] = dest_map.get(a.tienda, 0) + a.unidades_asignadas
        
        for t, uds in dest_map.items():
            pct = (uds / total_dist * 100) if total_dist > 0 else 0
            resumen_destinos.append(ResumenDestino(tienda=t, unidades=uds, porcentaje=round(pct, 2)))
        
        # Encontrar ID origen
        id_origen = request.inventario_origen[0].tienda if request.inventario_origen else "N/A"
        
        resumen = ResumenDistribucion(
            tienda_origen=id_origen,
            total_origen=total_origen,
            total_distribuido=total_dist,
            destinos=resumen_destinos
        )
        
        return ResponseDistribucion(asignaciones=asignaciones, resumen=resumen)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error interno en algoritmo: {str(e)}")


async def _parse_excel_request(contents: bytes, factor_cobertura: float, periodo: str = "ultimos_30_dias", formatos: list = None, grupos: list = None) -> tuple[RequestDistribucion, list]:
    """
    Helper: lee el Excel (Inventario + Parametros) y devuelve RequestDistribucion + Sugerencias.
    """
    xls = pd.read_excel(io.BytesIO(contents), sheet_name=None, dtype=str)
    
    for sheet in xls:
        xls[sheet] = xls[sheet].dropna(how='all')

    def get_sheet(names):
        for name in names:
            if name in xls:
                return xls[name].copy()
        return pd.DataFrame()

    df_inv = get_sheet(["Inventario", "Inventario_Completo", "inventario"])
    df_par = get_sheet(["Parametros", "Parametros_Distribucion", "parametros"])
    df_exc = get_sheet(["Excepciones", "excepciones"])

    if df_inv.empty or df_par.empty:
        raise ValueError("El archivo Excel debe contener las hojas 'Inventario' y 'Parametros'.")

    # 1. Segmentación
    inv_origen, inv_destino, porcentajes, id_origen = distribution_helper.segment_inventory(df_inv, df_par)

    # 2. Filtrado por Formato/Grupo (si se especifica)
    # Aquí podríamos filtrar inv_destino o porcentajes según los filtros globales
    # Pero usualmente los filtros globales se aplican al proceso.
    
    # 3. Ventas SQL
    skus = list(set([o.sku for o in inv_origen]))
    tiendas = list(set([p.tienda for p in porcentajes]))
    ventas_destino = distribution_helper.fetch_sales_from_sql(skus, tiendas, periodo)

    # 4. Sugerencias por Zona
    sugerencias = distribution_helper.get_zone_suggestions(id_origen, tiendas)

    # 5. Excepciones
    excepciones_list = []
    if not df_exc.empty:
        # Sanitizar y mapear excepciones (mantenemos lógica anterior simplificada)
        df_exc = df_exc.fillna("")
        excepciones_list = df_exc.to_dict(orient="records")
        # Asegurar campos requeridos para el modelo
        for exc in excepciones_list:
            if 'unidades' not in exc and 'cantidad' in exc:
                exc['unidades'] = int(pd.to_numeric(exc['cantidad'], errors='coerce') or 0)
            elif 'unidades' in exc:
                exc['unidades'] = int(pd.to_numeric(exc['unidades'], errors='coerce') or 0)
            
            if 'tipo' not in exc: exc['tipo'] = "ASIGNAR_FIJO"
            exc['sku'] = str(exc.get('SKU', exc.get('sku', ''))).strip()
            exc['tienda'] = str(exc.get('TIENDA', exc.get('tienda', ''))).strip()

    return RequestDistribucion(**{
        "inventario_origen":       inv_origen,
        "inventario_destino":      inv_destino,
        "ventas_destino":          ventas_destino,
        "porcentaje_distribucion": porcentajes,
        "excepciones":             excepciones_list,
        "factor_cobertura":        factor_cobertura,
    }), sugerencias


@router.post("/distribute/excel/resultado", tags=["Distribucion Excel"])
async def distribute_excel_resultado(
    factor_cobertura: float = Form(2.5, description="Factor multiplicador de cobertura (ej: 2.5)"),
    periodo: str = Form("ultimos_30_dias"),
    formatos: str = Form("[]"),
    grupos: str = Form("[]"),
    file: UploadFile = File(..., description="Archivo Excel con Inventario y Parametros")
):
    """
    Procesa el Excel y devuelve un Excel de resultado con tres hojas:
    - 'Distribucion': asignaciones por tienda y SKU.
    - 'Explicacion': detalle del razonamiento del algoritmo.
    - 'Sugerencias': tiendas en la misma zona no incluidas.
    """
    import json
    if not (file.filename.endswith('.xlsx') or file.filename.endswith('.xls')):
        raise HTTPException(status_code=400, detail="El archivo debe ser .xlsx o .xls")

    contents = await file.read()

    try:
        formatos_list = json.loads(formatos)
        grupos_list = json.loads(grupos)
        request, sugerencias = await _parse_excel_request(contents, factor_cobertura, periodo, formatos_list, grupos_list)
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        import traceback
        print(traceback.format_exc())
        raise HTTPException(status_code=400, detail=f"Error leyendo Excel: {str(e)}")

    try:
        asignaciones, auditoria = distribuir_inventario(request)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error en algoritmo: {str(e)}")

    # ── Hoja 1: Distribución ────────────────────────────────────────────────
    df_dist = pd.DataFrame([
        {
            "Tienda Origen":     request.inventario_origen[0].tienda if request.inventario_origen else "",
            "Tienda Destino":    a.tienda,
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

    # ── Hoja 3: Sugerencias ───────────────────────────────────────────────
    df_sug = pd.DataFrame(sugerencias)

    # ── Generar Excel en memoria ───────────────────────────────────────────────
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df_dist.to_excel(writer, sheet_name="Distribucion", index=False)
        df_exp.to_excel(writer,  sheet_name="Explicacion",  index=False)
        df_sug.to_excel(writer,  sheet_name="Sugerencias",  index=False)

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

@router.get("/unit-request/query", tags=["Solicitud de Unidades"])
def query_unit_request(cdcdgo: List[str] = Query(..., description="Una o varias referencias CDCDGO a buscar")):
    """Consulta la tabla tblSolicitudUnidades por una o varias referencias CDCDGO."""
    try:
        rows = consultar_solicitud_unidades(cdcdgo)
        return {"cdcdgo": cdcdgo, "rows": rows}
    except ValueError as ve:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(ve))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Error en la consulta: {str(e)}")

@router.get("/unit-request/query/export", tags=["Solicitud de Unidades"])
def export_unit_request_query(cdcdgo: List[str] = Query(..., description="Una o varias referencias CDCDGO a exportar")):
    """Exporta los registros de tblSolicitudUnidades correspondientes a una o varias referencias CDCDGO."""
    try:
        df = get_solicitud_unidades_dataframe(cdcdgo)
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine="openpyxl") as writer:
            df.to_excel(writer, sheet_name="Detalle", index=False)
        output.seek(0)
        filename = f"detalle_solicitud_unidades_{cdcdgo[0]}.xlsx" if len(cdcdgo) == 1 else "detalle_solicitud_unidades.xlsx"
        return StreamingResponse(
            output,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f"attachment; filename=\"{filename}\""}
        )
    except ValueError as ve:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(ve))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Error exportando detalle: {str(e)}")

@router.get("/unit-request/summary", tags=["Reportes y Análisis"])
def get_unit_request_summary(cdcdgo: List[str] = Query(None, description="Una o varias referencias CDCDGO a consultar")):
    """Retorna un resumen de unidades cargadas en tblSolicitudUnidades para una o varias referencias."""
    if not cdcdgo:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Debe proporcionar al menos una referencia CDCDGO para consultar el resumen. Ejemplo: /unit-request/summary?cdcdgo=REF123&cdcdgo=REF456"
        )
    try:
        return resumen_solicitud_unidades_por_referencia(cdcdgo)
    except ValueError as ve:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(ve))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Error generando resumen: {str(e)}")

@router.get("/inv-tiendas/summary", tags=["Reportes y Análisis"])
def get_inv_tiendas_summary(
    fecha: str = Query(..., description="Fecha de inventario a consultar (YYYY-MM-DD)"),
    warehouse_code: List[str] = Query(None, description="Una o varias tiendas (WarehouseCode) a filtrar"),
    referencia: List[str] = Query(None, description="Una o varias referencias a filtrar")
):
    """Retorna un resumen general y por formato del inventario de tiendas (inv_tiendas) para una fecha dada."""
    try:
        return resumen_inventario_tiendas(fecha, warehouse_code, referencia)
    except ValueError as ve:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(ve))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Error generando resumen de inventario: {str(e)}")

@router.get("/inv-tiendas/export", tags=["Reportes y Análisis"])
def export_inv_tiendas(
    fecha: str = Query(..., description="Fecha de inventario a exportar (YYYY-MM-DD)"),
    warehouse_code: List[str] = Query(None, description="Una o varias tiendas (WarehouseCode) a filtrar"),
    referencia: List[str] = Query(None, description="Una o varias referencias a filtrar")
):
    """Exporta la sábana completa de inventario de tiendas (inv_tiendas) para una fecha dada."""
    try:
        df = exportar_inventario_tiendas(fecha, warehouse_code, referencia)
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine="openpyxl") as writer:
            df.to_excel(writer, sheet_name="Inventario Tiendas", index=False)
        output.seek(0)
        filename = f"inventario_tiendas_{fecha}.xlsx"
        return StreamingResponse(
            output,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f"attachment; filename=\"{filename}\""}
        )
    except ValueError as ve:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(ve))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Error exportando inventario: {str(e)}")

@router.get("/planner/asignaciones", tags=["Planner"])
def get_planner_asignaciones():
    """Lista todas las asignaciones del Planner (hoja Control Principal)."""
    try:
        return planner_service.listar_asignaciones()
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Error consultando asignaciones: {str(e)}")

@router.post("/planner/asignaciones", tags=["Planner"])
def create_planner_asignacion(data: Dict[str, Any] = Body(...)):
    """Crea una nueva asignación en el Planner."""
    try:
        return planner_service.crear_asignacion(data)
    except ValueError as ve:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(ve))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Error creando asignación: {str(e)}")

@router.put("/planner/asignaciones/{asignacion_id}", tags=["Planner"])
def update_planner_asignacion(asignacion_id: int, data: Dict[str, Any] = Body(...)):
    """Actualiza una asignación existente del Planner por ID."""
    try:
        return planner_service.actualizar_asignacion(asignacion_id, data)
    except ValueError as ve:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(ve))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Error actualizando asignación: {str(e)}")

@router.delete("/planner/asignaciones/{asignacion_id}", tags=["Planner"])
def delete_planner_asignacion(asignacion_id: int):
    """Elimina una asignación del Planner por ID."""
    try:
        planner_service.eliminar_asignacion(asignacion_id)
        return {"success": True}
    except ValueError as ve:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(ve))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Error eliminando asignación: {str(e)}")

@router.get("/planner/usuarios", tags=["Planner"])
def get_planner_usuarios():
    """Lista los usuarios disponibles (hoja Usuarios) para poblar el dropdown."""
    try:
        return planner_service.get_usuarios()
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Error consultando usuarios: {str(e)}")

@router.get("/planner/prioridades", tags=["Planner"])
def get_planner_prioridades():
    """Lista las prioridades disponibles (hoja Prioridad) para poblar el dropdown."""
    try:
        return planner_service.get_prioridades()
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Error consultando prioridades: {str(e)}")

@router.get("/planner/estados", tags=["Planner"])
def get_planner_estados():
    """Lista los estados disponibles (hoja Estados) para poblar el dropdown."""
    try:
        return planner_service.get_estados()
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Error consultando estados: {str(e)}")

@router.get("/planner/reporte", tags=["Planner"])
def get_planner_reporte():
    """Resumen para el submódulo de Gráficos: totales, por estado, por responsable y cumplimiento de fechas."""
    try:
        return planner_service.obtener_reporte()
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Error generando reporte: {str(e)}")

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

@router.get("/curves", tags=["Curvas"])
def get_curves():
    """Retorna todos los datos de curvas y los filtros disponibles."""
    try:
        print(f"DEBUG: Iniciando consulta de curvas...")
        data = curve_service.get_all_curves()
        filters = curve_service.get_filters()
        print(f"DEBUG: Consulta exitosa. {len(data)} registros encontrados.")
        return {
            "data": data,
            "filters": filters
        }
    except Exception as e:
        print(f"ERROR en /curves: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/curves/update", tags=["Curvas"])
def update_curves(payload: CurveUpdate):
    """Actualiza una curva específica en el archivo Excel."""
    try:
        success = curve_service.update_curve(payload.tipo_prenda, payload.genero, payload.data)
        return {"success": success, "message": "Curva actualizada correctamente"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/consulta-curvas", tags=["Consulta de Curvas"])
def get_consulta_curvas():
    """Retorna los datos del Excel de curvas para consulta."""
    try:
        data = consulta_curvas_service.get_data()
        filters = consulta_curvas_service.get_filters(data)
        return {
            "data": data,
            "filters": filters
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/consulta-curvas/update", tags=["Consulta de Curvas"])
def update_consulta_curva(payload: ConsultaCurvaUpdate):
    """Actualiza los valores de una curva en el Excel."""
    try:
        success = consulta_curvas_service.update_curve(
            payload.tipo_prenda, 
            payload.genero, 
            payload.talla, 
            payload.data
        )
        return {"success": success, "message": "Registro actualizado correctamente"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/almacenes/filters", tags=["Maestra Almacenes"])
def get_almacenes_filters():
    """Retorna las opciones únicas para filtrar almacenes."""
    try:
        return almacenes_service.get_filter_options()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/almacenes/report", tags=["Maestra Almacenes"])
def get_almacenes_report(
    tiendas_ii: List[str] = Query(None),
    formato: List[str] = Query(None),
    zona: List[str] = Query(None),
    estado: List[str] = Query(None),
    ciudad: List[str] = Query(None),
    zona_ventas: List[str] = Query(None),
    pais: List[str] = Query(None),
    genero: List[str] = Query(None)
):
    """Consulta la maestra de almacenes con filtros múltiples."""
    try:
        filters = {
            "TIENDAS_II": tiendas_ii,
            "FORMATO": formato,
            "ZONA": zona,
            "ESTADO": estado,
            "CIUDAD": ciudad,
            "ZONA_VENTAS": zona_ventas,
            "PAIS": pais,
            "GENERO": genero
        }
        df = almacenes_service.get_maestra_almacenes(filters)
        return {
            "total": len(df),
            "data": df.to_dict(orient="records")
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/almacenes/export", tags=["Maestra Almacenes"])
def export_almacenes(
    tiendas_ii: List[str] = Query(None),
    formato: List[str] = Query(None),
    zona: List[str] = Query(None),
    estado: List[str] = Query(None),
    ciudad: List[str] = Query(None),
    zona_ventas: List[str] = Query(None),
    pais: List[str] = Query(None),
    genero: List[str] = Query(None)
):
    """Exporta la maestra de almacenes a Excel con filtros múltiples."""
    try:
        filters = {
            "TIENDAS_II": tiendas_ii,
            "FORMATO": formato,
            "ZONA": zona,
            "ESTADO": estado,
            "CIUDAD": ciudad,
            "ZONA_VENTAS": zona_ventas,
            "PAIS": pais,
            "GENERO": genero
        }
        df = almacenes_service.get_maestra_almacenes(filters)
        output = almacenes_service.generate_excel(df)
        
        filename = f"Maestra_Almacenes_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
        return StreamingResponse(
            output,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f"attachment; filename={filename}"}
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/traslados/opciones-destino", tags=["Traslados"])
def get_traslados_opciones_destino():
    """Devuelve los negocios, formatos y climas disponibles en la maestra de almacenes para filtrar traslados."""
    try:
        return traslados_service.get_opciones_destino()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error obteniendo las opciones: {str(e)}")

@router.post("/traslados/excel", tags=["Traslados"])
async def suggest_traslados_from_excel(
    file: UploadFile = File(..., description="Archivo Excel con columnas CODALMACEN, REFERENCIA, TALLA, COLOR, STOCK"),
    top_n: int = Form(5, description="Número de tiendas cercanas sugeridas por item"),
    origen_negocio: str = Form(None, description="Tipo de negocio de las tiendas origen. Vacío = todos"),
    destino_negocio: str = Form(None, description="Tipo de negocio de las tiendas destino. Vacío = todos"),
    formatos_destino: List[str] = Form(None, description="Formatos destino permitidos. Vacío = mismo formato que el origen"),
    climas_destino: List[str] = Form(None, description="Climas destino permitidos. Vacío = mismo clima que el origen")
):
    """Recibe un Excel con stock de tienda origen y sugiere posibles traslados a tiendas cercanas."""
    if not (file.filename.endswith('.xlsx') or file.filename.endswith('.xls')):
        raise HTTPException(status_code=400, detail="Debes subir un archivo Excel (.xlsx o .xls)")

    try:
        contents = await file.read()
        results = traslados_service.build_suggestions(
            contents,
            top_n=top_n,
            origen_negocio=(origen_negocio or None),
            destino_negocio=(destino_negocio or None),
            formatos_destino=(formatos_destino or None),
            climas_destino=(climas_destino or None)
        )
        return results
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error procesando el Excel de traslados: {str(e)}")

@router.post("/traslados/excel/export", tags=["Traslados"])
async def export_traslados_from_excel(
    file: UploadFile = File(..., description="Archivo Excel con columnas CODALMACEN, REFERENCIA, TALLA, COLOR, STOCK"),
    top_n: int = Form(5, description="Número de tiendas cercanas sugeridas por item"),
    origen_negocio: str = Form(None, description="Tipo de negocio de las tiendas origen. Vacío = todos"),
    destino_negocio: str = Form(None, description="Tipo de negocio de las tiendas destino. Vacío = todos"),
    formatos_destino: List[str] = Form(None, description="Formatos destino permitidos. Vacío = mismo formato que el origen"),
    climas_destino: List[str] = Form(None, description="Climas destino permitidos. Vacío = mismo clima que el origen")
):
    """Genera un archivo Excel con las sugerencias de traslado."""
    if not (file.filename.endswith('.xlsx') or file.filename.endswith('.xls')):
        raise HTTPException(status_code=400, detail="Debes subir un archivo Excel (.xlsx o .xls)")

    try:
        contents = await file.read()
        results = traslados_service.build_suggestions(
            contents,
            top_n=top_n,
            origen_negocio=(origen_negocio or None),
            destino_negocio=(destino_negocio or None),
            formatos_destino=(formatos_destino or None),
            climas_destino=(climas_destino or None)
        )
        output = traslados_service.generate_excel(results)
        filename = f"Traslados_Sugerencias_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
        return StreamingResponse(
            output,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f"attachment; filename={filename}"}
        )
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error generando el Excel de traslados: {str(e)}")

@router.get("/referencias-matriculadas", tags=["Referencias Matriculadas"])
def get_referencias_matriculadas(fecha: str = None, codigo_tienda: str = None, pais: str = "Colombia"):
    """
    Devuelve un resumen de referencias matriculadas a partir de tblAgotados.
    Filtra por país, mínimo mayor a cero, fecha opcional y tienda opcional.
    """
    try:
        summary = get_referencias_matriculadas_summary(
            fecha=fecha,
            codigo_tienda=codigo_tienda,
            pais=pais,
        )
        return summary
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/referencias-matriculadas/export", tags=["Referencias Matriculadas"])
def export_referencias_matriculadas(fecha: str = None, codigo_tienda: str = None, pais: str = "Colombia"):
    """
    Exporta el detalle completo de referencias matriculadas según los filtros seleccionados.
    """
    try:
        detail = get_referencias_matriculadas_export(fecha=fecha, codigo_tienda=codigo_tienda, pais=pais)
        if detail is None:
            raise HTTPException(status_code=404, detail="No se encontraron datos para los filtros seleccionados.")

        if isinstance(detail, dict):
            detail = pd.DataFrame(detail)

        if not hasattr(detail, "empty"):
            raise HTTPException(status_code=500, detail="El detalle de exportación no es un DataFrame válido.")

        if detail.empty:
            raise HTTPException(status_code=404, detail="No se encontraron datos para los filtros seleccionados.")

        output = io.BytesIO()
        with pd.ExcelWriter(output, engine="openpyxl") as writer:
            detail.to_excel(writer, sheet_name="Detalle", index=False)
        output.seek(0)

        display_date = fecha or datetime.now().strftime("%Y%m%d")
        filename = f"Referencias_Matriculadas_{display_date}.xlsx"
        headers = {"Content-Disposition": f'attachment; filename="{filename}"'}

        return StreamingResponse(
            output,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers=headers,
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/agotados/compare", tags=["Comparación de Agotados"])
def get_agotados_compare(fecha_1: str, fecha_2: str, formatos: str = Query(None), grupos: str = Query(None)):
    """
    Compara el comportamiento de los agotados entre dos fechas por formato y referencia.
    """
    import json
    try:
        formatos_list = json.loads(formatos) if formatos else None
        grupos_list = json.loads(grupos) if grupos else None

        result = agotados_compare_service.compare_agotados_data(fecha_1, fecha_2, formatos_list, grupos_list)
        res_agotadas = result["referencias_agotadas"]
        res_general = result["resumen_general"]
        res_formatos = result["resumen_formatos"]
        res_agotadas_dict = res_agotadas.replace([float('inf'), float('-inf')], None).fillna("").to_dict(orient="records")
        res_formatos_dict = res_formatos.replace([float('inf'), float('-inf')], None).fillna("").to_dict(orient="records")
        return {
            "referencias_agotadas": res_agotadas_dict,
            "resumen_general": res_general,
            "resumen_formatos": res_formatos_dict
        }
    except Exception as e:
        import traceback
        print(traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/agotados/compare/export", tags=["Comparación de Agotados"])
def export_agotados_compare(fecha_1: str, fecha_2: str, formatos: str = Query(None), grupos: str = Query(None)):
    """
    Genera y descarga el archivo Excel completo con la comparación de agotados.
    """
    import json
    try:
        formatos_list = json.loads(formatos) if formatos else None
        grupos_list = json.loads(grupos) if grupos else None

        result = agotados_compare_service.compare_agotados_data(fecha_1, fecha_2, formatos_list, grupos_list)
        
        if result["resumen_formatos"].empty and result["detalle_referencias"].empty:
            raise HTTPException(status_code=404, detail="No se encontraron datos para las fechas seleccionadas.")

        output = agotados_compare_service.generate_comparison_excel(
            result["resumen_formatos"],
            result["detalle_referencias"],
            fecha_1,
            fecha_2
        )
        
        filename = f"Comparacion_Agotados_{fecha_1}_vs_{fecha_2}.xlsx"
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
        import traceback
        print(traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(e))



