"""Streamlit UI — Lokerblog.com Scraper.

Perbaikan:
  #1  Progress bar tidak melompat mundur (discovery 0-40%, scrape 40-100%).
  #7  Warning jika ada baris yang gagal di-scrape.
"""

import io
from datetime import date

import pandas as pd
import streamlit as st

from scraper import discover_urls, scrape_all

st.set_page_config(page_title="Loker Scraper", layout="wide")
st.title("🔍 Lokerblog.com Scraper")

EDU_OPTIONS = ["SMA/SMK", "D1", "D2", "D3", "D4", "S1", "S2", "S3"]

# ----- Sidebar -----
with st.sidebar:
    st.header("⚙️ Filter")
    start = st.date_input("Tanggal Mulai", value=date(2026, 1, 1))
    end = st.date_input("Tanggal Akhir", value=date(2026, 11, 30))
    st.caption("Filter tanggal memakai `lastmod` sitemap (≈ tanggal posting).")
    run = st.button("🚀 Mulai Scrape", type="primary", use_container_width=True)


# ----- Phase 1: Discovery + Scrape -----
if run:
    if start > end:
        st.error("Tanggal mulai harus ≤ tanggal akhir.")
        st.stop()

    progress = st.progress(0, text="Memulai...")
    status = st.empty()

    # Discovery: 0% → 40%
    def cb_discover(msg, pct):
        status.info(msg)
        progress.progress(int(pct * 100), text=msg)

    entries = discover_urls(start, end, progress_cb=cb_discover)
    st.success(f"✅ Discovery: **{len(entries)}** URL dalam rentang tanggal")

    if not entries:
        st.stop()

    # Scraping: 40% → 100%  (#1 fix: tidak melompat mundur)
    def cb_scrape(i, total, url):
        pct = 40 + int(60 * i / total)
        progress.progress(pct, text=f"Scraping {i}/{total}: …{url[-50:]}")
        status.info(f"Mengambil detail {i}/{total}")

    results = scrape_all(entries, progress_cb=cb_scrape)
    progress.progress(100, text="Selesai")
    st.session_state["raw_df"] = pd.DataFrame(results)
    status.success(f"✅ Selesai: {len(results)} lowongan diproses")


# ----- Phase 2: Preview + Filter + Export -----
if "raw_df" in st.session_state:
    df = st.session_state["raw_df"].copy()
    st.markdown("---")
    st.subheader(f"📊 Hasil Scraping — {len(df)} baris")

    # #7: peringatan untuk baris yang gagal
    if "error" in df.columns:
        n_err = df["error"].notna().sum()
        if n_err:
            st.warning(
                f"⚠️ **{n_err}** URL gagal di-scrape. "
                f"Cek kolom `error` di tabel untuk detail."
            )

    # Filter pendidikan
    selected = st.multiselect(
        "Filter pendidikan (kosongkan = tampil semua)",
        EDU_OPTIONS, key="edu_filter",
    )
    if selected:
        mask = df["education_levels"].apply(
            lambda x: isinstance(x, list) and any(e in x for e in selected)
        )
        filtered = df[mask]
    else:
        filtered = df

    st.caption(f"Menampilkan **{len(filtered)}** lowongan")
    st.dataframe(filtered, use_container_width=True)

    # ----- Export -----
    st.markdown("### 📥 Export")
    export_df = filtered.copy()
    for col in ("education_levels", "labels"):
        if col in export_df.columns:
            export_df[col] = export_df[col].apply(
                lambda x: ", ".join(x) if isinstance(x, list) else ""
            )

    c1, c2 = st.columns(2)
    with c1:
        st.download_button(
            "⬇️ Download CSV",
            export_df.to_csv(index=False).encode("utf-8"),
            file_name="loker_data.csv",
            mime="text/csv",
            use_container_width=True,
        )
    with c2:
        buf = io.BytesIO()
        with pd.ExcelWriter(buf, engine="openpyxl") as w:
            export_df.to_excel(w, sheet_name="Lowongan", index=False)
            if "company_name" in export_df.columns:
                summary = (
                    export_df.groupby("company_name")
                    .size()
                    .reset_index(name="jumlah")
                    .sort_values("jumlah", ascending=False)
                )
                summary.to_excel(w, sheet_name="Ringkasan", index=False)
        st.download_button(
            "⬇️ Download Excel",
            buf.getvalue(),
            file_name="loker_data.xlsx",
            mime=(
                "application/vnd.openxmlformats-officedocument."
                "spreadsheetml.sheet"
            ),
            use_container_width=True,
        )