import streamlit as st
from google.cloud import bigquery
from google.oauth2.credentials import Credentials

st.set_page_config(
    page_title="Consulta Downgrades",
    page_icon="📉",
    layout="centered",
)


def _bq_client():
    project = "meli-bi-data"
    if "gcp" in st.secrets:
        s = st.secrets["gcp"]
        creds = Credentials(
            token=None,
            refresh_token=s["refresh_token"],
            token_uri="https://oauth2.googleapis.com/token",
            client_id=s["client_id"],
            client_secret=s["client_secret"],
            quota_project_id=project,
        )
        return bigquery.Client(project=project, credentials=creds)
    return bigquery.Client(project=project)


def build_query(sid: int) -> str:
    return f"""
WITH semanas AS (
  SELECT
    DATE_TRUNC(DATE_SUB(CURRENT_DATE(), INTERVAL 1 WEEK), WEEK(MONDAY))                            AS fin,
    DATE_SUB(DATE_TRUNC(DATE_SUB(CURRENT_DATE(), INTERVAL 1 WEEK), WEEK(MONDAY)), INTERVAL 7 WEEK) AS inicio
),
downgrade_status AS (
  SELECT SMI_STATUS_ID, MSI_ACTIVATION_DATE_DTTM
  FROM `meli-bi-data.WHOWNER.LK_SHP_SELLER_MIGRATION`
  WHERE CUS_CUST_ID = {sid}
    AND SMI_FLOW_TYPE_ID = 'DOWNGRADE'
    AND SMI_STATUS_ID IN ('ACTIVE','IN_PROGRESS','COMPLETE','TO_COMMUNICATE')
    AND MSI_ACTIVATION_DATE_DTTM >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
    AND SIT_SITE_ID = 'MLA'
  ORDER BY MSI_ACTIVATION_DATE_DTTM DESC
  LIMIT 1
),
weekly_shp AS (
  SELECT
    DATE_TRUNC(CAST(shp_date_handling_id AS DATE), WEEK(MONDAY)) AS week_start,
    COUNT(DISTINCT shp.SHP_SHIPMENT_ID)                           AS shipments
  FROM `meli-bi-data.WHOWNER.BT_SHP_SHIPMENTS` shp
  LEFT JOIN `meli-bi-data.WHOWNER.LK_SHP_USR_PREF_LOGISTIC_TYPES` LT
    ON LT.shp_sender_id = shp.shp_sender_id
  CROSS JOIN semanas sc
  WHERE shp.shp_sender_id = {sid}
    AND shp.sit_site_id = 'MLA'
    AND shp.shp_source_id = 'MELI'
    AND shp.shp_shipping_mode_id = 'me2'
    AND shp.shp_type = 'forward'
    AND shp.shp_picking_type_id IN ('drop_off','xd_drop_off','cross_docking')
    AND CAST(shp_date_handling_id AS DATE) BETWEEN sc.inicio AND sc.fin
    AND shp.shp_status_id NOT IN ('cancelled','PENDING')
    AND fecha_hasta IS NULL
    AND logistic_mode = 'me2'
    AND logistic_status = 'active'
    AND SIT_SITE_ID_CUS = 'MLA'
    AND logistic_type = 'cross_docking'
    AND shp.SHP_CBT_FLAG = 0
  GROUP BY 1
  ORDER BY 1
)

SELECT
  (SELECT MAX(CUS_NICKNAME)
   FROM `meli-bi-data.WHOWNER.LK_CUS_CUSTOMERS_DATA`
   WHERE CUS_CUST_ID = {sid})                            AS nombre,
  (SELECT SMI_STATUS_ID        FROM downgrade_status)    AS downgrade_status,
  (SELECT MSI_ACTIVATION_DATE_DTTM FROM downgrade_status) AS downgrade_fecha,
  w.week_start,
  DATE_ADD(w.week_start, INTERVAL 6 DAY)                 AS week_end,
  EXTRACT(WEEK FROM w.week_start)                        AS week_num,
  w.shipments,
  (SELECT inicio FROM semanas)                           AS periodo_inicio,
  (SELECT fin     FROM semanas)                          AS periodo_fin
FROM weekly_shp w
ORDER BY w.week_start
"""


# ── UI ───────────────────────────────────────────────────────────────
st.markdown(
    "<h1 style='margin-bottom:0'>📉 Consulta de Downgrades</h1>"
    "<p style='color:grey;margin-top:4px'>Verificá el estado de baja de un seller y su actividad en el período analizado.</p>",
    unsafe_allow_html=True,
)
st.divider()

seller_raw = st.text_input("Seller ID", placeholder="Ej: 432145923")
buscar     = st.button("Buscar", type="primary", use_container_width=True)

if not buscar:
    st.stop()

if not seller_raw.strip():
    st.warning("Ingresá un Seller ID.")
    st.stop()
try:
    seller_id = int(seller_raw.strip())
except ValueError:
    st.error("El Seller ID debe ser un número entero.")
    st.stop()

with st.spinner("Consultando BigQuery…"):
    try:
        df = _bq_client().query(build_query(seller_id)).to_dataframe()
    except Exception as exc:
        st.error(f"Error al consultar BigQuery: {exc}")
        st.stop()

if df.empty:
    st.warning(f"No se encontró actividad para el Seller ID **{seller_id}** en el período analizado.")
    st.stop()

r0             = df.iloc[0]
nombre         = r0.get("nombre") or f"Seller {seller_id}"
dg_status      = r0.get("downgrade_status")
periodo_inicio = r0.get("periodo_inicio")
periodo_fin    = r0.get("periodo_fin")

# ── Header ───────────────────────────────────────────────────────────
st.subheader(f"{nombre}  —  ID: {seller_id}")
if periodo_inicio and periodo_fin:
    st.caption(f"Período analizado: {periodo_inicio.strftime('%d/%m/%Y')} al {periodo_fin.strftime('%d/%m/%Y')}")
st.divider()

# ── Estado de baja ───────────────────────────────────────────────────
STATUS_LABELS = {
    "ACTIVE":         "Activo",
    "IN_PROGRESS":    "En proceso",
    "COMPLETE":       "Completado",
    "TO_COMMUNICATE": "A comunicar",
}

if dg_status:
    label = STATUS_LABELS.get(dg_status, dg_status)
    st.error(f"### ❌  EN PROCESO DE BAJA  —  {label}")
else:
    st.success("### ✅  NO ESTÁ EN PROCESO DE BAJA")

st.divider()

# ── Envíos por semana ────────────────────────────────────────────────
if df.empty or df["week_start"].isna().all():
    st.info("Sin envíos registrados en el período.")
    st.stop()

weeks = df[["week_start", "week_end", "week_num", "shipments"]].dropna(subset=["week_start"])
weeks = weeks.sort_values("week_start").reset_index(drop=True)

mes1 = weeks.iloc[:4]
mes2 = weeks.iloc[4:]

st.markdown("**Envíos del período de análisis (8 semanas)**")

col1, col2 = st.columns(2)

def render_mes(col, title, data):
    col.markdown(f"**{title}**")
    for _, row in data.iterrows():
        ws  = row["week_start"]
        we  = row["week_end"]
        shp = int(row["shipments"])
        label = f"Semana {int(row['week_num'])}  ({ws.strftime('%d/%m')} – {we.strftime('%d/%m')})"
        col.metric(label, f"{shp:,}")
    col.divider()
    total = int(data["shipments"].sum())
    col.metric(f"**Total {title}**", f"**{total:,}**")

render_mes(col1, "Mes 1  (semanas 1-4)", mes1)
render_mes(col2, "Mes 2  (semanas 5-8)", mes2)
