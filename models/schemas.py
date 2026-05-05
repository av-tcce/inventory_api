from pydantic import BaseModel, Field, model_validator
from typing import List, Literal, Optional

# ────────────────────────────────────────────────────────────────────────────────
# INPUT MODELS
# Llave de relación entre hojas: (tienda, sku)
# Los campos genero/talla/color son descriptivos y viajan al output final.
# ────────────────────────────────────────────────────────────────────────────────

class InventarioOrigenItem(BaseModel):
    """Inventario de la tienda que va a cerrar / ceder el stock."""
    tienda:  str = Field(..., description="Código de la tienda ORIGEN")
    sku:     str = Field(..., description="SKU del producto (llave única por variante)")
    genero:  str = Field(default="",  description="Género (ej: HOMBRE, MUJER, UNISEX)")
    talla:   str = Field(default="",  description="Talla (ej: S, M, L, 38, 40…)")
    color:   str = Field(default="",  description="Color del artículo")
    unidades: int = Field(..., ge=0,  description="Unidades disponibles para distribuir")

class InventarioDestinoItem(BaseModel):
    """Stock que cada tienda destino ya tiene antes de recibir mercancía."""
    tienda:           str = Field(..., description="Código de la tienda DESTINO")
    sku:              str = Field(..., description="SKU del producto")
    genero:           str = Field(default="",  description="Género")
    talla:            str = Field(default="",  description="Talla")
    color:            str = Field(default="",  description="Color")
    unidades_actuales: int = Field(..., ge=0, description="Unidades que la tienda ya tiene")

class VentasDestinoItem(BaseModel):
    """
    Ventas históricas por tienda y SKU.
    Clave de relación con Destino: (tienda, sku).
    """
    tienda:           str = Field(..., description="Código de la tienda")
    sku:              str = Field(..., description="SKU — mismo que en Origen y Destino")
    genero:           str = Field(default="",  description="Género")
    talla:            str = Field(default="",  description="Talla")
    color:            str = Field(default="",  description="Color")
    unidades_vendidas: int = Field(..., ge=0, description="Unidades vendidas históricamente")

class PorcentajeDistribucionItem(BaseModel):
    """Peso de distribución base de cada tienda. La suma debe ser 100."""
    tienda:     str   = Field(..., description="Código de la tienda")
    nombre:     Optional[str] = Field(default="", description="Nombre descriptivo (opcional)")
    porcentaje: float = Field(..., ge=0, le=100)

class ExcepcionItem(BaseModel):
    """
    Regla especial para un (tienda, SKU) específico.
    - ASIGNAR_FIJO: enviar exactamente N unidades a esa tienda.
    - NO_ASIGNAR:   no enviar nada de ese SKU a esa tienda.
    Los campos genero/talla/color son informativos y aparecerán en el output.
    """
    tipo:    Literal["ASIGNAR_FIJO", "NO_ASIGNAR", "MAXIMO"] = Field(default="ASIGNAR_FIJO")
    tienda:  str = Field(..., description="Código de la tienda")
    sku:     str = Field(..., description="SKU al que aplica la excepción")
    genero:  str = Field(default="",  description="Género (informativo)")
    talla:   str = Field(default="",  description="Talla (informativo)")
    color:   str = Field(default="",  description="Color (informativo)")
    unidades: Optional[int] = Field(None, ge=0, description="Unidades (obligatorio si ASIGNAR_FIJO o MAXIMO)")
    motivo:  str = Field(default="Carga por Excel")

# ────────────────────────────────────────────────────────────────────────────────
# REQUEST WRAPPER
# ────────────────────────────────────────────────────────────────────────────────

class RequestDistribucion(BaseModel):
    inventario_origen:      List[InventarioOrigenItem]
    inventario_destino:     List[InventarioDestinoItem]
    ventas_destino:         List[VentasDestinoItem]
    porcentaje_distribucion: List[PorcentajeDistribucionItem]
    excepciones:            List[ExcepcionItem] = []
    factor_cobertura:       float = Field(..., gt=0)

    @model_validator(mode='after')
    def validate_business_rules(self) -> 'RequestDistribucion':
        total_pct = sum(p.porcentaje for p in self.porcentaje_distribucion)
        if not (99.9 <= total_pct <= 100.1):
            raise ValueError(
                f"La suma de porcentajes debe ser 100. Suma actual: {total_pct:.2f}"
            )
        for exc in self.excepciones:
            if exc.tipo in ("ASIGNAR_FIJO", "MAXIMO") and exc.unidades is None:
                raise ValueError(
                    f"Excepción {exc.tipo} para tienda={exc.tienda} / sku={exc.sku} requiere el campo 'unidades'."
                )
        return self

# ────────────────────────────────────────────────────────────────────────────────
# OUTPUT MODELS
# ────────────────────────────────────────────────────────────────────────────────

class AsignacionItem(BaseModel):
    tienda:             str
    sku:                str
    genero:             str = ""
    talla:              str = ""
    color:              str = ""
    unidades_asignadas: int
    tipo_asignacion:    Literal["NORMAL", "FIJO", "REDISTRIBUIDO"]

class ResponseDistribucion(BaseModel):
    asignaciones: List[AsignacionItem]
