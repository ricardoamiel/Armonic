import streamlit as st
import pandas as pd
# from demanda import render_forecast
# from facturas import render_facturas
# from proveedores import render_proveedores
# from rutas import render_rutas


# @st.cache_data
# def load_data():
#     return pd.read_csv("data/archivo.csv")

st.set_page_config(
    page_title="Armonic",
    page_icon="📊",
    layout="wide"
)

# if "logged_in" not in st.session_state:
#     st.session_state.logged_in = False

demanda = st.Page("pages/demanda.py", title="Forecast", icon=":material/dashboard:", default=True)
facturas = st.Page("pages/facturas.py", title="Facturación", icon=":material/bug_report:")
proveedores = st.Page("pages/proveedores.py", title="Registro de Proveedores", icon=":material/notification_important:")
#rutas = st.Page("pages/rutas.py", title="Rutas", icon=":material/search:")
pg = st.navigation([demanda,facturas,proveedores])

pg.run()

# if st.session_state.logged_in:
#     pg = st.navigation(
#         {
#             "Account": [logout_page],
#             "Reports": [dashboard, bugs, alerts],
#             "Tools": [search],
#         }
#     )
# else:
#     pg = st.navigation([login_page])
