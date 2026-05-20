import os
import streamlit as st
from google.cloud import bigquery
from google.oauth2.credentials import Credentials

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

st.set_page_config(
    page_title="Validador de Upgrades",
    page_icon="📦",
    layout="centered",
)

# ── Cobertura ────────────────────────────────────────────────────────
_COB = """
    SELECT zip FROM UNNEST(GENERATE_ARRAY(1001, 1130)) AS zip
    UNION ALL SELECT zip FROM UNNEST(GENERATE_ARRAY(1133, 1296)) AS zip
    UNION ALL SELECT zip FROM UNNEST(GENERATE_ARRAY(1405, 1440)) AS zip
    UNION ALL SELECT zip FROM UNNEST(GENERATE_ARRAY(1602, 1692)) AS zip
    UNION ALL SELECT zip FROM UNNEST(GENERATE_ARRAY(1701, 1793)) AS zip
    UNION ALL SELECT zip FROM UNNEST(GENERATE_ARRAY(1801, 1898)) AS zip
    UNION ALL SELECT zip FROM UNNEST(GENERATE_ARRAY(1900, 1942)) AS zip
    UNION ALL SELECT zip FROM UNNEST(GENERATE_ARRAY(2000, 2015)) AS zip
    UNION ALL SELECT zip FROM UNNEST([
      2045,2046,2107,2121,2124,2126,2129,2130,2132,
      2150,2151,2152,2153,2154,2156,2200,2201,2202,2300,
      2800,2802,2804,2812,2813,2814,2816,
      3000,3002,3004,3006,3008,3016,3017,3020,3040,
      3100,3102,3104,3106,
      4000,4001,4002,4101,4103,4104,4105,4107,4109,4111,4116,4172,4178,
      5000,5105,5125,5152,
      5500,5501,5504,5505,5507,5515,5519,5521,5523,5525,5526,5527,5539,
      6700,6702,7600,7603,7605,7606,7608,
      8000,8001,8002,8003
    ]) AS zip
"""

def _addr_cte(cust_id: int, alias: str = "seller_info") -> str:
    return f"""
{alias} AS (
  SELECT
    {cust_id}              AS seller,
    MAX(CUS_CUST_NAME)     AS nombre,
    MAX(ADD_ZIP_CODE)      AS zip,
    MAX(ADD_STREET_NUMBER) AS street_num,
    MAX(ADD_STATE_NAME)    AS provincia,
    MAX(ADD_CITY_NAME)     AS ciudad
  FROM (
    SELECT CUS_CUST_ID, CUS_CUST_NAME, ADD_ZIP_CODE, ADD_STREET_NUMBER,
           ADD_STATE_NAME, ADD_CITY_NAME,
           ROW_NUMBER() OVER (PARTITION BY CUS_CUST_ID ORDER BY ADD_UPDATED_DATE DESC) AS rn
    FROM `WHOWNER.LK_CUS_ADDRESS`
    WHERE CUS_CUST_ID = {cust_id} AND ADD_SHIPPING_TYPE_FLAG = 1
  ) a WHERE rn = 1
)"""


# ── Queries ──────────────────────────────────────────────────────────

