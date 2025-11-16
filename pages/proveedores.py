# pages/proveedores.py
import streamlit as st
import pandas as pd
import numpy as np
import os, json, re
from datetime import datetime
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()
API_KEY = os.getenv("API_KEY")
client = OpenAI(api_key=API_KEY) if API_KEY else None

st.set_page_config(page_title="Armonic — Entradas de Mercadería", page_icon="📦", layout="wide")
st.title("📦 Entradas de Mercadería")
st.caption("Compara el presupuesto vs las entradas reales de insumos por proveedor y selecciona qué incluir en el presupuesto final.")

# -------- utils --------
def _coerce_float(x):
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

def _save_downloads(df: pd.DataFrame, name: str):
    csv = df.to_csv(index=False).encode("utf-8")
    json_bytes = json.dumps(df.to_dict(orient="records"), ensure_ascii=False, indent=2).encode("utf-8")
    st.download_button("⬇️ CSV", data=csv, file_name=f"{name}.csv", mime="text/csv")
    st.download_button("⬇️ JSON", data=json_bytes, file_name=f"{name}.json", mime="application/json")

def llm_insight_from_table(df: pd.DataFrame, proveedor: str) -> str:
    if client is None or df.empty:
        return "Configura tu API_KEY o carga datos para ver insights."
    today = datetime.now().strftime("%d/%m/%Y")
    sample = df.to_dict(orient="records")
    prompt = (
        f"Fecha actual: {today}. Eres analista logístico de una pyme restaurante en Perú. "
        f"Proveedor filtrado: {proveedor}. "
        f"Con base en esta tabla JSON (producto, estimación, entradas de insumos, presupuesto, monto real y dif), "
        f"nota que las entradas de insumos son UNIDADES, no son kg, ni g, ni litros. "
        f"Da 2–3 insights muy concisos (<35 palabras cada uno) sobre: "
        f"sobrecostos, riesgo de faltantes y recomendación de ajustar compras o cambiar proveedor.\n\n"
        f"TABLA:\n{json.dumps(sample, ensure_ascii=False)}"
    )
    resp = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": "Eres un analista logístico muy conciso y práctico."},
            {"role": "user", "content": prompt},
        ],
        temperature=0.25,
        max_tokens=180,
    )
    return resp.choices[0].message.content.strip()

# -------- cargar data desde facturas.py --------
if "entradas_insumos_df" in st.session_state:
    df = st.session_state["entradas_insumos_df"].copy()
else:
    st.info("Aún no se cargaron facturas en la página de Facturación. Usando demo de entradas.")
    df = pd.DataFrame({
        "PRODUCTO": ["PAPA", "CHULETA", "POLLO", "CHORIZO"],
        "PROVEEDOR": ["LOS CABALLOS"] * 4,
        "Q_ESTIMACION": [40, 15, 20, 10],
        "ENTRADAS: CANTIDAD INSUMOS": [90, 100, 90, 90],
        "PRESUPUESTO": [210, 63, 105, 63],
        "MONTO_REAL": [0, 0, 0, 0],
        "DIF": [210, 63, 105, 63],
    })

# si no vino PROVEEDOR desde facturas.py, ponemos uno por defecto
if "PROVEEDOR" not in df.columns:
    df["PROVEEDOR"] = "LOS CABALLOS"

# asegurar columnas numéricas
for col in ["Q_ESTIMACION", "ENTRADAS: CANTIDAD INSUMOS", "PRESUPUESTO", "MONTO_REAL", "DIF"]:
    if col not in df.columns:
        df[col] = 0.0
    df[col] = df[col].apply(_coerce_float)

# columna para check de inclusión en presupuesto
if "INCLUIR" not in df.columns:
    df["INCLUIR"] = True

# -------- filtro por proveedor --------
proveedores = df["PROVEEDOR"].fillna("SIN PROVEEDOR").unique().tolist()
col_filtro, _ = st.columns([1, 3])
with col_filtro:
    proveedor_sel = st.selectbox("Filtro: Proveedor", options=["Todos"] + proveedores)

if proveedor_sel != "Todos":
    df_filtrado = df[df["PROVEEDOR"] == proveedor_sel].copy()
else:
    df_filtrado = df.copy()

# -------- tabla editable --------
st.subheader("Entradas de Mercadería (por proveedor filtrado)")

cols_order = [
    "INCLUIR",                      # checkbox
    "PRODUCTO",
    "PROVEEDOR",
    "Q_ESTIMACION",
    "ENTRADAS: CANTIDAD INSUMOS",
    "PRESUPUESTO",
    "MONTO_REAL",
    "DIF",
]
df_filtrado = df_filtrado[cols_order]

edited = st.data_editor(
    df_filtrado,
    hide_index=True,
    key="editor_entradas_proveedor",
    num_rows="dynamic",
    column_config={
        "INCLUIR": st.column_config.CheckboxColumn(
            "✔ Incluir",
            help="Marca qué insumos quieres considerar en el presupuesto final."
        )
    },
)

# actualizar estado global con lo editado (para no perder cambios)
df_update = df.copy()
# hacemos merge por PRODUCTO+PROVEEDOR para actualizar INCLUIR, MONTO_REAL, DIF, etc.
df_update = df_update.drop(columns=["INCLUIR"], errors="ignore")
edited_no_idx = edited.drop(columns=[], errors="ignore")
df_merged = df_update.merge(
    edited_no_idx,
    on=["PRODUCTO", "PROVEEDOR", "Q_ESTIMACION",
        "ENTRADAS: CANTIDAD INSUMOS", "PRESUPUESTO", "MONTO_REAL", "DIF"],
    how="right",
)
# en la práctica, con pocos datos, esto funciona; si quieres algo más robusto, se puede ajustar luego
st.session_state["entradas_insumos_df"] = edited.copy()

# considerar sólo filas con INCLUIR = True para métricas / insights / descargas
if "INCLUIR" in edited.columns:
    filtered = edited[edited["INCLUIR"] == True].copy()
else:
    filtered = edited.copy()

if filtered.empty:
    st.warning("No hay insumos seleccionados (INCLUIR) para el cálculo del presupuesto.")
else:
    total_faltante = float(np.nansum(filtered["DIF"]))
    valorizado_entrante = float(np.nansum(filtered["MONTO_REAL"]))
    valorizado_restante = float(np.nansum(np.maximum(filtered["DIF"], 0)))

    c1, c2, c3 = st.columns(3)
    c1.metric("TOTAL FALTANTE", f"{total_faltante:,.2f}")
    c2.metric("VALORIZADO_ENTRANTE", f"{valorizado_entrante:,.2f}")
    c3.metric("VALORIZADO_RESTANTE", f"{valorizado_restante:,.2f}")

# -------- insights --------
st.markdown("---")
st.subheader("💡 Insights logísticos")

insight = llm_insight_from_table(filtered if not filtered.empty else edited, proveedor_sel)
st.write(insight)

# -------- descargas --------
st.markdown("---")
st.subheader("Generar presupuesto")

if "show_downloads" not in st.session_state:
    st.session_state["show_downloads"] = False

if st.button("💰 Generar presupuesto"):
    st.session_state["show_downloads"] = True

if st.session_state["show_downloads"]:
    if filtered.empty:
        st.info("No hay filas seleccionadas con INCLUIR = True. Marca al menos un insumo para descargar.")
        _save_downloads(edited, "entradas_mercaderia_filtradas")  # fallback
    else:
        _save_downloads(filtered, "presupuesto_proveedor")
