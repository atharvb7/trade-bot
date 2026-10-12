import pandas as pd
import streamlit as st
from sqlalchemy import create_engine

from bot.config import CONFIG_DIR, ROOT, load_config

st.title("Logs and settings")
url = load_config().app.database_url
url = f"sqlite:///{ROOT / url.removeprefix('sqlite:///')}" if url.startswith("sqlite:///") else url
eng = create_engine(url)
st.subheader("Recent events and errors")
try:
    ev = pd.read_sql("select * from events order by ts desc limit 200", eng)
    lvl = st.multiselect("Level", sorted(ev["level"].unique()) if len(ev) else [])
    st.dataframe(ev[ev["level"].isin(lvl)] if lvl else ev, use_container_width=True)
except Exception:
    st.info("No events table yet.")
st.subheader("Current config (read-only; secrets live in .env and are never shown)")
for f in sorted(CONFIG_DIR.glob("*.yaml")):
    with st.expander(f.name):
        st.code(f.read_text(), language="yaml")
st.subheader("Config change history")
try:
    st.dataframe(
        pd.read_sql("select ts, file, content_hash from config_changes order by ts desc", eng),
        use_container_width=True,
    )
except Exception:
    st.info("No config changes recorded yet.")
