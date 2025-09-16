# business_plan_simulator.py

# ---------- core setup ----------
import streamlit as st
from pathlib import Path

st.set_page_config(
    page_title="Executive Partners – Business Plan Simulator",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ---------- SAFE THEME LOADER (uses styles/ep.css, else built-in fallback) ----------
CSS_PATH = Path(__file__).parent / "styles" / "ep.css"
_BUILTIN_CSS = """
/* (fallback EP skin – trimmed for brevity) */
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');
:root{--ep-bg:#0B0E13;--ep-bg-2:#111827;--ep-text:#fff;--ep-text-dim:rgba(255,255,255,.78);
--ep-text-mute:rgba(255,255,255,.64);--ep-primary:#1D4ED8;--ep-primary-600:#2563EB;--ep-primary-800:#1E40AF;
--ep-border:rgba(255,255,255,.12);--ep-card:rgba(255,255,255,.04);--ep-card-2:rgba(255,255,255,.06);--ep-radius:16px}
html,body,[data-testid="stAppViewContainer"]{font-family:Inter,ui-sans-serif,system-ui,-apple-system,Segoe UI,Roboto,Helvetica,Arial,"Apple Color Emoji","Segoe UI Emoji","Segoe UI Symbol"!important;color:var(--ep-text)}
[data-testid="stAppViewContainer"]{background:
radial-gradient(1200px 420px at 18% -10%, rgba(59,130,246,.16) 0%, rgba(59,130,246,0) 60%),
radial-gradient(1000px 380px at 110% 0%, rgba(16,185,129,.15) 0%, rgba(16,185,129,0) 60%),
var(--ep-bg)}
main.block-container{padding-top:2.25rem;padding-bottom:3.25rem;max-width:1080px}
h1{font-weight:800;letter-spacing:-.01em;line-height:1.06;font-size:clamp(2.25rem,5.4vw,3.5rem);text-align:center;margin:.25rem 0 1.1rem}
h2{font-weight:700;font-size:clamp(1.4rem,2.6vw,2rem);margin:1.4rem 0 .75rem}
h3{font-weight:600;font-size:1.125rem;margin:1rem 0 .5rem}
p,li,label,span{color:var(--ep-text-dim)}
.ep-card{background:linear-gradient(180deg,var(--ep-card),var(--ep-card-2));border:1px solid var(--ep-border);border-radius:var(--ep-radius);padding:16px 18px;box-shadow:0 1px 3px rgba(0,0,0,.25);backdrop-filter:blur(6px)}
.stButton>button{border-radius:12px;border:1px solid var(--ep-border);font-weight:600;padding:.7rem 1rem;transition:all .18s ease;background:color-mix(in srgb, var(--ep-primary) 86%, transparent);color:#fff;box-shadow:0 18px 45px rgba(37,99,235,.28)}
.stButton>button:hover{transform:translateY(-1px);background:#2563EB;box-shadow:0 22px 55px rgba(37,99,235,.36)}
.stButton>button:active{transform:translateY(0);background:#1E40AF}
.dataframe,.stTable table{border-collapse:separate;border-spacing:0;overflow:hidden;border-radius:14px;background:rgba(255,255,255,.03);border:1px solid var(--ep-border)}
.stTable table thead th{background:rgba(255,255,255,.06)!important;color:#fff;font-weight:700}
.stTable table td,.stTable table th{padding:12px 14px!important;border-bottom:1px solid rgba(255,255,255,.06)!important}
.stTable table tr:last-child td{border-bottom:0!important}
[data-testid="stMetric"]{background:linear-gradient(180deg,var(--ep-card),var(--ep-card-2));border:1px solid var(--ep-border);border-radius:14px;padding:14px 16px}
[data-testid="stMetricValue"]{color:#fff!important;font-weight:800;letter-spacing:-.01em;font-size:1.35rem}
a{color:#fff;text-decoration:underline;text-underline-offset:3px}
"""
try:
    css = CSS_PATH.read_text(encoding="utf-8")
    st.markdown(f"<style>{css}</style>", unsafe_allow_html=True)
except Exception:
    st.markdown(f"<style>{_BUILTIN_CSS}</style>", unsafe_allow_html=True)

# ---------- warnings / env ----------
import warnings
try:
    from urllib3.exceptions import NotOpenSSLWarning
    warnings.filterwarnings("ignore", category=NotOpenSSLWarning)
except Exception:
    pass

import os as _os
_os.environ.pop("GOOGLE_APPLICATION_CREDENTIALS_JSON", None)
_os.environ.pop("GOOGLE_APPLICATION_CREDENTIALS", None)

# ---------- std imports ----------
import os
import json
from datetime import datetime
import pandas as pd

# ---------- 3rd party ----------
try:
    import gspread
except Exception:
    # keep UI running; show nothing noisy to end users
    gspread = None

# ================== CONFIG ==================
SHEET_ID = "1A__yEhD_0LYQwBF45wTSbWqdkRe0HAdnnBSj70qgpic"
WORKSHEET_NAME = "BP_Entries"
HEADER_ORDER = [
    "Timestamp","Candidate Name","Candidate Email","Current Role","Candidate Location",
    "Current Employer","Current Market","Currency","Base Salary","Last Bonus",
    "Current Number of Clients","Current AUM (M CHF)",
    "NNM Year 1 (M CHF)","NNM Year 2 (M CHF)","NNM Year 3 (M CHF)",
    "Revenue Year 1 (CHF)","Revenue Year 2 (CHF)","Revenue Year 3 (CHF)",
    "Total Revenue 3Y (CHF)","Profit Margin (%)","Total Profit 3Y (CHF)",
    "Score","AI Evaluation Notes"
]

SA_EMAIL = None
SA_SOURCE = ""

from pathlib import Path as _Path
def _service_account_path() -> _Path:
    return _Path(__file__).parent / "service_account.json"

def _read_sa_email_from_file(p: _Path) -> str:
    try:
        info = json.loads(p.read_text(encoding="utf-8"))
        return info.get("client_email", "")
    except Exception:
        return ""

def _make_highlighter(df_len: int):
    def _highlight(row):
        return [
            "background-color: rgba(37,99,235,.2); font-weight: 700;"
            if (row.name == df_len - 1) else ""
            for _ in row
        ]
    return _highlight

# ---------- small helpers (needed in multiple sections) ----------
def _email_valid(e: str) -> bool:
    return isinstance(e, str) and "@" in e and "." in e.split("@")[-1]

# ================== SHEETS (robust) ==================
def connect_sheet():
    """Returns: (worksheet or None, human_message). Never raises."""
    global SA_EMAIL, SA_SOURCE
    if gspread is None:
        return None, "gspread not available."

    try:
        sa_path = _service_account_path()
        if not sa_path.exists():
            return None, (
                "⚠️ service_account.json not found next to this script.\n"
                f"Place the file at: {sa_path}"
            )

        SA_SOURCE = f"local-file:{sa_path}"
        SA_EMAIL = _read_sa_email_from_file(sa_path)

        gc = gspread.service_account(filename=str(sa_path))

        try:
            sh = gc.open_by_key(SHEET_ID)
        except Exception as e:
            msg = str(e)
            if "PERMISSION_DENIED" in msg or "403" in msg:
                hint = (f"Permission denied. Share the Google Sheet with "
                        f"{SA_EMAIL or '[service account email]'} as Editor.")
                return None, f"⚠️ Could not connect to Google Sheet: {hint}"
            if "NOT_FOUND" in msg or "404" in msg:
                return None, "⚠️ Could not connect: Sheet not found. Check SHEET_ID."
            return None, f"⚠️ Google API error while opening sheet: {e}"

        try:
            ws = sh.worksheet(WORKSHEET_NAME)
        except gspread.exceptions.WorksheetNotFound:
            ws = sh.add_worksheet(title=WORKSHEET_NAME, rows=2000, cols=50)

        headers = ws.row_values(1)
        if headers != HEADER_ORDER:
            ws.update("A1", [HEADER_ORDER])

        return ws, "✅ Connected to Google Sheet"
    except Exception as e:
        return None, f"⚠️ Could not connect to Google Sheet: {e}"

def append_in_header_order(ws, data_dict: dict):
    headers = ws.row_values(1) or HEADER_ORDER
    row = [data_dict.get(h, "") for h in headers]
    ws.append_row(row, value_input_option="USER_ENTERED")

def clean_trailing_columns(ws, first_bad_letter="X"):
    ws.batch_clear([f"{first_bad_letter}2:ZZ"])
    ws.resize(cols=len(HEADER_ORDER))

# ================== MODE (Admin vs Candidate) ==================
try:
    qp = st.query_params  # new API
except Exception:
    qp = st.experimental_get_query_params()  # fallback

def _truthy(x) -> bool:
    if x is None: return False
    s = str(x).strip("[]'\" ").lower()
    return s in ("1","true","yes","on")

ADMIN_DEFAULT = _truthy(qp.get("admin"))
ADMIN_MODE = st.sidebar.checkbox("🔑 Admin Mode", value=ADMIN_DEFAULT)

# ================== HERO ==================
st.markdown("# 📊 Business Plan Simulator — vNOW (business_plan_simulator.py)")
st.markdown(
    '<p class="ep-sub" style="text-align:center;max-width:820px;margin:0 auto">'
    "Confidential, high-contrast planning for RM & PB hires — aligned with the Executive Partners site."
    "</p>",
    unsafe_allow_html=True,
)

worksheet, sheet_status = connect_sheet()
if ADMIN_MODE and sheet_status:
    with st.expander("🔎 Connection diagnostics", expanded=False):
        st.caption(sheet_status)
        if SA_SOURCE: st.caption(f"Cred source: {SA_SOURCE}")
        if SA_EMAIL: st.caption(f"Service account email: {SA_EMAIL}")

st.info("*Fields marked with an asterisk (*) are mandatory and handled confidentially.")

# ================== MAIN UI (wrapped to avoid crashes) ==================
try:
    # ---------- SECTION 1 ----------
    st.markdown("---")
    st.subheader("1️⃣ Basic Candidate Information")
    st.info("Please complete all required fields (*) before proceeding.")

    col1, col2 = st.columns(2)
    with col1:
        candidate_name = st.text_input("Candidate Name")
        candidate_email = st.text_input("Candidate Email *", key="candidate_email", placeholder="name@example.com")
        # Inline hint to make the dependency on Section 6 obvious
        email_val = st.session_state.get("candidate_email", "").strip()
        if not _email_valid(email_val):
            st.markdown('<div style="color:#fca5a5; font-size:0.9rem">↳ Required to unlock the preview & download in <strong>Section 6</strong>.</div>', unsafe_allow_html=True)

        years_experience = st.number_input("Years of Experience *", min_value=0, step=1)
        inherited_book = st.slider("Inherited Book (% of total AUM) *", 0, 100, 0, 1)
        current_role = st.selectbox(
            "Current Role *",
            [
                "Relationship Manager","Senior Relationship Manager","Assistant Relationship Manager",
                "Investment Advisor","Managing Director","Director","Team Head","Market Head","Other",
            ],
        )
        candidate_location = st.selectbox(
            "Candidate Location *",
            [
                "— Select —","Zurich","Geneva","Lausanne","Basel","Luzern",
                "Dubai","London","Hong Kong","Singapore","New York","Miami","Madrid","Lisbon","Sao Paulo",
            ],
        )
        if candidate_location == "— Select —":
            st.markdown('<div style="color:#fca5a5; font-size:0.9rem">↳ Choose a location to unlock the preview & download in <strong>Section 6</strong>.</div>', unsafe_allow_html=True)

    with col2:
        current_employer = st.text_input("Current Employer *")
        current_market = st.selectbox(
            "Current Market *",
            [
                "CH Onshore","UK","Portugal","Spain","Germany","MEA","LATAM",
                "CIS","CEE","France","Benelux","Asia","Argentina","Brazil","Conosur","NRI","India","US","China",
            ],
        )
        currency = st.selectbox("Currency *", ["CHF","USD","EUR","AED","SGD","HKD"])
        base_salary = st.number_input(f"Current Base Salary ({currency}) *", min_value=0, step=1000)
        last_bonus = st.number_input(f"Last Bonus ({currency}) *", min_value=0, step=1000)
        current_number_clients = st.number_input("Current Number of Clients *", min_value=0)
        current_assets = st.number_input("Current Assets Under Management (in million CHF) *", min_value=0.0, step=0.1)

    # ---------- SECTION 2 ----------
    st.markdown("---")
    st.subheader("2️⃣ Net New Money Projection over 3 years")
    st.info("Please complete all fields in this section for accurate projections.")
    c1, c2, c3 = st.columns(3)
    with c1:
        nnm_y1 = st.number_input("NNM Year 1 (in M CHF)", min_value=0.0, step=0.1)
    with c2:
        nnm_y2 = st.number_input("NNM Year 2 (in M CHF)", min_value=0.0, step=0.1)
    with c3:
        nnm_y3 = st.number_input("NNM Year 3 (in M CHF)", min_value=0.0, step=0.1)
    d1, d2, d3 = st.columns(3)
    with d1:
        proj_clients_y1 = st.number_input("Projected Clients Year 1", min_value=0)
    with d2:
        proj_clients_y2 = st.number_input("Projected Clients Year 2", min_value=0)
    with d3:
        proj_clients_y3 = st.number_input("Projected Clients Year 3", min_value=0)

    # ---------- SECTION 3 ----------
    st.markdown("---")
    st.subheader("3️⃣ Enhanced NNA / Prospects Table")
    st.info("Add prospects with the fields below. Use ✏️ Edit to modify a row, or 🗑 Delete to remove it.")

    if "prospects_list" not in st.session_state:
        st.session_state.prospects_list = []
    if "edit_index" not in st.session_state:
        st.session_state.edit_index = -1

    for key, default in [
        ("p_name", ""),
        ("p_source", "Self Acquired"),
        ("p_wealth", 0.0),
        ("p_best", 0.0),
        ("p_worst", 0.0),
    ]:
        if key not in st.session_state:
            st.session_state[key] = default

    with st.expander("📥 Import prospects from CSV (Name, Source, Wealth (M), Best NNM (M), Worst NNM (M))"):
        import pandas as _pd
        up = st.file_uploader("Upload CSV", type=["csv"])
        if up is not None:
            try:
                df_up = _pd.read_csv(up)
                df_up = df_up.rename(columns=lambda x: x.strip())
                needed = ["Name","Source","Wealth (M)","Best NNM (M)","Worst NNM (M)"]
                if not all(c in df_up.columns for c in needed):
                    st.error("CSV missing one of the required columns.")
                else:
                    for c in ["Wealth (M)","Best NNM (M)","Worst NNM (M)"]:
                        df_up[c] = _pd.to_numeric(df_up[c], errors="coerce").fillna(0.0)
                    st.session_state.prospects_list += df_up[needed].to_dict(orient="records")
                    st.success(f"Imported {len(df_up)} prospects.")
            except Exception as e:
                st.exception(e)

    f1, f2, f3, f4, f5 = st.columns([2,2,2,2,2])
    with f1:
        st.session_state.p_name = (
            st.text_input("Name", value=st.session_state.p_name, key="p_name_input")
            or st.session_state.p_name
        )
        st.session_state.p_name = st.session_state.p_name_input
    with f2:
        options = ["Self Acquired","Inherited","Finder"]
        st.session_state.p_source = st.selectbox(
            "Source",
            options,
            index=options.index(st.session_state.p_source) if st.session_state.p_source in options else 0,
            key="p_source_input"
        )
        st.session_state.p_source = st.session_state.p_source_input
    with f3:
        st.session_state.p_wealth = st.number_input(
            "Wealth (M)", min_value=0.0, step=0.1, value=float(st.session_state.p_wealth), key="p_wealth_input"
        )
    with f4:
        st.session_state.p_best = st.number_input(
            "Best NNM (M)", min_value=0.0, step=0.1, value=float(st.session_state.p_best), key="p_best_input"
        )
    with f5:
        st.session_state.p_worst = st.number_input(
            "Worst NNM (M)", min_value=0.0, step=0.1, value=float(st.session_state.p_worst), key="p_worst_input"
        )

    def _validate_row(name, source, wealth, best, worst):
        errs = []
        if not name or not name.strip():
            errs.append("Name is required.")
        if source not in ["Self Acquired","Inherited","Finder"]:
            errs.append("Source must be Self Acquired / Inherited / Finder.")
        for label, val in [("Wealth (M)", wealth), ("Best NNM (M)", best), ("Worst NNM (M)", worst)]:
            try:
                x = float(val)
                if x < 0:
                    errs.append(f"{label} must be ≥ 0.")
            except Exception:
                errs.append(f"{label} must be a number.")
        return errs

    def _reset_form():
        st.session_state.p_name = ""
        st.session_state.p_source = "Self Acquired"
        st.session_state.p_wealth = 0.0
        st.session_state.p_best = 0.0
        st.session_state.p_worst = 0.0

    c_add, c_update, c_cancel = st.columns([1,1,1])
    add_clicked = c_add.button("➕ Add", disabled=(st.session_state.edit_index != -1), type="primary")
    update_clicked = c_update.button("💾 Update", disabled=(st.session_state.edit_index == -1))
    cancel_clicked = c_cancel.button("✖ Cancel Edit", disabled=(st.session_state.edit_index == -1))

    if add_clicked:
        errs = _validate_row(
            st.session_state.p_name, st.session_state.p_source,
            st.session_state.p_wealth, st.session_state.p_best, st.session_state.p_worst
        )
        if errs:
            st.error("\n".join(f"• {e}" for e in errs))
        else:
            st.session_state.prospects_list.append(
                {
                    "Name": st.session_state.p_name.strip(),
                    "Source": st.session_state.p_source,
                    "Wealth (M)": float(st.session_state.p_wealth),
                    "Best NNM (M)": float(st.session_state.p_best),
                    "Worst NNM (M)": float(st.session_state.p_worst),
                }
            )
            _reset_form()
            st.success("Prospect added.")

    if update_clicked:
        idx = st.session_state.edit_index
        errs = _validate_row(
            st.session_state.p_name, st.session_state.p_source,
            st.session_state.p_wealth, st.session_state.p_best, st.session_state.p_worst
        )
        if errs:
            st.error("\n".join(f"• {e}" for e in errs))
        else:
            st.session_state.prospects_list[idx] = {
                "Name": st.session_state.p_name.strip(),
                "Source": st.session_state.p_source,
                "Wealth (M)": float(st.session_state.p_wealth),
                "Best NNM (M)": float(st.session_state.p_best),
                "Worst NNM (M)": float(st.session_state.p_worst),
            }
            st.session_state.edit_index = -1
            _reset_form()
            st.success("Prospect updated.")

    if cancel_clicked:
        st.session_state.edit_index = -1
        _reset_form()
        st.info("Edit cancelled.")

    df_pros = pd.DataFrame(
        st.session_state.prospects_list,
        columns=["Name","Source","Wealth (M)","Best NNM (M)","Worst NNM (M)"]
    )

    if not df_pros.empty:
        st.write(" ")
        for i, row in df_pros.iterrows():
            colA, colB, colC, colD, colE, colF = st.columns([2,2,2,2,1,1])
            colA.write(row["Name"])
            colB.write(row["Source"])
            colC.write(f"{row['Wealth (M)']:,.1f}")
            colD.write(f"{row['Best NNM (M)']:,.1f} / {row['Worst NNM (M)']:,.1f}")

            if colE.button("✏️ Edit", key=f"edit_{i}"):
                st.session_state.edit_index = i
                st.session_state.p_name = row["Name"]
                st.session_state.p_source = row["Source"] if row["Source"] in ["Self Acquired","Inherited","Finder"] else "Self Acquired"
                st.session_state.p_wealth = float(row["Wealth (M)"] or 0.0)
                st.session_state.p_best = float(row["Best NNM (M)"] or 0.0)
                st.session_state.p_worst = float(row["Worst NNM (M)"] or 0.0)
                st.rerun()

            if colF.button("🗑 Delete", key=f"del_{i}"):
                del st.session_state.prospects_list[i]
                st.rerun()

    cols = ["Name", "Source", "Wealth (M)", "Best NNM (M)", "Worst NNM (M)"]
    if df_pros.empty:
        df_pros = pd.DataFrame(columns=cols).astype({
            "Name": "string","Source": "string",
            "Wealth (M)": "float64","Best NNM (M)": "float64","Worst NNM (M)": "float64",
        })
    else:
        df_pros = df_pros.astype({
            "Name": "string","Source": "string",
            "Wealth (M)": "float64","Best NNM (M)": "float64","Worst NNM (M)": "float64",
        }, errors="ignore")

    total_row = pd.DataFrame(
        [{
            "Name": "TOTAL","Source": "",
            "Wealth (M)": float(df_pros["Wealth (M)"].sum()) if not df_pros.empty else 0.0,
            "Best NNM (M)": float(df_pros["Best NNM (M)"].sum()) if not df_pros.empty else 0.0,
            "Worst NNM (M)": float(df_pros["Worst NNM (M)"].sum()) if not df_pros.empty else 0.0,
        }],
        columns=cols
    ).astype(df_pros.dtypes.to_dict(), errors="ignore")

    import pandas as _pd2
    frames = [df for df in (df_pros, total_row) if not df.empty]
    df_display = _pd2.concat(frames, ignore_index=True) if frames else total_row.copy()

    highlighter = _make_highlighter(len(df_display))
    st.dataframe(df_display.style.apply(highlighter, axis=1), use_container_width=True)

    best_sum = float(df_pros["Best NNM (M)"].sum()) if not df_pros.empty else 0.0
    st.caption(f"Δ Best NNM vs NNM Y1: {best_sum - float((locals().get('nnm_y1') or 0.0)):+.1f} M")

    # ---------- SECTION 4 ----------
    st.markdown("---")
    st.subheader("4️⃣ Revenue, Costs & Net Margin Analysis")
    st.info("Ensure all inputs above are filled before analysis.")

    roa_cols = st.columns(3)
    roa_y1 = roa_cols[0].number_input("ROA % Year 1", min_value=0.0, value=1.0, step=0.1)
    roa_y2 = roa_cols[1].number_input("ROA % Year 2", min_value=0.0, value=1.0, step=0.1)
    roa_y3 = roa_cols[2].number_input("ROA % Year 3", min_value=0.0, value=1.0, step=0.1)

    # (calculations unchanged)
    rev1 = (locals().get('nnm_y1') or 0.0) * roa_y1 / 100 * 1_000_000
    rev2 = (locals().get('nnm_y2') or 0.0) * roa_y2 / 100 * 1_000_000
    rev3 = (locals().get('nnm_y3') or 0.0) * roa_y3 / 100 * 1_000_000
    fixed_cost = (locals().get('base_salary') or 0.0) * 1.25
    nm1 = rev1 - fixed_cost
    nm2 = rev2 - fixed_cost
    nm3 = rev3 - fixed_cost
    gross_total = rev1 + rev2 + rev3
    total_costs = fixed_cost * 3
    nm_total = nm1 + nm2 + nm3

    df_rev = pd.DataFrame(
        {
            "Year": ["Year 1", "Year 2", "Year 3", "Total"],
            "Gross Revenue": [rev1, rev2, rev3, gross_total],
            "Fixed Cost": [fixed_cost, fixed_cost, fixed_cost, total_costs],
            "Net Margin": [nm1, nm2, nm3, nm_total],
        }
    )
    ctable, cchart = st.columns(2)
    with ctable:
        st.table(
            df_rev.set_index("Year").style.format(
                {"Gross Revenue": "{:,.0f}", "Fixed Cost": "{:,.0f}", "Net Margin": "{:,.0f}"}
            )
        )
    with cchart:
        st.bar_chart(df_rev.set_index("Year")[["Gross Revenue", "Net Margin"]])

    # ---------- SECTION 5 (Dual Mode) ----------
    st.markdown("---")
    st.subheader("5️⃣ Candidate Insights & Recruiter Evaluation")

    if ADMIN_MODE:
        seg_col1, seg_col2 = st.columns(2)
        with seg_col1:
            target_segment = st.selectbox("Target Segment (for thresholds)", ["HNWI", "UHNWI"], index=0)
        with seg_col2:
            tolerance_pct = st.slider("NNM vs Prospects tolerance (%)", 0, 50, 10, 1)

        total_nnm_3y = float((locals().get('nnm_y1') or 0.0) + (locals().get('nnm_y2') or 0.0) + (locals().get('nnm_y3') or 0.0))
        avg_roa = float((roa_y1 + roa_y2 + roa_y3) / 3)

        current_market = locals().get('current_market', "CH Onshore")
        current_assets = float(locals().get('current_assets') or 0.0)
        base_salary_val2 = float(locals().get('base_salary') or 0.0)
        last_bonus = float(locals().get('last_bonus') or 0.0)
        years_experience = int(locals().get('years_experience') or 0)
        current_number_clients = int(locals().get('current_number_clients') or 0)

        aum_min = 200.0 if (current_market == "CH Onshore" or target_segment == "HNWI") else 300.0

        score = 0
        reasons_pos, reasons_neg, flags = [], [], []

        if years_experience >= 7:
            score += 2; reasons_pos.append("Experience ≥7 years in market")
        elif years_experience >= 6:
            score += 1; reasons_pos.append("Experience 6 years")
        else:
            reasons_neg.append("Experience <6 years")

        if current_assets >= aum_min:
            if current_market == "CH Onshore" and current_assets >= 250:
                score += 2; reasons_pos.append("AUM meets CH 250M target")
            else:
                score += 2; reasons_pos.append(f"AUM ≥ {aum_min}M")
        else:
            reasons_neg.append(f"AUM shortfall: {aum_min - current_assets:.0f}M")

        if base_salary_val2 > 200_000 and last_bonus > 100_000:
            score += 2; reasons_pos.append("Comp indicates hunter profile")
        elif base_salary_val2 <= 150_000 and last_bonus <= 50_000:
            score -= 1; reasons_neg.append("Low comp indicates inherited/low portability")
        else:
            flags.append("Comp neutral – clarify origin of book")

        if avg_roa >= 1.0:
            score += 2; reasons_pos.append(f"Avg ROA {avg_roa:.2f}% (excellent)")
        elif avg_roa >= 0.8:
            score += 1; reasons_pos.append(f"Avg ROA {avg_roa:.2f}% (acceptable)")
        else:
            reasons_neg.append(f"Avg ROA {avg_roa:.2f}% is low")

        if current_number_clients == 0:
            flags.append("Clients not provided")
        elif current_number_clients > 80:
            reasons_neg.append(f"High client count ({current_number_clients}) – likely lower segment")
        else:
            score += 1; reasons_pos.append("Client load appropriate (≤80)")

        df_pros_check = pd.DataFrame(
            st.session_state.prospects_list,
            columns=["Name","Source","Wealth (M)","Best NNM (M)","Worst NNM (M)"]
        )
        nnm_y1_val = float((locals().get('nnm_y1') or 0.0))
        best_sum = float(df_pros_check["Best NNM (M)"].sum()) if not df_pros_check.empty else 0.0
        tol = max(0.0, tolerance_pct) / 100.0
        if nnm_y1_val == 0.0 and best_sum == 0.0:
            flags.append("Prospects & NNM Y1 both zero")
        elif abs(best_sum - nnm_y1_val) <= tol * max(nnm_y1_val, 1e-9):
            score += 1; reasons_pos.append(f"Prospects Best NNM {best_sum:.1f}M ≈ NNM Y1 {nnm_y1_val:.1f}M")
        else:
            reasons_neg.append(f"Prospects {best_sum:.1f}M vs NNM Y1 {nnm_y1_val:.1f}M (> {int(tolerance_pct)}% dev)")

        if total_nnm_3y >= (100.0 if target_segment == "HNWI" else 200.0):
            score += 2; reasons_pos.append(f"3Y NNM {total_nnm_3y:.1f}M meets target")
        else:
            reasons_neg.append(f"3Y NNM {total_nnm_3y:.1f}M below target")

        verdict = "🟢 Strong Candidate" if score >= 7 else "🟡 Medium Potential" if score >= 4 else "🔴 Weak Candidate"

        st.subheader(f"Traffic Light: {verdict} (score {score}/10)")
        colA, colB, colC = st.columns(3)
        with colA:
            st.markdown("**Positives**")
            for r in reasons_pos or ["—"]:
                st.markdown(f"- ✅ {r}")
        with colB:
            st.markdown("**Risks / Gaps**")
            for r in reasons_neg or ["—"]:
                st.markdown(f"- ❌ {r}")
        with colC:
            st.markdown("**Flags / To Clarify**")
            for r in flags or ["—"]:
                st.markdown(f"- ⚠️ {r}")

        m1, m2, m3, m4 = st.columns(4)
        with m1: st.metric("AUM (M)", f"{current_assets:,.0f}")
        with m2: st.metric("Avg ROA %", f"{avg_roa:.2f}")
        with m3: st.metric("3Y NNM (M)", f"{total_nnm_3y:.1f}")
        with m4: st.metric("Clients", f"{int(current_number_clients)}")

    else:
        total_nnm_3y = float((locals().get('nnm_y1') or 0.0) + (locals().get('nnm_y2') or 0.0) + (locals().get('nnm_y3') or 0.0))
        avg_roa = float((roa_y1 + roa_y2 + roa_y3) / 3)
        current_assets = float(locals().get('current_assets') or 0.0)
        current_number_clients = int(locals().get('current_number_clients') or 0)

        st.info("Neutral insights to help you plan your growth (no recruiter scoring shown).")
        c1, c2, c3, c4 = st.columns(4)
        with c1: st.metric("AUM (M)", f"{current_assets:,.0f}")
        with c2: st.metric("Avg ROA %", f"{avg_roa:.2f}")
        with c3: st.metric("3Y NNM (M)", f"{total_nnm_3y:.1f}")
        with c4: st.metric("Clients", f"{int(current_number_clients)}")

        st.markdown("### 💡 Areas to consider")
        hints = []
        if current_assets < 200:
            hints.append("Grow AUM towards 200M+ to strengthen platform portability.")
        if avg_roa < 0.8:
            hints.append("Improve ROA via higher-margin advisory or deeper DPM penetration.")
        if current_number_clients > 80:
            hints.append("Reduce client load to focus on UHNW wallet share and service depth.")
        if total_nnm_3y < 100:
            hints.append("Aim for ≥100M 3-year NNM trajectory to stand out in top-tier platforms.")
        if not hints:
            hints.append("Your profile looks solid — keep consistency on NNM and advisory penetration.")
        for h in hints:
            st.markdown(f"- {h}")

    # ---------- SECTION 6 ----------
    st.markdown("---")
    st.subheader("6️⃣ Summary & Download")

    # Keep worksheet accessible to the callback
    st.session_state["worksheet"] = worksheet

    # Build final row (same fields as before)
    nnm_y1 = float(locals().get('nnm_y1') or 0.0)
    nnm_y2 = float(locals().get('nnm_y2') or 0.0)
    nnm_y3 = float(locals().get('nnm_y3') or 0.0)
    roa_y1 = float(locals().get('roa_y1') or 0.0)
    roa_y2 = float(locals().get('roa_y2') or 0.0)
    roa_y3 = float(locals().get('roa_y3') or 0.0)
    base_salary_val = float(locals().get('base_salary') or 0.0)

    total_rev_3y = ((nnm_y1 * roa_y1) + (nnm_y2 * roa_y2) + (nnm_y3 * roa_y3)) / 100 * 1_000_000
    profit_margin_pct = (((total_rev_3y - (base_salary_val * 1.25 * 3)) / total_rev_3y) * 100.0) if total_rev_3y > 0 else 0.0
    total_profit_3y = (
        (nnm_y1 * roa_y1 / 100 * 1_000_000) +
        (nnm_y2 * roa_y2 / 100 * 1_000_000) +
        (nnm_y3 * roa_y3 / 100 * 1_000_000)
    ) - (base_salary_val * 1.25 * 3)

    # read email from session state to ensure we capture typed value
    email_value = st.session_state.get("candidate_email", "").strip()

    data_dict = {
        "Timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "Candidate Name": locals().get('candidate_name', ""),
        "Candidate Email": email_value,
        "Current Role": locals().get('current_role', ""),
        "Candidate Location": locals().get('candidate_location', ""),
        "Current Employer": locals().get('current_employer', ""),
        "Current Market": locals().get('current_market', ""),
        "Currency": locals().get('currency', ""),
        "Base Salary": base_salary_val,
        "Last Bonus": float(locals().get('last_bonus') or 0.0),
        "Current Number of Clients": int(locals().get('current_number_clients') or 0),
        "Current AUM (M CHF)": float(locals().get('current_assets') or 0.0),
        "NNM Year 1 (M CHF)": nnm_y1,
        "NNM Year 2 (M CHF)": nnm_y2,
        "NNM Year 3 (M CHF)": nnm_y3,
        "Revenue Year 1 (CHF)": nnm_y1 * roa_y1 / 100 * 1_000_000,
        "Revenue Year 2 (CHF)": nnm_y2 * roa_y2 / 100 * 1_000_000,
        "Revenue Year 3 (CHF)": nnm_y3 * roa_y3 / 100 * 1_000_000,
        "Total Revenue 3Y (CHF)": total_rev_3y,
        "Profit Margin (%)": profit_margin_pct,
        "Total Profit 3Y (CHF)": total_profit_3y,
        "Score": int(locals().get('score') or 0),
        "AI Evaluation Notes": locals().get('verdict') or "",
    }

    # Validate required fields before offering the download
    missing = []
    if not _email_valid(data_dict["Candidate Email"]):
        missing.append("Candidate Email (valid)")
    if (data_dict["Candidate Location"] or "— Select —") == "— Select —":
        missing.append("Candidate Location")

    # Helper: append to Google Sheet (safe)
    def _append_sheet_safe(row: dict):
        ws = st.session_state.get("worksheet")
        if not ws:
            st.session_state["sheet_status_msg"] = "⚠️ Google Sheet connection not available."
            return
        try:
            append_in_header_order(ws, row)
            st.session_state["sheet_status_msg"] = "✅ Saved to Google Sheet"
        except Exception as e:
            st.session_state["sheet_status_msg"] = f"⚠️ Save error: {e}"

    if missing:
        st.warning("To continue, complete **Candidate Email** and **Candidate Location** in **Section 1** above. The preview and the download button will appear here automatically.")
        # Visual affordance: show a disabled download button so users know what to expect
        st.button("⬇️ Download your BP (CSV)", disabled=True, help="Fill in Candidate Email and Candidate Location in Section 1 to enable this.")
    else:
        # Small preview (formatted)
        preview_cols = [
            "Candidate Name","Candidate Email","Current Role","Candidate Location",
            "Current Employer","Current Market","Currency","Base Salary","Last Bonus",
            "Current AUM (M CHF)","NNM Year 1 (M CHF)","NNM Year 2 (M CHF)","NNM Year 3 (M CHF)",
            "Revenue Year 1 (CHF)","Revenue Year 2 (CHF)","Revenue Year 3 (CHF)",
            "Total Revenue 3Y (CHF)","Profit Margin (%)","Total Profit 3Y (CHF)",
            "Score","AI Evaluation Notes"
        ]
        df_prev = pd.DataFrame([{k: data_dict.get(k, "") for k in preview_cols}])
        st.dataframe(
            df_prev.style.format({
                "Base Salary": "{:,.0f}",
                "Last Bonus": "{:,.0f}",
                "Current AUM (M CHF)": "{:,.1f}",
                "NNM Year 1 (M CHF)": "{:,.1f}",
                "NNM Year 2 (M CHF)": "{:,.1f}",
                "NNM Year 3 (M CHF)": "{:,.1f}",
                "Revenue Year 1 (CHF)": "{:,.0f}",
                "Revenue Year 2 (CHF)": "{:,.0f}",
                "Revenue Year 3 (CHF)": "{:,.0f}",
                "Total Revenue 3Y (CHF)": "{:,.0f}",
                "Profit Margin (%)": "{:,.1f}",
                "Total Profit 3Y (CHF)": "{:,.0f}",
            }),
            use_container_width=True
        )

        # Prepare CSV and show a single "Download your BP" button (also auto-saves to Google Sheet)
        csv_bytes = df_prev.to_csv(index=False).encode("utf-8")
        st.session_state["bp_row"] = data_dict  # for completeness

        st.download_button(
            label="⬇️ Download your BP (CSV)",
            data=csv_bytes,
            file_name=f"bp_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
            mime="text/csv",
            on_click=_append_sheet_safe,
            kwargs={"row": data_dict},
            help="Downloads your Business Plan and securely stores a copy with Executive Partners."
        )

        # Status of Google Sheet save (if any)
        if st.session_state.get("sheet_status_msg"):
            st.caption(st.session_state["sheet_status_msg"])

except Exception as e:
    st.error("An unexpected error occurred while building the UI.")
    st.exception(e)