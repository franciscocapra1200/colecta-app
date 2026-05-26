import streamlit as st
from google.cloud import bigquery
from google.oauth2.credentials import Credentials

st.set_page_config(page_title="Estado de Migración", page_icon="📋", layout="centered")
st.title("📋 Estado de Migración a Colecta")

FORM_URL = (
    "https://www.mercadolibre.com/jms/mla/lgz/login"
    "?platform_id=ML"
    "&go=https%3A%2F%2Fenvios.mercadolibre.com.ar%2Fseller-migrations%2Fhub"
    "&loginType=explicit"
    "&client_id=6280072776285528"
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


def get_migration_status(seller_id: int):
    client = _bq_client()
    query = f"""
        SELECT
            CUS_CUST_ID,
            SMI_FLOW_TYPE_ID,
            SMI_LOGSTIC_TYPE,
            SMI_STATUS_ID,
            MSI_LIMIT_DATE_DTTM,
            MSI_ACTIVATION_DATE_DTTM
        FROM WHOWNER.LK_SHP_SELLER_MIGRATION
        WHERE SMI_FLOW_TYPE_ID IN ('UPGRADE', 'MIGRATION')
          AND SMI_LOGSTIC_TYPE IN ('CROSS_DOCKING')
          AND SIT_SITE_ID IN ('MLA')
          AND CUS_CUST_ID = {seller_id}
        ORDER BY MSI_ACTIVATION_DATE_DTTM DESC
        LIMIT 1
    """
    return client.query(query).to_dataframe()


def fmt_date(val):
    if val is None or str(val) == "NaT":
        return "—"
    try:
        return val.strftime("%d/%m/%Y")
    except Exception:
        return str(val)


def show_status(row):
    status = row["SMI_STATUS_ID"]
    limit_date = fmt_date(row["MSI_LIMIT_DATE_DTTM"])
    activation_date = fmt_date(row["MSI_ACTIVATION_DATE_DTTM"])

    if status == "TO_COMMUNICATE":
        st.warning("🔔 **Próximamente invitado**")
        st.write(
            "El seller fue seleccionado para migrar a Colecta, pero todavía no recibió "
            "la invitación oficial. En los próximos días recibirá la comunicación con "
            "el formulario para completar."
        )

    elif status == "IN_PROGRESS":
        st.info("✉️ **Invitado — formulario pendiente**")
        st.write(
            f"El seller fue invitado a la migración a Colecta. "
            f"Tiene tiempo hasta el **{limit_date}** para completar el formulario."
        )
        if activation_date != "—":
            st.write(f"Una vez completado, la activación está programada para el **{activation_date}**.")
        st.link_button("Ir al formulario de migración", FORM_URL)

    elif status == "COMPLETE":
        st.success("✅ **Formulario completado**")
        st.write("El seller ya completó el formulario de migración a Colecta.")
        if activation_date != "—":
            st.write(f"La activación está programada para el **{activation_date}**.")

    elif status == "ACTIVE":
        st.success("🟢 **Activo en Colecta**")
        st.write("El seller ya está activo en Colecta.")
        if activation_date != "—":
            st.write(f"Fecha de activación: **{activation_date}**.")

    elif status == "NOT_MIGRATED":
        st.error("⏰ **No completó la migración**")
        st.write(
            f"El seller no completó el proceso de migración en tiempo y forma. "
            f"El plazo venció el **{limit_date}**."
        )

    elif status == "EXTERNALLY_REMOVED":
        st.error("🚫 **Removido del proceso**")
        st.write(
            "El seller fue removido del proceso de migración a Colecta de forma externa. "
            "Contactar al equipo de Colecta para más información."
        )

    elif status == "SUSPENDED":
        st.warning("⏸️ **Proceso suspendido**")
        st.write(
            "El proceso de migración del seller está suspendido. "
            "Contactar al equipo de Colecta para más información."
        )

    elif status == "FAIL_ACTIVATION":
        st.error("❌ **Error en activación**")
        st.write(
            f"Hubo un error técnico al intentar activar al seller en Colecta. "
            f"La activación estaba programada para el **{activation_date}**. "
            "Contactar al equipo de tecnología para resolver el inconveniente."
        )

    else:
        st.info(f"ℹ️ Estado: **{status}**")
        st.write("Estado no reconocido. Contactar al equipo de Colecta para más información.")

    # Detalle técnico colapsable
    with st.expander("Ver detalle técnico"):
        st.write(f"**Flow type:** {row['SMI_FLOW_TYPE_ID']}")
        st.write(f"**Logistic type:** {row['SMI_LOGSTIC_TYPE']}")
        st.write(f"**Estado:** {status}")
        st.write(f"**Fecha límite formulario:** {limit_date}")
        st.write(f"**Fecha de activación:** {activation_date}")


# ── UI ──────────────────────────────────────────────────────────────────────

seller_input = st.text_input("Seller ID", placeholder="Ej: 123456789")

if st.button("Consultar", type="primary"):
    if not seller_input.strip():
        st.warning("Ingresá un Seller ID.")
    elif not seller_input.strip().isdigit():
        st.error("El Seller ID debe ser numérico.")
    else:
        seller_id = int(seller_input.strip())
        with st.spinner("Consultando..."):
            try:
                df = get_migration_status(seller_id)
            except Exception as e:
                st.error(f"Error al consultar BigQuery: {e}")
                st.stop()

        if df.empty:
            st.error("❌ **No invitado**")
            st.write(
                "Este seller no aparece en el proceso de migración a Colecta. "
                "No fue invitado en ninguna campaña de upgrade o migración."
            )
        else:
            row = df.iloc[0]
            show_status(row)
