"""Embed locally generated review HTML across supported Streamlit versions."""
def render_html(html, *, height, scrolling=False):
    import streamlit as st
    if hasattr(st, "iframe"):
        return st.iframe(html, height=height)
    from streamlit.components.v1 import html as legacy_html
    return legacy_html(html, height=height, scrolling=scrolling)
