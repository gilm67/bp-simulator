# business_plan_simulator_full.py

# --- Kill noisy LibreSSL warning (harmless) ---
import warnings
try:
    from urllib3.exceptions import NotOpenSSLWarning  # may not exist on older urllib3
    warnings.filterwarnings("ignore", category=NotOpenSSLWarning)
except Exception:
    pass

# --- HARD-DISABLE any env-based Google creds (prevent base64/env noise) ---
import os as _os
_os.environ.pop("GOOGLE_APPLICATION_CREDENTIALS_JSON", None)
_os.environ.pop("GOOGLE_APPLICATION_CREDENTIALS", None)

# --- Standard imports ---
import os
import json
from datetime import datetime
from pathlib import Path
from io import BytesIO
import hashlib  # de-dupe signature

import gspread
import pandas as pd
import streamlit as st

# --- PDF/reportlab imports ---
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import cm
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, KeepTogether
)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle

# ================== CONFIG ==================
# Keep these in Python (NOT in Secrets)
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

# Brand / watermark
COMPANY_NAME = os.getenv("BP_COMPANY_NAME", "Executive Partners")

# Auto-save behavior: "on_pdf" (default), "always", or "off"
AUTO_SAVE_MODE = os.getenv("BP_AUTO_SAVE_MODE", "on_pdf").lower()

SA_EMAIL = None
SA_SOURCE = ""  # set when local file or secrets are used

# ---------- helpers ----------
def _service_account_path() -> Path:
    here = Path(__file__).parent
    return here / "service_account.json"

def _read_sa_email_from_file(p: Path) -> str:
    try:
        info = json.loads(p.read_text(encoding="utf-8"))
        return info.get("client_email", "")
    except Exception:
        return ""

def _make_highlighter(df_len: int):
    def _highlight(row):
        return [
            "background-color: #E9F5FF; font-weight: bold;"
            if (row.name == df_len - 1) else ""
            for _ in row
        ]
    return _highlight

# ----- stable signature for idempotent saves -----
def _canonicalize_number(x):
    try:
        return float(f"{float(x):.6f}")  # round to avoid float jitter
    except Exception:
        return x

def _make_signature(candidate_dict: dict) -> str:
    fields = [
        "Candidate Name","Candidate Email","Current Role","Candidate Location",
        "Current Employer","Current Market","Currency","Base Salary","Last Bonus",
        "Current Number of Clients","Current AUM (M CHF)",
        "NNM Year 1 (M CHF)","NNM Year 2 (M CHF)","NNM Year 3 (M CHF)",
        "Revenue Year 1 (CHF)","Revenue Year 2 (CHF)","Revenue Year 3 (CHF)",
        "Total Revenue 3Y (CHF)","Profit Margin (%)","Total Profit 3Y (CHF)",
    ]
    payload = {k: _canonicalize_number(candidate_dict.get(k, "")) for k in fields}
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()

# ---------- secrets diagnostics ----------
def _secrets_presence():
    """Return a tuple (has_gcp_dict, has_google_json, client_email_or_empty)."""
    has_gcp, has_json, email = False, False, ""
    try:
        if "gcp_service_account" in st.secrets:
            has_gcp = True
            val = st.secrets["gcp_service_account"]
            d = val if isinstance(val, dict) else json.loads(str(val))
            email = d.get("client_email", "") or email
        if "GOOGLE_SERVICE_ACCOUNT_JSON" in st.secrets:
            has_json = True
            try:
                d2 = json.loads(str(st.secrets["GOOGLE_SERVICE_ACCOUNT_JSON"]))
                email = d2.get("client_email", "") or email
            except Exception:
                # If it's not valid JSON, we'll catch it during connect
                pass
    except Exception:
        pass
    return has_gcp, has_json, email