def build_query_normal(sid: int) -> str:
    return f"""
WITH
params AS (
  SELECT
    DATE_TRUNC(DATE_SUB(CURRENT_DATE(), INTERVAL 2 MONTH), MONTH) AS m2_start,
    LAST_DAY(DATE_SUB(CURRENT_DATE(), INTERVAL 2 MONTH))           AS m2_end,
    DATE_TRUNC(DATE_SUB(CURRENT_DATE(), INTERVAL 1 MONTH), MONTH) AS m1_start,
    LAST_DAY(DATE_SUB(CURRENT_DATE(), INTERVAL 1 MONTH))           AS m1_end
),
cobertura AS ({_COB}),
{_addr_cte(sid)},

ultimo_picking AS (
  SELECT shp_picking_type_id
  FROM `WHOWNER.BT_SHP_SHIPMENTS`
  WHERE shp_sender_id = {sid}
    AND sit_site_id = 'MLA' AND shp_source_id = 'MELI'
    AND shp_shipping_mode_id = 'me2' AND shp_type = 'forward'
    AND shp_status_id NOT IN ('cancelled','PENDING')
  ORDER BY shp_date_handling_id DESC LIMIT 1
),
tiene_proximity AS (
  SELECT COUNT(*) AS cnt
  FROM `meli-bi-data.WHOWNER.LK_SHP_USER_PREFERENCE`
  WHERE SHP_SENDER_ID = {sid}
    AND SHP_SERVICE IN ('470341','496503','1266122')
),
shp_by_type AS (
  SELECT
    shp_picking_type_id,
    DATE_TRUNC(CAST(shp_date_handling_id AS DATE), MONTH)  AS month,
    COUNT(DISTINCT SHP_SHIPMENT_ID)                         AS shipments,
    CAST(ROUND(SUM(shp_order_cost)) AS INT64)               AS gmv
  FROM `WHOWNER.BT_SHP_SHIPMENTS`
  CROSS JOIN params p
  WHERE shp_sender_id = {sid}
    AND sit_site_id = 'MLA' AND shp_source_id = 'MELI'
    AND shp_shipping_mode_id = 'me2' AND shp_type = 'forward'
    AND shp_picking_type_id IN ('xd_drop_off','drop_off')
    AND shp_status_id NOT IN ('cancelled','PENDING')
    AND CAST(shp_date_handling_id AS DATE) BETWEEN p.m2_start AND p.m1_end
  GROUP BY 1,2
),
volumes AS (
  SELECT
    shp_picking_type_id,
    MAX(IF(month=(SELECT m2_start FROM params),shipments,0))                      AS shp_m2,
    MAX(IF(month=(SELECT m1_start FROM params),shipments,0))                      AS shp_m1,
    MAX(IF(month=(SELECT m2_start FROM params),SAFE_DIVIDE(gmv,shipments),NULL))  AS ticket_m2,
    MAX(IF(month=(SELECT m1_start FROM params),SAFE_DIVIDE(gmv,shipments),NULL))  AS ticket_m1
  FROM shp_by_type GROUP BY 1
),
avg_ticket_pm AS (
  SELECT
    DATE_TRUNC(CAST(shp_date_handling_id AS DATE), MONTH) AS month,
    SAFE_DIVIDE(CAST(ROUND(SUM(shp_order_cost)) AS INT64), COUNT(DISTINCT SHP_SHIPMENT_ID)) AS avg_t
  FROM `WHOWNER.BT_SHP_SHIPMENTS`
  CROSS JOIN params p
  WHERE sit_site_id='MLA' AND shp_source_id='MELI'
    AND shp_shipping_mode_id='me2' AND shp_type='forward'
    AND shp_picking_type_id='cross_docking'
    AND shp_status_id NOT IN ('cancelled','PENDING')
    AND CAST(shp_date_handling_id AS DATE) BETWEEN p.m2_start AND p.m1_end
  GROUP BY 1
),
avg_ticket AS (
  SELECT
    MAX(IF(month=(SELECT m2_start FROM params),avg_t,NULL)) AS avg_m2,
    MAX(IF(month=(SELECT m1_start FROM params),avg_t,NULL)) AS avg_m1
  FROM avg_ticket_pm
)

SELECT
  si.seller, si.nombre, si.zip,
  SAFE_CAST(si.zip AS INT64) AS zip_num,
  si.provincia, si.ciudad,
  CASE WHEN EXISTS(SELECT 1 FROM cobertura WHERE zip=SAFE_CAST(si.zip AS INT64))
       THEN TRUE ELSE FALSE END                                                    AS tiene_cobertura,
  COALESCE((SELECT shp_picking_type_id FROM ultimo_picking LIMIT 1)='cross_docking',FALSE) AS excluido_xd,
  (SELECT cnt FROM tiene_proximity)>0                                              AS excluido_proximity,
  COALESCE((SELECT shp_m2 FROM volumes WHERE shp_picking_type_id='xd_drop_off'),0) AS xddo_m2,
  COALESCE((SELECT shp_m1 FROM volumes WHERE shp_picking_type_id='xd_drop_off'),0) AS xddo_m1,
  (SELECT ticket_m2 FROM volumes WHERE shp_picking_type_id='xd_drop_off')          AS xddo_ticket_m2,
  (SELECT ticket_m1 FROM volumes WHERE shp_picking_type_id='xd_drop_off')          AS xddo_ticket_m1,
  COALESCE((SELECT shp_m2 FROM volumes WHERE shp_picking_type_id='drop_off'),0)    AS ds_m2,
  COALESCE((SELECT shp_m1 FROM volumes WHERE shp_picking_type_id='drop_off'),0)    AS ds_m1,
  (SELECT ticket_m2 FROM volumes WHERE shp_picking_type_id='drop_off')             AS ds_ticket_m2,
  (SELECT ticket_m1 FROM volumes WHERE shp_picking_type_id='drop_off')             AS ds_ticket_m1,
  (SELECT avg_m2 FROM avg_ticket)                                                   AS avg_ticket_m2,
  (SELECT avg_m1 FROM avg_ticket)                                                   AS avg_ticket_m1
FROM seller_info si
"""


