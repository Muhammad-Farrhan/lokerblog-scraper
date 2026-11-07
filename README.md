# Lokerblog Scraper

Aplikasi berbasis Streamlit untuk melakukan scraping lowongan kerja dari Lokerblog.com berdasarkan rentang tanggal dan filter pendidikan.

## Fitur
- Discovery URL via Sitemap (Early-stop mechanism)
- Filter tanggal (lastmod) dan pendidikan (SMA/SMK, D3, S1, dll)
- Export hasil ke CSV dan Excel

## Cara Menjalankan
1. `pip install -r requirements.txt`
2. `streamlit run app.py`