# ================== SHEETS (SECRETS FIRST, THEN LOCAL FILE) ==================
def connect_sheet():
    """
    Returns: (worksheet or None, human_message)
    Priority for credentials:
      1) Streamlit Secrets: 
         - TOML section [gcp_service_account] (dict or JSON-stringified dict)
         - OR key GOOGLE_SERVICE_ACCOUNT_JSON (full JSON string)
      2) Local ./service_account.json (for local dev)
    """
    global SA_EMAIL, SA_SOURCE
    try:
        gc = None
        creds_dict = None

        # --- 1) Try Streamlit Cloud Secrets (preferred on Streamlit Community Cloud) ---
        try:
            if "gcp_service_account" in st.secrets:
                val = st.secrets["gcp_service_account"]
                creds_dict = val if isinstance(val, dict) else json.loads(str(val))
            elif "GOOGLE_SERVICE_ACCOUNT_JSON" in st.secrets:
                creds_dict = json.loads(str(st.secrets["GOOGLE_SERVICE_ACCOUNT_JSON"]))
        except Exception as e:
            creds_dict = None

        if creds_dict:
            try:
                SA_EMAIL = creds_dict.get("client_email", "")
                SA_SOURCE = "streamlit-secrets"
                gc = gspread.service_account_from_dict(creds_dict)
            except Exception as e:
                return None, f"⚠️ Could not use Streamlit Secrets for Google auth: {e}"

        # --- 2) Fallback to local file (useful for local development) ---
        if gc is None:
            sa_path = _service_account_path()
            if not sa_path.exists():
                has_gcp, has_json, email = _secrets_presence()
                hint_bits = []
                if not (has_gcp or has_json):
                    hint_bits.append("No [gcp_service_account] or GOOGLE_SERVICE_ACCOUNT_JSON found in Secrets.")
                else:
                    hint_bits.append("Secrets are present but could not be parsed/used.")
                return None, (
                    "⚠️ No Google credentials found. "
                    + " ".join(hint_bits) + " "
                    "Add your service account JSON to **Streamlit Secrets** (preferred on cloud), "
                    "or place service_account.json next to this script for local dev."
                )
            SA_SOURCE = f"local-file:{sa_path}"
            SA_EMAIL = _read_sa_email_from_file(sa_path)
            gc = gspread.service_account(filename=str(sa_path))

        # --- Open target spreadsheet ---
        try:
            sh = gc.open_by_key(SHEET_ID)
        except gspread.exceptions.APIError as e:
            msg = str(e)
            if "PERMISSION_DENIED" in msg or "403" in msg:
                hint = (
                    f"Permission denied. Share the Google Sheet with "
                    f"{SA_EMAIL or '[your service account email]'} as an **Editor**."
                )
                return None, f"⚠️ Could not connect to Google Sheet: {hint}"
            if "NOT_FOUND" in msg or "404" in msg:
                return None, "⚠️ Could not connect: Sheet not found. Check SHEET_ID."
            return None, f"⚠️ Google API error while opening sheet: {e}"

        # --- Get/create worksheet & ensure header row ---
        try:
            ws = sh.worksheet(WORKSHEET_NAME)
        except gspread.exceptions.WorksheetNotFound:
            ws = sh.add_worksheet(title=WORKSHEET_NAME, rows=2000, cols=50)

        headers = ws.row_values(1)
        if headers != HEADER_ORDER:
            ws.update("A1", [HEADER_ORDER])

        src_label = "✅ Connected to Google Sheet"
        if SA_SOURCE:
            src_label += f" (auth: {SA_SOURCE})"
        return ws, src_label

    except gspread.exceptions.APIError as e:
        return None, f"⚠️ Google API error: {e}"
    except Exception as e:
        return None, f"⚠️ Could not connect to Google Sheet: {e}"

def append_in_header_order(ws, data_dict: dict):
    headers = ws.row_values(1) or HEADER_ORDER
    row = [data_dict.get(h, "") for h in headers]
    ws.append_row(row, value_input_option="USER_ENTERED")

def clean_trailing_columns(ws, first_bad_letter="X"):
    ws.batch_clear([f"{first_bad_letter}2:ZZ"])
    ws.resize(cols=len(HEADER_ORDER))

# ================== Recruiter visibility control ==================
RECRUITER_PIN = os.getenv("BP_RECRUITER_PIN", "2468")

def _is_recruiter() -> bool:
    """Enable recruiter mode via URL or PIN login (uses st.query_params)."""
    if st.session_state.get("_recruiter_ok", False):
        return True

    qp = st.query_params  # replaces deprecated experimental API

    def _first(key: str) -> str:
        v = qp.get(key)
        if v is None:
            return ""
        return v[0] if isinstance(v, (list, tuple)) else v

    mode = (_first("mode") or "").lower()
    rflag = _first("r")
    pin = _first("pin")

    if ((mode == "recruiter") or (rflag == "1")) and pin == RECRUITER_PIN:
        st.session_state["_recruiter_ok"] = True
        return True
    return False

# ================== Recruiter visibility control ==================
RECRUITER_PIN = os.getenv("BP_RECRUITER_PIN", "2468")

def _is_recruiter() -> bool:
    ...
    return False

def _recruiter_login_ui():
    """Simple recruiter login UI (no nested expander)."""
    st.markdown("#### 🔒 Recruiter login")
    pin_try = st.text_input("Enter PIN", type="password", key="recruiter_pin_input")
    if st.button("Enable recruiter mode", key="recruiter_enable_btn"):
        if pin_try == RECRUITER_PIN:
            st.session_state["_recruiter_ok"] = True
            st.success("Recruiter mode enabled for this session.")
        else:
            st.error("Wrong PIN.")

def _exit_recruiter_mode():
    # Clear session flag
    st.session_state.pop("_recruiter_ok", None)
    # Clear any recruiter params from URL (new API first, fall back to legacy)
    try:
        st.query_params.clear()
    except Exception:
        try:
            st.experimental_set_query_params()  # legacy way to clear
        except Exception:
            pass
    st.rerun()

# ================== PDF GENERATION ==================
def _fmt_money(v):
    try:
        return f"{float(v):,.0f}"
    except Exception:
        return str(v or "")

def _fmt_float1(v):
    try:
        return f"{float(v):,.1f}"
    except Exception:
        return str(v or "")

