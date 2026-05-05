from typing import List, Tuple
from models.schemas import RequestDistribucion, AsignacionItem
import math


class AuditoriaItem:
    def __init__(self, sku, tienda, genero, talla, color, decision,
                 ventas, capacidad_max, stock_actual, unidades_asignadas, razon):
        self.sku               = sku
        self.tienda            = tienda
        self.genero            = genero
        self.talla             = talla
        self.color             = color
        self.decision          = decision
        self.ventas            = ventas
        self.capacidad_max     = capacidad_max
        self.stock_actual      = stock_actual
        self.unidades_asignadas = unidades_asignadas
        self.razon             = razon


def distribuir_inventario(
    request: RequestDistribucion,
) -> Tuple[List[AsignacionItem], List[AuditoriaItem]]:

    asignaciones_finales: List[AsignacionItem] = []
    auditoria: List[AuditoriaItem] = []

    # ── Índices O(1) ─────────────────────────────────────────────────────────
    porcentajes_dict = {p.tienda: p.porcentaje / 100.0 for p in request.porcentaje_distribucion}
    todas_las_tiendas = list(porcentajes_dict.keys())

    inv_actual_dict = {(d.tienda, d.sku): d.unidades_actuales for d in request.inventario_destino}
    ventas_dict     = {(v.tienda, v.sku): v.unidades_vendidas  for v in request.ventas_destino}

    # Atributos descriptivos del origen (por sku)
    attrs_origen: dict = {
        o.sku: {"genero": o.genero, "talla": o.talla, "color": o.color}
        for o in request.inventario_origen
    }

    excepciones_por_sku: dict = {}
    for exc in request.excepciones:
        excepciones_por_sku.setdefault(exc.sku, []).append(exc)

    factor = request.factor_cobertura

    # ── Por cada SKU del inventario origen ───────────────────────────────────
    for origen in request.inventario_origen:
        sku               = origen.sku
        genero            = origen.genero
        talla             = origen.talla
        color             = origen.color
        unidades_pendientes = origen.unidades
        excepciones_sku   = excepciones_por_sku.get(sku, [])
        tiendas_elegibles = set(todas_las_tiendas)
        asignaciones_sku: List[AsignacionItem] = []

        # PASO 2 – Excluir tiendas con NO_ASIGNAR
        for exc in excepciones_sku:
            if exc.tipo == "NO_ASIGNAR" and exc.tienda in tiendas_elegibles:
                tiendas_elegibles.remove(exc.tienda)
                auditoria.append(AuditoriaItem(
                    sku=sku, tienda=exc.tienda,
                    genero=genero, talla=talla, color=color,
                    decision="NO_ASIGNAR",
                    ventas=ventas_dict.get((exc.tienda, sku), 0),
                    capacidad_max=0,
                    stock_actual=inv_actual_dict.get((exc.tienda, sku), 0),
                    unidades_asignadas=0,
                    razon=f"Tienda bloqueada por excepción. Motivo: {exc.motivo}"
                ))

        # PASO 3 – Aplicar ASIGNAR_FIJO
        for exc in excepciones_sku:
            if exc.tipo == "ASIGNAR_FIJO" and exc.tienda in tiendas_elegibles:
                u_asignar = exc.unidades or 0
                u_real    = min(u_asignar, unidades_pendientes)
                ventas    = ventas_dict.get((exc.tienda, sku), 0)
                cap_max   = round(ventas * factor, 2)
                stock_act = inv_actual_dict.get((exc.tienda, sku), 0)

                if u_real > 0:
                    asignaciones_sku.append(AsignacionItem(
                        tienda=exc.tienda, sku=sku,
                        genero=genero, talla=talla, color=color,
                        unidades_asignadas=u_real,
                        tipo_asignacion="FIJO"
                    ))
                    unidades_pendientes -= u_real

                auditoria.append(AuditoriaItem(
                    sku=sku, tienda=exc.tienda,
                    genero=genero, talla=talla, color=color,
                    decision="ASIGNAR_FIJO",
                    ventas=ventas, capacidad_max=cap_max,
                    stock_actual=stock_act, unidades_asignadas=u_real,
                    razon=(
                        f"Asignación fija por excepción. Motivo: {exc.motivo}. "
                        f"Solicitadas: {u_asignar}, asignadas: {u_real}."
                    )
                ))
                tiendas_elegibles.remove(exc.tienda)

        if unidades_pendientes <= 0:
            asignaciones_finales.extend(asignaciones_sku)
            continue

        # PASO 4 – Calcular capacidad por tienda (Respetando excepciones de MAXIMO)
        maximos_sku = {exc.tienda: exc.unidades for exc in excepciones_sku if exc.tipo == "MAXIMO"}
        capacidades: dict = {}
        for t in tiendas_elegibles:
            ventas    = ventas_dict.get((t, sku), 0)
            stock_act = inv_actual_dict.get((t, sku), 0)
            
            # Capacidad base teórica
            cap_teorica = 0 if ventas == 0 else max(0.0, (ventas * factor) - stock_act)
            
            if t in maximos_sku:
                u_limit = maximos_sku[t] or 0
                cap_disponible_max = max(0.0, float(u_limit) - stock_act)
                # La capacidad real es el mínimo entre lo que el algoritmo quiere enviar y el límite físico
                capacidades[t] = min(cap_teorica, cap_disponible_max)
            else:
                capacidades[t] = cap_teorica

        tiendas_con_capacidad = [t for t in tiendas_elegibles if capacidades[t] > 0]
        if not tiendas_con_capacidad:
            tiendas_con_capacidad = list(tiendas_elegibles)
            for t in tiendas_con_capacidad:
                capacidades[t] = float('inf')

        if not tiendas_con_capacidad:
            asignaciones_finales.extend(asignaciones_sku)
            continue

        # PASO 5 – Pesos re-normalizados
        p_total = sum(porcentajes_dict.get(t, 0) for t in tiendas_con_capacidad)
        peso_dict = {
            t: (porcentajes_dict.get(t, 0) / p_total if p_total > 0 else 1.0 / len(tiendas_con_capacidad))
            for t in tiendas_con_capacidad
        }

        # PASO 6 – Distribuir y limitar a capacidad
        asigs_tmp = {t: 0.0 for t in tiendas_con_capacidad}
        undist = unidades_pendientes
        for t in tiendas_con_capacidad:
            real = min(unidades_pendientes * peso_dict[t], capacidades[t])
            asigs_tmp[t] = real
            undist -= real

        # PASO 7 – Redistribuir excedentes
        iters = 0
        while round(undist, 5) > 0 and iters < 100:
            iters += 1
            resto = [t for t in tiendas_con_capacidad if capacidades[t] > asigs_tmp[t]]
            if not resto:
                for t in tiendas_con_capacidad:
                    capacidades[t] = float('inf')
                resto = tiendas_con_capacidad
            p_r = sum(peso_dict[t] for t in resto)
            for t in resto:
                w   = peso_dict[t] / p_r if p_r > 0 else 1.0 / len(resto)
                ag  = min(undist * w, capacidades[t] - asigs_tmp[t])
                asigs_tmp[t] += ag
                undist       -= ag
            if round(undist, 5) <= 0:
                break

        # PASO 8 – Largest Remainder Method
        entero: dict = {}
        resto_d: dict = {}
        sum_e = 0
        for t, v in asigs_tmp.items():
            e = math.floor(v)
            entero[t]  = e
            resto_d[t] = v - e
            sum_e += e
        faltantes = unidades_pendientes - sum_e
        for i, t in enumerate(sorted(resto_d, key=resto_d.get, reverse=True)):
            if i >= int(faltantes):
                break
            entero[t] += 1

        # PASO 9 – Generar asignaciones + auditoría
        for t, cantidad in entero.items():
            ventas    = ventas_dict.get((t, sku), 0)
            stock_act = inv_actual_dict.get((t, sku), 0)
            cap_max   = round(ventas * factor, 2)
            pct       = round(peso_dict[t] * 100, 2)
            teorico_puro = unidades_pendientes * porcentajes_dict.get(t, 0)
            redistribuido = capacidades[t] == float('inf') and cantidad > teorico_puro
            tipo = "REDISTRIBUIDO" if redistribuido else "NORMAL"

            if cantidad > 0:
                asignaciones_sku.append(AsignacionItem(
                    tienda=t, sku=sku,
                    genero=genero, talla=talla, color=color,
                    unidades_asignadas=cantidad,
                    tipo_asignacion=tipo
                ))

            if ventas == 0:
                razon = (
                    f"Sin ventas históricas → distribución proporcional forzada. "
                    f"Peso: {pct}%."
                )
            elif capacidades[t] == float('inf'):
                razon = (
                    f"Capacidad libre (otras tiendas sin espacio). "
                    f"Peso: {pct}% → {cantidad} uds."
                )
            else:
                cap_disp = round(cap_max - stock_act, 2)
                reason_parts = [
                    f"Ventas históricas: {ventas} uds · Factor: {factor} → Cap. máx: {cap_max}",
                    f"Stock actual: {stock_act} · Cap. disponible: {cap_disp}",
                ]
                
                if t in maximos_sku:
                    u_limit = maximos_sku[t]
                    reason_parts.append(f"Límite MAXIMO: {u_limit} uds totales.")
                
                razon = " · ".join(reason_parts) + f" · Peso: {pct}% → {cantidad} uds asignadas."

            auditoria.append(AuditoriaItem(
                sku=sku, tienda=t,
                genero=genero, talla=talla, color=color,
                decision=tipo,
                ventas=ventas, capacidad_max=cap_max,
                stock_actual=stock_act, unidades_asignadas=cantidad,
                razon=razon
            ))

        asignaciones_finales.extend(asignaciones_sku)

    return asignaciones_finales, auditoria
