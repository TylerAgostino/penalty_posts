"""Penalty Posts — Navigation entry point.

Defines the multi-page app using st.navigation / st.Page.
All page-specific logic lives under pages/.
"""

import streamlit as st

st.set_page_config(
    page_title="Penalty Posts",
    page_icon="⚖️",
    layout="wide",
)

pg = st.navigation(
    [
        st.Page("pages/Queue.py", title="Queue", icon="📋"),
        st.Page("pages/Completed_Posts.py", title="Completed Posts", icon="✅"),
    ]
)

pg.run()