def build_pdf(candidate, prospects_df, revenue_df) -> BytesIO:
    """Build a professional PDF including Sections 1–4 with a watermark."""
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4, leftMargin=2*cm, rightMargin=2*cm, topMargin=2.2*cm, bottomMargin=2*cm
    )

    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="TitleXL", fontSize=20, leading=24, spaceAfter=14))
    styles.add(ParagraphStyle(name="H2", fontSize=14, leading=18, spaceBefore=10, spaceAfter=6))
    styles.add(ParagraphStyle(name="Label", fontSize=9, textColor=colors.HexColor("#555555")))
    styles.add(ParagraphStyle(name="Value", fontSize=11, spaceAfter=6))
    styles.add(ParagraphStyle(name="Small", fontSize=8, textColor=colors.HexColor("#666666")))

    def _decorate(canvas, doc):
        canvas.saveState()
        footer = f"{COMPANY_NAME} • Confidential • Generated {datetime.now().strftime('%Y-%m-%d %H:%M')}"
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(colors.HexColor("#666666"))
        canvas.drawRightString(A4[0]-2*cm, 1.2*cm, footer)
        canvas.translate(A4[0]/2, A4[1]/2)
        canvas.rotate(45)
        canvas.setFont("Helvetica-Bold", 48)
        canvas.setFillColor(colors.Color(0.8, 0.85, 0.95, alpha=0.12))
        canvas.drawCentredString(0, 0, COMPANY_NAME.upper())
        canvas.restoreState()

    story = []
    story.append(Paragraph("Business Plan Projection", styles["TitleXL"]))
    story.append(Paragraph(COMPANY_NAME, styles["H2"]))
    story.append(Spacer(1, 6))

    grid_left = [
        ["Candidate Name", candidate.get("Candidate Name", "")],
        ["Email", candidate.get("Candidate Email", "")],
        ["Current Role", candidate.get("Current Role", "")],
        ["Location", candidate.get("Candidate Location", "")],
    ]
    grid_right = [
        ["Employer", candidate.get("Current Employer", "")],
        ["Market", candidate.get("Current Market", "")],
        [f"Base Salary ({candidate.get('Currency','')})", _fmt_money(candidate.get("Base Salary", ""))],
        [f"Last Bonus ({candidate.get('Currency','')})", _fmt_money(candidate.get("Last Bonus", ""))],
    ]

    def _styled_table(data, col_widths=None):
        t = Table(data, colWidths=col_widths)
        t.setStyle(TableStyle([
            ("FONT", (0,0), (-1,-1), "Helvetica", 9),
            ("BACKGROUND", (0,0), (-1,0), colors.HexColor("#F5F7FA")),
            ("TEXTCOLOR", (0,0), (-1,0), colors.HexColor("#0F172A")),
            ("GRID", (0,0), (-1,-1), 0.25, colors.HexColor("#D1D5DB")),
            ("ROWBACKGROUNDS", (0,1), (-1,-1), [colors.white, colors.HexColor("#FBFCFF")]),
            ("VALIGN", (0,0), (-1,-1), "MIDDLE"),
            ("LEFTPADDING", (0,0), (-1,-1), 6),
            ("RIGHTPADDING", (0,0), (-1,-1), 6),
        ]))
        return t

    story.append(_styled_table([["Section 1 — Candidate Summary",""]] + grid_left, [7*cm, 7*cm]))
    story.append(Spacer(1, 6))
    story.append(_styled_table([["Compensation & Market",""]] + grid_right, [7*cm, 7*cm]))
    story.append(Spacer(1, 12))

    s2_rows = [
        ["NNM Year 1 (M CHF)", _fmt_float1(candidate.get("NNM Year 1 (M CHF)", 0))],
        ["NNM Year 2 (M CHF)", _fmt_float1(candidate.get("NNM Year 2 (M CHF)", 0))],
        ["NNM Year 3 (M CHF)", _fmt_float1(candidate.get("NNM Year 3 (M CHF)", 0))],
        ["Current AUM (M CHF)", _fmt_float1(candidate.get("Current AUM (M CHF)", 0))],
        ["Current # Clients", str(candidate.get("Current Number of Clients", 0))],
    ]
    story.append(_styled_table([["Section 2 — NNM Projection",""]] + s2_rows, [7*cm, 7*cm]))
    story.append(Spacer(1, 12))

    story.append(Paragraph("Section 3 — Prospects (NNA)", styles["H2"]))
    if prospects_df is None or prospects_df.empty:
        story.append(Paragraph("No prospects captured.", styles["Small"]))
    else:
        pros_table = [["Name","Source","Wealth (M)","Best NNM (M)","Worst NNM (M)"]]
        for _, r in prospects_df.iterrows():
            pros_table.append([
                str(r.get("Name","")),
                str(r.get("Source","")),
                _fmt_float1(r.get("Wealth (M)",0)),
                _fmt_float1(r.get("Best NNM (M)",0)),
                _fmt_float1(r.get("Worst NNM (M)",0)),
            ])
        if "Name" in prospects_df.columns and (prospects_df["Name"].astype(str).str.upper() == "TOTAL").any():
            total_row = prospects_df.iloc[-1]
            pros_table.append([
                "TOTAL","",
                _fmt_float1(total_row.get("Wealth (M)",0)),
                _fmt_float1(total_row.get("Best NNM (M)",0)),
                _fmt_float1(total_row.get("Worst NNM (M)",0)),
            ])
        t = _styled_table(pros_table, [5*cm, 2.6*cm, 3*cm, 3*cm, 3*cm])
        story.append(KeepTogether([t]))
    story.append(Spacer(1, 12))

    story.append(Paragraph("Section 4 — Revenue, Costs & Net Margin", styles["H2"]))
    if revenue_df is None or revenue_df.empty:
        story.append(Paragraph("No revenue data.", styles["Small"]))
    else:
        tbl = [["Year","Gross Revenue (CHF)","Fixed Cost (CHF)","Net Margin (CHF)"]]
        for _, r in revenue_df.iterrows():
            tbl.append([
                str(r["Year"]),
                _fmt_money(r["Gross Revenue"]),
                _fmt_money(r["Fixed Cost"]),
                _fmt_money(r["Net Margin"]),
            ])
        t_rev = _styled_table(tbl, [3*cm, 4.5*cm, 4.5*cm, 4.5*cm])
        story.append(t_rev)

    doc.build(story, onFirstPage=_decorate, onLaterPages=_decorate)
    buffer.seek(0)
    return buffer

