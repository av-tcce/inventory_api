import io
import pandas as pd
from services.tallaje_matriculado_service import _cargar_dataset

ORDEN_TALLAS = [
    '0-3', '3-6', '6-9', '9-12', '12-18', '18-24',
    '2T', '3T', '4T', '5T', '6T',
    '4', '6', '8', '10', '12', '14',
    '28', '30', '32', '34', '36',
    'XS', 'S', 'M', 'L', 'XL'
]

# Tiers de tienda ("TOP PDV") que usa unit_request_service.py para elegir la cantidad base
# por tienda. Confirmados contra Maestra_Almacenes (canales de Solicitud de Unidades): A, AA, B, C.
TIERS_TOP_VENTA = ['AA', 'A', 'B', 'C']

DETALLE_COLUMNS = [
    'CDCDGO', 'DSDSCRPCION', 'CDTLLA', 'CDCLOR', 'GENERO', 'PERSONAJE',
    'SILUETA', 'TIPOPRENDA', 'ESTRATEGIA', 'MUEBLE'
] + TIERS_TOP_VENTA

REQUIRED_SOURCE_COLUMNS = ['REFERENCIA', 'GENERO', 'LICENCIA', 'TIPO PRENDA', 'SILUETA', 'ESTRATEGIA']


def _ordenar_tallas(tallas: list[str]) -> list[str]:
    en_orden = [t for t in ORDEN_TALLAS if t in tallas]
    extra = sorted(t for t in tallas if t not in ORDEN_TALLAS)
    return en_orden + extra


def _mapa_tallas_por_genero_tipo() -> dict[tuple[str, str], list[str]]:
    """
    {(GENERO, TIPO_DE_PRENDA) en mayúsculas: [tallas ordenadas]} según lo matriculado
    (MINIMO > 0) en la fecha más reciente de tblAgotados, sin filtrar por formato/canal
    (reutiliza el mismo dataset cacheado que usa el módulo de Tallaje Matriculado).
    """
    _, dataset = _cargar_dataset(None)
    if dataset.empty:
        return {}

    mapa: dict[tuple[str, str], list[str]] = {}
    for (genero, tipo), grupo in dataset.groupby(['GENERO', 'TIPO_DE_PRENDA']):
        clave = (str(genero).strip().upper(), str(tipo).strip().upper())
        mapa[clave] = _ordenar_tallas(sorted(set(grupo['TALLA'].tolist())))
    return mapa


def generar_estructura_solicitud(source_content: bytes) -> io.BytesIO:
    """
    A partir de un Excel de referencias nuevas (columnas REFERENCIA, GENERO, LICENCIA,
    'TIPO PRENDA', SILUETA, ESTRATEGIA, ...), genera un archivo con la estructura de la
    hoja DETALLE que espera el módulo de Solicitud de Unidades: una fila por cada talla
    matriculada para esa combinación Género + Tipo de Prenda.

    Las columnas de cantidad por tienda (AA/A/B/C) y MUEBLE quedan en blanco: este módulo
    solo arma el esqueleto; las cantidades se completan manualmente antes de subir el
    archivo resultante al módulo de Solicitud de Unidades.
    """
    df_source = pd.read_excel(io.BytesIO(source_content), sheet_name=0, header=0, dtype={'REFERENCIA': str})
    df_source.columns = [str(c).strip() for c in df_source.columns]

    faltantes_cols = [c for c in REQUIRED_SOURCE_COLUMNS if c not in df_source.columns]
    if faltantes_cols:
        raise ValueError(f"Al archivo le faltan columnas requeridas: {faltantes_cols}")

    tallas_por_combo = _mapa_tallas_por_genero_tipo()

    filas = []
    sin_tallaje = []

    for _, fuente in df_source.iterrows():
        referencia = str(fuente.get('REFERENCIA', '') or '').strip()
        if not referencia or referencia.lower() == 'nan':
            continue

        genero = str(fuente.get('GENERO', '') or '').strip()
        tipo_prenda = str(fuente.get('TIPO PRENDA', '') or '').strip()
        licencia = str(fuente.get('LICENCIA', '') or '').strip()
        silueta = str(fuente.get('SILUETA', '') or '').strip()
        estrategia = str(fuente.get('ESTRATEGIA', '') or '').strip()

        tallas = tallas_por_combo.get((genero.upper(), tipo_prenda.upper()), [])

        if not tallas:
            fila_sin = fuente.to_dict()
            fila_sin['MOTIVO'] = "No se encontró tallaje matriculado para esta combinación de Género + Tipo de Prenda"
            sin_tallaje.append(fila_sin)
            continue

        descripcion = f"{licencia} {tipo_prenda}".strip()

        for talla in tallas:
            fila = {
                'CDCDGO': referencia,
                'DSDSCRPCION': descripcion,
                'CDTLLA': talla,
                'CDCLOR': 'UNICO',
                'GENERO': genero,
                'PERSONAJE': licencia,
                'SILUETA': silueta,
                'TIPOPRENDA': tipo_prenda,
                'ESTRATEGIA': estrategia,
                'MUEBLE': ''
            }
            for tier in TIERS_TOP_VENTA:
                fila[tier] = None
            filas.append(fila)

    if not filas:
        raise ValueError(
            "No se generó ninguna fila: revise que las referencias tengan REFERENCIA, GENERO y "
            "TIPO PRENDA diligenciados, y que exista tallaje matriculado para esas combinaciones "
            "(revise la hoja Sin_Tallaje si el archivo sí trae datos)."
        )

    df_detalle = pd.DataFrame(filas, columns=DETALLE_COLUMNS)
    df_sin_tallaje = pd.DataFrame(sin_tallaje)

    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        df_detalle.to_excel(writer, sheet_name='DETALLE', index=False)
        if not df_sin_tallaje.empty:
            df_sin_tallaje.to_excel(writer, sheet_name='Sin_Tallaje', index=False)
    output.seek(0)
    return output
