"""Albert Heijn product lookup and reviewed purchase imports."""

from datetime import date

import pandas as pd
import streamlit as st

from ah import extract_invoice_text, get_product_page, search_products, suggested_invoice_lines
from auth import require_password
from db import fetch_ah_purchase_items, init_db, insert_ah_purchase_items

require_password()
st.set_page_config(page_title="Albert Heijn", page_icon="🛒", layout="wide")
init_db()

st.title("🛒 Albert Heijn")
st.caption("Public product information and your reviewed purchase history.")

st.subheader("Look up a product")
query = st.text_input("Product name", placeholder="e.g. AH Greek yoghurt")
if st.button("Search Albert Heijn", type="primary") and query:
    try:
        st.session_state.ah_results = search_products(query)
    except Exception as error:
        st.error(f"Albert Heijn search is unavailable right now: {error}")

for product in st.session_state.get("ah_results", []):
    if st.button(product["name"], key=product["url"]):
        try:
            st.session_state.ah_product = get_product_page(product["url"])
        except Exception as error:
            st.error(f"Could not retrieve this product: {error}")

product = st.session_state.get("ah_product")
if product:
    st.markdown(f"**{product['name']}**")
    st.link_button("Open official product page", product["url"])
    if product["nutrition_text"]:
        st.text(product["nutrition_text"])
    else:
        st.info("Open the official product page to see its current nutritional values.")

st.divider()
st.subheader("Import a purchase invoice")
st.caption(
    "Upload an AH invoice PDF, review the suggested product lines, then save them. "
    "Purchases are not automatically logged as meals."
)
uploaded = st.file_uploader("AH invoice PDF", type="pdf")
if uploaded and st.button("Read invoice"):
    try:
        text = extract_invoice_text(uploaded.getvalue())
        suggestions = suggested_invoice_lines(text)
        st.session_state.ah_invoice_lines = "\n".join(suggestions)
        st.session_state.ah_invoice_name = uploaded.name
        if not suggestions:
            st.warning("No product lines were detected. Add them manually below.")
    except Exception as error:
        st.error(f"Could not read this PDF: {error}")

review_lines = st.text_area(
    "One purchased product per line (review and correct before saving)",
    value=st.session_state.get("ah_invoice_lines", ""),
    height=220,
)
purchase_date = st.date_input("Purchase date", value=date.today())
if st.button("Save reviewed purchases"):
    names = [line.strip() for line in review_lines.splitlines() if line.strip()]
    if not names:
        st.warning("Add at least one product line first.")
    else:
        insert_ah_purchase_items(
            [
                {"product_name": name, "quantity": 1, "purchased_on": purchase_date.isoformat()}
                for name in names
            ],
            st.session_state.get("ah_invoice_name"),
        )
        st.success(f"Saved {len(names)} purchase item(s).")

purchases = fetch_ah_purchase_items()
if purchases:
    st.subheader("Imported purchases")
    st.dataframe(pd.DataFrame(purchases), hide_index=True, use_container_width=True)
