import streamlit as st
from google.cloud import bigquery
from google.oauth2.credentials import Credentials

_SBOX = "meli-bi-data.SBOX_FMMLA.COLECTA_UPGRADES_DAILY"


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

# ── Consulta al SBOX ─────────────────────────────────────────────────
with st.spinner("Consultando…"):
    try:
        client = _bq_client()
        if tipo == "Multicuenta":
            sql = f"SELECT * FROM `{_SBOX}` WHERE seller IN ({seller_id}, {madre_id})"
        else:
            sql = f"SELECT * FROM `{_SBOX}` WHERE seller = {seller_id}"
        df = client.query(sql).to_dataframe()
    except Exception as exc:
        st.error(f"Error al consultar BigQuery: {exc}")
        st.stop()

if df.empty:
    st.warning(f"No se encontró información para el Seller ID **{seller_id}**.")
    st.stop()

# ── Datos base del hijo ───────────────────────────────────────────────
hijo_rows = df[df["seller"] == seller_id]
if hijo_rows.empty:
    st.warning(f"No se encontró información para el Seller ID **{seller_id}**.")
    st.stop()

row      = hijo_rows.iloc[0]
zip_num  = int(row["zip_num"]) if row.get("zip_num") else 0
zip_code = str(zip_num) if zip_num else (str(row.get("zip", "")) or "Sin CP")
provincia = row.get("provincia") or "N/D"
ciudad    = row.get("ciudad")    or "N/D"

st.subheader(f"Seller ID: {seller_id}")
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
    madre_rows = df[df["seller"] == madre_id]

    tiene_cob   = bool(row["tiene_cobertura"])
    excl_prox   = bool(row["excluido_proximity"])
    hijo_street = str(row.get("street_num", "") or "") or "Sin número"

    if not madre_rows.empty:
        madre_row     = madre_rows.iloc[0]
        tiene_col_mad = bool(madre_row["tiene_colecta_activa"])
        madre_zip     = str(madre_row.get("zip", "") or "") or "Sin CP"
        madre_street  = str(madre_row.get("street_num", "") or "") or "Sin número"
        mismo_dom     = (
            row.get("zip") is not None and row.get("street_num") is not None
            and madre_row.get("zip") is not None and madre_row.get("street_num") is not None
            and str(row["zip"]) == str(madre_row["zip"])
            and str(row["street_num"]) == str(madre_row["street_num"])
        )
    else:
        tiene_col_mad = False
        madre_zip     = "Sin CP"
        madre_street  = "Sin número"
        mismo_dom     = False

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
    c2.metric("Mismo domicilio", f"{ok(mismo_dom)} {'Sí' if mismo_dom else 'No'}")
    c2.caption(f"Madre → CP: {madre_zip} / Nro: {madre_street}  |  Hijo → CP: {zip_code} / Nro: {hijo_street}")

    c3, c4 = st.columns(2)
    c3.metric("Cobertura geográfica", f"{ok(tiene_cob)} {'Aplica' if tiene_cob else 'Sin cobertura'}")
    c3.caption(f"CP: {zip_code}")
    c4.metric("Proximity", f"{ok(not excl_prox)} {'Sin proximity' if not excl_prox else 'Tiene proximity'}")

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
