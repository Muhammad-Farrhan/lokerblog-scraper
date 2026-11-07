"""Scraper lokerblog.com — sitemap-driven, tanpa database.

Perbaikan dibanding versi sebelumnya:
  #2  _extract_location  → anchor lebih spesifik, tidak over-capture.
  #3  _extract_company   → 3 pola alternatif, mendukung BUMN/BPJS/Bank/dll.
  #4  _extract_education → canonical mapping (SMA/SMK satu entri).
  #5  scrape_all         → progress callback dipanggil setelah fetch.
"""

import re
import time
from datetime import date, datetime

import requests
from bs4 import BeautifulSoup

SITEMAP_INDEX = "https://www.lokerblog.com/sitemap.xml"
USER_AGENT = "LokerScraper/1.0 (educational; contact@example.com)"
HEADERS = {"User-Agent": USER_AGENT}
TIMEOUT = 15
DELAY = 1.0  # detik antar request

MONTHS = {
    "januari": 1, "februari": 2, "maret": 3, "april": 4, "mei": 5, "juni": 6,
    "juli": 7, "agustus": 8, "september": 9, "oktober": 10,
    "november": 11, "desember": 12,
}

# --- Kanonikalisasi pendidikan (#4) ---
# Label "SMA/SMK", "SMA", "SMK", "SMU" semuanya dipetakan ke satu entri "SMA/SMK".
EDU_CANONICAL = {
    "SMA": "SMA/SMK", "SMK": "SMA/SMK", "SMU": "SMA/SMK", "SMA/SMK": "SMA/SMK",
    "D1": "D1", "D2": "D2", "D3": "D3", "D4": "D4",
    "S1": "S1", "S2": "S2", "S3": "S3",
}

# Pola fallback dari body text (dipakai saat label tidak lengkap).
EDU_PATTERNS = {
    "SMA/SMK": r"\b(SMA|SMK|SMU)(?:[/\s]*(?:SMA|SMK|SMU))?\b",
    "D1":      r"\bD1\b|\bDiploma\s*1\b",
    "D2":      r"\bD2\b|\bDiploma\s*2\b",
    "D3":      r"\bD3\b|\bDiploma\s*3\b",
    "D4":      r"\bD4\b|\bDiploma\s*4\b",
    "S1":      r"\bS1\b|\bSarjana\b",
    "S2":      r"\bS2\b|\bMagister\b",
    "S3":      r"\bS3\b|\bDoktor\b",
}


# ---------- HTTP ----------
def _fetch(url):
    r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
    r.raise_for_status()
    return r.text


# ---------- Sitemap ----------
def _parse_index(xml):
    soup = BeautifulSoup(xml, "xml")
    return [loc.text.strip() for loc in soup.find_all("loc")]


def _parse_urlset(xml):
    soup = BeautifulSoup(xml, "xml")
    out = []
    for u in soup.find_all("url"):
        loc = u.find("loc")
        lm = u.find("lastmod")
        if loc:
            out.append({
                "loc": loc.text.strip(),
                "lastmod": lm.text.strip() if lm else None,
            })
    return out


def _parse_date(s):
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def discover_urls(start, end, progress_cb=None, safety_margin=2):
    """Kembalikan list {loc, lastmod} yang lastmod ∈ [start, end].

    Early-stop aktif setelah `safety_margin` halaman berturut-turut tanpa hit,
    ATAU ketika semua lastmod di halaman < start_date.
    """
    if progress_cb:
        progress_cb("Memuat sitemap index...", 0.02)
    subs = _parse_index(_fetch(SITEMAP_INDEX))
    total = len(subs)
    results, hits, miss_streak = [], 0, 0

    for i, sub in enumerate(subs, 1):
        if progress_cb:
            # Skala 2%..40% untuk discovery (lihat app.py)
            progress_cb(
                f"Fetch sub-sitemap {i}/{total}...",
                0.02 + 0.38 * i / total,
            )
        try:
            entries = _parse_urlset(_fetch(sub))
        except Exception as e:
            print(f"[warn] {sub}: {e}")
            continue
        finally:
            time.sleep(DELAY)

        page_hit = 0
        max_lm = None
        for e in entries:
            d = _parse_date(e["lastmod"])
            if d is None:
                continue
            max_lm = d if max_lm is None else max(max_lm, d)
            if start <= d <= end:
                results.append(e)
                page_hit += 1

        if page_hit:
            hits += page_hit
            miss_streak = 0
        else:
            miss_streak += 1

        if hits > 0 and miss_streak > safety_margin:
            print(f"[info] early-stop page {i} (tidak ada hit {safety_margin} page)")
            break
        if max_lm is not None and max_lm < start:
            print(f"[info] early-stop page {i} (semua < start_date)")
            break

    return results


# ---------- Detail parser ----------
def _extract_date(soup, text, lastmod):
    t = soup.find("time")
    if t and t.get("datetime"):
        try:
            return datetime.fromisoformat(
                t["datetime"].replace("Z", "+00:00")
            ).date()
        except ValueError:
            pass
    for m in re.finditer(r"(\w+)\s+(\d{1,2}),\s+(\d{4})", text):
        name, d, y = m.group(1).lower(), int(m.group(2)), int(m.group(3))
        if name in MONTHS:
            try:
                return date(y, MONTHS[name], d)
            except ValueError:
                continue
    return lastmod


