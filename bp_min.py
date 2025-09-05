import streamlit as st

st.set_page_config(page_title="Business Plan Simulator", page_icon="📈", layout="wide")

st.markdown("## 📊 Business Plan Simulator — Minimal UI")
st.caption("If you see this, the simulator UI is loading correctly.")

st.markdown("---")
st.subheader("1️⃣ Basic Candidate Information")

col1, col2 = st.columns(2)
with col1:
    candidate_name = st.text_input("Candidate Name")
    candidate_email = st.text_input("Candidate Email *")
    years_experience = st.number_input("Years of Experience *", min_value=0, step=1)
with col2:
    current_employer = st.text_input("Current Employer *")
    current_market = st.selectbox(
        "Current Market *",
        ["CH Onshore","UK","Portugal","Spain","Germany","MEA","LATAM","CIS","CEE","France","Benelux","Asia"]
    )

st.markdown("---")
st.subheader("2️⃣ Quick calc preview")
nnm_y1 = st.number_input("NNM Year 1 (in M CHF)", min_value=0.0, step=0.1)
roa_y1 = st.number_input("ROA % Year 1", min_value=0.0, value=1.0, step=0.1)
rev1 = nnm_y1 * roa_y1 / 100 * 1_000_000
st.metric("Revenue Year 1 (CHF)", f"{rev1:,.0f}")

if st.button("Pretend save"):
    st.success("✅ UI works. Next step will be Google Sheets.")
