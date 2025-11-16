# tabs/tendencias.py
import streamlit as st
import pandas as pd
import numpy as np
import altair as alt
import gc
from io import StringIO
from dotenv import load_dotenv
from openai import OpenAI
import os, json
from datetime import datetime
import streamlit.components.v1 as components

load_dotenv()
API_KEY = os.getenv("API_KEY")
client = OpenAI(api_key=API_KEY)

# st.session_state

# st.session_state["forecast_time_selector"]
# st.session_state["forecast_time"]
# st.session_state["load_data"]
# st.session_state["data"]
# st.session_state["insights"]

def set_params_demanda():
    if "forecast_time_selector" not in st.session_state:
        st.session_state["forecast_time_selector"] = "14 días"
    
    if "load_data" not in st.session_state:
        st.session_state["load_data"] = False
    if "historical_data" not in st.session_state:
        st.session_state["historical_data"] = pd.DataFrame({
            "date":[],
            "name":[],
            "id_order":[],
            "id":[],
            "cantidad":[],
            "day":[]
        })

    if "upload_historical_data" not in st.session_state:
        st.session_state["upload_historical_data"] = False
    # date, name, id_order, id, cantidad, day, historical_data
    if "historico_ordenes" not in st.session_state:
        st.session_state["historico_ordenes"] = pd.DataFrame({
            "fecha": [],
            "ordenes diarias": []
        })
    if "graph_orders" not in st.session_state:
        st.session_state["graph_orders"] = pd.DataFrame({
            "fecha":[],
            "ordenes diarias":[]
        })
    if "insights" not in st.session_state:
        st.session_state["insights"] = {
            14:[],
            30:[],
            90:[]
        }
    if "gestion_productos" not in st.session_state:
        # 'id', 'name', 'p', 'q', 'E', 'scaled', 'floor', 'frac', 'alloc'
        st.session_state["gestion_productos"] = pd.DataFrame({
            "id": [],
            "Nombre": [],
            "Estimacion": [],
            "Ajuste de negocio(%)": [],
            "Total": []
        })

    if "forecast" not in st.session_state:
        info_forecast = {}
        with open("data/predict14.json", "r") as f:
            info_forecast[14] = json.load(f)
        with open("data/predict30.json", "r") as f:
            info_forecast[30] = json.load(f)
        with open("data/predict90.json", "r") as f:
            info_forecast[90] = json.load(f)
        st.session_state["forecast"] = info_forecast
    
    if "metadata" not in st.session_state:
        with open("data/metadata.json", "r") as f:
            metadata = json.load(f)
        # {"avg_items_per_order": 2.746347168526636, "historical_daily_orders": 102.93197091835034, "total_orders": 22038}
        st.session_state["metadata"] = metadata
        

#==========================================================================================
PATH_DIR_DATA = os.path.join("data")

@st.cache_data
def cargar_series_de_tiempo():
    set_params_demanda()
    return st.session_state["historical_data"]

@st.cache_data
def cargar_receta():
    # path = os.path.join("data","producto_con_receta.csv")
    # df = pd.read_csv(path, low_memory=False)
    # st.session_state["productos"] = df
    # return st.session_state["productos"]
    return None 

@st.cache_data
def cargar_insights():
    return st.session_state["insights"] 

        
#=======================================================================================================

