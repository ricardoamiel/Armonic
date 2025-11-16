# pages/facturas.py
import streamlit as st
import pandas as pd
import numpy as np
import base64, os, json, re
from io import BytesIO
from lxml import etree
from dotenv import load_dotenv
from openai import OpenAI
import hashlib

# ================== CONFIG ==================
load_dotenv()
API_KEY = os.getenv("API_KEY")
client = OpenAI(api_key=API_KEY) if API_KEY else None
OPENAI_MODEL_VISION = "gpt-4o-mini"  # rápido y suficiente para este módulo

DATA_DIR = os.path.join(os.getcwd(), "data")
RECETAS_PATH = os.path.join(DATA_DIR, "recetas_completas.csv")

st.set_page_config(page_title="Armonic — Gestionar Compra", page_icon="🧾", layout="wide")
st.title("🧾 Gestionar Compra desde la Factura")
st.caption("Sube una factura (PDF/PNG/JPG/XML) y completa la tabla de compra usando IA + recetas.")

# ================== UTILIDADES ==================
def coerce_float(x):
    if x in (None, "", " "):
        return 0.0
    if isinstance(x, (int, float)):
        return float(x)
    s = str(x).replace(",", ".")
    s = re.sub(r"[^\d.\-]", "", s)
    try:
        return float(s)
    except Exception:
        return 0.0

def to_data_url(file_bytes: bytes, mime: str) -> str:
    b64 = base64.b64encode(file_bytes).decode("utf-8")
    return f"data:{mime};base64,{b64}"

def clean_str(s: str) -> str:
    return re.sub(r"\s{2,}", " ", str(s or "").upper()).strip()

@st.cache_data
def cargar_recetas(path: str) -> pd.DataFrame:
    if not os.path.exists(path):
        st.warning(f"No se encontró recetas.csv en {path}. Usando demo.")
        demo = pd.DataFrame({
            "PRODUCTO":["VIKINGA 1"]*4,
            "INSUMO":["PAPA","CHULETA","POLLO","CHORIZO"],
            "UNIDAD":["KG","UNIDAD","KG","KG"],
            "CANTIDAD":[0.2,1.0,0.2,0.2],
            "PRECIO_REFERENCIA":[4,4,4,4],
            "CONVERSION":[0.8,4.0,0.8,0.8],
        })
        return demo
    df_raw = pd.read_csv(path)
    # tu recetas.csv real tiene: codigo_producto,producto_nombre,id_insumo,um_insumo,cantidad,costo_unitario
    # aquí generamos una vista estilo boceto
    df = df_raw.rename(columns={
        "name":"PRODUCTO", # producto_nombre
        "id_insumo":"INSUMO",
        "um_insumo":"UNIDAD",
        "cantidad":"CANTIDAD",
        "costo_unitario":"PRECIO_REFERENCIA"
    }).copy()
    df["CONVERSION"] = 1.0  # placeholder, se puede ajustar más adelante
    return df[["PRODUCTO","INSUMO","UNIDAD","CANTIDAD","PRECIO_REFERENCIA","CONVERSION"]]

# ================== OCR / XML ==================
VISION_SYSTEM = (
    "Eres un experto en OCR de facturas y notas de pedido peruanas. "
    "Recibes una imagen o PDF de factura / boleta / nota de venta / nota de pedido. "
    "Tu objetivo es extraer SOLO el detalle de ítems en formato JSON. "
    "Cada ítem debe tener SIEMPRE estas claves: "
    "proveedor, descripcion, cantidad, pu, desc, importe, um. "
    "Si un campo no existe (por ejemplo desc), usa 0 para números y \"\" para texto."
)