def build_query_multicuenta(sid: int, madre_id: int) -> str:
    return f"""
WITH
cobertura AS ({_COB}),
{_addr_cte(sid)},

madre_info AS (
  SELECT
    {madre_id}             AS madre,
    MAX(ADD_ZIP_CODE)      AS zip,
    MAX(ADD_STREET_NUMBER) AS street_num
  FROM (
    SELECT CUS_CUST_ID, ADD_ZIP_CODE, ADD_STREET_NUMBER,
           ROW_NUMBER() OVER (PARTITION BY CUS_CUST_ID ORDER BY ADD_UPDATED_DATE DESC) AS rn
    FROM `WHOWNER.LK_CUS_ADDRESS`
    WHERE CUS_CUST_ID = {madre_id} AND ADD_SHIPPING_TYPE_FLAG = 1
  ) a WHERE rn = 1
),
tiene_proximity AS (
  SELECT COUNT(*) AS cnt
  FROM `meli-bi-data.WHOWNER.LK_SHP_USER_PREFERENCE`
  WHERE SHP_SENDER_ID = {sid}
    AND SHP_SERVICE IN ('470341','496503','1266122')
)

SELECT
  si.seller, si.nombre, si.zip, si.street_num, si.provincia, si.ciudad,
  CASE WHEN EXISTS(SELECT 1 FROM cobertura WHERE zip=SAFE_CAST(si.zip AS INT64))
       THEN TRUE ELSE FALSE END                                    AS tiene_cobertura,
  (SELECT cnt FROM tiene_proximity)>0                              AS excluido_proximity,
  EXISTS (
    SELECT 1 FROM `meli-bi-data.WHOWNER.LK_SHP_USR_PREF_LOGISTIC_TYPES`
    WHERE SHP_SENDER_ID={madre_id}
      AND LOGISTIC_TYPE='cross_docking'
      AND LOGISTIC_STATUS='active'
      AND FECHA_HASTA IS NULL
  )                                                                AS tiene_colecta_madre,
  (si.zip IS NOT NULL AND si.street_num IS NOT NULL
   AND si.zip = m.zip AND si.street_num = m.street_num)           AS mismo_domicilio,
  m.zip          AS madre_zip,
  m.street_num   AS madre_street_num
FROM seller_info si
CROSS JOIN madre_info m
"""