def allocate_to_target(df_products, forecast_orders, avg_items_per_order, buffer_quantile=0.0):
    df = df_products.copy()
    # 1) target total units
    T = int(round(forecast_orders * avg_items_per_order * (1.0 + buffer_quantile)))
    if T <= 0:
        df['alloc'] = 0
        return df

    # 2) If all E are zero, fallback to proportional by historical counts or equal split
    if df['E'].sum() == 0:
        # fallback: proportional to historical counts field if present, else equal
        if 'historical_count' in df.columns and df['historical_count'].sum() > 0:
            df['E'] = df['historical_count'] / df['historical_count'].sum() * T
        else:
            df['E'] = 1.0 / len(df) * T

    # 3) Scale expectations so they sum to T
    sumE = df['E'].sum()
    df['scaled'] = df['E'] / sumE * T

    # 4) Largest Remainder (Hamilton) rounding to integers summing to T
    df['floor'] = np.floor(df['scaled']).astype(int)
    remainder = T - df['floor'].sum()
    # fractional parts sorted desc
    df['frac'] = df['scaled'] - df['floor']
    df = df.sort_values('frac', ascending=False).reset_index(drop=True)
    df['alloc'] = df['floor'].copy()
    if remainder > 0:
        df.loc[0:remainder-1, 'alloc'] += 1

    # 6) Final sanitizing: ensure non-negative int and sum equals (approx) T
    df['alloc'] = df['alloc'].clip(lower=0).astype(int)
    final_sum = df['alloc'].sum()
    # final adjustment: if sum differs, distribute the difference by frac desc/asc
    diff = T - final_sum
    if diff > 0:
        # add 1 to top-diff items by frac (or any priority)
        idxs = df.sort_values('frac', ascending=False).index[:diff]
        df.loc[idxs, 'alloc'] += 1
    elif diff < 0:
        diff = -diff
        idxs = df.sort_values('frac', ascending=True).index[:diff]
        df.loc[idxs, 'alloc'] = (df.loc[idxs, 'alloc'] - 1).clip(lower=0)

    # restore original order
    return df.sort_index()

def actualizar_gestion_productos(df):

    proportions_list = []
    total_dias = len(df["day"].unique())
    # total_dias 
    for idx, group in df.groupby(by=["name"]):
        (name_id, ) = idx
        apariciones_diarias = len(group["day"].unique())
        cantidad_tota_de_apariciones = group["cantidad"].sum()
        id_product = group["id"].iloc[0]
        proportions_list.append({"id":id_product, "name":name_id,"p": apariciones_diarias/total_dias, "q":cantidad_tota_de_apariciones/apariciones_diarias})

    proporciones = pd.DataFrame(proportions_list)
    
    time_dict = {"14 días":14, "1 mes":30, "3 meses":90}
    forecast_data = st.session_state["forecast"]
    window = st.session_state["forecast_time_selector"]
    predict = forecast_data[time_dict[window]]
    orders_day = pd.Series(predict["prediccion"])
    
    metadata = st.session_state["metadata"]
    historical_daily_orders = metadata["historical_daily_orders"]
    # total_orders = metadata["total_orders"]
    avg_items_per_order = metadata["avg_items_per_order"]


    scale_factor = orders_day/historical_daily_orders
    total_scale = scale_factor.sum()
    tmp = proporciones.copy()
    tmp["E"] = tmp["p"] * tmp["q"] * total_scale

    total_forecast_orders = np.sum(predict["prediccion"])
    
    products_allocaton = allocate_to_target(tmp, total_forecast_orders, avg_items_per_order)
    # products_allocaton.columns
    main_cols = ["id", "name", "alloc"]
    tmp = products_allocaton[main_cols]
    tmp = tmp.rename(columns={   
        "name": "Nombre",
        "alloc": "Estimacion"
    })
    tmp.loc[:,"Ajuste de negocio(%)"] = 0
    tmp.loc[:,"Total"] = tmp.loc[:, "Estimacion"]*(1+tmp.loc[:,"Ajuste de negocio(%)"])
    
    st.session_state["gestion_productos"] = tmp

def actualizar_prediccion():    
    time_dict = {"14 días":14, "1 mes":30, "3 meses":90}
    forecast_data = st.session_state["forecast"]
    window = st.session_state["forecast_time_selector"]
    predict = forecast_data[time_dict[window]]

    forecast = pd.DataFrame(predict)
    forecast = forecast.rename(columns={"fechas":"fecha"})
    forecast["fecha"] = pd.to_datetime(forecast["fecha"])

    st.session_state["forecast_data"] = forecast
    