def _extract_company(body):
    """#3: tiga pola alternatif, mendukung BUMN/BPJS/Bank/Kementerian/dll."""
    if body is None:
        return None

    PATTERNS = [
        # Prioritas 1: heading "Lowongan Kerja [apapun] Terbaru {Nama} Tahun YYYY"
        r"Lowongan\s+Kerja(?:\s+\w+)*?\s+Terbaru\s+(.+?)\s+Tahun\s+\d{4}",
        # Prioritas 2: heading "Lowongan Kerja [apapun] Terbaru {Nama} {Bulan} YYYY"
        (r"Lowongan\s+Kerja(?:\s+\w+)*?\s+Terbaru\s+(.+?)\s+"
         r"(?:Januari|Februari|Maret|April|Mei|Juni|Juli|Agustus|"
         r"September|Oktober|November|Desember)\s+\d{4}"),
        # Prioritas 3: "Lowongan Kerja {Nama} - " di paragraf pertama
        (r"Lowongan\s+Kerja\s+"
         r"((?:PT|CV|Bank|BPJS|Komnas|Kementerian|Badan|Lembaga|Perum|"
         r"Direktorat|Otoritas|Sekretariat|Rumah\s+Sakit|Institut|"
         r"Universitas|Dinas|Pemerintah)\s+[^\-]{2,80}?)\s+-\s+"),
    ]

    # Coba dari heading dulu (pola 1 & 2 lebih akurat).
    for h in body.find_all(["h2", "h3", "h4"]):
        text = h.get_text(" ", strip=True)
        for pat in PATTERNS[:2]:
            m = re.search(pat, text, re.I)
            if m:
                return m.group(1).strip()

    # Fallback: seluruh body (pola 3 untuk yang diawali PT/Bank/etc).
    full = body.get_text(" ", strip=True)
    for pat in PATTERNS:
        m = re.search(pat, full, re.I)
        if m:
            return m.group(1).strip()
    return None


def _extract_position(body):
    if body is None:
        return None
    for tag in body.find_all(["b", "strong", "h3", "h4"]):
        txt = tag.get_text(" ", strip=True)
        if "posisi" in txt.lower() and len(txt) < 30:
            nxt = tag.find_next(["p", "div"])
            if nxt:
                val = nxt.get_text(" ", strip=True)
                if val:
                    return val
    m = re.search(r"Posisi\s*:?\s*\n+\s*(.+)",
                  body.get_text("\n", strip=True), re.I)
    return m.group(1).strip() if m else None


def _extract_qualification(body):
    if body is None:
        return ""
    text = body.get_text("\n", strip=True)
    m = re.search(
        r"Kualifikasi\s*:?\s*\n(.+?)"
        r"(?:\n\s*Bagi Anda|\n\s*PENDAFTARAN|\n\s*Silahkan|\Z)",
        text, re.DOTALL | re.I,
    )
    return m.group(1).strip() if m else ""


def _extract_location(text):
    """#2: anchor spesifik supaya tidak over-capture sampai akhir body."""
    m = re.search(
        r"ditempatkan\s+di\s+"
        r"([^\n]{2,80}?)"
        r"(?:\.|,\s*Bagi|\s+Bagi\s+Anda|\s+Silahkan|\s+Kirim|\s+\Z)",
        text, re.I,
    )
    return m.group(1).strip() if m else None


def _extract_education(labels, text):
    """#4: label → canonical → set unik. Body parse sebagai fallback."""
    edu = set()

    # Prioritas 1: labels (paling akurat, sudah dikurasi penulis).
    for lbl in labels:
        up = lbl.upper().strip()
        for tok in re.split(r"[/\s]+", up):
            if tok in EDU_CANONICAL:
                edu.add(EDU_CANONICAL[tok])

    # Prioritas 2: fallback regex dari body (hanya untuk yang belum terdeteksi).
    for tag, pat in EDU_PATTERNS.items():
        if re.search(pat, text, re.I):
            edu.add(EDU_CANONICAL[tag.split("/")[0]])

    return sorted(edu)


def parse_detail(html, url, lastmod):
    soup = BeautifulSoup(html, "lxml")
    h1 = soup.find("h1") or soup.find("title")
    body = (
        soup.find("div", class_=re.compile("post-body|entry-content"))
        or soup.find("article")
    )
    body_text = (
        body.get_text(" ", strip=True) if body else soup.get_text(" ", strip=True)
    )

    labels = [a.get_text(strip=True) for a in soup.select('a[rel="tag"]')]

    return {
        "source_url": url,
        "sitemap_lastmod": str(lastmod) if lastmod else None,
        "title": h1.get_text(strip=True) if h1 else None,
        "posted_date": str(_extract_date(soup, body_text, lastmod) or ""),
        "company_name": _extract_company(body),
        "position": _extract_position(body),
        "qualification": _extract_qualification(body),
        "education_levels": _extract_education(labels, body_text),
        "location": _extract_location(body_text),
        "labels": labels,
    }


def scrape_all(entries, progress_cb=None):
    """#5: progress dipanggil setelah fetch (bukan sebelum)."""
    out = []
    total = len(entries)
    for i, e in enumerate(entries):
        try:
            html = _fetch(e["loc"])
            out.append(parse_detail(html, e["loc"], _parse_date(e["lastmod"])))
        except Exception as ex:
            out.append({"source_url": e["loc"], "error": str(ex)})
        finally:
            if progress_cb:
                progress_cb(i + 1, total, e["loc"])
            time.sleep(DELAY)
    return out