# ================== APP ==================
st.set_page_config(page_title="Business Plan Simulator", page_icon="📈", layout="wide")

# === Build/version tag ===
build_time = datetime.now().strftime("%Y-%m-%d %Hh%M")
st.caption(f"🔄 Build: {build_time}")

# === Brand & CSS ===
BRAND = {
    "company": "Executive Partners",
    "primary": "#0EA5E9",
    "dark": "#0F172A",
    "muted": "#64748B",
    "bg": "#F8FAFC",
    "accent": "#22C55E"
}
st.markdown(
    f"""
    <style>
      .stApp {{
        background: linear-gradient(180deg, {BRAND["bg"]} 0%, #FFFFFF 100%);
        color: {BRAND["dark"]};
        font-family: Inter, ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, Helvetica, Arial, "Apple Color Emoji","Segoe UI Emoji";
      }}
      h1, h2, h3 {{ letter-spacing: .2px; }}
      h1 {{ font-weight: 800; }}
      h2 {{ font-weight: 700; }}
      .stButton>button, .stDownloadButton>button {{
        border-radius: 12px !important;
        padding: .8rem 1rem !important;
        border: 1px solid rgba(15,23,42,.08);
        box-shadow: 0 1px 2px rgba(15,23,42,.06);
        transition: transform .05s ease-in-out;
      }}
      .stButton>button:hover, .stDownloadButton>button:hover {{ transform: translateY(-1px); }}
      .ep-card {{
        background: #FFFFFF;
        border: 1px solid rgba(15,23,42,.06);
        border-radius: 16px;
        padding: 18px 18px 8px 18px;
        box-shadow: 0 1px 3px rgba(15,23,42,.06);
        margin-bottom: 16px;
      }}
      .ep-chip {{
        display:inline-flex; align-items:center; gap:.5rem;
        background: rgba(14,165,233,.10);
        color:{BRAND["primary"]}; font-weight:600;
        border-radius:999px; padding:.25rem .75rem; font-size:.9rem;
      }}
      .ep-note {{ color:{BRAND["muted"]}; font-size:.9rem; }}
      .ep-hero {{
        background: radial-gradient(1200px 400px at 20% -20%, rgba(14,165,233,.18) 0%, transparent 60%),
                    radial-gradient(900px 400px at 120% 0%, rgba(34,197,94,.18) 0%, transparent 60%);
        border: 1px solid rgba(15,23,42,.06);
        border-radius: 20px;
        padding: 22px 24px;
        box-shadow: 0 1px 3px rgba(15,23,42,.06);
        margin-top: .25rem;
        margin-bottom: .5rem;
      }}
    </style>
    """,
    unsafe_allow_html=True
)

# --- Branded Hero Header ---
st.markdown(
    f"""
    <div class="ep-hero">
      <div style="display:flex; align-items:center; gap:.9rem;">
        <div style="font-size:2rem;">📈</div>
        <div>
          <div style="font-size:1rem; color:{BRAND["muted"]}; font-weight:600; letter-spacing:.5px;">
            {BRAND["company"]}
          </div>
          <div style="font-size:1.9rem; font-weight:800; color:{BRAND["dark"]}; line-height:1.1;">
            Business Plan Simulator
          </div>
          <div class="ep-note">Private & Confidential</div>
        </div>
      </div>
    </div>
    """,
    unsafe_allow_html=True
)
# Show a small recruiter login box on the page
with st.expander("🔒 Recruiter login", expanded=False):
    _recruiter_login_ui()

# Diagnostics tucked away
with st.expander("⚙️ Diagnostics (staff)", expanded=False):
    st.caption(f"Running file: {os.path.abspath(__file__)}")
    st.caption(
        "ENV — GAC: "
        f"{'set' if os.getenv('GOOGLE_APPLICATION_CREDENTIALS') else 'unset'} | "
        "GAC_JSON: "
        f"{'set' if os.getenv('GOOGLE_APPLICATION_CREDENTIALS_JSON') else 'unset'}"
    )
    has_gcp, has_json, email_guess = _secrets_presence()
    st.caption(
        "Secrets: "
        + ("[gcp_service_account] ✓ " if has_gcp else "[gcp_service_account] ✗ ")
        + ("GOOGLE_SERVICE_ACCOUNT_JSON ✓ " if has_json else "GOOGLE_SERVICE_ACCOUNT_JSON ✗ ")
        + (f"| client_email: `{email_guess}`" if email_guess else "| client_email: (unknown)")
    )
    