def actualizar_historico_ordenes(df):
    tmp = df.copy()
    tmp.loc[:,"fecha_diaria"] = tmp["date"].dt.floor("D")
    tmp = tmp.groupby(by=["fecha_diaria"]).agg({"cantidad":"sum"}).reset_index()
    tmp = tmp.rename(columns={"fecha_diaria":"fecha", "cantidad":"ordenes diarias"})
    st.session_state["historico_ordenes"] = tmp
    
def cargar_historico_ventas(df):
    # df = pd.read_csv(path_data, low_memory=False)
    df = df.rename(columns={
        "fecha":"date",
        "item_nombre":"name",
        "codunicopedido":"id_order",
        "codigo_producto":"id"
    })
    # fecha,item_nombre,codunicopedido,codigo_producto,cantidad,day
    # date, name, id_order, id, cantidad, day, historical_data
    # df["name"].value_counts()
    df["date"] = pd.to_datetime(df["date"])
    df["day"] = df["date"].dt.floor("D")
    st.session_state["historical_data"] = df
    window = st.session_state["forecast_time_selector"]
    if window != None:
        actualizar_historico_ordenes(df)
        actualizar_gestion_productos(df)
        actualizar_prediccion()


def update_graph_data():
    # graph_orders = st.session_state.get("graph_orders").copy()
    window = st.session_state["forecast_time_selector"] 
    tmp = st.session_state.get("historico_ordenes").sort_values(by=["fecha"]).copy()
    tmp["fecha"] = pd.to_datetime(tmp["fecha"])
    time_dict = {"14 días":14, "1 mes":30, "3 meses":90}
    window = time_dict[window]
    if window == 14:
       tmp = tmp.iloc[-(window+30):] 
    elif window == 30:
       tmp = tmp.iloc[-(window+60):] 
    else:
       tmp = tmp.iloc[-(window+90):] 
    print(tmp.head())
    st.session_state["graph_orders"] = tmp

#=======================================================================

def reload_all():    
    set_params_demanda()

def update_forecast():
    flag_historical_data = st.session_state["upload_historical_data"]
    # elif not flag_historical_data:
    #     st.info("Cargue los datos de su historial de ventas.")
    # elif st.session_state.get("forecast_data") is None:
        # st.info(".")
    window = st.session_state["forecast_time_selector"]
    if flag_historical_data and window != None: 
        df = st.session_state.get("historical_data")
        
        actualizar_gestion_productos(df)
        actualizar_prediccion()
        update_graph_data()

#===================================================================================
set_params_demanda()
st.markdown("""
<style>
/* Hide the entire file uploader container */
div[data-testid="stFileUploader"] {
    position: absolute !important;
    top: -10000px !important;
    left: -10000px !important;
    height: 1px !important;
    width: 1px !important;
    opacity: 0 !important;
    pointer-events: none !important;
    float: right !important;
}
</style>

<style>
/* Apunta a la clase que envuelve el contenido de st.metric */
div[data-testid="stMetric"] {
    /* Quita el borde y el sombreado que simula el borde */
    border: none !important; 
    box-shadow: none !important;
    align-items: center !important;
}

/* Opcional: Si quieres quitar el color de fondo */
div[data-testid="stMetric"] > div {
    background-color: transparent !important;
}
</style>
""", unsafe_allow_html=True)
# st.markdown(custom_css, unsafe_allow_html=True)
# gestion_productos = st.session_state.get("gestion_productos")
print("TIME WINDOW: ", st.session_state["forecast_time_selector"])

flag_historical_data = st.session_state["upload_historical_data"]
if not flag_historical_data:
    st.info("Cargue los datos de su historial de ventas.")
window = st.session_state.get("forecast_time_selector")
if window is None:
    st.info("Elija una ventana de tiempo para el pronóstico.")

# st.button(label="reload", on_click=reload_all)
cols = st.columns([0.6, 0.4], border=False, vertical_alignment="top")

with cols[0]:
    if not flag_historical_data or window == None:
        st.header(f"Gestión de inventarios al siguiente nivel 😎")
    else:
        st.header(f"Demanda de los próximos {window}")

