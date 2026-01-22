import streamlit as st
from constants import DEFAULT_CATEGORIES

def init_session_state():
    if "categories" not in st.session_state:
        st.session_state.categories = DEFAULT_CATEGORIES.copy()
    if "search_query" not in st.session_state:
        st.session_state.search_query = ""