def build_query_hb(sid: int) -> str:
    return f"""
WITH
params AS (
  SELECT
    DATE_TRUNC(DATE_SUB(CURRENT_DATE(), INTERVAL 2 MONTH), MONTH) AS m2_start,
    LAST_DAY(DATE_SUB(CURRENT_DATE(), INTERVAL 2 MONTH))           AS m2_end,
    DATE_TRUNC(DATE_SUB(CURRENT_DATE(), INTERVAL 1 MONTH), MONTH) AS m1_start,
    LAST_DAY(DATE_SUB(CURRENT_DATE(), INTERVAL 1 MONTH))           AS m1_end
),
cobertura AS ({_COB}),
{_addr_cte(sid)},

tiene_proximity AS (
  SELECT COUNT(*) AS cnt
  FROM `meli-bi-data.WHOWNER.LK_SHP_USER_PREFERENCE`
  WHERE SHP_SENDER_ID = {sid}
    AND SHP_SERVICE IN ('470341','496503','1266122')
),
hb_by_month AS (
  SELECT
    DATE_TRUNC(CAST(SHP_CREATED_DATETIME_TZ AS DATE), MONTH) AS month,
    SHP_SHIPPING_MODE                                          AS modo,
    COUNT(DISTINCT SHP_SHIPMENT_ID)                            AS shipments
  FROM `WHOWNER.BT_SHP_SHIPMENTS_SUMMARY`
  CROSS JOIN params p
  WHERE shp_sender_id = {sid}
    AND CAST(SHP_CREATED_DATETIME_TZ AS DATE) BETWEEN p.m2_start AND p.m1_end
    AND SHP_SHIPPING_MODE IS NOT NULL
    AND (
      SHP_SHIPPING_MODE = 'ME1'
      OR (SHP_SHIPPING_MODE = 'ME2'
          AND SHP_PICKING_TYPE IN ('DROP_OFF','XD_DROP_OFF','CROSS_DOCKING'))
    )
  GROUP BY 1, 2
)

SELECT
  si.seller, si.nombre, si.zip,
  SAFE_CAST(si.zip AS INT64) AS zip_num,
  si.provincia, si.ciudad,
  CASE WHEN EXISTS(SELECT 1 FROM cobertura WHERE zip=SAFE_CAST(si.zip AS INT64))
       THEN TRUE ELSE FALSE END                                      AS tiene_cobertura,
  (SELECT cnt FROM tiene_proximity)>0                                AS excluido_proximity,
  COALESCE((SELECT MAX(IF(month=(SELECT m2_start FROM params) AND modo='ME1',shipments,0)) FROM hb_by_month),0) AS me1_m2,
  COALESCE((SELECT MAX(IF(month=(SELECT m1_start FROM params) AND modo='ME1',shipments,0)) FROM hb_by_month),0) AS me1_m1,
  COALESCE((SELECT MAX(IF(month=(SELECT m2_start FROM params) AND modo='ME2',shipments,0)) FROM hb_by_month),0) AS me2_m2,
  COALESCE((SELECT MAX(IF(month=(SELECT m1_start FROM params) AND modo='ME2',shipments,0)) FROM hb_by_month),0) AS me2_m1,
  COALESCE((SELECT SUM(IF(month=(SELECT m2_start FROM params),shipments,0)) FROM hb_by_month),0) AS hb_m2,
  COALESCE((SELECT SUM(IF(month=(SELECT m1_start FROM params),shipments,0)) FROM hb_by_month),0) AS hb_m1
FROM seller_info si
"""


# ── Helpers de display ───────────────────────────────────────────────
def ok(v: bool) -> str:
    return "✅" if v else "❌"

_FORM_URL = "https://forms.gle/YY3NqFQtTPyiw3x77"

def _cta_aplica():
    st.divider()
    st.link_button("Completar formulario de alta", _FORM_URL, type="primary", use_container_width=True)

def _cta_no_aplica(sid: int):
    st.divider()
    st.link_button("Solicitar excepción via formulario", _FORM_URL, use_container_width=True)


# ── UI ───────────────────────────────────────────────────────────────
st.markdown(
    "<h1 style='margin-bottom:0'>📦 Validador de Upgrades</h1>"
    "<p style='color:grey;margin-top:4px'>Verificá si un seller aplica para tener colecta Activa en su domicilio!</p>",
    unsafe_allow_html=True,
)
st.divider()


# ── Formulario ───────────────────────────────────────────────────────
col_id, col_tipo = st.columns([2, 2])
with col_id:
    seller_raw = st.text_input("Seller ID", placeholder="Ej: 432145923")
with col_tipo:
    tipo = st.radio("Tipo de consulta", ["Normal", "Multicuenta", "H&B"], horizontal=True)

madre_raw = ""
if tipo == "Multicuenta":
    madre_raw = st.text_input("ID de la cuenta madre", placeholder="Ej: 123456789")

buscar = st.button("Buscar", type="primary", use_container_width=True)

if not buscar:
    st.stop()

# ── Validaciones ─────────────────────────────────────────────────────
if not seller_raw.strip():
    st.warning("Ingresá un Seller ID.")
    st.stop()
try:
    seller_id = int(seller_raw.strip())
except ValueError:
    st.error("El Seller ID debe ser un número entero.")
    st.stop()

madre_id = None
if tipo == "Multicuenta":
    if not madre_raw.strip():
        st.warning("Ingresá el ID de la cuenta madre.")
        st.stop()
    try:
        madre_id = int(madre_raw.strip())
    except ValueError:
        st.error("El ID de la cuenta madre debe ser un número entero.")
        st.stop()

# ── Consulta ─────────────────────────────────────────────────────────
with st.spinner("Consultando BigQuery…"):
    try:
        client = _bq_client()
        if tipo == "Normal":
            df = client.query(build_query_normal(seller_id)).to_dataframe()
        elif tipo == "Multicuenta":
            df = client.query(build_query_multicuenta(seller_id, madre_id)).to_dataframe()
        else:
            df = client.query(build_query_hb(seller_id)).to_dataframe()
    except Exception as exc:
        st.error(f"Error al consultar BigQuery: {exc}")
        st.stop()