with cols[1]:
    # uploaded_file = st.file_uploader(label=":floppy_disk: Sube aquí tu Archivo", type="csv", accept_multiple_files=False, width="stretch")
    # uploaded_file = st.file_uploader("", key="hidden_uploader", type="csv", accept_multiple_files=False)
    uploaded_file = st.file_uploader("Ok", key="hidden_uploader", type="csv", accept_multiple_files=False)
    button_html = """
    <style>
    /* Custom button style */
    .upload-wrapper {
        display: flex;
        justify-content: flex-end;   /* ← Align to the right */
    }

    .my-upload-btn {
        padding: 10px 18px;
        border-radius: 8px;
        background: #f5f1f0;
        color: #0d0e09;
        font-weight: 700;
        font-family: sans-serif;
        cursor: pointer;
        box-shadow: 0 3px 8px rgba(0,0,0,0.12);
        border: none;
    }
    .my-upload-btn:hover {
        background: #e68900;
    }
    </style>
    <div class="upload-wrapper">
        <button class="my-upload-btn" id="myUploadBtn">📁 Seleccionar archivo</button>
    </div>

    <script>
    const btn = document.getElementById('myUploadBtn');
    // Use window.parent to access the Streamlit DOM containing the real <input>
    btn.addEventListener('click', () => {
    try {
        const fileInput = window.parent.document.querySelector('[data-testid="stFileUploadDropzone"] input[type=file]');
        if (fileInput) {
        fileInput.click();
        } else {
        // Fallback: attempt to find any input[type=file]
        const anyFile = window.parent.document.querySelector('input[type=file]');
        if (anyFile) anyFile.click();
        else alert('No file input found in parent document.');
        }
    } catch (err) {
        // If cross-origin or other issue, show a message (rare in normal Streamlit)
        console.error(err);
        alert('Could not trigger file selector. Refresh and try again.');
    }
    });
    </script>
    """

    # Render the button (height small so it looks like part of the page)
    components.html(button_html, height=70)

    if uploaded_file is not None:
        dataframe = pd.read_csv(uploaded_file)
        st.session_state["historico_ventas"] = dataframe.copy()
        st.session_state["upload_historical_data"] = True
        flag_historical_data = True
        cargar_historico_ventas(dataframe)
        # st.write(dataframe)

# st.header(f"📈 Demanda de los próximos {st.session_state.get('forecast_time')}")

cols = st.columns([1.8, 2, 1.5], border=True, vertical_alignment="top")

with cols[0]:
    st.metric(label="Ganancia total", value=850000, delta="35%")

with cols[1]:
    st.metric(label="Monto Ahorrado", value=150000, delta="50%")

with cols[2]:
    st.segmented_control(
        label="Ventana de predicción",
        options=["14 días", "1 mes", "3 meses"],
        selection_mode="single",
        default=st.session_state.get("forecast_time"),
        key="forecast_time_selector",
        on_change=update_forecast
    )


if "forecast_data" in st.session_state and st.session_state["forecast_data"] is not None and window != None:
    print("vuelve a renderizare")
    graph_orders = st.session_state["graph_orders"].copy()
    forecast = st.session_state["forecast_data"].copy()

    # Rename forecast columns
    forecast = forecast.rename(columns={
        "fechas": "fecha",
        "prediccion": "estimación ajustada"
    })
    
    graph_orders["fecha"] = pd.to_datetime(graph_orders["fecha"])
    forecast["fecha"] = pd.to_datetime(forecast["fecha"])
    
    df_combined = pd.merge(
        graph_orders,
        forecast,
        on="fecha",
        how="outer"
    )
    value_vars = []
    if "ordenes diarias" in df_combined.columns:
        value_vars.append("ordenes diarias")
    if "estimación ajustada" in df_combined.columns:
        value_vars.append("estimación ajustada")

    df_long = df_combined.melt(
        id_vars=["fecha"],
        value_vars=value_vars,
        var_name="variable",
        value_name="valor"
    ).sort_values("fecha")

    df_long = df_long.dropna(subset=["valor"])
    chart = (
    alt.Chart(df_long)
    .mark_line(strokeWidth=3)
    .encode(
        x=alt.X("fecha:T", title="Fecha"),
        y=alt.Y("valor:Q", title="Valor"),
        color=alt.Color(
            "variable:N",
            scale=alt.Scale(
                domain=["ordenes diarias", "estimación ajustada"],
                range=["#6e6e6e", "#0072B2"]
            ),
            legend=alt.Legend(title="Serie")
        ),
        tooltip=["fecha:T", "variable:N", "valor:Q"]
    )
)