VISION_USER = (
    "Busca la tabla de detalle (cabeceras como CANT., DESCRIPCIÓN, P. UNIT., IMPORTE).\n\n"
    "Reglas específicas para notas de pedido tipo SELECTA:\n"
    "- El proveedor siempre está junto a EIRL, SAC o al lado de NOTA DE PEDIDO, en la parte superior.\n"
    "- La columna CANT. (izquierda) tiene la cantidad de unidades: úsala como `cantidad`.\n"
    "- La columna P. UNIT. suele mostrar algo como '10 UND', '20 UND': ignora 'UND' como unidad de medida.\n"
    "- En la parte derecha (columna IMPORTE) muchas veces aparece un número seguido de 'kg' o 'g', "
    "  por ejemplo '3.20 kg', '5.25 kg'. En ese caso:\n"
    "    * Usa el número (ej. 3.20) como `importe`.\n"
    "    * Usa 'kg' o 'g' de esa columna como `um`.\n"
    "- Sólo si NO encuentras 'kg' o 'g' en la derecha, puedes usar 'und' o 'unidad' como `um`.\n\n"
    "Para cada fila de producto/servicio devuelve un objeto JSON con:\n"
    "{\n"
    "  \"proveedor\": \"nombre del proveedor\",\n"
    "  \"descripcion\": \"texto del ítem\",\n"
    "  \"cantidad\": numero,          // de la columna CANT.\n"
    "  \"pu\": numero,                // precio unitario si existe\n"
    "  \"desc\": numero,              // descuento (0 si no hay)\n"
    "  \"importe\": numero,           // total de la fila o kilos totales si la derecha es '3.20 kg'\n"
    "  \"um\": \"kg|g|und|unidad|lt|...\"  // si ves '3.20 kg' o '5.25 g', usa esa unidad\n"
    "}\n\n"
    "Devuelve SOLO un array JSON (por ejemplo: [ { ... }, { ... } ] ) sin texto adicional."
)



def ocr_items_from_image(file_bytes: bytes, mime: str) -> pd.DataFrame:
    if client is None:
        st.error("No hay API_KEY configurada para usar OCR por IA.")
        return pd.DataFrame(columns=["descripcion","cantidad","pu","desc","importe","um"])

    data_url = to_data_url(file_bytes, mime)
    resp = client.chat.completions.create(
        model=OPENAI_MODEL_VISION,
        messages=[
            {"role": "system", "content": VISION_SYSTEM},
            {"role": "user", "content": [
                {"type": "text", "text": VISION_USER},
                {"type": "image_url", "image_url": {"url": data_url, "detail": "high"}},
            ]},
        ],
        temperature=0
    )
    content = resp.choices[0].message.content or "[]"

    # recortar al JSON
    start = min([i for i in [content.find("["), content.find("{")] if i != -1] or [0])
    raw = content[start:]
    end_br = max(raw.rfind("]"), raw.rfind("}"))
    raw = raw[:end_br + 1] if end_br > 0 else raw

    data = json.loads(raw)
    if isinstance(data, dict):
        data = [data]

    rows = []
    for r in data:
        rows.append({
            "proveedor": clean_str(r.get("proveedor", "")),
            "descripcion": clean_str(r.get("descripcion", "")),
            "cantidad": coerce_float(r.get("cantidad", 0)),
            "pu":       coerce_float(r.get("pu", 0)),
            "desc":     coerce_float(r.get("desc", 0)),
            "importe":  coerce_float(r.get("importe", 0)),
            "um":       str(r.get("um") or "").lower()
        })

    return pd.DataFrame(rows, columns=["proveedor","descripcion","cantidad","pu","desc","importe","um"])


def parse_invoice_xml(xml_bytes: bytes) -> pd.DataFrame:
    parser = etree.XMLParser(recover=True, huge_tree=True)
    root = etree.fromstring(xml_bytes, parser=parser)
    ns = root.nsmap

    def findall(expr):
        try:
            return root.findall(expr, namespaces=ns)
        except Exception:
            return []

    rows = []

    # UBL InvoiceLine
    for line in findall(".//cac:InvoiceLine"):
        desc = (
            line.findtext(".//cbc:Description", namespaces=ns)
            or line.findtext(".//cac:Item/cbc:Description", namespaces=ns)
            or ""
        )

        qty_el = line.find(".//cbc:InvoicedQuantity", namespaces=ns)
        qty = qty_el.text if qty_el is not None else "0"
        um = qty_el.get("unitCode") if qty_el is not None else ""

        price_el = line.find(".//cac:Price/cbc:PriceAmount", namespaces=ns)
        pu = price_el.text if price_el is not None else "0"

        # monto total de la línea si existe
        line_total_el = line.find(".//cbc:LineExtensionAmount", namespaces=ns)
        importe = line_total_el.text if line_total_el is not None else "0"

        # descuento (si está detallado)
        disc_el = line.find(".//cac:AllowanceCharge/cbc:Amount", namespaces=ns)
        desc_monto = disc_el.text if disc_el is not None else "0"

        rows.append({
            "proveedor": "",  # no viene en XML
            "descripcion": clean_str(desc),
            "cantidad": coerce_float(qty),
            "pu":       coerce_float(pu),
            "desc":     coerce_float(desc_monto),
            "importe":  coerce_float(importe),
            "um":       (um or "").lower()
        })

    # fallback simple si no hay filas
    if not rows:
        return pd.DataFrame(columns=["proveedor","descripcion","cantidad","pu","desc","importe","um"])

    return pd.DataFrame(rows, columns=["proveedor","descripcion","cantidad","pu","desc","importe","um"])