if df.empty:
    st.warning(f"No se encontró información para el Seller ID **{seller_id}**.")
    st.stop()

row = df.iloc[0]
nombre   = row.get("nombre") or f"Seller {seller_id}"
zip_num  = int(row["zip_num"]) if row.get("zip_num") else 0
zip_code = str(zip_num) if zip_num else (str(row.get("zip","")) or "Sin CP")
provincia = row.get("provincia") or "N/D"
ciudad    = row.get("ciudad")    or "N/D"

st.subheader(f"{nombre}  —  ID: {seller_id}")
st.caption(f"📍 {ciudad}, {provincia}  |  CP: {zip_code}")
st.divider()

# ════════════════════════════════════════════════════════════════════
#  NORMAL
# ════════════════════════════════════════════════════════════════════
if tipo == "Normal":
    tiene_cob  = bool(row["tiene_cobertura"])
    excl_xd    = bool(row["excluido_xd"])
    excl_prox  = bool(row["excluido_proximity"])
    vol_min    = 400 if 0 < zip_num <= 1999 else 300

    xddo_m2, xddo_m1 = int(row["xddo_m2"] or 0), int(row["xddo_m1"] or 0)
    ds_m2,   ds_m1   = int(row["ds_m2"]   or 0), int(row["ds_m1"]   or 0)
    xddo_t2, xddo_t1 = row["xddo_ticket_m2"], row["xddo_ticket_m1"]
    ds_t2,   ds_t1   = row["ds_ticket_m2"],   row["ds_ticket_m1"]
    avg_m2,  avg_m1  = row["avg_ticket_m2"],  row["avg_ticket_m1"]

    base_ok = tiene_cob and not excl_xd and not excl_prox

    xddo_xd_ok = base_ok and xddo_m2 >= vol_min and xddo_m1 >= vol_min
    ds_xd_ok   = base_ok and ds_m2   >= vol_min and ds_m1   >= vol_min

    def _tick(t2, t1, a2, a1) -> bool:
        if any(v is None for v in [t2, t1, a2, a1]):
            return False
        return float(t2) >= 2 * float(a2) and float(t1) >= 2 * float(a1)

    no_vol = not xddo_xd_ok and not ds_xd_ok
    xddo_col_ok = base_ok and no_vol and xddo_m2 >= 200 and xddo_m1 >= 200 and _tick(xddo_t2, xddo_t1, avg_m2, avg_m1)
    ds_col_ok   = base_ok and no_vol and ds_m2   >= 200 and ds_m1   >= 200 and _tick(ds_t2, ds_t1, avg_m2, avg_m1)

    if   xddo_xd_ok:  upgrade = "XDDO → XD"
    elif ds_xd_ok:    upgrade = "DS → XD"
    elif xddo_col_ok: upgrade = "XDDO → Colecta"
    elif ds_col_ok:   upgrade = "DS → Colecta"
    else:             upgrade = None

    any_200 = (xddo_m2 >= 200 and xddo_m1 >= 200) or (ds_m2 >= 200 and ds_m1 >= 200)

    if excl_xd:
        st.success("### ✅  COLECTA ACTIVA")
    elif upgrade:
        st.success(f"### ✅  APLICA  —  {upgrade}")
        _cta_aplica()
    else:
        st.error("### ❌  NO APLICA")
        if any_200:
            _cta_no_aplica(seller_id)

    st.divider()
    st.markdown("**Criterios evaluados**")
    c1, c2 = st.columns(2)
    c1.metric("Cobertura geográfica", f"{ok(tiene_cob)} {'CP: ' + zip_code if tiene_cob else 'Sin cobertura'}")
    c2.metric("Colecta Activa",       f"{'✅ Sí' if excl_xd else '❌ No'}")

    st.divider()
    st.markdown("**Volumen de envíos** (últimos 2 meses cerrados)")

    tab_labels = []
    if xddo_m2 > 0 or xddo_m1 > 0: tab_labels.append("XDDO (xd_drop_off)")
    if ds_m2   > 0 or ds_m1   > 0: tab_labels.append("DS (drop_off)")

    if tab_labels:
        tabs = st.tabs(tab_labels)
        idx  = 0
        if "XDDO (xd_drop_off)" in tab_labels:
            with tabs[idx]:
                a, b, c = st.columns(3)
                a.metric("Mes -2", f"{xddo_m2:,}")
                b.metric("Mes -1", f"{xddo_m1:,}")
                c.metric("XDDO → XD", ok(xddo_xd_ok))
                st.markdown("---")
                t1, t2, t3 = st.columns(3)
                t1.metric("Ticket mes -2", f"${xddo_t2:,.0f}" if xddo_t2 else "N/D")
                t2.metric("Ticket mes -1", f"${xddo_t1:,.0f}" if xddo_t1 else "N/D")
                t3.metric("XDDO → Colecta", ok(xddo_col_ok))
            idx += 1
        if "DS (drop_off)" in tab_labels:
            with tabs[idx]:
                a, b, c = st.columns(3)
                a.metric("Mes -2", f"{ds_m2:,}")
                b.metric("Mes -1", f"{ds_m1:,}")
                c.metric("DS → XD", ok(ds_xd_ok))
                st.markdown("---")
                t1, t2, t3 = st.columns(3)
                t1.metric("Ticket mes -2", f"${ds_t2:,.0f}" if ds_t2 else "N/D")
                t2.metric("Ticket mes -1", f"${ds_t1:,.0f}" if ds_t1 else "N/D")
                t3.metric("DS → Colecta", ok(ds_col_ok))
    else:
        st.info("No se encontraron envíos XDDO ni DS en los últimos 2 meses.")

    if not upgrade:
        st.divider()
        st.markdown("**Motivo del rechazo**")
        if not tiene_cob:
            st.markdown(f"• **Sin cobertura**: el CP `{zip_code}` no está dentro de la zona de colecta.")
        if excl_xd:
            st.markdown("• **Ya opera con Cross Docking**: el último envío registrado fue `cross_docking`.")
        if base_ok:
            if xddo_m2 == 0 and xddo_m1 == 0 and ds_m2 == 0 and ds_m1 == 0:
                st.markdown("• **Sin envíos**: no se encontraron envíos XDDO ni DS en los últimos 2 meses.")
            else:
                if not (xddo_m2 >= vol_min and xddo_m1 >= vol_min) and not (ds_m2 >= vol_min and ds_m1 >= vol_min):
                    st.markdown(f"• **Volumen insuficiente para XD**: se requieren {vol_min:,} envíos/mes en ambos meses.")
                any_200 = (xddo_m2 >= 200 and xddo_m1 >= 200) or (ds_m2 >= 200 and ds_m1 >= 200)
                if any_200 and avg_m1:
                    st.markdown(f"• **Ticket insuficiente para Colecta**: no alcanza el doble del promedio de colecta (${2*float(avg_m1):,.0f}).")