# --- Determine recruiter mode from URL or prior login ---
# First: if the URL has no recruiter params, clear any stale recruiter flag
_no_recruiter_params = all(k not in st.query_params for k in ("mode", "r", "pin"))
if _no_recruiter_params and st.session_state.get("_recruiter_ok"):
    st.session_state.pop("_recruiter_ok", None)

# Now compute the mode (after clearing)
recruiter_mode = _is_recruiter()

if recruiter_mode:
    st.caption("🛡️ Recruiter mode is ON (Section 5 is visible).")
    st.button("🚪 Exit recruiter mode", on_click=_exit_recruiter_mode)
else:
    st.caption("Recruiter mode is OFF. Section 5 hidden until PIN entered.")

# Connect to Google Sheet
worksheet, sheet_status = connect_sheet()
st.info(sheet_status)

with st.expander("🔎 Connection diagnostics", expanded=False):
    st.caption(f"Cred source: {SA_SOURCE or 'unknown'}")
    if SA_EMAIL:
        st.caption(f"Using service account: `{SA_EMAIL}`")
    else:
        st.caption("Service account email not readable from credentials.")
    if worksheet:
        st.success("Worksheet is ready.")
    else:
        st.warning("Worksheet not available yet. You can still use the simulator; saving will be disabled.")

with st.expander("🧹 Maintenance", expanded=False):
    cols_m = st.columns(2)
    with cols_m[0]:
        if worksheet and st.button("Clean extra columns (X → ZZ)"):
            try:
                clean_trailing_columns(worksheet, "X")
                st.success("Cleared columns X:ZZ and resized sheet to A:W.")
            except Exception as e:
                st.error(f"Cleanup failed: {e}")
    with cols_m[1]:
        if st.button("Run connection health check"):
            if worksheet:
                try:
                    _ = worksheet.row_values(1)
                    st.success("✅ Read test OK. Service account can access the sheet.")
                except Exception as e:
                    st.error(f"Read test failed: {e}")
            else:
                st.warning("No worksheet available to test.")

st.info("*Fields marked with an asterisk (*) are mandatory and handled confidentially.")

# ---------- SECTION 1 ----------
st.markdown('<div class="ep-card">', unsafe_allow_html=True)
st.markdown('<span class="ep-chip">1️⃣ Basic Candidate Information</span>', unsafe_allow_html=True)
col1, col2 = st.columns(2)
with col1:
    st.caption("Contact & Role")
    candidate_name = st.text_input("Candidate Name", placeholder="e.g., Jane Smith")
    candidate_email = st.text_input("Candidate Email *", placeholder="name@company.com")
    years_experience = st.number_input("Years of Experience *", min_value=0, step=1, help="Total years in wealth/market")
    inherited_book = st.slider("Inherited Book (% of total AUM) *", 0, 100, 0, 1, help="Share of AUM expected to be inherited")
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
with col2:
    st.caption("Employer & Compensation")
    current_employer = st.text_input("Current Employer *", placeholder="e.g., UBS")
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
st.markdown('</div>', unsafe_allow_html=True)

# ---------- SECTION 2 ----------
st.markdown('<div class="ep-card">', unsafe_allow_html=True)
st.markdown('<span class="ep-chip">2️⃣ Net New Money Projection (3 years)</span>', unsafe_allow_html=True)
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
st.markdown('</div>', unsafe_allow_html=True)

# ---------- SECTION 3 ----------
st.markdown('<div class="ep-card">', unsafe_allow_html=True)
st.markdown('<span class="ep-chip">3️⃣ Prospects & NNA</span>', unsafe_allow_html=True)
st.caption("Add prospects with the fields below. Use **Edit** to modify and **Delete** to remove.")
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

with st.expander("📥 Import prospects from CSV (columns: Name, Source, Wealth (M), Best NNM (M), Worst NNM (M))", expanded=False):
    up = st.file_uploader("Upload CSV", type=["csv"])
    if up is not None:
        try:
            df_up = pd.read_csv(up)
            df_up = df_up.rename(columns=lambda x: x.strip())
            needed = ["Name","Source","Wealth (M)","Best NNM (M)","Worst NNM (M)"]
            for c in needed:
                if c not in df_up.columns:
                    st.error(f"Missing column in CSV: {c}")
                    df_up = None
                    break
            if df_up is not None:
                for c in ["Wealth (M)","Best NNM (M)","Worst NNM (M)"]:
                    df_up[c] = pd.to_numeric(df_up[c], errors="coerce").fillna(0.0)
                st.session_state.prospects_list += df_up[needed].to_dict(orient="records")
                st.success(f"Imported {len(df_up)} prospects.")
        except Exception as e:
            st.error(f"Import failed: {e}")

f1, f2, f3, f4, f5 = st.columns([2,2,2,2,2])
with f1:
    st.session_state.p_name = (
        st.text_input("Name", value=st.session_state.p_name, key="p_name_input", placeholder="Prospect name")
        or st.session_state.p_name
    )
    st.session_state.p_name = st.session_state.p_name_input
