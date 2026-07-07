import os
import logging
from io import BytesIO
from datetime import datetime, date

import pandas as pd
import plotly.express as px
import pytz
import requests
import streamlit as st
import plotly.graph_objects as go
from requests.adapters import HTTPAdapter
from requests.packages.urllib3.util.retry import Retry
import sqlite3

# =========================================================
# 1) PAGE CONFIG - WAJIB PALING ATAS
# =========================================================
st.set_page_config(
    layout="wide",
    page_title="SIBIMA Performance Dashboard",
    initial_sidebar_state="expanded"
)

# =========================================================
# 2) LOGGING CONFIG
# =========================================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)
logger = logging.getLogger(__name__)

# =========================================================
# 3) APP CONFIG
# =========================================================
TIMEZONE = pytz.timezone("Asia/Jakarta")
# Ambil tanggal hari ini
today = date.today()

# Default: tanggal 1 bulan aktif sampai hari ini
DEFAULT_START_DATE = date(today.year, today.month, 1)
DEFAULT_END_DATE = today
REQUEST_TIMEOUT = int(os.getenv("SIBIMA_API_TIMEOUT", "120"))


BASE_URL = {
    "outstanding": "https://eas.sibima.id/api/dashboard/",
    "eas": "https://eas.sibima.id/api/",
    "brp": "https://brp.sibima.id/api/"
}

API_TOKEN = os.getenv("SIBIMA_API_TOKEN", "44b71f38c25ddd02cd31b409f85e9f3aca4f337f02f2fa90237afc2a0736")

# Pastikan setiap URL diakhiri dengan "/"
for key in BASE_URL:
    if not BASE_URL[key].endswith("/"):
        BASE_URL[key] += "/"

def create_session():
    session = requests.Session()
    retries = Retry(
        total=3,
        backoff_factor=2,
        status_forcelist=[502, 503, 504, 429],
    )
    adapter = HTTPAdapter(max_retries=retries, pool_connections=10, pool_maxsize=10)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session

# =========================================================
# 4) CSS CUSTOM
# =========================================================
st.markdown("""
<style>
/* ====== TITLE UTAMA ====== */
h1 {
    font-size: 1.5rem !important;   /* paling besar */
    font-weight: 800;
    color: #222;
}

/* ====== SUBTITLE & SUBHEADER ====== */
h2, h3, h4, h5, h6 {
    font-size: 1rem !important;   /* lebih kecil dari h1 */
    font-weight: 600;
    color: #444;
}

/* ====== LAYOUT CONTAINER ====== */
.block-container {
    padding-top: 2rem;
    padding-bottom: 1rem;
    padding-left: 2rem;
    padding-right: 2rem;
    max-width: 100%;
}

/* ====== METRIC COMPONENTS ====== */
[data-testid="stMetricLabel"] {
    font-size: 0.7rem !important;
}
[data-testid="stMetricValue"] {
    font-size: 0.5rem !important;
}

/* ====== CUSTOM METRIC CARD ====== */
.metric-card {
    background-color: #f4f4f4;
    border: 1px solid #dcdcdc;
    border-radius: 12px;
    padding: 2px;
    box-shadow: 1px 2px 8px rgba(0,0,0,0.05);
    text-align: center;
    margin-top: 3px;
    margin-bottom: 7px;
    margin-left: 2.5px;
    font-size: 0.75rem;
}
            
.metric-card div {
    font-size: 0.67rem !important;
}            

/* ====== SMALL NOTES ====== */
.small-note {
    color: #666;
    font-size: 0.70rem;
}
            
h3, h4, h5 {
    margin-bottom: 0.1rem !important;
}

/* Kurangi jarak antar komponen container */
div[data-testid="stVerticalBlock"] {
    margin-top: 0.1rem !important;
    margin-bottom: 0.1rem !important;
}

/* Kurangi padding default di dalam container */
div[data-testid="stContainer"] {
    padding-top: 0.1rem !important;
    padding-bottom: 0.1rem !important;
}
            

/* ====== FILTER INPUTS ====== */
div[data-testid="stDateInput"], 
div[data-testid="stTextInput"] {
    font-size: 0.7rem !important;   /* ukuran teks lebih kecil */
}

label, .stTextInput label, .stDateInput label {
    font-size: 0.7rem !important;   /* label input lebih kecil */
    color: #555 !important;
}

/* Kurangi tinggi box input agar lebih ramping */
input, textarea {
    font-size: 0.7rem !important;
    padding: 4px 6px !important;
}
            
@media (max-width: 768px) {
    h1 { font-size: 1.2rem !important; }
    h2, h3, h4 { font-size: 0.9rem !important; }
    .metric-card {
        font-size: 0.65rem !important;
        padding: 4px !important;
    }
    [data-testid="stMetricValue"] {
        font-size: 0.7rem !important;
    }
    .block-container {
        padding-left: 0.5rem !important;
        padding-right: 0.5rem !important;
    }
}

                        
</style>
""", unsafe_allow_html=True)


# =========================================================
# 5) UTILITIES
# =========================================================
def metric_card(label: str, value: str):
    st.markdown(
        f"""
        <div class="metric-card">
            <div style="color: #666; font-size: 0.95rem;">{label}</div>
            <div style="font-size: 0.9rem; font-weight: 700; color: #222;">{value}</div>
        </div>
        """,
        unsafe_allow_html=True
    )


