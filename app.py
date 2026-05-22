import streamlit as st

st.set_page_config(
    page_title="Colecta MELI",
    page_icon="📦",
    layout="centered",
)

upgrades  = st.Page("pages/1_Upgrades.py",   title="Validador de Upgrades",  icon="📦")
downgrades = st.Page("pages/2_Downgrades.py", title="Consulta Downgrades",    icon="📉")

pg = st.navigation([upgrades, downgrades])
pg.run()