with f2:
    st.session_state.p_source = st.selectbox(
        "Source",
        ["Self Acquired","Inherited","Finder"],
        index=["Self Acquired","Inherited","Finder"].index(st.session_state.p_source)
        if st.session_state.p_source in ["Self Acquired","Inherited","Finder"] else 0,
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
add_clicked = c_add.button("➕ Add", disabled=(st.session_state.edit_index != -1))
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

frames = [df for df in (df_pros, total_row) if not df.empty]
df_display = pd.concat(frames, ignore_index=True) if frames else total_row.copy()

highlighter = _make_highlighter(len(df_display))
st.dataframe(df_display.style.apply(highlighter, axis=1), use_container_width=True)
st.markdown('</div>', unsafe_allow_html=True)

best_sum = float(df_pros["Best NNM (M)"].sum()) if not df_pros.empty else 0.0
st.caption(f"Δ Best NNM vs NNM Y1: {best_sum - float(nnm_y1 or 0.0):+.1f} M")

# ---------- SECTION 4 ----------
st.markdown('<div class="ep-card">', unsafe_allow_html=True)
st.markdown('<span class="ep-chip">4️⃣ Revenue, Costs & Net Margin Analysis</span>', unsafe_allow_html=True)
roa_cols = st.columns(3)
roa_y1 = roa_cols[0].number_input("ROA % Year 1", min_value=0.0, value=1.0, step=0.1)
roa_y2 = roa_cols[1].number_input("ROA % Year 2", min_value=0.0, value=1.0, step=0.1)
roa_y3 = roa_cols[2].number_input("ROA % Year 3", min_value=0.0, value=1.0, step=0.1)

rev1 = nnm_y1 * roa_y1 / 100 * 1_000_000
rev2 = nnm_y2 * roa_y2 / 100 * 1_000_000
rev3 = nnm_y3 * roa_y3 / 100 * 1_000_000

fixed_cost = base_salary * 1.25

nm1 = rev1 - fixed_cost
nm2 = rev2 - fixed_cost
nm3 = rev3 - fixed_cost

gross_total = rev1 + rev2 + rev3
total_costs = fixed_cost * 3
nm_total = nm1 + nm2 + nm3

df_rev = pd.DataFrame(
    {
        "Year": ["Year 1", "Year 2", "Year 3", "Total"],
        "Gross Revenue": [rev1, rev2, rev3, rev1+rev2+rev3],
        "Fixed Cost": [fixed_cost, fixed_cost, fixed_cost, total_costs],
        "Net Margin": [nm1, nm2, nm3, nm_total],
    }
)
col_table, col_chart = st.columns(2)
with col_table:
    st.table(
        df_rev.set_index("Year").style.format(
            {"Gross Revenue": "{:,.0f}", "Fixed Cost": "{:,.0f}", "Net Margin": "{:,.0f}"}
        )
    )
with col_chart:
    st.bar_chart(df_rev.set_index("Year")[["Gross Revenue", "Net Margin"]])
st.markdown('</div>', unsafe_allow_html=True)

# === Sidebar Snapshot (live) ===
with st.sidebar:
    st.markdown("#### Snapshot")
    st.caption("Auto-updates as you fill the form")
    st.metric("Total 3-Year Gross (CHF)", f"{(rev1+rev2+rev3):,.0f}")
    st.metric("Total 3-Year Net (CHF)", f"{nm_total:,.0f}")
    st.metric("Avg ROA (%)", f"{((roa_y1+roa_y2+roa_y3)/3):.2f}")
    _verdict_preview = "—"
    if "🟢" in st.session_state.get("_verdict",""):
        _verdict_preview = "🟢 Strong"
    elif "🟡" in st.session_state.get("_verdict",""):
        _verdict_preview = "🟡 Medium"
    elif "🔴" in st.session_state.get("_verdict",""):
        _verdict_preview = "🔴 Weak"
    st.metric("Fit Indicator", _verdict_preview)
    st.divider()
    st.caption("Powered by Executive Partners · Secure submission")

  # ------ AI analysis (compute always; render only if recruiter_mode) ------
total_nnm_3y = float((nnm_y1 or 0.0) + (nnm_y2 or 0.0) + (nnm_y3 or 0.0))
avg_roa = float(((roa_y1 or 0.0) + (roa_y2 or 0.0) + (roa_y3 or 0.0)) / 3.0)

# Thresholds
if current_market == "CH Onshore":
    aum_min = 200.0
else:
    # default to HNWI thresholds unless recruiter overrides in the gated UI
    aum_min = 200.0

score = 0
reasons_pos, reasons_neg, flags = [], [], []

# Experience
if years_experience >= 7:
    score += 2; reasons_pos.append("Experience ≥7 years in market")
elif years_experience >= 6:
    score += 1; reasons_pos.append("Experience 6 years")
else:
    reasons_neg.append("Experience <6 years")

# AUM
if current_assets >= aum_min:
    if current_market == "CH Onshore" and current_assets >= 250:
        score += 2; reasons_pos.append("AUM meets CH 250M target")
    else:
        score += 2; reasons_pos.append(f"AUM ≥ {aum_min}M")
else:
    reasons_neg.append(f"AUM shortfall: {max(0.0, aum_min - current_assets):.0f}M")

# Comp profile
if base_salary > 200_000 and last_bonus > 100_000:
    score += 2; reasons_pos.append("Comp indicates hunter profile")
elif base_salary <= 150_000 and last_bonus <= 50_000:
    score -= 1; reasons_neg.append("Low comp indicates inherited/low portability")
else:
    flags.append("Comp neutral – clarify origin of book")

# ROA
if avg_roa >= 1.0:
    score += 2; reasons_pos.append(f"Avg ROA {avg_roa:.2f}% (excellent)")
elif avg_roa >= 0.8:
    score += 1; reasons_pos.append(f"Avg ROA {avg_roa:.2f}% (acceptable)")
else:
    reasons_neg.append(f"Avg ROA {avg_roa:.2f}% is low")

# Clients
if current_number_clients == 0:
    flags.append("Clients not provided")
elif current_number_clients > 80:
    reasons_neg.append(f"High client count ({current_number_clients}) – likely lower segment")
else:
    score += 1; reasons_pos.append("Client load appropriate (≤80)")

# Prospects consistency vs NNM Y1
df_pros_check = pd.DataFrame(
    st.session_state.prospects_list,
    columns=["Name","Source","Wealth (M)","Best NNM (M)","Worst NNM (M)"]
)
nnm_y1_val = float(nnm_y1 or 0.0)
best_sum = float(df_pros_check["Best NNM (M)"].sum()) if not df_pros_check.empty else 0.0
tolerance_pct = 10  # default; recruiter can adjust inside gated UI
tol = tolerance_pct / 100.0

if nnm_y1_val == 0.0 and best_sum == 0.0:
    flags.append("Prospects & NNM Y1 both zero")
elif abs(best_sum - nnm_y1_val) <= tol * max(nnm_y1_val, 1e-9):
    score += 1; reasons_pos.append(
        f"Prospects Best NNM {best_sum:.1f}M ≈ NNM Y1 {nnm_y1_val:.1f}M"
    )
else:
    reasons_neg.append(
        f"Prospects {best_sum:.1f}M vs NNM Y1 {nnm_y1_val:.1f}M (> {int(tolerance_pct)}% dev)"
    )

# Verdict
if score >= 7:
    verdict = "🟢 Strong Candidate"
elif score >= 4:
    verdict = "🟡 Medium Potential"
else:
    verdict = "🔴 Weak Candidate"

# Keep quick access in session for the sidebar
st.session_state["_score"] = score
st.session_state["_verdict"] = verdict  

# ---------- SECTION 5 (Recruiter-only UI; render only when recruiter_mode) ----------
if recruiter_mode:
    st.markdown('<div class="ep-card">', unsafe_allow_html=True)
    st.markdown('<span class="ep-chip">5️⃣ AI Candidate Analysis (Recruiter)</span>', unsafe_allow_html=True)

    # In recruiter mode, allow adjusting segment & tolerance
    seg_col1, seg_col2 = st.columns(2)
    with seg_col1:
        target_segment = st.selectbox("Target Segment (for thresholds)", ["HNWI", "UHNWI"], index=0)
    with seg_col2:
        tolerance_pct = st.slider("NNM vs Prospects tolerance (%)", 0, 50, 10, 1)

    # Recompute aum_min and tolerance impact for transparency (optional to re-score live)
    aum_min = 200.0 if target_segment == "HNWI" else 300.0

    st.subheader(f"Traffic Light: {verdict} (score {score}/10)")
    colA, colB, colC = st.columns(3)
    with colA:
        st.markdown("**Positives**")
        for r in (reasons_pos or ["—"]):
            st.markdown(f"- ✅ {r}" if r != "—" else "- —")
    with colB:
        st.markdown("**Risks / Gaps**")
        for r in (reasons_neg or ["—"]):
            st.markdown(f"- ❌ {r}" if r != "—" else "- —")
    with colC:
        st.markdown("**Flags / To Clarify**")
        for r in (flags or ["—"]):
            st.markdown(f"- ⚠️ {r}" if r != "—" else "- —")

    m1, m2, m3, m4 = st.columns(4)
    with m1:
        st.metric("AUM (M)", f"{float(current_assets or 0):,.0f}")
    with m2:
        st.metric("Avg ROA %", f"{avg_roa:.2f}")
    with m3:
        st.metric("3Y NNM (M)", f"{total_nnm_3y:.1f}")
    with m4:
        st.metric("Clients", f"{int(current_number_clients or 0)}")

    st.markdown('</div>', unsafe_allow_html=True)
# else: render nothing for Section 5

# ---------- SECTION 6 ----------
st.markdown('<div class="ep-card">', unsafe_allow_html=True)
st.markdown('<span class="ep-chip">6️⃣ Summary, PDF & Save</span>', unsafe_allow_html=True)
st.caption("Your PDF includes Sections 1–4 with **Executive Partners** watermark.")

score = st.session_state.get("_score", 0)
verdict = st.session_state.get("_verdict", "")

def _email_valid(e: str) -> bool:
    return isinstance(e, str) and "@" in e and "." in (e.split("@")[-1] if "@" in e else "")

def _build_data_dict():
    total_rev_3y = ((nnm_y1 * roa_y1) + (nnm_y2 * roa_y2) + (nnm_y3 * roa_y3)) / 100 * 1_000_000
    profit_margin_pct = (
        (((total_rev_3y - (base_salary * 1.25 * 3)) / total_rev_3y) * 100.0) if total_rev_3y > 0 else 0.0
    )
    total_profit_3y = (
        (nnm_y1 * roa_y1 / 100 * 1_000_000) +
        (nnm_y2 * roa_y2 / 100 * 1_000_000) +
        (nnm_y3 * roa_y3 / 100 * 1_000_000)
    ) - (base_salary * 1.25 * 3)

    return {
        "Timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "Candidate Name": candidate_name,
        "Candidate Email": candidate_email,
        "Current Role": current_role,
        "Candidate Location": candidate_location,
        "Current Employer": current_employer,
        "Current Market": current_market,
        "Currency": currency,
        "Base Salary": base_salary,
        "Last Bonus": last_bonus,
        "Current Number of Clients": current_number_clients,
        "Current AUM (M CHF)": current_assets,
        "NNM Year 1 (M CHF)": nnm_y1,
        "NNM Year 2 (M CHF)": nnm_y2,
        "NNM Year 3 (M CHF)": nnm_y3,
        "Revenue Year 1 (CHF)": nnm_y1 * roa_y1 / 100 * 1_000_000,
        "Revenue Year 2 (CHF)": nnm_y2 * roa_y2 / 100 * 1_000_000,
        "Revenue Year 3 (CHF)": nnm_y3 * roa_y3 / 100 * 1_000_000,
        "Total Revenue 3Y (CHF)": total_rev_3y,
        "Profit Margin (%)": profit_margin_pct,
        "Total Profit 3Y (CHF)": total_profit_3y,
        "Score": score,
        "AI Evaluation Notes": verdict
    }

def _inputs_ok_for_save():
    missing = []
    if not _email_valid(candidate_email):
        missing.append("Candidate Email (valid)")
    if candidate_location == "— Select —":
        missing.append("Candidate Location")
    return (len(missing) == 0, ", ".join(missing))

def _save_to_sheet_if_possible(data_dict, reason=""):
    if not worksheet:
        st.warning("⚠️ Google Sheet connection not available.")
        return False
    # de-dupe by signature
    sig = _make_signature(data_dict)
    if st.session_state.get("_last_sig") == sig:
        st.info("Already saved. No duplicate entry created.")
        return False
    try:
        append_in_header_order(worksheet, data_dict)
        st.session_state["_last_sig"] = sig
        if reason:
            st.success(f"✅ Saved to Google Sheet ({reason}).")
        else:
            st.success("✅ Saved to Google Sheet.")
        return True
    except Exception as e:
        st.error(f"Error saving to Google Sheet: {e}")
        return False

# Build data + PDF once
candidate_dict = _build_data_dict()
pdf_buf = build_pdf(
    candidate=candidate_dict,
    prospects_df=df_display,  # includes TOTAL row
    revenue_df=pd.DataFrame({
        "Year": ["Year 1","Year 2","Year 3","Total"],
        "Gross Revenue": [rev1, rev2, rev3, rev1+rev2+rev3],
        "Fixed Cost": [fixed_cost, fixed_cost, fixed_cost, fixed_cost*3],
        "Net Margin": [nm1, nm2, nm3, nm1+nm2+nm3],
    })
)

# Actions row
left, right = st.columns([0.68, 0.32])
with left:
    download_clicked = st.download_button(
        label="📄 Download your Business Plan projection (PDF)",
        file_name=f"BP_{candidate_name or 'candidate'}_{datetime.now().strftime('%Y%m%d_%H%M')}.pdf",
        mime="application/pdf",
        data=pdf_buf.getvalue(),
        use_container_width=True
    )
with right:
    manual_clicked = st.button("💾 Save to Google Sheet (manual)", use_container_width=True)

# Validation + actions
ok_to_save, missing_msg = _inputs_ok_for_save()

# Auto-save: always
if AUTO_SAVE_MODE == "always" and ok_to_save:
    if not st.session_state.get("_autosaved_hash"):
        st.session_state["_autosaved_hash"] = ""
    current_hash = json.dumps({
        "email": candidate_email,
        "nnm": [nnm_y1, nnm_y2, nnm_y3],
        "aum": current_assets,
        "base": base_salary,
    }, sort_keys=True)
    if current_hash != st.session_state["_autosaved_hash"]:
        if _save_to_sheet_if_possible(candidate_dict, reason="AUTO (always)"):
            st.session_state["_autosaved_hash"] = current_hash

# Auto-save: when PDF generated
if AUTO_SAVE_MODE == "on_pdf" and download_clicked:
    if ok_to_save:
        _save_to_sheet_if_possible(candidate_dict, reason="PDF generated")
    else:
        st.warning(f"Not saved — missing: {missing_msg}")

# Manual save
if manual_clicked:
    if ok_to_save:
        _save_to_sheet_if_possible(candidate_dict, reason="manual")
    else:
        st.error("Please complete the required fields: " + missing_msg)

st.markdown('</div>', unsafe_allow_html=True)