# ================== BUILD BASE Q_ESTIMACION POR INSUMO ==================
# ================== RECETAS (solo para referencia visual) ==================
recetas_df = cargar_recetas(RECETAS_PATH)

with st.expander("Ver recetas base (PRODUCTO → INSUMO)", expanded=False):
    st.dataframe(recetas_df, use_container_width=True)

if "factura_hash" not in st.session_state:
    st.session_state["factura_hash"] = None
if "items_factura_df" not in st.session_state:
    st.session_state["items_factura_df"] = pd.DataFrame(
        columns=["proveedor","descripcion","cantidad","pu","desc","importe","um"]
    )

# ================== UI: SUBIR FACTURA ==================
st.subheader("1) Subir factura")
uploaded = st.file_uploader(
    "Factura / boleta (PDF, PNG, JPG o XML)",
    type=["pdf","png","jpg","jpeg","xml"],
    accept_multiple_files=False,
)

items_df = pd.DataFrame(columns=["proveedor","descripcion","cantidad","pu","desc","importe","um"])

items_df["cantidad"] = items_df["cantidad"].astype(float)
items_df["pu"] = items_df["pu"].astype(float)
items_df["importe"] = items_df["cantidad"] * items_df["pu"]

if uploaded is not None:
    ext = uploaded.name.split(".")[-1].lower()
    file_bytes = uploaded.read()

    # hash del archivo para saber si es nuevo
    file_hash = hashlib.sha1(file_bytes).hexdigest()

    # solo reprocesar si cambió el archivo
    if st.session_state["factura_hash"] != file_hash:
        if ext == "xml":
            items_df = parse_invoice_xml(file_bytes)
        else:
            mime = (
                "application/pdf" if ext == "pdf"
                else "image/png" if ext == "png"
                else "image/jpeg"
            )
            items_df = ocr_items_from_image(file_bytes, mime)

        # recalcular importe SIEMPRE aquí
        items_df["cantidad"] = items_df["cantidad"].astype(float)
        items_df["pu"] = items_df["pu"].astype(float)
        items_df["importe"] = items_df["cantidad"] * items_df["pu"]

        # nuevo doc: actualizar hash y detalle
        st.session_state["factura_hash"] = file_hash
        st.session_state["items_factura_df"] = items_df.copy()

        # importante: resetear tabla Gestionar Compra
        if "gc_input_df" in st.session_state:
            del st.session_state["gc_input_df"]
        if "entradas_insumos_df" in st.session_state:
            del st.session_state["entradas_insumos_df"]
    else:
        # misma factura que antes => reutiliza el OCR previo
        items_df = st.session_state["items_factura_df"].copy()
else:
    # no hay archivonuevo => reutiliza el OCR previo
    items_df = st.session_state["items_factura_df"].copy()

# Si no hay nada todavía, no mostramos tabla
if items_df is not None and not items_df.empty:
    st.markdown("#### Detalle detectado en la factura (corrige UM si es necesario)")

    UM_OPTIONS = ["kg", "g", "und", "lt", "ml"]
    items_df["um"] = items_df["um"].str.lower().str.strip()
    items_df.loc[~items_df["um"].isin(UM_OPTIONS), "um"] = "kg"

    items_edited = st.data_editor(
        items_df,
        hide_index=True,
        key="editor_detalle_factura",
        column_config={
            "um": st.column_config.SelectboxColumn(
                "UM",
                options=UM_OPTIONS,
                required=True,
                default="kg",
            )
        },
    )

    # seguir usando items_edited para construir Gestionar Compra
    items_df = items_edited

    # importante: guardar lo editado para futuros reruns
    st.session_state["items_factura_df"] = items_df.copy()
else:
    st.info("Sube una factura/nota para ver el detalle de ítems.")

# ================== TABLA GESTIONAR COMPRA (SOLO ÍTEMS FACTURA) ==================
st.subheader("2) Tabla Gestionar Compra")

if items_df.empty and "gc_input_df" not in st.session_state:
    st.warning("Aún no hay datos de factura. Carga una para comenzar.")