else:
    # Only historico_ordenes available
    graph_orders = st.session_state.get("graph_orders").copy()
    df_long = graph_orders.melt(
        id_vars=["fecha"],
        value_vars=["ordenes diarias"],
        var_name="variable",
        value_name="valor"
    )

    chart = (
        alt.Chart(df_long)
        .mark_line(strokeWidth=3, color="#6e6e6e")
        .encode(
            x="fecha:T",
            y="valor:Q",
            tooltip=["fecha:T", "valor:Q"]
        )
    )

st.altair_chart(chart, width="stretch")
# st.altair_chart(chart, use_container_width=True)



gestion_productos = st.session_state.get("gestion_productos")
if st.session_state["upload_historical_data"]:
    st.info("Puedes ajustar los valores que necesites")
    gestion_productos = st.session_state.get("gestion_productos")

edited_tmp = st.data_editor(
    gestion_productos,
    hide_index=True,
    key="editor_tmp",
    column_config={
        "Ajuste de la demanda": st.column_config.NumberColumn(
            label="Ajuste cantidad de ingredientes",
            min_value=0,
            max_value=1,
            step=0.01,
            format="percent",
        ),
        "Ajuste de precio": st.column_config.NumberColumn(
            "Ajuste de precio",
            min_value=0,
            max_value=1,
            step=0.01,
            format="percent",
        ),
        "Total": st.column_config.NumberColumn(
            "Costo total",
            min_value=0,
            format="compact",
        )
    },
)


st.subheader("💡 Insight de la proyección (IA)")
if window == None:
    st.info("Elija una ventan a de forecast")
if flag_historical_data and window != None:
    df_for_insight = edited_tmp.copy()
    summary_rows = df_for_insight.head(20).to_dict(orient="records")
    today = datetime.now().strftime("%d/%m/%Y")

    prompt = (
        f"Fecha: {today}. Eres un planificador de demanda para restaurantes en Perú. "
        f"Con base en el siguiente JSON de productos (estimación, ajustes y costo total), "
        f"entrega 2 bullets de insight, máximo 30 palabras cada uno. "
        f"Considera feriados, fines de semana y días flojos.\n\n"
        f"TABLA:\n{json.dumps(summary_rows, ensure_ascii=False)}"
    )


    insights_state = st.session_state.get('insights', {})

    time_dict = {"14 días":14, "1 mes":30, "3 meses":90}
    tmp_window = time_dict[window]
    
    if not insights_state or tmp_window not in insights_state:
        st.warning("Datos de insights no disponibles para la ventana seleccionada. Cargando...")

    if len(insights_state[tmp_window]) == 0:
        if client:
            try:
                resp = client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[
                        {"role":"system","content":"Eres un analista de demanda conciso y práctico."},
                        {"role":"user","content":prompt},
                    ],
                    temperature=0.2,
                    max_tokens=120,
                )
                out_message = resp.choices[0].message.content.strip()
                insights_state[tmp_window] = out_message
                st.session_state["insights"] = insights_state
                st.write(out_message)
            except Exception as e:
                st.warning(f"No se pudo generar el insight: {e}")
        else:
            st.info("Configura tu API_KEY en el .env para generar insights.")
    else:
        st.write(insights_state[tmp_window])