# ════════════════════════════════════════════════════════════════════
#  MULTICUENTA
# ════════════════════════════════════════════════════════════════════
elif tipo == "Multicuenta":
    tiene_cob      = bool(row["tiene_cobertura"])
    excl_prox      = bool(row["excluido_proximity"])
    tiene_col_mad  = bool(row["tiene_colecta_madre"])
    mismo_dom      = bool(row["mismo_domicilio"])
    madre_zip      = str(row["madre_zip"])      if row.get("madre_zip")      else "Sin CP"
    madre_street   = str(row["madre_street_num"]) if row.get("madre_street_num") else "Sin número"
    hijo_street    = str(row.get("street_num", "")) or "Sin número"

    aplica = tiene_col_mad and mismo_dom and tiene_cob and not excl_prox

    if aplica:
        st.success("### ✅  APLICA  —  Multicuenta")
    else:
        st.error("### ❌  NO APLICA  —  Multicuenta")

    st.divider()
    st.markdown("**Criterios evaluados**")

    c1, c2 = st.columns(2)
    c1.metric("Colecta activa en cuenta madre", f"{ok(tiene_col_mad)} {'Sí' if tiene_col_mad else 'No'}")
    c1.caption(f"ID madre: {madre_id}")
    c2.metric("Mismo domicilio",               f"{ok(mismo_dom)} {'Sí' if mismo_dom else 'No'}")
    c2.caption(f"Madre → CP: {madre_zip} / Nro: {madre_street}  |  Hijo → CP: {zip_code} / Nro: {hijo_street}")

    c3, c4 = st.columns(2)
    c3.metric("Cobertura geográfica",  f"{ok(tiene_cob)} {'Aplica' if tiene_cob else 'Sin cobertura'}")
    c3.caption(f"CP: {zip_code}")
    c4.metric("Proximity",             f"{ok(not excl_prox)} {'Sin proximity' if not excl_prox else 'Tiene proximity'}")

    if not aplica:
        st.divider()
        if not tiene_col_mad:
            st.warning(f"### La cuenta madre ({madre_id}) no tiene Colecta activa.")
        if not mismo_dom:
            st.warning(f"### Domicilios distintos: la cuenta hijo no comparte número y CP con la cuenta madre.")
        if not tiene_cob:
            st.warning(f"### Sin cobertura: el CP {zip_code} no está dentro de la zona de Colecta.")
        if excl_prox:
            st.warning("### Tiene servicio Proximity activo.")
    else:
        _cta_aplica()