else:
    # 1) Construir input inicial solo 1 vez (o cuando hay factura nueva)
    if "gc_input_df" not in st.session_state and not items_df.empty:
        base_df = items_df.copy()
        base_df["PRODUCTO"] = base_df["descripcion"].str.upper().str.strip()

        # Q_ESTIMACION random solo la PRIMERA vez
        base_df["Q_ESTIMACION"] = base_df["cantidad"].apply(
            lambda x: np.random.randint(max(10, int(x)), max(20, int(x) + 20))
        )

        # Proveedor inicial: del OCR si lo tienes, si no default
        base_df["PROVEEDOR"] = base_df["proveedor"].replace("", "LOS CABALLOS")

        base_df["PRECIO_HISTORICO"] = base_df["pu"]
        base_df["UNIDAD"] = base_df["um"].str.upper()
        base_df["ENTRADAS: CANTIDAD INSUMOS"] = base_df["cantidad"]

        # PRECIO_MERCADO empieza igual que HISTORICO pero luego se puede editar
        base_df["PRECIO_MERCADO"] = base_df["PRECIO_HISTORICO"]
        base_df["AJUSTE_MERMAS"] = 0.05

        gc_input_df = base_df[[
            "PRODUCTO",
            "Q_ESTIMACION",
            "PROVEEDOR",
            "PRECIO_HISTORICO",
            "UNIDAD",
            "ENTRADAS: CANTIDAD INSUMOS",
            "PRECIO_MERCADO",
            "AJUSTE_MERMAS",
        ]].copy()

        st.session_state["gc_input_df"] = gc_input_df

    else:
        # Ya existe → usar lo que el usuario dejó la última vez
        gc_input_df = st.session_state["gc_input_df"].copy()

    # 2) Recalcular columnas derivadas SIEMPRE a partir de las editables
    df_gc = gc_input_df.copy()
    df_gc["MONTO_ESTIMADO"] = df_gc["Q_ESTIMACION"] * df_gc["PRECIO_HISTORICO"]
    df_gc["PRESUPUESTO"] = df_gc["MONTO_ESTIMADO"] * (1 + df_gc["AJUSTE_MERMAS"])
    df_gc["MONTO_REAL"] = df_gc["ENTRADAS: CANTIDAD INSUMOS"] * df_gc["PRECIO_MERCADO"]
    df_gc["DIF"] = df_gc["PRESUPUESTO"] - df_gc["MONTO_REAL"]

    cols_gc = [
        "PRODUCTO",
        "Q_ESTIMACION",
        "PROVEEDOR",
        "PRECIO_HISTORICO",
        "UNIDAD",
        "ENTRADAS: CANTIDAD INSUMOS",
        "MONTO_ESTIMADO",
        "PRECIO_MERCADO",
        "AJUSTE_MERMAS",
        "PRESUPUESTO",
        "MONTO_REAL",
        "DIF",
    ]
    df_gc = df_gc[cols_gc]

    edited_gc = st.data_editor(
        df_gc,
        hide_index=True,
        num_rows="dynamic",
        key="editor_gc_factura",
        disabled=[
            "MONTO_ESTIMADO",
            "PRESUPUESTO",
            "MONTO_REAL",
            "DIF",
        ],  # ✅ estas columnas no se pueden editar
    )

    # 3) Guardar SOLO las columnas editables para el siguiente rerun
    editable_cols = [
        "PRODUCTO",
        "Q_ESTIMACION",
        "PROVEEDOR",
        "PRECIO_HISTORICO",
        "UNIDAD",
        "ENTRADAS: CANTIDAD INSUMOS",
        "PRECIO_MERCADO",
        "AJUSTE_MERMAS",
    ]
    st.session_state["gc_input_df"] = edited_gc[editable_cols].copy()

    # 4) Lo que necesita proveedores.py
    st.session_state["entradas_insumos_df"] = edited_gc[
        ["PRODUCTO", "PROVEEDOR", "Q_ESTIMACION",
         "ENTRADAS: CANTIDAD INSUMOS", "PRESUPUESTO", "MONTO_REAL", "DIF"]
    ].copy()

    total_presupuesto = float(edited_gc["PRESUPUESTO"].sum())
    st.metric("Presupuesto total", f"{total_presupuesto:,.2f}")

    if st.button("➡️ GESTIONAR COMPRA"):
        st.switch_page("pages/proveedores.py")
