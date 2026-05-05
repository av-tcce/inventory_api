import sys
import os

# Ajustar ruta
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from models.schemas import RequestDistribucion
from services.algorithm import distribuir_inventario

test_payload = {
    "inventario_origen": [
        {"sku": "SKU123", "referencia": "REF123", "talla": "M", "genero": "UNISEX", "unidades": 50}
    ],
    "inventario_destino": [
        {"tienda": "MALL_SUR", "sku": "SKU123", "unidades_actuales": 2},
        {"tienda": "MALL_NORTE", "sku": "SKU123", "unidades_actuales": 0},
        {"tienda": "CENTRO", "sku": "SKU123", "unidades_actuales": 1}
    ],
    "ventas_destino": [
        {"tienda": "MALL_SUR", "referencia": "REF123", "talla": "M", "genero": "UNISEX", "unidades_vendidas": 10},
        {"tienda": "MALL_NORTE", "referencia": "REF123", "talla": "M", "genero": "UNISEX", "unidades_vendidas": 15},
        {"tienda": "CENTRO", "referencia": "REF123", "talla": "M", "genero": "UNISEX", "unidades_vendidas": 0}
    ],
    "porcentaje_distribucion": [
        {"tienda": "MALL_SUR", "porcentaje": 30.0},
        {"tienda": "MALL_NORTE", "porcentaje": 50.0},
        {"tienda": "CENTRO", "porcentaje": 20.0}
    ],
    "excepciones": [
        {"tipo": "NO_ASIGNAR", "tienda": "CENTRO", "sku": "SKU123", "motivo": "Local en remodelación"},
        {"tipo": "ASIGNAR_FIJO", "tienda": "MALL_SUR", "sku": "SKU123", "unidades": 5, "motivo": "Pedido especial cliente"}
    ],
    "factor_cobertura": 2.5
}

request = RequestDistribucion(**test_payload)
resultado = distribuir_inventario(request)

print("Resultados de Asignacion:")
for asig in resultado:
    print(asig.model_dump())
    
total_asignado = sum(a.unidades_asignadas for a in resultado)
print(f"Total Asignado: {total_asignado} vs Pendiente 50")
assert total_asignado == 50, "El total asignado debe ser 50"
print("TEST OK")