# ════════════════════════════════════════════════════════════════════
#  H&B
# ════════════════════════════════════════════════════════════════════
else:
    tiene_cob  = bool(row["tiene_cobertura"])
    excl_prox  = bool(row["excluido_proximity"])
    me1_m2     = int(row["me1_m2"] or 0)
    me1_m1     = int(row["me1_m1"] or 0)
    me2_m2     = int(row["me2_m2"] or 0)
    me2_m1     = int(row["me2_m1"] or 0)
    hb_m2      = int(row["hb_m2"] or 0)
    hb_m1      = int(row["hb_m1"] or 0)
    vol_ok     = hb_m2 >= 100 and hb_m1 >= 100

    aplica = tiene_cob and not excl_prox and vol_ok

    if aplica:
        st.success("### ✅  APLICA  —  H&B")
    else:
        st.error("### ❌  NO APLICA  —  H&B")

    st.divider()
    st.markdown("**Criterios evaluados**")

    c1, c2 = st.columns(2)
    c1.metric("Cobertura geográfica", f"{ok(tiene_cob)} {'CP: ' + zip_code if tiene_cob else 'Sin cobertura'}")
    c2.metric("Proximity",            f"{ok(not excl_prox)} {'Sin proximity' if not excl_prox else 'Tiene proximity'}")

    st.divider()
    st.markdown("**Volumen ME1 + ME2** (últimos 2 meses cerrados — mínimo 100/mes)")

    _, col_m2, col_m1 = st.columns([1, 2, 2])
    col_m2.markdown("**Mes -2**")
    col_m1.markdown("**Mes -1**")

    r1a, r1b, r1c = st.columns([1, 2, 2])
    r1a.markdown("ME1")
    r1b.metric("", f"{me1_m2:,}", label_visibility="collapsed")
    r1c.metric("", f"{me1_m1:,}", label_visibility="collapsed")

    r2a, r2b, r2c = st.columns([1, 2, 2])
    r2a.markdown("ME2")
    r2b.metric("", f"{me2_m2:,}", label_visibility="collapsed")
    r2c.metric("", f"{me2_m1:,}", label_visibility="collapsed")

    r3a, r3b, r3c = st.columns([1, 2, 2])
    r3a.markdown("**Total**")
    r3b.metric("", f"**{hb_m2:,}**", label_visibility="collapsed")
    r3c.metric("", f"**{hb_m1:,}**", label_visibility="collapsed")

    _, chk_m2, chk_m1 = st.columns([1, 2, 2])
    chk_m2.markdown(f"{ok(hb_m2 >= 100)} {'OK' if hb_m2 >= 100 else 'Insuficiente'} (mín 100)")
    chk_m1.markdown(f"{ok(hb_m1 >= 100)} {'OK' if hb_m1 >= 100 else 'Insuficiente'} (mín 100)")

    if not aplica:
        st.divider()
        st.markdown("**Motivo del rechazo**")
        if not tiene_cob:
            st.markdown(f"• **Sin cobertura**: el CP `{zip_code}` no está dentro de la zona de colecta.")
        if excl_prox:
            st.markdown("• **Tiene servicio Proximity activo**.")
        if not vol_ok:
            st.markdown(f"• **Volumen insuficiente**: tuvo {hb_m2:,} (mes -2) y {hb_m1:,} (mes -1). Se requieren al menos 100 en ambos meses.")
        _cta_no_aplica(seller_id)
    else:
        _cta_aplica()