def ensure_columns(df: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    """Pastikan semua kolom ada agar operasi berikutnya aman."""
    if df.empty:
        for col in columns:
            if col not in df.columns:
                df[col] = pd.Series(dtype="object")
        return df

    for col in columns:
        if col not in df.columns:
            df[col] = pd.NA
    return df


def safe_to_numeric(df: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    """Konversi kolom ke numerik dengan aman."""
    for col in columns:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)
    return df


def safe_to_datetime(df: pd.DataFrame, col: str) -> pd.DataFrame:
    """Konversi kolom tanggal dengan aman dan hilangkan timezone."""
    if col in df.columns:
        df[col] = pd.to_datetime(df[col], errors="coerce")
        try:
            df[col] = df[col].dt.tz_localize(None)
        except Exception:
            pass
    return df


def normalize_text_columns(df: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    """Normalisasi string agar aman untuk pencarian."""
    for col in columns:
        if col in df.columns:
            df[col] = df[col].fillna("").astype(str).str.strip()
    return df


def safe_unique_count(df: pd.DataFrame, col: str) -> int:
    if df.empty or col not in df.columns:
        return 0
    return df[col].nunique(dropna=True)


def safe_mean(df: pd.DataFrame, col: str) -> float:
    if df.empty or col not in df.columns:
        return 0.0
    return float(df[col].mean()) if not df[col].dropna().empty else 0.0

def safe_sum(df: pd.DataFrame, col: str) -> float:
    if df.empty:
        return 0.0
    if col not in df.columns:
        # fallback ke kolom lain yang mirip
        for alt in ["Nominal", "discount", "price"]:
            if alt in df.columns:
                col = alt
                break
    return float(pd.to_numeric(df[col], errors="coerce").fillna(0).sum())



def to_excel_bytes(df: pd.DataFrame, sheet_name: str = "Data") -> bytes:
    output = BytesIO()
    with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
        df.to_excel(writer, index=False, sheet_name=sheet_name)
    return output.getvalue()


# =========================================================
# 6) API FETCHING
# =========================================================
@st.cache_data(ttl=300, show_spinner=False)
def get_api_data_old(endpoint: str, source: str = "outstanding", start_date=None, end_date=None):
    base_url = BASE_URL.get(source, BASE_URL["outstanding"])
    url = f"{base_url}{endpoint}"
    params = {"date_start": start_date, "date_end": end_date}

    try:
        logger.info("Fetching endpoint=%s from source=%s params=%s", endpoint, source, params)

        # 🔹 Gunakan session dengan retry
        session = create_session()
        response = session.get(url, params=params, timeout=REQUEST_TIMEOUT)

        response.raise_for_status()
        payload = response.json()

        if isinstance(payload, dict):
            data_layer = payload.get("data", {})
            if isinstance(data_layer, dict):
                rows = data_layer.get("data", [])
                if isinstance(rows, list):
                    df = pd.DataFrame(rows)
                    df = safe_to_datetime(df, "transaction_date")
                    return df
        return pd.DataFrame()

    except Exception as e:
        st.warning(f"Gagal mengambil data dari endpoint {endpoint} ({source}): {e}")
        return pd.DataFrame()

@st.cache_data(ttl=300, show_spinner=False)
def get_api_data_new(endpoint: str, source: str = "eas", start_date=None, end_date=None):
    base_url = BASE_URL.get(source, BASE_URL["eas"])
    url = f"{base_url}{endpoint}"
    params = {
        "date_start": start_date,
        "date_end": end_date,
        "token": API_TOKEN
    }

    try:
        # 🔹 Gunakan session dengan retry
        session = create_session()
        response = session.get(url, params=params, timeout=REQUEST_TIMEOUT)

        response.raise_for_status()
        payload = response.json()

        rows = payload.get("data", [])
        if isinstance(rows, list):
            all_rows = []
            for row in rows:
                items = row.get("items", [])
                if items:
                    for item in items:
                        flat = {**row, **{f"item_{k}": v for k, v in item.items()}}
                        all_rows.append(flat)
                else:
                    all_rows.append(row)

            df = pd.DataFrame(all_rows)
            df = safe_to_datetime(df, "transaction_date")
            return df

        return pd.DataFrame()

    except Exception as e:
        st.warning(f"Gagal mengambil data dari endpoint {endpoint} ({source}): {e}")
        return pd.DataFrame()


def load_all_data(start_date=None, end_date=None) -> dict[str, pd.DataFrame]:
    endpoint_map = {
        "po": ("po-balance", {"Tgl. PO": "transaction_date"}),
        "grn": ("grn-balance", {"Tgl. GRN": "transaction_date"}),
        "do": ("do-balance", {"Tgl. DO": "transaction_date"}),
        "npr": ("outstanding-npr", {"Tanggal": "transaction_date"}),
        #"pur": ("outstanding-pur", {"Tanggal": "transaction_date"})
    }

    result = {}
    for key, (endpoint, rename_map) in endpoint_map.items():
        df = get_api_data_old(endpoint, source="outstanding", start_date=start_date, end_date=end_date)

        if not df.empty:
            df = df.rename(columns=rename_map)
            df = safe_to_datetime(df, "transaction_date")
        result[key] = df

    return result



def load_all_data_new(start_date=None, end_date=None) -> dict[str, pd.DataFrame]:
    # Mapping endpoint baru sesuai API kamu
    endpoint_map_new = {
        "pr": "purchase-requests",
        "po": "purchase-orders",
        "do": "delivery-orders",
        "grn": "goods-receipt-notes",
    }

    result_new = {}
    for key, endpoint in endpoint_map_new.items():
        df = get_api_data_new(endpoint, source="eas", start_date=start_date, end_date=end_date)
        result_new[key] = df

    return result_new




# =========================================================
# 7) FILTERS & TRANSFORM
# =========================================================
def apply_cumulative_filter(df: pd.DataFrame, end_date_val) -> pd.DataFrame:
    """
    Ambil SEMUA data dari awal hingga end_date.
    """
    if df.empty or "transaction_date" not in df.columns:
        return df.copy()

    working = df.copy()
    working = safe_to_datetime(working, "transaction_date")

    upper_limit = pd.to_datetime(end_date_val).replace(hour=23, minute=59, second=59)
    return working[
        working["transaction_date"].notna() &
        (working["transaction_date"] <= upper_limit)
    ].copy()

def apply_realization_filter(df: pd.DataFrame, start_date_val, end_date_val) -> pd.DataFrame:
    """
    Ambil data hanya dalam rentang tanggal tertentu (start_date sampai end_date).
    Contoh: 1 Mei 2026 s/d 31 Mei 2026.
    """
    if df.empty or "transaction_date" not in df.columns:
        return df.copy()

    working = df.copy()
    working = safe_to_datetime(working, "transaction_date")

    lower_limit = pd.to_datetime(start_date_val).replace(hour=0, minute=0, second=0)
    upper_limit = pd.to_datetime(end_date_val).replace(hour=23, minute=59, second=59)

    return working[
        working["transaction_date"].notna() &
        (working["transaction_date"] >= lower_limit) &
        (working["transaction_date"] <= upper_limit)
    ].copy()



def apply_search_filter(
    df: pd.DataFrame,
    search_number: str = "",
    search_status: str = "",
    search_pic: str = ""
) -> pd.DataFrame:
    if df.empty:
        return df.copy()

    working = df.copy()
    working = normalize_text_columns(
        working,
        ["Status", "PIC Purchasing", "PIC Purchasing", "PIC", "No. PR", "No. DO", "No. PUR", "No. Transaksi"]
    )

    # Filter nomor transaksi: mencari di semua kolom string
    if search_number:
        pattern = search_number.strip().lower()
        string_cols = working.select_dtypes(include=["object"]).columns.tolist()
        if string_cols:
            mask_number = working[string_cols].apply(
                lambda col: col.str.lower().str.contains(pattern, na=False)
            ).any(axis=1)
            working = working[mask_number]

    # Filter status
    if search_status and "Status" in working.columns:
        working = working[
            working["Status"].str.contains(search_status.strip(), case=False, na=False)
        ]

    # Filter PIC -> OR logic, bukan AND
    if search_pic:
        pic_cols = [col for col in ["PIC Purchasing", "PIC Purchasing", "PIC"] if col in working.columns]
        if pic_cols:
            mask_pic = working[pic_cols].apply(
                lambda col: col.str.contains(search_pic.strip(), case=False, na=False)
            ).any(axis=1)
            working = working[mask_pic]

    return working.copy()


def assign_unassigned(df: pd.DataFrame, col: str) -> pd.DataFrame:
    working = df.copy()
    if col in working.columns:
        working[col] = working[col].fillna("Unassigned").astype(str).str.strip()
        working.loc[working[col] == "", col] = "Unassigned"
    return working


def get_top_pic(df: pd.DataFrame, pic_col: str, doc_col: str) -> str:
    if df.empty or pic_col not in df.columns or doc_col not in df.columns or "Status" not in df.columns:
        return "Tidak ada"

    working = assign_unassigned(df, pic_col)
    working = working[working[pic_col] != "Unassigned"]

    if working.empty:
        return "Tidak ada"

    # 🔹 Urutan prioritas status (semakin tinggi nilainya, semakin pending)
    status_priority = {
        "Need Approve": 4,
        "Approved": 3,
        "In Progress": 2,
        "Complete": 1
    }

    working["Status_Score"] = working["Status"].map(status_priority).fillna(0)

    summary = (
        working.groupby(pic_col)
        .agg(
            Total_Doc=(doc_col, "nunique"),
            Avg_Status_Score=("Status_Score", "mean")
        )
        .reset_index()
    )

    # 🔹 Urutkan berdasarkan jumlah dokumen dan tingkat pending (semakin tinggi skor, semakin pending)
    summary = summary.sort_values(["Total_Doc", "Avg_Status_Score"], ascending=[False, False])

    return summary.iloc[0][pic_col] if not summary.empty else "Tidak ada"


def summarize_status(df: pd.DataFrame, doc_col: str, nominal_col: str = "Nominal") -> pd.DataFrame:
    if df.empty or "Status" not in df.columns:
        return pd.DataFrame(columns=["Status", "Total_Doc", "Total_Amount"])

    working = df.copy()
    working = ensure_columns(working, [doc_col, nominal_col, "Status"])
    working = safe_to_numeric(working, [nominal_col])

    summary = (
        working.groupby("Status", dropna=False)
        .agg(
            Total_Doc=(doc_col, "nunique"),
            Total_Amount=(nominal_col, "sum")
        )
        .reset_index()
    )
    return summary

def summarize_pic_status(df: pd.DataFrame, pic_col: str, doc_col: str) -> pd.DataFrame:
    if df.empty or pic_col not in df.columns or "Status" not in df.columns or doc_col not in df.columns:
        return pd.DataFrame(columns=[pic_col, "Status", "Jumlah_Doc"])

    working = assign_unassigned(df, pic_col)

    summary = (
        working.groupby([pic_col, "Status"], dropna=False)
        .agg(Jumlah_Doc=(doc_col, "nunique"))
        .reset_index()
        .sort_values(by="Jumlah_Doc", ascending=False)
    )
    return summary

# =========================================================
# 8) CHART HELPERS
# =========================================================
STATUS_COLORS = {
    "Complete": "#00CC96",
    "In Progress": "#F2C94C",
    "Approved": "#F2994A",
    "Need Approve": "#EB5757",
    "Pending": "#56CCF2",
}

def render_status_pie(summary_df: pd.DataFrame, title: str):
    if summary_df.empty:
        st.info("Data status tidak tersedia.")
        return

    fig = px.pie(
        summary_df,
        values="Total_Amount",
        names="Status",
        color="Status",
        color_discrete_map=STATUS_COLORS,
        hole=0.45,
    )
    

    fig.update_traces(
        textinfo="percent+value",
        texttemplate="%{percent:.1%}<br>(Rp %{value:,.0f})"
    )
    st.plotly_chart(fig, use_container_width=True)


def render_status_bar(summary_df: pd.DataFrame, title: str):
    if summary_df.empty:
        st.info("Data status tidak tersedia.")
        return

    fig = px.bar(
        summary_df,
        x="Status",
        y="Total_Amount",
        color="Status",
        color_discrete_map=STATUS_COLORS,
        title=title
    )

    fig.update_traces(
        texttemplate="Rp %{y:,.0f}",
        textposition="outside"
    )
    fig.update_layout(
        showlegend=False,
        yaxis=dict(
            tickformat=",.0f",
            title="Total Nominal (Rp)"
        )
    )
    st.plotly_chart(fig, use_container_width=True)


def render_pic_bar(summary_df: pd.DataFrame, x_col: str, y_col: str, color_col: str | None):
    if summary_df.empty:
        st.info("Data PIC tidak tersedia.")
        return

    # Hitung total transaksi per PIC
    summary_df["Total_Doc"] = summary_df.groupby(x_col)[y_col].transform("sum")

    kwargs = {
        "data_frame": summary_df,
        "x": x_col,
        "y": y_col,
    }

    if color_col and color_col in summary_df.columns:
        kwargs["color"] = color_col
        kwargs["color_discrete_map"] = STATUS_COLORS

    fig = px.bar(**kwargs)

    # 🔹 Label per status (segmen warna) → di dalam bar
    fig.update_traces(
        texttemplate="%{y}",          # angka per status
        textposition="inside",
        textfont=dict(size=10, color="white")
    )

    # 🔹 Tambahkan angka total per PIC → di atas bar
    totals = summary_df.groupby(x_col)[y_col].sum().reset_index()
    for _, row in totals.iterrows():
        fig.add_annotation(
            x=row[x_col],             # posisi di sumbu X (PIC)
            y=row[y_col],             # tinggi bar total
            text=f"{row[y_col]}",     # angka total
            showarrow=False,
            font=dict(size=12, color="black"),
            yshift=10                 # geser sedikit ke atas
        )

    fig.update_layout(
        uniformtext_mode="hide",
        uniformtext_minsize=8,
    )

    st.plotly_chart(fig, use_container_width=True)


def render_pic_heatmap(df: pd.DataFrame, pic_col: str, date_col: str, doc_col: str, title: str):
    if df.empty or pic_col not in df.columns or date_col not in df.columns or doc_col not in df.columns:
        st.info("Data tidak tersedia untuk heatmap aktivitas PIC.")
        return

    working = df.copy()
    working[date_col] = pd.to_datetime(working[date_col], errors="coerce")
    working[pic_col] = working[pic_col].fillna("Unassigned")

    bulan_map = {1:"Jan",2:"Feb",3:"Mar",4:"Apr",5:"May",6:"Jun",7:"Jul",8:"Aug",9:"Sep",10:"Oct",11:"Nov",12:"Dec"}
    working["Bulan"] = working[date_col].dt.month.map(bulan_map)
    bulan_order = list(bulan_map.values())
    working["Bulan"] = pd.Categorical(working["Bulan"], categories=bulan_order, ordered=True)

    # gunakan doc_col dinamis
    working[doc_col] = working[doc_col].astype(str).str.strip().str.upper()
    summary = (
        working.groupby([pic_col, "Bulan"])[doc_col]
        .nunique()
        .reset_index(name="Jumlah Transaksi")
        .sort_values("Bulan")
    )

    fig = px.density_heatmap(summary, x="Bulan", y=pic_col, z="Jumlah Transaksi",
                             color_continuous_scale=["#138207","#F2994A","#A80B0B"], text_auto=True)
    
    # tambahkan pengaturan layout di sini
    fig.update_layout(
        coloraxis_showscale=False,   # 🔹 sembunyikan color bar
        coloraxis_colorbar=dict(title=None),  # 🔹 hilangkan teks "sum of Jumlah Transaksi"
        xaxis_title="Bulan",
        yaxis_title="PIC Purchasing",
        margin=dict(l=100, r=40, t=60, b=120),
        height=500
        )
    st.plotly_chart(fig, use_container_width=True)


    # Tambahkan keterangan di bawah heatmap
    st.markdown(
        "<div style='text-align:center; font-size:0.8rem; color:#6f6f6f;'>"
        "📝 <b>Keterangan:</b> " \
        "Kotak dengan warna mendekati merah artinya punya outstanding PR yang lebih banyak sedangkan " \
        "kotak dengan warna mendekati biru artinya outstanding PRnya lebih sedikit"
        "</div>",
        unsafe_allow_html=True
    )


def calculate_aging(df: pd.DataFrame, date_col: str, prefer: str = "approved") -> pd.DataFrame:
    """
    Hitung aging dengan prioritas tanggal sesuai preferensi.
    prefer bisa: "approved", "inprogress", "complete"
    Default: "approved"
    """
    if df.empty or date_col not in df.columns:
        return df.copy()

    working = df.copy()
    working = safe_to_datetime(working, date_col)
    working = safe_to_datetime(working, "date_inprogress")
    working = safe_to_datetime(working, "date_complete")
    working = safe_to_datetime(working, "date_approved")

    today = pd.Timestamp.today().normalize()

    # Default aging = today - transaction_date
    working["Aging"] = (today - working[date_col]).dt.days

    # Terapkan prioritas sesuai prefer
    if prefer == "approved":
        mask = working["date_approved"].notna()
        working.loc[mask, "Aging"] = (
            working.loc[mask, "date_approved"] - working.loc[mask, date_col]
        ).dt.days

    elif prefer == "inprogress":
        mask = working["date_inprogress"].notna()
        working.loc[mask, "Aging"] = (
            working.loc[mask, "date_inprogress"] - working.loc[mask, date_col]
        ).dt.days

    elif prefer == "complete":
        mask = working["date_complete"].notna()
        working.loc[mask, "Aging"] = (
            working.loc[mask, "date_complete"] - working.loc[mask, date_col]
        ).dt.days

    return working


def categorize_aging(df: pd.DataFrame) -> pd.DataFrame:
    bins = [-1, 30, 60, 90, float("inf")]   # 🔹 ubah dari 0 → -1
    labels = ["0-30 hari", "31-60 hari", "61-90 hari", ">90 hari"]
    df["Aging Category"] = pd.cut(df["Aging"], bins=bins, labels=labels, right=True)
    return df


def render_aging_bar(df: pd.DataFrame, doc_col: str, chart_key: str = "aging_bar"):
    if df.empty or "Aging Category" not in df.columns:
        st.info("Data aging tidak tersedia.")
        return

    summary = (
        df.groupby("Aging Category")[doc_col]
        .nunique()
        .reset_index(name="Jumlah Transaksi")
    )

    fig = px.bar(
        summary,
        x="Aging Category",
        y="Jumlah Transaksi",
        color="Aging Category",
        color_discrete_map={
            "0-30 hari": "#2F80ED",
            "31-60 hari": "#7ABBEE",
            "61-90 hari": "#FCA27F",
            ">90 hari": "#EB5757"
        },
        text="Jumlah Transaksi"
    )
    fig.update_traces(textposition="outside")

    # ✅ tambahkan key unik di sini
    st.plotly_chart(fig, use_container_width=True, key=chart_key)


def summarize_pic_aging(df: pd.DataFrame, pic_col: str, doc_col: str) -> pd.DataFrame:
    if df.empty or pic_col not in df.columns or "Aging" not in df.columns or "Status" not in df.columns:
        return pd.DataFrame(columns=[pic_col, "Average Aging", "Total_Doc", "Outstanding_Doc", "Completed_Doc", "Over90Pct"])

    working = assign_unassigned(df, pic_col)

    summary = (
        working.groupby(pic_col).agg(
            Average_Aging=("Aging", "mean"),   # 🔹 ubah nama kolom di sini
            Total_Doc=(doc_col, "nunique"),
            Outstanding_Doc=(doc_col, lambda x: (working.loc[x.index, "Status"] != "Complete").sum()),
            Completed_Doc=(doc_col, lambda x: (working.loc[x.index, "Status"] == "Complete").sum()),
            Over90Pct=("Aging", lambda x: (x > 90).sum() / len(x) * 100 if len(x) > 0 else 0)
        )
        .reset_index()
    )
    return summary

def render_pic_aging_bar(summary_df: pd.DataFrame):
    if summary_df.empty:
        st.info("Data aging per PIC tidak tersedia.")
        return
    color_continuous_scale=[
    (0.0, "#56CCF2"),   # hijau muda untuk aging rendah
    (0.5, "#F2994A"),   # kuning untuk sedang
    (1.0, "#EB5757")    # merah untuk aging tinggi
    ]

    fig = px.bar(
    summary_df,
    x="PIC Purchasing",
    y="Average_Aging",   # 🔹 gunakan nama baru
    text="Average_Aging",
    color="Average_Aging",
    color_continuous_scale=[(0.0, "#56CCF2"), (0.5, "#F2C94C"), (1.0, "#EB5757")]
    )

    # Tambahkan pengaturan ukuran teks
    fig.update_traces(
    texttemplate="%{text:.1f} hari",
    textposition="outside",
    textfont=dict(
        size=20,          # ubah sesuai kebutuhan (misalnya 18 atau 20)
        color="black",    # warna teks agar kontras
        family="Arial"    # jenis font agar lebih jelas
        )
    )

    fig.update_layout(
    coloraxis_showscale=False  # sembunyikan color scale di sisi kanan
    )


    st.plotly_chart(fig, use_container_width=True)

def render_sla_gauge(df: pd.DataFrame, threshold: int = 5, title: str = "SLA Compliance"):
    if df.empty or "Aging" not in df.columns:
        st.info("Data aging tidak tersedia untuk SLA.")
        return

    sla_compliance = (df["Aging"] <= threshold).mean() * 100

    fig = go.Figure(go.Indicator(
        mode="gauge+number",
        value=sla_compliance,
        number={'suffix': '%', 'font': {'size': 48, 'color': "#000"}},  # 🔹 tambahkan ini
        title={'text': f"{title} (≤{threshold} hari)"},
        gauge={
            'axis': {'range': [0, 100]},
            'bar': {'color': "blue"},
            'steps': [
                {'range': [0, 50], 'color': "red"},
                {'range': [50, 80], 'color': "yellow"},
                {'range': [80, 100], 'color': "green"}
            ]
        }
    ))
    st.plotly_chart(fig, use_container_width=True)


def summarize_pic_sla(df: pd.DataFrame, pic_col: str, doc_col: str, threshold: int = 5) -> pd.DataFrame:
    if df.empty or pic_col not in df.columns or "Aging" not in df.columns:
        return pd.DataFrame(columns=[pic_col, "Total_Doc", "SLA_Compliance"])

    working = assign_unassigned(df, pic_col)

    summary = (
        working.groupby(pic_col).agg(
            Total_Doc=(doc_col, "nunique"),
            SLA_Compliance=(doc_col, lambda x: (working.loc[x.index, "Aging"] <= threshold).sum() / len(x) * 100 if len(x) > 0 else 0)
        )
        .reset_index()
    )
    return summary

def render_pic_sla_bar(summary_df: pd.DataFrame):
    if summary_df.empty:
        st.info("Data SLA per PIC tidak tersedia.")
        return

    fig = px.bar(
        summary_df,
        x="PIC Purchasing",
        y="SLA_Compliance",
        text="SLA_Compliance",
        color="SLA_Compliance",
        color_continuous_scale=["#EB5757", "#F2C94C", "#6FCF97"],  # merah → kuning → hijau
    )
    fig.update_traces(
        texttemplate="%{text:.1f}%",
        textposition="outside",
        textfont=dict(size=14, color="black")
    )
    fig.update_layout(coloraxis_showscale=False)
    st.plotly_chart(fig, use_container_width=True)


def render_sla_trend(df: pd.DataFrame, threshold: int = 5, date_col: str = "transaction_date"):
    if df.empty or "Aging" not in df.columns or date_col not in df.columns:
        st.info("Data tidak tersedia untuk trend SLA.")
        return

    # Pastikan kolom tanggal dalam format datetime
    df = safe_to_datetime(df, date_col)

    # Tambahkan kolom bulan (Period)
    df["Bulan"] = df[date_col].dt.to_period("M").dt.to_timestamp()

    # Hitung SLA compliance per bulan
    sla_trend = (
        df.groupby("Bulan")
        .agg(SLA_Compliance=("Aging", lambda x: (x <= threshold).mean() * 100))
        .reset_index()
    )

    # Buat line chart
    fig = px.line(
        sla_trend,
        x="Bulan",
        y="SLA_Compliance",
        markers=True,
        title=f"Trend SLA Compliance per Bulan (≤{threshold} hari)"
    )
    fig.update_traces(
        texttemplate="%{y:.1f}%",
        textposition="top center"
    )
    fig.update_layout(
        yaxis=dict(title="SLA Compliance (%)", range=[0, 100])
    )

    st.plotly_chart(fig, use_container_width=True)

def render_eta_histogram(df: pd.DataFrame, eta_col: str = "ETA_PO"):
    if df.empty or eta_col not in df.columns:
        st.info("Data ETA tidak tersedia.")
        return

    # Hitung selisih hari antara ETA dan transaction_date
    df = safe_to_datetime(df, "transaction_date")
    df = safe_to_datetime(df, eta_col)
    df["ETA_Days"] = (df[eta_col] - df["transaction_date"]).dt.days

    fig = px.histogram(
        df,
        x="ETA_Days",
        nbins=20,
        title="Distribusi ETA (hari)",
        color_discrete_sequence=["#2F80ED"]
    )
    fig.update_layout(
        xaxis_title="Selisih ETA (hari)",
        yaxis_title="Jumlah Dokumen"
    )
    st.plotly_chart(fig, use_container_width=True)

DB_FILE = "eta_deadline.db"

def init_db():
    conn = sqlite3.connect("sibima.db")
    cursor = conn.cursor()
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS po_eta (
        Nomor_Dokumen TEXT PRIMARY KEY,
        PIC TEXT,
        ETA_PO TEXT,
        Deadline_DO TEXT,
        Deadline_SI TEXT,
        Timestamp TEXT
    )
    """)
    conn.commit()
    conn.close()

def save_eta_data(nomor_dokumen, pic, eta_po, deadline_do, deadline_si):
    conn = sqlite3.connect("sibima.db")
    cursor = conn.cursor()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    cursor.execute("""
    INSERT INTO po_eta (Nomor_Dokumen, PIC, ETA_PO, Deadline_DO, Deadline_SI, Timestamp)
    VALUES (?, ?, ?, ?, ?, ?)
    ON CONFLICT(Nomor_Dokumen) DO UPDATE SET
        PIC=excluded.PIC,
        ETA_PO=excluded.ETA_PO,
        Deadline_DO=excluded.Deadline_DO,
        Deadline_SI=excluded.Deadline_SI,
        Timestamp=excluded.Timestamp
    """, (nomor_dokumen, pic, str(eta_po), str(deadline_do), str(deadline_si), now))

    conn.commit()
    conn.close()

def load_eta_data():
    conn = sqlite3.connect("sibima.db")
    df_po_eta = pd.read_sql_query("SELECT * FROM po_eta", conn)
    conn.close()
    return df_po_eta


def delete_eta_data(nomor_dokumen):
    conn = sqlite3.connect("sibima.db")
    cursor = conn.cursor()
    cursor.execute("DELETE FROM po_eta WHERE Nomor_Dokumen=?", (nomor_dokumen,))
    conn.commit()
    conn.close()


# =========================================================
# 9) MAIN APP
# =========================================================

def main():
    st.title("SIBIMA Performance Dashboard")

    # ---------- TOP FILTERS ----------
    today = date.today()
    default_start = date(today.year, today.month, 1)

    col_head1, col_head2, col_head3, col_head4, col_head5 = st.columns([1, 1, 1, 1, 1])

    with col_head1:
        selected_date_range = st.date_input(
            "Select Date Range 📅",
            value=(default_start, today),
            max_value=today
        )

    with col_head2:
        selected_doc_type = st.selectbox("Pilih Jenis Dokumen 📑", ["PO", "GRN", "CRUD"])

    with col_head3:
        search_number = st.text_input("Cari Nomor Transaksi 🔍", placeholder="No. PR / No. DO / No. NPR / No. PUR")

    with col_head4:
        search_status = st.text_input("Cari Status 🔍", placeholder="Complete / In Progress / Approved / Need Approve")

    with col_head5:
        search_pic = st.text_input("Cari PIC 🔍", placeholder="PIC Purchasing")

    # ---------- LOAD DATA ----------
    if isinstance(selected_date_range, (tuple, list)) and len(selected_date_range) == 2:
        start_date, end_date = selected_date_range
    else:
        start_date, end_date = default_start, today

    with st.spinner("Mengambil data dashboard..."):
        data_old = load_all_data()
        data_new = load_all_data_new(start_date=start_date, end_date=end_date)

    # ---------- ASSIGN DATAFRAME ----------
    df_po = data_old["po"]
    df_grn = data_old["grn"]
    df_do = data_old["do"]
    #df_pur = data_old["pur"]

    df_po_final = data_new["po"]
    df_grn_final = data_new["grn"]

    # Pastikan kolom PIC dan Status sesuai
    #PO
    df_po_final = df_po_final.rename(columns={
        "item_pic_purchasing_name": "PIC Purchasing",
        "status_description": "Status",
        "date" : "transaction_date"
    })
    #GRN
    df_grn_final = df_grn_final.rename(columns={
        "item_pic_procurement_name": "PIC Purchasing",
        "status_description": "Status"
    })

    df_grn = df_grn.rename(columns={
        "Status GRN": "Status"
    })

    # Pastikan kolom tanggal sudah dalam format datetime
    #PO
    df_po_final = safe_to_datetime(df_po_final, "transaction_date")
    df_po_final = safe_to_datetime(df_po_final, "date_approved")
    df_po_final = safe_to_datetime(df_po_final, "date_inprogress")
    df_po_final = safe_to_datetime(df_po_final, "date_complete")
    #GRN
    df_grn_final = safe_to_datetime(df_grn_final, "transaction_date")
    df_grn_final = safe_to_datetime(df_grn_final, "date_approved")
    df_grn_final = safe_to_datetime(df_grn_final, "date_inprogress")
    df_grn_final = safe_to_datetime(df_grn_final, "date_complete")

    # ---------- DEFAULT SAFE COPY ----------
    df_po_f = df_po.copy()
    df_grn_f = df_grn.copy()
    df_do_f = df_do.copy()
    #df_pur_f = df_pur.copy()
    df_po_final_f = df_po_final.copy()
    df_grn_final_f = df_grn_final.copy()

    # ---------- DATE FILTER ----------
    if isinstance(selected_date_range, (tuple, list)) and len(selected_date_range) == 2:
        report_start_date, report_end_date = selected_date_range
        df_po_f = apply_cumulative_filter(df_po_f, report_end_date)
        df_grn_f = apply_cumulative_filter(df_grn_f, report_end_date)
        df_do_f = apply_cumulative_filter(df_do_f, report_end_date)
        #df_pur_f = apply_cumulative_filter(df_pur_f, report_end_date)
        df_po_final_f = apply_cumulative_filter(df_po_final_f, report_end_date)
        df_grn_final_f = apply_cumulative_filter(df_grn_final_f, report_end_date)

        # 🔹 Dataset baru (PR Final) pakai realisasi
        df_po_final_real = apply_realization_filter(df_po_final, report_start_date, report_end_date)
        df_grn_final_real = apply_realization_filter(df_grn_final, report_start_date, report_end_date)

    # ---------- SEARCH FILTER ----------
    df_po_f = apply_search_filter(df_po_f, search_number, search_status, search_pic)
    df_grn_f = apply_search_filter(df_grn_f, search_number, search_status, search_pic)
    df_do_f = apply_search_filter(df_do_f, search_number, search_status, search_pic)
    #df_pur_f = apply_search_filter(df_pur_f, search_number, search_status, search_pic)
    df_po_final_real = apply_search_filter(df_po_final_real, search_number, search_status, search_pic)


    # ---------- ENSURE IMPORTANT COLUMNS ----------
    df_po_f = ensure_columns(df_po_f, ["Nominal"])
    df_grn_f = ensure_columns(df_grn_f, ["Nominal"])
    df_do_f = ensure_columns(df_do_f, ["Nominal", "No. DO", "PIC Purchasing"])
    #df_pur_f = ensure_columns(df_pur_f, ["No. PUR", "PIC", "Status"])
    df_po_final_real = ensure_columns(df_po_final_real, ["PIC Purchasing", "transaction_number","Status", "price", "quantity", "discount", "transaction_total", "tax1_percentage", "tax2_percentage"])
    df_grn_final_real = ensure_columns(df_grn_final_real, ["PIC Purchasing", "transaction_number","Status", "price", "quantity", "discount", "transaction_total", "tax1_percentage", "tax2_percentage"])

    df_po_f = safe_to_numeric(df_po_f, ["Nominal"])
    df_grn_f = safe_to_numeric(df_grn_f, ["Nominal"])
    df_do_f = safe_to_numeric(df_do_f, ["Nominal"])
    df_po_final_real= safe_to_numeric(df_po_final_real, ["item_price", "item_discount", "item_quantity", "item_tax1_percentage", "item_tax2_percentage"])
    df_grn_final_real= safe_to_numeric(df_grn_final_real, ["item_price", "item_discount", "item_quantity", "item_tax1_percentage", "item_tax2_percentage"])
    
    # ---------- METRICS ----------
    total_po_unpr = safe_sum(df_po_f, "Nominal")
    total_grn_unpr = safe_sum(df_grn_f, "Nominal")
    total_do_unpr = safe_sum(df_do_f, "Nominal")

    df_po_final_real = normalize_text_columns(df_po_final_real, ["item_PIC_Purchasing"])
    df_grn_final_real = normalize_text_columns(df_grn_final_real, ["item_PIC_Purchasing"])


    df_po_final_real["disc_per_unit"] = df_po_final_real["item_price"] * (df_po_final_real["item_discount"] / 100)
    df_po_final_real["tax_unit"] = (df_po_final_real["item_price"] - df_po_final_real["disc_per_unit"]) * (df_po_final_real["item_tax1_percentage"] / 100)
    df_po_final_real["net_price_unit"] = df_po_final_real["item_price"] - df_po_final_real["disc_per_unit"] + df_po_final_real["tax_unit"]
    df_po_final_real["total_po_row"] = df_po_final_real["item_quantity"] * df_po_final_real["net_price_unit"]
    total_po = df_po_final_real["total_po_row"].sum()

    df_grn_final_real["disc_per_unit"] = df_grn_final_real["item_price"] * (df_grn_final_real["item_discount"] / 100)
    df_grn_final_real["tax_unit"] = (df_grn_final_real["item_price"] - df_grn_final_real["disc_per_unit"]) * (df_grn_final_real["item_tax1_percentage"] / 100)
    df_grn_final_real["net_price_unit"] = df_grn_final_real["item_price"] - df_grn_final_real["disc_per_unit"] + df_grn_final_real["tax_unit"]
    df_grn_final_real["total_grn_row"] = df_grn_final_real["item_quantity"] * df_grn_final_real["net_price_unit"]
    total_grn = df_grn_final_real["total_grn_row"].sum()

    #df_grn_final_real["disc_per_unit"] = df_grn_finalReal["item_price"] * (df_grn_finalReal["item_discount"] / 100)
    #df_grn_final_real["tax_unit"] = (df_grn_final_real["item_price"] - df_grn_final_real["disc_per_unit"]) * (df_grn_final_real["item_tax1_percentage"] / 100)
    #df_grn_final_real["tax_unit"] = df_grn_final_real["item_tax1_value"] + df_grn_final_real["item_tax1_value"]
    #df_grn_final_real["net_price_unit"] = df_grn_final_real["item_price"] - df_grn_final_real["disc_per_unit"] + df_grn_final_real["tax_unit"]
    #df_grn_final_real["net_price_unit"] = df_grn_final_real["item_price"] - df_grn_final_real["disc_per_unit"]
    #df_grn_final_real["total_grn_row"] = df_grn_final_real["item_quantity"] * df_grn_final_real["net_price_unit"]
    total_grn = df_grn_final_real["total_grn_row"].sum()

    total_po_count = safe_unique_count(df_po_final_real, "transaction_number")
    total_po_balance_count = safe_unique_count(df_po_f, "No. PO")
    total_po_rows = len(df_po_final_real)
    total_po_balance_rows = len(df_po_f)
    total_grn_count = safe_unique_count(df_grn_final_real, "transaction_number")
    total_grn_balance_count = safe_unique_count(df_grn_f, "No. GRN")
    total_grn_rows = len(df_grn_final_real)
    total_grn_balance_rows = len(df_grn_f)

    avg_nominal_grn = safe_mean(df_grn_f, "Nominal")

    top_pic_po = get_top_pic(df_po_f, "PIC Purchasing", "No. PO")
    top_pic_grn = get_top_pic(df_grn_f, "PIC Purchasing", "No. GRN")
    #top_pic_pur = get_top_pic(df_pur_f, "PIC", "No. PUR")

    # ---------- LAYOUT ----------
    col_kiri, col_tengah, col_kanan = st.columns([1, 1, 1], gap="small")

    # =====================================================
    # LEFT - PO
    # =====================================================
    if selected_doc_type == "PO":
        with col_kiri:
            with st.container(border=True):
                st.subheader("📊 Detail PO")

                c1, c2 = st.columns(2)
                with c1:
                    metric_card("Total PO", f"Rp {total_po:,.0f}")
                with c2:
                    metric_card("PO Balance", f"Rp {total_po_unpr:,.0f}")

                c1, c2 = st.columns(2)
                with c1:
                    metric_card("Total Transaksi PO", f"{total_po_count:,}")
                with c2:
                    metric_card("Total Transaksi PO Balance", f"{total_po_balance_count:,}")


                #st.write("Kolom:", df_po_final_f.columns)
                #st.write("Contoh tanggal:", df_po_final_f["transaction_date"].head())
                #st.write(df_po_final_f[["item_price", "item_discount", "item_quantity"]].head())

                c1, c2, c3 = st.columns(3)
                with c1:
                    metric_card("Total Item PO", f"{total_po_rows:,}")
                with c2:
                    metric_card("Total Item PO Balance", total_po_balance_rows)
                with c3:
                    metric_card("PIC Terbanyak", top_pic_po)


                po_summary = summarize_status(df_po_f, doc_col="No. PO", nominal_col="Nominal")

                with st.container(border=True):
                    st.subheader("🍩 Proporsi Nominal PO Balance per Status")
                    render_status_pie(po_summary, "Persentase Distribusi Nominal PO Balance")

            pic_summary_po = summarize_pic_status(df_po_f, "PIC Purchasing", "No. PO")
            with st.container(border=True):
                st.subheader("👤 Analisis Transaksi PO Balance per PIC Purchasing & per Status")
                render_pic_bar(
                    summary_df=pic_summary_po,
                    x_col="PIC Purchasing",
                    y_col="Jumlah_Doc",
                    color_col="Status",
                )

            with st.container(border=True):
                st.subheader("🔥 Heatmap PO Balance - Aktivitas PIC Purchasing")
                render_pic_heatmap(df_po_f, "PIC Purchasing", "transaction_date", "No. PO", "Heatmap Aktivitas PIC Purchasing per Bulan")

            # Download PO Balance by status
            with st.container(border=True):
                st.subheader("📥 Download Data PO Balance (Periode & Status)")

                if not df_po_final_f.empty and "Status" in df_po_final_f.columns:
                    all_statuses = sorted([s for s in df_po_final_f["Status"].dropna().astype(str).unique().tolist() if s.strip()])
                    selected_statuses = st.multiselect(
                        "Pilih Status untuk di-download:",
                        all_statuses,
                        default=all_statuses,
                        key="po_balance_status_export"
                    )

                    df_download_po_balance = df_po_final_f[df_po_final_f["Status"].isin(selected_statuses)].copy()

                    if not df_download_po_balance.empty:
                        st.download_button(
                            label=f"⬇️Download {len(df_download_po_balance):,} Baris Data (Filtered).xlsx",
                            data=to_excel_bytes(df_download_po_balance, sheet_name="Data_PO"),
                            file_name=f"Data_PO_Export_{datetime.now().strftime('%Y%m%d')}.xlsx",
                            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                        )
                        st.caption(f"Menampilkan {len(df_download_po_balance):,} baris data yang akan di-download.")
                    else:
                        st.warning("Tidak ada data yang sesuai dengan filter yang dipilih.")
                else:
                    st.info("Data PO Balance tidak tersedia untuk export.")

            # Download per PIC PO Balance
            with st.container(border=True):
                st.subheader("📥 Download Data PO Balance per PIC")

                if not df_po_final_f.empty and "PIC Purchasing" in df_po_final_f.columns:
                    # Filter status hanya Need Approved, Approved, In Progress
                    df_filtered_status = df_po_final_f[
                        df_po_final_f["Status"].isin(["Need Approved", "Approved", "In Progress"])
                    ].copy()

                    # Tambahkan opsi "Semua"
                    options = ["Semua"] + sorted(
                        df_filtered_status["PIC Purchasing"].fillna("Unassigned").astype(str).unique().tolist()
                    )

                    selected_pic = st.selectbox("Pilih PIC Purchasing:", options, key="po_balance_pic_select")

                    # Jika pilih "Semua", ambil semua data sesuai status
                    if selected_pic == "Semua":
                        filtered = df_filtered_status.copy()
                    else:
                        filtered = df_filtered_status[
                            df_filtered_status["PIC Purchasing"].fillna("Unassigned").astype(str) == selected_pic
                        ].copy()

                    st.download_button(
                        label=f"⬇️Download Data {selected_pic}.xlsx",
                        data=to_excel_bytes(filtered, sheet_name="Data_PO_Balance"),
                        file_name=f"Data_PO_balance_{selected_pic}_{datetime.now().strftime('%Y%m%d')}.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                    )
                    st.caption(f"Menampilkan {len(filtered):,} baris data yang akan di-download.")
                else:
                    st.info("Data tidak tersedia untuk fitur download PO Balance per PIC.")

    # =====================================================
    # MID PR
    # =====================================================
        with col_tengah:

            # 🔹 Filter hanya PO yang sudah punya tanggal inprogress atau complete
            #Aging PO
            #df_po_final_valid = df_po_final_real[
            #df_po_final_real["date_inprogress"].notna() | df_po_final_real["date_complete"].notna()
            #].copy()
            df_po_final_valid = df_po_final_real[
            df_po_final_real["Status"].isin(["Approved", "In Progress", "Complete"])
            ].copy()
            df_po_final_valid = apply_search_filter(df_po_final_valid, search_number, search_status, search_pic)

            #Aging PO Balance
            # Filter PO Balance hanya untuk status aktif (exclude Complete & Draft)
            df_po_valid = df_po_final_f[
            ~df_po_final_f["Status"].isin(["Complete", "Draft"])
            ].copy()
            df_po_valid = apply_search_filter(df_po_valid, search_number, search_status, search_pic)


            # Lanjutkan proses aging hanya untuk PO yang valid
            #Aging PO
            #df_po_final_valid = calculate_aging(df_po_final_valid, "transaction_date")
            df_po_final_valid = calculate_aging(df_po_final_valid, "transaction_date", prefer="approved")
            df_po_final_valid = categorize_aging(df_po_final_valid)
            #Aging PO Balance
            #df_po_valid = calculate_aging(df_po_valid, "transaction_date")
            df_po_valid = calculate_aging(df_po_valid, "transaction_date", prefer="approved")
            df_po_valid = categorize_aging(df_po_valid)
            #df_po_valid = df_po_valid.drop_duplicates(subset=["transaction_number"])

            # Filter hanya PO valid aktif, exclude Draft
            df_po_final_valid = df_po_final_valid[
            ~df_po_final_valid["Status"].str.contains("Draft", case=False, na=False)
            ].copy()
            # Filter hanya PO aktif, exclude Draft
            #df_po_valid = df_po_valid[
            #~df_po_valid["Status"].str.contains("Draft", case=False, na=False)
            #].copy()

            with st.container(border=True):
                st.subheader("⏳ Distribusi Aging PO")
                render_aging_bar(df_po_final_valid, "transaction_number", chart_key="aging_po")

            with st.container(border=True):
                st.subheader("⏳ Distribusi Aging PO Balance")
                render_aging_bar(df_po_valid, "transaction_number", chart_key="aging_po_outstanding")

                pic_aging_summary = summarize_pic_aging(df_po_valid, "PIC Purchasing", "transaction_number")
                pic_aging_summary_final = summarize_pic_aging(df_po_final_valid, "PIC Purchasing", "transaction_number")

            with st.container(border=True):
                st.subheader("👥 Rata-rata Proses PO")
                #st.dataframe(pic_aging_summary, use_container_width=True, hide_index=True)
                render_pic_aging_bar(pic_aging_summary_final)

            with st.container(border=True):
                st.subheader("👥 Rata-rata Proses PO Balance")
                #st.dataframe(pic_aging_summary, use_container_width=True, hide_index=True)
                render_pic_aging_bar(pic_aging_summary)

            # Download per Category PR Aging
            with st.container(border=True):
                st.subheader("📥 Download Data per Categori Aging PO")

                if not df_po_final_valid.empty:
                    # Filter data aging PO berdasarkan kategori yang dipilih
                    selected_category_po = st.selectbox(
                        "Pilih kategori aging PO untuk diunduh 📂",
                        ["Semua", "0-30 hari", "31-60 hari", "61-90 hari", ">90 hari"]
                    )

                    # Jika bukan 'Semua', filter sesuai kategori
                    if selected_category_po != "Semua":
                        df_po_filtered = df_po_final_valid[
                            df_po_final_valid["Aging Category"] == selected_category_po
                        ].copy()
                    else:
                        df_po_filtered = df_po_final_valid.copy()

                    # Tombol download
                    st.download_button(
                    label=f"⬇️Download Data PO Aging ({selected_category_po})",
                    data=to_excel_bytes(df_po_filtered, sheet_name="PO Aging"),
                    file_name=f"PO_Aging_{selected_category_po.replace(' ', '_')}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    key=f"download_po_aging_{selected_category_po}"   # 🔹 key unik
                    )

                else:
                    st.info("Data tidak tersedia untuk fitur download per Category Aging PO.")

            # Download per Category PO Balance Aging
            with st.container(border=True):
                st.subheader("📥 Download Data per Categori Aging PO Balance")

                if not df_po_valid.empty:
                    # Filter data aging PO berdasarkan kategori yang dipilih
                    selected_category_balance = st.selectbox(
                        "Pilih kategori aging PO Balance untuk diunduh 📂",
                        ["Semua", "0-30 hari", "31-60 hari", "61-90 hari", ">90 hari"]
                    )

                    # Jika bukan 'Semua', filter sesuai kategori
                    if selected_category_balance != "Semua":
                        df_balance_filtered = df_po_valid[
                            df_po_valid["Aging Category"] == selected_category_balance
                        ].copy()
                    else:
                        df_balance_filtered = df_po_valid.copy()

                    # Tombol download
                    st.download_button(
                    label=f"⬇️Download Data PO Balance Aging ({selected_category_balance})",
                    data=to_excel_bytes(df_balance_filtered, sheet_name="PO Balance Aging"),
                    file_name=f"PO_Balance_Aging_{selected_category_balance.replace(' ', '_')}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    key=f"download_po_balance_{selected_category_balance}"   # 🔹 key unik
                    )

                else:
                    st.info("Data tidak tersedia untuk fitur download per Category Aging PO Balance.")


    # =====================================================
    # RIGHT - PO
    # =====================================================
        with col_kanan:
            with st.container(border=True):
                st.subheader("📏 SLA Compliance PO")
                render_sla_gauge(df_po_final_valid, threshold=5, title="SLA Compliance PO")

            with st.container(border=True):
                st.subheader("📏 SLA Compliance PO Balance")
                render_sla_gauge(df_po_valid, threshold=5, title="SLA Compliance PO Balance")

            pic_sla_summary = summarize_pic_sla(df_po_final_valid, "PIC Purchasing", "transaction_number", threshold=5)

            with st.container(border=True):
                st.subheader("📏 SLA Compliance per PIC Purchasing")
                #st.dataframe(pic_sla_summary, use_container_width=True, hide_index=True)
                render_pic_sla_bar(pic_sla_summary)

            with st.container(border=True):
                st.subheader("📈 Trend SLA")
                render_sla_trend(df_po_final_valid, threshold=5, date_col="transaction_date")


            # Download PO by period & status
            with st.container(border=True):
                st.subheader("📥 Download Data PO (Periode & Status)")

                if not df_po_final_real.empty and "Status" in df_po_final_real.columns:
                    all_statuses = sorted([s for s in df_po_final_real["Status"].dropna().astype(str).unique().tolist() if s.strip()])
                    selected_statuses = st.multiselect(
                        "Pilih Status untuk di-download:",
                        all_statuses,
                        default=all_statuses,
                        key="po_status_export"
                    )

                    df_download = df_po_final_real[df_po_final_real["Status"].isin(selected_statuses)].copy()

                    if not df_download.empty:
                        st.download_button(
                            label=f"⬇️Download {len(df_download):,} Baris Data (Filtered).xlsx",
                            data=to_excel_bytes(df_download, sheet_name="Data_PO"),
                            file_name=f"Data_PO_Export_{datetime.now().strftime('%Y%m%d')}.xlsx",
                            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                            key=f"download {len(df_download):,} Baris Data (Filtered)"   # 🔹 key unik
                        )
                        st.caption(f"Menampilkan {len(df_download):,} baris data yang akan di-download.")
                    else:
                        st.warning("Tidak ada data yang sesuai dengan filter yang dipilih.")
                else:
                    st.info("Data PO tidak tersedia untuk export.")

            # Download per PIC PO
            with st.container(border=True):
                st.subheader("📥 Download Data PO per PIC")

                if not df_po_final_real.empty and "PIC Purchasing" in df_po_final_real.columns:
                    # Filter status hanya Need Approved, Approved, In Progress
                    df_filtered_status = df_po_final_real[
                        df_po_final_real["Status"].isin(["Approved", "In Progress", "Complete"])
                    ].copy()

                    # Tambahkan opsi "Semua"
                    options = ["Semua"] + sorted(
                        df_filtered_status["PIC Purchasing"].fillna("Unassigned").astype(str).unique().tolist()
                    )

                    selected_pic = st.selectbox("Pilih PIC Purchasing:", options, key="po_pic_select")

                    # Jika pilih "Semua", ambil semua data sesuai status
                    if selected_pic == "Semua":
                        filtered = df_filtered_status.copy()
                    else:
                        filtered = df_filtered_status[
                            df_filtered_status["PIC Purchasing"].fillna("Unassigned").astype(str) == selected_pic
                        ].copy()

                    st.download_button(
                        label=f"⬇️Download Data {selected_pic}.xlsx",
                        data=to_excel_bytes(filtered, sheet_name="Data_PO"),
                        file_name=f"Data_PO_{selected_pic}_{datetime.now().strftime('%Y%m%d')}.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                    )
                    st.caption(f"Menampilkan {len(filtered):,} baris data yang akan di-download.")
                else:
                    st.info("Data tidak tersedia untuk fitur download PO Balance per PIC.")


    # =====================================================
    # LEFT - GRN
    # =====================================================
    elif selected_doc_type == "GRN":
        with col_kiri:
            with st.container(border=True):
                st.subheader("📊 Detail GRN")

                c1, c2 = st.columns(2)
                with c1:
                    metric_card("Total GRN", f"Rp {total_grn:,.0f}")
                with c2:
                    metric_card("GRN Balance", f"Rp {total_grn_unpr:,.0f}")

                c1, c2 = st.columns(2)
                with c1:
                    metric_card("Total Transaksi GRN", f"{total_grn_count:,}")
                with c2:
                    metric_card("Total Transaksi GRN Balance", f"{total_grn_balance_count:,}")


                #st.write("Kolom:", df_po_final_f.columns)
                #st.write("Contoh tanggal:", df_po_final_f["transaction_date"].head())
                #st.write(df_po_final_f[["item_price", "item_discount", "item_quantity"]].head())

                c1, c2, c3 = st.columns(3)
                with c1:
                    metric_card("Total Item GRN", f"{total_grn_rows:,}")
                with c2:
                    metric_card("Total Item GRN Balance", total_grn_balance_rows)
                with c3:
                    metric_card("PIC Terbanyak", top_pic_grn)


                do_summary = summarize_status(df_grn_f, doc_col="No. GRN", nominal_col="Nominal")

                with st.container(border=True):
                    st.subheader("🍩 Proporsi Nominal GRN Balance per Status")
                    render_status_pie(do_summary, "Persentase Distribusi Nominal GRN Balance")

            pic_summary_do = summarize_pic_status(df_grn_f, "PIC Purchasing", "No. GRN")
            with st.container(border=True):
                st.subheader("👤 Analisis Transaksi GRN Balance per PIC Purchasing & per Status")
                render_pic_bar(
                    summary_df=pic_summary_do,
                    x_col="PIC Purchasing",
                    y_col="Jumlah_Doc",
                    color_col="Status",
                )

            with st.container(border=True):
                st.subheader("🔥 Heatmap GRN Balance - Aktivitas PIC Purchasing")
                render_pic_heatmap(df_grn_f, "PIC Purchasing", "transaction_date", "No. GRN", "Heatmap Aktivitas PIC Purchasing per Bulan")

            # Download GRN Balance by status
            with st.container(border=True):
                st.subheader("📥 Download Data GRN Balance (Periode & Status)")

                if not df_grn_final_f.empty and "Status" in df_grn_final_f.columns:
                    all_statuses = sorted([s for s in df_grn_final_f["Status"].dropna().astype(str).unique().tolist() if s.strip()])
                    selected_statuses = st.multiselect(
                        "Pilih Status untuk di-download:",
                        all_statuses,
                        default=all_statuses,
                        key="grn_balance_status_export"
                    )

                    df_download_grn_balance = df_grn_final_f[df_grn_final_f["Status"].isin(selected_statuses)].copy()

                    if not df_download_grn_balance.empty:
                        st.download_button(
                            label=f"⬇️Download {len(df_download_grn_balance):,} Baris Data (Filtered).xlsx",
                            data=to_excel_bytes(df_download_grn_balance, sheet_name="Data_GRN"),
                            file_name=f"Data_GRN_Export_{datetime.now().strftime('%Y%m%d')}.xlsx",
                            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                        )
                        st.caption(f"Menampilkan {len(df_download_grn_balance):,} baris data yang akan di-download.")
                    else:
                        st.warning("Tidak ada data yang sesuai dengan filter yang dipilih.")
                else:
                    st.info("Data GRN Balance tidak tersedia untuk export.")

            # Download per PIC GRN Balance
            with st.container(border=True):
                st.subheader("📥 Download Data GRN Balance per PIC")

                if not df_grn_final_f.empty and "PIC Purchasing" in df_grn_final_f.columns:
                    # Filter status hanya Need Approved, Approved, In Progress
                    df_filtered_status = df_grn_final_f[
                        df_grn_final_f["Status"].isin(["Need Approved", "Approved", "In Progress"])
                    ].copy()

                    # Tambahkan opsi "Semua"
                    options = ["Semua"] + sorted(
                        df_filtered_status["PIC Purchasing"].fillna("Unassigned").astype(str).unique().tolist()
                    )

                    selected_pic = st.selectbox("Pilih PIC Purchasing:", options, key="grn_balance_pic_select")

                    # Jika pilih "Semua", ambil semua data sesuai status
                    if selected_pic == "Semua":
                        filtered = df_filtered_status.copy()
                    else:
                        filtered = df_filtered_status[
                            df_filtered_status["PIC Purchasing"].fillna("Unassigned").astype(str) == selected_pic
                        ].copy()

                    st.download_button(
                        label=f"⬇️Download Data {selected_pic}.xlsx",
                        data=to_excel_bytes(filtered, sheet_name="Data_GRN_Balance"),
                        file_name=f"Data_GRN_balance_{selected_pic}_{datetime.now().strftime('%Y%m%d')}.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                    )
                    st.caption(f"Menampilkan {len(filtered):,} baris data yang akan di-download.")
                else:
                    st.info("Data tidak tersedia untuk fitur download GRN Balance per PIC.")

    # =====================================================
    # MID GRN
    # =====================================================
        with col_tengah:

            # 🔹 Filter hanya GRN yang sudah punya tanggal inprogress atau complete
            #Aging GRN
            df_grn_final_valid = df_grn_final_real[
            df_grn_final_real["Status"].isin(["Approved", "In Progress", "Complete"])
            ].copy()
            df_grn_final_valid = apply_search_filter(df_grn_final_valid, search_number, search_status, search_pic)

            #Aging GRN Balance
            # Filter GRN Balance hanya untuk status aktif (exclude Complete & Draft)
            df_grn_valid = df_grn_final_f[
            ~df_grn_final_f["Status"].isin(["Complete", "Draft"])
            ].copy()
            df_grn_valid = apply_search_filter(df_grn_valid, search_number, search_status, search_pic)


            # Lanjutkan proses aging hanya untuk GRN yang valid
            #Aging GRN
            df_grn_final_valid = calculate_aging(df_grn_final_valid, "transaction_date", prefer="approved")
            df_grn_final_valid = categorize_aging(df_grn_final_valid)
            #Aging GRN Balance
            df_grn_valid = calculate_aging(df_grn_valid, "transaction_date", prefer="approved")
            df_grn_valid = categorize_aging(df_grn_valid)

            # Filter hanya GRN valid aktif, exclude Draft
            df_grn_final_valid = df_grn_final_valid[
            ~df_grn_final_valid["Status"].str.contains("Draft", case=False, na=False)
            ].copy()

            with st.container(border=True):
                st.subheader("⏳ Distribusi Aging GRN")
                render_aging_bar(df_grn_final_valid, "transaction_number", chart_key="aging_grn")

            with st.container(border=True):
                st.subheader("⏳ Distribusi Aging GRN Balance")
                render_aging_bar(df_grn_valid, "transaction_number", chart_key="aging_grn_outstanding")


                pic_aging_summary_grn = summarize_pic_aging(df_grn_valid, "PIC Purchasing", "transaction_number")
                pic_aging_summary_final_grn = summarize_pic_aging(df_grn_final_valid, "PIC Purchasing", "transaction_number")

            with st.container(border=True):
                st.subheader("👥 Rata-rata Proses GRN")
                #st.dataframe(pic_aging_summary, use_container_width=True, hide_index=True)
                render_pic_aging_bar(pic_aging_summary_final_grn)

            with st.container(border=True):
                st.subheader("👥 Rata-rata Proses GRN Balance")
                #st.dataframe(pic_aging_summary, use_container_width=True, hide_index=True)
                render_pic_aging_bar(pic_aging_summary_grn)


            # Download per Category GRN Aging
            with st.container(border=True):
                st.subheader("📥 Download Data per Categori Aging GRN")

                if not df_grn_final_valid.empty:
                    # Filter data aging GRN berdasarkan kategori yang dipilih
                    selected_category_grn = st.selectbox(
                        "Pilih kategori aging GRN untuk diunduh 📂",
                        ["Semua", "0-30 hari", "31-60 hari", "61-90 hari", ">90 hari"]
                    )

                    # Jika bukan 'Semua', filter sesuai kategori
                    if selected_category_grn != "Semua":
                        df_grn_filtered = df_grn_final_valid[
                            df_grn_final_valid["Aging Category"] == selected_category_grn
                        ].copy()
                    else:
                        df_grn_filtered = df_grn_final_valid.copy()

                    # Tombol download
                    st.download_button(
                    label=f"⬇️Download Data GRN Aging ({selected_category_grn})",
                    data=to_excel_bytes(df_grn_filtered, sheet_name="GRN Aging"),
                    file_name=f"GRN_Aging_{selected_category_grn.replace(' ', '_')}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    key=f"download_grn_aging_{selected_category_grn}"   # 🔹 key unik
                    )

                else:
                    st.info("Data tidak tersedia untuk fitur download per Category Aging GRN.")

            # Download per Category GRN Balance Aging
            with st.container(border=True):
                st.subheader("📥 Download Data per Categori Aging GRN Balance")

                if not df_grn_valid.empty:
                    # Filter data aging GRN berdasarkan kategori yang dipilih
                    selected_category_grn_balance = st.selectbox(
                        "Pilih kategori aging GRN Balance untuk diunduh 📂",
                        ["Semua", "0-30 hari", "31-60 hari", "61-90 hari", ">90 hari"]
                    )

                    # Jika bukan 'Semua', filter sesuai kategori
                    if selected_category_grn_balance != "Semua":
                        df_balance_grn_filtered = df_grn_valid[
                            df_grn_valid["Aging Category"] == selected_category_grn_balance
                        ].copy()
                    else:
                        df_balance_grn_filtered = df_grn_valid.copy()

                    # Tombol download
                    st.download_button(
                    label=f"⬇️Download Data GRN Balance Aging ({selected_category_grn_balance})",
                    data=to_excel_bytes(df_balance_grn_filtered, sheet_name="GRN Balance Aging"),
                    file_name=f"GRN_Balance_Aging_{selected_category_grn_balance.replace(' ', '_')}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    key=f"download_grn_balance_{selected_category_grn_balance}"   # 🔹 key unik
                    )

                else:
                    st.info("Data tidak tersedia untuk fitur download per Category Aging GRN Balance.")

    # =====================================================
    # RIGHT - DO
    # =====================================================
        with col_kanan:
            with st.container(border=True):
                st.subheader("📏 SLA Compliance GRN")
                render_sla_gauge(df_grn_final_valid, threshold=5, title="SLA Compliance GRN")

            with st.container(border=True):
                st.subheader("📏 SLA Compliance GRN Balance")
                render_sla_gauge(df_grn_valid, threshold=5, title="SLA Compliance GRN Balance")

            pic_sla_summary_grn = summarize_pic_sla(df_grn_final_valid, "PIC Purchasing", "transaction_number", threshold=5)

            with st.container(border=True):
                st.subheader("📏 SLA Compliance per PIC Purchasing")
                #st.dataframe(pic_sla_summary, use_container_width=True, hide_index=True)
                render_pic_sla_bar(pic_sla_summary_grn)

            with st.container(border=True):
                st.subheader("📈 Trend SLA")
                render_sla_trend(df_grn_final_valid, threshold=5, date_col="transaction_date")


            # Download GRN by period & status
            with st.container(border=True):
                st.subheader("📥 Download Data GRN (Periode & Status)")

                if not df_grn_final_valid.empty and "Status" in df_grn_final_valid.columns:
                    all_statuses_grn = sorted([s for s in df_grn_final_valid["Status"].dropna().astype(str).unique().tolist() if s.strip()])
                    selected_statuses_grn = st.multiselect(
                        "Pilih Status untuk di-download:",
                        all_statuses_grn,
                        default=all_statuses_grn,
                        key="grn_status_export"
                    )

                    df_download_grn = df_grn_final_valid[df_grn_final_valid["Status"].isin(selected_statuses_grn)].copy()

                    if not df_download_grn.empty:
                        st.download_button(
                            label=f"⬇️Download {len(df_download_grn):,} Baris Data (Filtered).xlsx",
                            data=to_excel_bytes(df_download_grn, sheet_name="Data_GRN"),
                            file_name=f"Data_GRN_Export_{datetime.now().strftime('%Y%m%d')}.xlsx",
                            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                            key=f"download {len(df_download_grn):,} Baris Data (Filtered)"   # 🔹 key unik
                        )
                        st.caption(f"Menampilkan {len(df_download_grn):,} baris data yang akan di-download.")
                    else:
                        st.warning("Tidak ada data yang sesuai dengan filter yang dipilih.")
                else:
                    st.info("Data GRN tidak tersedia untuk export.")

            # Download per PIC GRN
            with st.container(border=True):
                st.subheader("📥 Download Data GRN per PIC")

                if not df_grn_final_valid.empty and "PIC Purchasing" in df_grn_final_valid.columns:
                    # Filter status hanya Need Approved, Approved, In Progress
                    df_filtered_status_grn = df_grn_final_valid[
                        df_grn_final_valid["Status"].isin(["Approved", "In Progress", "Complete"])
                    ].copy()

                    # Tambahkan opsi "Semua"
                    options = ["Semua"] + sorted(
                        df_filtered_status_grn["PIC Purchasing"].fillna("Unassigned").astype(str).unique().tolist()
                    )

                    selected_pic_grn = st.selectbox("Pilih PIC Purchasing:", options, key="pr_pic_select")

                    # Jika pilih "Semua", ambil semua data sesuai status
                    if selected_pic_grn == "Semua":
                        filtered_grn = df_filtered_status_grn.copy()
                    else:
                        filtered_grn = df_filtered_status_grn[
                            df_filtered_status_grn["PIC Purchasing"].fillna("Unassigned").astype(str) == selected_pic_grn
                        ].copy()

                    st.download_button(
                        label=f"⬇️Download Data {selected_pic_grn}.xlsx",
                        data=to_excel_bytes(filtered_grn, sheet_name="Data_GRN"),
                        file_name=f"Data_GRN_{selected_pic_grn}_{datetime.now().strftime('%Y%m%d')}.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                    )
                    st.caption(f"Menampilkan {len(filtered_grn):,} baris data yang akan di-download.")
                else:
                    st.info("Data tidak tersedia untuk fitur download GRN Balance per PIC.")


    # =====================================================
    # CRUD langsung ke df_po_final_valid
    # =====================================================

    elif selected_doc_type == "CRUD":
    st.subheader("📌 CRUD ETA & Deadline")

    # Ambil data dari API
    df_po_api = df_po_final_f[
        ~df_po_final_f["Status"].isin(["Complete", "Draft"])
    ].copy()
    df_po_api = apply_search_filter(df_po_api, search_number, search_status, search_pic)

    if "transaction_number" in df_po_api.columns:
        df_po_api["Nomor_Dokumen"] = df_po_api["transaction_number"].astype(str).str.strip()

    # Ambil data ETA dari SQLite
    init_db()
    df_po_eta = load_eta_data()

    # Merge data API dan ETA
    df_po_ed = pd.merge(df_po_api, df_po_eta, on="Nomor_Dokumen", how="left")

    # Form CRUD
    with st.form("form_eta_deadline"):
        nomor_dokumen = st.text_input("Nomor Dokumen")
        pic = st.text_input("PIC")
        eta_po = st.date_input("ETA PO", value=None)
        deadline_do = st.date_input("Deadline DO", value=None)
        deadline_si = st.date_input("Deadline SI", value=None)

        simpan = st.form_submit_button("Simpan")
        hapus = st.form_submit_button("Hapus Data")

        if simpan:
            save_eta_data(nomor_dokumen, pic, eta_po, deadline_do, deadline_si)
            st.success(f"Data ETA/Deadline untuk dokumen {nomor_dokumen} berhasil disimpan.")
            df_po_eta = load_eta_data()

        if hapus:
            delete_eta_data(nomor_dokumen)
            st.success(f"Data untuk dokumen {nomor_dokumen} berhasil dihapus.")
            df_po_eta = load_eta_data()

        # Merge ulang setelah simpan/hapus
        df_po_ed = pd.merge(df_po_api, df_po_eta, on="Nomor_Dokumen", how="left")

    # ✅ Pisahkan tabel sudah diisi vs belum diisi
    df_sudah = df_po_ed.dropna(subset=["ETA_PO","Deadline_DO","Deadline_SI"], how="any")
    df_belum = df_po_ed[df_po_ed[["ETA_PO","Deadline_DO","Deadline_SI"]].isna().any(axis=1)]

    st.write("📄 Data ETA & Deadline **Sudah Diisi**:")
    st.dataframe(df_sudah[["Nomor_Dokumen","PIC","ETA_PO","Deadline_DO","Deadline_SI"]],
                 use_container_width=True)

    st.write("📄 Data ETA & Deadline **Belum Diisi**:")
    st.dataframe(df_belum[["Nomor_Dokumen","PIC"]],
                 use_container_width=True)


    # ---------- FOOTER INFO ----------
    with st.expander("ℹ️ Informasi Teknis Dashboard"):
        selected_report_date = (
            selected_date_range[1]
            if isinstance(selected_date_range, (tuple, list)) and len(selected_date_range) == 2
            else date.today()
        )

        st.markdown(
            f"""
- **Base URL:** `{BASE_URL}`
- **Timeout Request:** `{REQUEST_TIMEOUT}` detik
- **Tanggal report sampai:** `{selected_report_date}`
- **Mode filter tanggal:** kumulatif (semua data sampai tanggal akhir)
- **Cache API:** 600 detik
            """
        )


if __name__ == "__main__":
    main()