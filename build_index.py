"""
BUILD_INDEX.PY - Realtime Crawler & Compiler for The Great Courses (index.html)
Bersih, Standalone Single File, Tanpa Ketergantungan Folder 'tgc-courses' atau 'katalog.json'.

Fitur:
  - Membaca basis data 950+ kursus yang sudah ada dari index.html.
  - Melakukan CRAWL REALTIME ke shop.thegreatcourses.com (seluruh 48 halaman katalog).
  - Mendeteksi kursus baru & langsung mengambil detail episode, durasi, guidebook URL secara realtime.
  - Mengompilasi Single-Page Application (SPA) index.html modern, mandiri, tanpa file sampah.

Penggunaan:
  python build_index.py              # Pindai seluruh katalog online (48 halaman) & perbarui index.html
  python build_index.py --quick      # Pindai cepat 3 halaman terdepan untuk cek rilis terbaru
  python build_index.py <slug_kursus> # Crawl kursus spesifik (misal: python build_index.py microeconomics-made-clear)
"""

import sys
import os
import re
import json
import gzip
import base64
import time
import html
import urllib.request
import urllib.error
from concurrent.futures import ThreadPoolExecutor, as_completed

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

def normalize_text(text):
    if not text:
        return ""
    text = html.unescape(text)
    reps = {
        '\u2018': "'", '\u2019': "'", '\u201c': '"', '\u201d': '"',
        '\u2013': "-", '\u2014': "--", '\u2026': "...", '\xa0': " "
    }
    for k, v in reps.items():
        text = text.replace(k, v)
    return re.sub(r'\s+', ' ', text).strip()

def sanitize_filename(name):
    if not name:
        return "TGC"
    name = html.unescape(name)
    clean = re.sub(r'[\\/*?:"<>|]', '', name)
    clean = clean.replace(' ', '_').replace('-', '_')
    clean = re.sub(r'_+', '_', clean)
    return clean.strip('_')[:100]

def fetch_url(url, timeout=20):
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode('utf-8', errors='replace')

def fetch_catalog_page(page):
    url = f"https://shop.thegreatcourses.com/shop/courses?promo=all&sortoption=newest&page={page}"
    try:
        content = fetch_url(url, timeout=15)
        page_items = []
        for s in re.findall(r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', content, re.DOTALL):
            if "CollectionPage" in s:
                try:
                    data = json.loads(s)
                    items = data.get("mainEntity", {}).get("itemListElement", [])
                    for item in items:
                        if isinstance(item, dict):
                            name = normalize_text(item.get("name", ""))
                            u = item.get("url", "").rstrip("/")
                            slug = u.split("/")[-1] if u else ""
                            sub = item.get("itemListElement", {})
                            cid = sub.get("@id") if isinstance(sub, dict) else None
                            if not cid:
                                img = item.get("image", "")
                                m = re.search(r'/courses/(\d+)/', img)
                                cid = m.group(1) if m else ""
                            sku = f"ZV{cid}" if cid else ""
                            if name and u:
                                page_items.append({
                                    "name": name,
                                    "url": u,
                                    "slug": slug,
                                    "cid": str(cid) if cid else "",
                                    "sku": sku
                                })
                except Exception:
                    pass
        return page, page_items
    except Exception:
        return page, []

def crawl_course_details(page_url):
    try:
        content = fetch_url(page_url, timeout=20)
    except Exception:
        return None

    # Cari courseId
    cid_match = re.search(r'"courseId"\s*:\s*["\']?(\d+)', content)
    course_id = cid_match.group(1) if cid_match else ""

    # Cari skema Course JSON-LD
    course_name = ""
    course_desc = ""
    parts = []
    for s in re.findall(r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', content, re.DOTALL):
        if '"Course"' in s:
            try:
                data = json.loads(s[s.find('{'):s.rfind('}')+1])
                course_name = normalize_text(data.get("name", ""))
                course_desc = normalize_text(data.get("description", ""))
                parts = data.get("hasCourseInstance", {}).get("hasPart", [])
                if parts:
                    break
            except Exception:
                pass

    if not course_name:
        m_t = re.search(r'<title>(.*?)</title>', content, re.IGNORECASE)
        if m_t:
            course_name = m_t.group(1).split('|')[0].strip()

    # Cari URL Guide Book
    guidebook_url = ""
    m_gb = re.search(r'https://secureimages\S+?\.pdf', content)
    if m_gb:
        guidebook_url = m_gb.group(0).strip()

    # Susun list episode kuliah
    cid = course_id
    sku_course = f"ZV{cid}" if cid else "TGC"
    lectures = []
    for i, p in enumerate(parts, 1):
        if isinstance(p, dict):
            lec_title = normalize_text(p.get("name") or f"Kuliah {i}")
            dur_raw = p.get("timeRequired", "")
            dur = dur_raw.replace('PT', '').replace('M', ' min').replace('H', 'h ').strip()
            desc = normalize_text(p.get("description", ""))
            lec_sku = f"{sku_course}-L{i:02d}"
            lectures.append({
                'n': i,
                't': lec_title,
                'd': dur,
                's': desc,
                'k': lec_sku
            })

    slug = page_url.rstrip("/").split("/")[-1]
    clean_sku = sanitize_filename(sku_course)
    clean_slug = sanitize_filename(slug)
    html_filename = f"{clean_sku}_{clean_slug}.html"

    return {
        'i': cid,
        'k': sku_course,
        't': course_name,
        's': course_desc,
        'g': guidebook_url,
        'f': html_filename,
        'l': lectures
    }

def load_existing_courses(index_path="index.html"):
    if not os.path.exists(index_path):
        if index_path == "index.html" and os.path.exists("index_compressed.html"):
            index_path = "index_compressed.html"
        else:
            return []
    try:
        with open(index_path, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()
        
        # 1. Format Base64 Gzip
        marker_b64 = 'const COURSES_B64 = "'
        idx_b64 = content.find(marker_b64)
        if idx_b64 != -1:
            start = idx_b64 + len(marker_b64)
            end = content.find('";', start)
            b64_str = content[start:end].strip()
            decomp = gzip.decompress(base64.b64decode(b64_str)).decode('utf-8')
            data = json.loads(decomp)
            print(f"[*] Berhasil memuat {len(data)} kursus (format terkompresi) dari '{index_path}'.")
            return data

        # 2. Format Raw JSON
        marker = "const COURSES = "
        idx = content.find(marker)
        if idx != -1:
            start = idx + len(marker)
            end = content.find(";\n", start)
            if end == -1:
                end = content.find(";", start)
            raw_json = content[start:end].strip()
            if raw_json != "[]":
                data = json.loads(raw_json)
                print(f"[*] Berhasil memuat {len(data)} kursus dari '{index_path}'.")
                return data

        return []
    except Exception as e:
        print(f"[!] Gagal membaca data dari {index_path}: {e}")
        return []

def build_index_html(courses_data, output_path="index.html"):
    courses_data.sort(key=lambda x: x.get('r', 9999))
    total_lectures = sum(len(c.get('l', [])) for c in courses_data)
    courses_json = json.dumps(courses_data, ensure_ascii=False)

    doc = TEMPLATE_HTML.replace("__COURSES_DATA__", courses_json)
    doc = re.sub(r'(<span class="stats-highlight">)\d+(</span> Kursus)', rf'\g<1>{len(courses_data)}\g<2>', doc)
    doc = re.sub(r'(<span id="totalLecturesCountText">)\d+(</span> Total Episode)', rf'\g<1>{total_lectures}\g<2>', doc)

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(doc)
    
    size_mb = os.path.getsize(output_path) / (1024 * 1024)
    print("\n" + "=" * 70)
    print("           KOMPILASI INDEX.HTML SELESAI")
    print("=" * 70)
    print(f"Total Kursus   : {len(courses_data)}")
    print(f"Total Episode  : {total_lectures}")
    print(f"Ukuran File    : {size_mb:.2f} MB")
    print(f"Lokasi Output  : {os.path.abspath(output_path)}")
    print("=" * 70)
    return output_path

def main():
    t0 = time.time()
    args = sys.argv[1:]

    courses_map = {}

    # 1. Muat basis data yang sudah ada
    for c in load_existing_courses("index.html"):
        key = c.get('k') or c.get('i') or c.get('t')
        if key:
            courses_map[key] = c

    # 2. Tentukan mode crawl
    max_pages = 48  # Default: seluruh katalog (48 halaman = ~952 kursus)
    target_course_url = None

    if args:
        a = args[0].strip().lower()
        if a in ['--quick', '-quick', '-q']:
            max_pages = 3
            print(f"[*] Mode: Pindai cepat 3 halaman katalog...")
        elif a in ['--pages', '-pages', '-p'] and len(args) > 1:
            try:
                max_pages = int(args[1])
            except ValueError:
                max_pages = 48
            print(f"[*] Mode: Pindai {max_pages} halaman katalog...")
        elif a.startswith("http://") or a.startswith("https://"):
            target_course_url = args[0].strip()
        elif re.match(r'^ZV?\d+$', a, re.I):
            num = re.sub(r'\D', '', a)
            target_course_url = f"https://shop.thegreatcourses.com/{num}"
        elif a not in ['--help', '-h', '--all', '-all', 'all']:
            target_course_url = f"https://shop.thegreatcourses.com/{a}"

    # 3. Crawl kursus spesifik jika diberikan argumen
    if target_course_url:
        print(f"[*] Melakukan crawl realtime untuk kursus: {target_course_url} ...")
        c_detail = crawl_course_details(target_course_url)
        if c_detail and c_detail.get('t'):
            key = c_detail.get('k') or c_detail.get('i') or c_detail.get('t')
            courses_map[key] = c_detail
            print(f"[OK] Berhasil mengambil: {c_detail['t']} ({len(c_detail['l'])} kuliah)")
        else:
            print(f"[!] Gagal mengambil kursus dari URL tersebut.")

    # 4. Crawl katalog online realtime
    else:
        print(f"[*] Melakukan crawl katalog realtime (halaman 1 s/d {max_pages}) ...")
        page_dict = {}
        with ThreadPoolExecutor(max_workers=16) as ex:
            futures = {ex.submit(fetch_catalog_page, p): p for p in range(1, max_pages + 1)}
            for fut in as_completed(futures):
                p = futures[fut]
                _, items = fut.result()
                page_dict[p] = items

        catalog_items = []
        for p in range(1, max_pages + 1):
            catalog_items.extend(page_dict.get(p, []))

        # Petakan ranking rilis (1 = terbaru, 952 = terlama)
        rank_map = {}
        for rank, it in enumerate(catalog_items, 1):
            if it.get('sku'): rank_map[it['sku']] = rank
            if it.get('cid'): rank_map[it['cid']] = rank
            if it.get('name'): rank_map[it['name'].lower()] = rank

        for c in courses_map.values():
            r = rank_map.get(c.get('k')) or rank_map.get(c.get('i')) or rank_map.get((c.get('t') or '').lower())
            if r:
                c['r'] = r

        # Cari kursus yang belum ada di basis data
        new_items = []
        for it in catalog_items:
            sku = it.get('sku')
            cid = it.get('cid')
            name = it.get('name')
            if (sku and sku in courses_map) or (cid and cid in courses_map) or (name and name in courses_map):
                continue
            new_items.append(it)

        if new_items:
            print(f"[+] Ditemukan {len(new_items)} kursus BARU di katalog! Mengambil detail realtime...")
            done_cnt = 0
            with ThreadPoolExecutor(max_workers=35) as ex:
                futures = {ex.submit(crawl_course_details, it['url']): it for it in new_items}
                for fut in as_completed(futures):
                    it = futures[fut]
                    done_cnt += 1
                    try:
                        res = fut.result()
                        if res and res.get('t'):
                            key = res.get('k') or res.get('i') or res.get('t')
                            courses_map[key] = res
                            print(f"  [{done_cnt:3d}/{len(new_items)}] [+] Ditambahkan: {res['t']} ({len(res['l'])} kuliah)")
                        else:
                            cid = it.get('cid', '')
                            sku = it.get('sku', '') or (f"ZV{cid}" if cid else "TGC")
                            slug = it.get('slug', '')
                            clean_sku = sanitize_filename(sku)
                            clean_slug = sanitize_filename(slug)
                            courses_map[sku or cid or it.get('name')] = {
                                'i': cid,
                                'k': sku,
                                't': it.get('name', 'Kursus'),
                                's': '',
                                'g': '',
                                'f': f"{clean_sku}_{clean_slug}.html",
                                'l': []
                            }
                            print(f"  [{done_cnt:3d}/{len(new_items)}] [~] Terdaftar dari katalog: {it.get('name')}")
                    except Exception as e:
                        print(f"  [!] Gagal crawl {it.get('name')}: {e}")
        else:
            print(f"[*] Katalog online sudah sinkron dengan basis data ({len(courses_map)} kursus).")

    # 5. Kompilasi ke index.html
    courses_list = list(courses_map.values())
    build_index_html(courses_list, "index.html")

# Template HTML SPA mandiri (raw string, tanpa modifikasi backslash)
TEMPLATE_HTML = r"""<!DOCTYPE html>
<html lang="id">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>The Great Courses — Ultimate Interactive Media Library (SPA)</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet">
    <style>
        :root {
            --bg-body: #0a0e17;
            --bg-card: #131a2b;
            --bg-card-hover: #1c263d;
            --bg-card-inner: #0f1523;
            --bg-input: #1a233a;
            --primary: #3b82f6;
            --primary-hover: #2563eb;
            --primary-glow: rgba(59, 130, 246, 0.25);
            --accent-green: #10b981;
            --text-main: #f8fafc;
            --text-sub: #94a3b8;
            --text-muted: #64748b;
            --border-color: #212c45;
            --border-focus: #3b82f6;
            --radius-lg: 14px;
            --radius-md: 10px;
            --radius-sm: 6px;
        }

        * {
            box-sizing: border-box;
            margin: 0;
            padding: 0;
        }

        body {
            background-color: var(--bg-body);
            color: var(--text-main);
            font-family: 'Inter', -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            min-height: 100vh;
            line-height: 1.5;
            overflow-x: hidden;
        }

        /* Header Bar */
        .site-header {
            position: sticky;
            top: 0;
            z-index: 100;
            background: rgba(10, 14, 23, 0.88);
            backdrop-filter: blur(14px);
            -webkit-backdrop-filter: blur(14px);
            border-bottom: 1px solid var(--border-color);
            padding: 16px 24px;
            transition: all 0.2s ease;
        }

        .header-container {
            max-width: 1480px;
            margin: 0 auto;
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 20px;
            flex-wrap: wrap;
        }

        .brand-box {
            display: flex;
            align-items: center;
            gap: 12px;
            cursor: pointer;
        }

        .brand-logo-icon {
            width: 38px;
            height: 38px;
            background: linear-gradient(135deg, #3b82f6 0%, #1d4ed8 100%);
            border-radius: 10px;
            display: flex;
            align-items: center;
            justify-content: center;
            box-shadow: 0 4px 14px rgba(59, 130, 246, 0.4);
            color: #ffffff;
            font-weight: 800;
            font-size: 18px;
        }

        .brand-text h1 {
            font-size: 18px;
            font-weight: 800;
            color: #ffffff;
            letter-spacing: -0.3px;
            line-height: 1.2;
        }

        .brand-text p {
            font-size: 12px;
            color: var(--text-sub);
        }

        /* Search & Controls */
        .search-area {
            flex: 1;
            max-width: 580px;
            position: relative;
        }

        .search-input {
            width: 100%;
            background: var(--bg-input);
            border: 1px solid var(--border-color);
            color: #ffffff;
            padding: 11px 40px 11px 42px;
            border-radius: 10px;
            font-size: 14px;
            outline: none;
            transition: all 0.2s;
        }

        .search-input:focus {
            border-color: var(--primary);
            box-shadow: 0 0 0 3px var(--primary-glow);
            background: #1f2a46;
        }

        .search-icon {
            position: absolute;
            left: 14px;
            top: 50%;
            transform: translateY(-50%);
            fill: var(--text-muted);
            pointer-events: none;
        }

        .clear-search-btn {
            position: absolute;
            right: 12px;
            top: 50%;
            transform: translateY(-50%);
            background: transparent;
            border: none;
            color: var(--text-muted);
            cursor: pointer;
            font-size: 16px;
            display: none;
            padding: 4px;
        }

        .clear-search-btn:hover {
            color: #ffffff;
        }

        .filter-controls {
            display: flex;
            align-items: center;
            gap: 10px;
            flex-wrap: wrap;
        }

        .select-filter {
            background: var(--bg-input);
            border: 1px solid var(--border-color);
            color: #ffffff;
            padding: 9px 14px;
            border-radius: 8px;
            font-size: 13px;
            font-weight: 500;
            outline: none;
            cursor: pointer;
        }

        .select-filter:focus {
            border-color: var(--primary);
        }

        .btn-filter-tag {
            background: var(--bg-input);
            border: 1px solid var(--border-color);
            color: var(--text-sub);
            padding: 8px 14px;
            border-radius: 8px;
            font-size: 13px;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.2s;
            display: inline-flex;
            align-items: center;
            gap: 6px;
        }

        .btn-filter-tag.active {
            background: rgba(59, 130, 246, 0.18);
            border-color: var(--primary);
            color: #60a5fa;
        }

        /* Sub-bar / Stats */
        .stats-bar {
            max-width: 1480px;
            margin: 20px auto 16px;
            padding: 0 24px;
            display: flex;
            align-items: center;
            justify-content: space-between;
            font-size: 14px;
            color: var(--text-sub);
            flex-wrap: wrap;
            gap: 12px;
        }

        .stats-highlight {
            color: #ffffff;
            font-weight: 600;
        }

        /* Cards Grid */
        .main-container {
            max-width: 1480px;
            margin: 0 auto;
            padding: 0 24px 80px;
        }

        .courses-grid {
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(310px, 1fr));
            gap: 22px;
        }

        .course-card {
            background: var(--bg-card);
            border: 1px solid var(--border-color);
            border-radius: var(--radius-lg);
            overflow: hidden;
            display: flex;
            flex-direction: column;
            cursor: pointer;
            transition: transform 0.22s ease, border-color 0.22s ease, box-shadow 0.22s ease;
        }

        .course-card:hover {
            transform: translateY(-5px);
            border-color: #3b82f6aa;
            box-shadow: 0 16px 32px -12px rgba(0, 0, 0, 0.7);
        }

        .thumb-box {
            position: relative;
            width: 100%;
            padding-top: 56.25%; /* 16:9 ratio */
            background: #020617;
            overflow: hidden;
        }

        .thumb-box img {
            position: absolute;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            object-fit: cover;
            transition: transform 0.35s ease;
        }

        .course-card:hover .thumb-box img {
            transform: scale(1.06);
        }

        .badge-overlay-sku {
            position: absolute;
            top: 10px;
            left: 10px;
            background: rgba(10, 14, 23, 0.85);
            backdrop-filter: blur(4px);
            color: #60a5fa;
            border: 1px solid rgba(59, 130, 246, 0.4);
            font-size: 11px;
            font-weight: 700;
            padding: 3px 8px;
            border-radius: 6px;
            z-index: 2;
        }

        .badge-overlay-guide {
            position: absolute;
            top: 10px;
            right: 10px;
            background: rgba(16, 185, 129, 0.9);
            color: #ffffff;
            font-size: 10px;
            font-weight: 700;
            padding: 3px 7px;
            border-radius: 6px;
            z-index: 2;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }

        .thumb-hover-overlay {
            position: absolute;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            background: rgba(10, 14, 23, 0.55);
            display: flex;
            align-items: center;
            justify-content: center;
            opacity: 0;
            transition: opacity 0.2s ease;
            z-index: 1;
        }

        .course-card:hover .thumb-hover-overlay {
            opacity: 1;
        }

        .hover-btn-badge {
            background: var(--primary);
            color: #ffffff;
            font-size: 13px;
            font-weight: 700;
            padding: 8px 16px;
            border-radius: 8px;
            box-shadow: 0 4px 14px rgba(59, 130, 246, 0.6);
            display: flex;
            align-items: center;
            gap: 6px;
        }

        .card-body {
            padding: 18px;
            display: flex;
            flex-direction: column;
            flex: 1;
        }

        .card-badges-row {
            display: flex;
            align-items: center;
            gap: 8px;
            margin-bottom: 10px;
            flex-wrap: wrap;
        }

        .badge-cid, .badge-count {
            background: #1b2438;
            color: #94a3b8;
            font-size: 11px;
            font-weight: 600;
            padding: 3px 8px;
            border-radius: 6px;
            border: 1px solid rgba(255, 255, 255, 0.05);
        }

        .card-title {
            font-size: 16px;
            font-weight: 700;
            line-height: 1.4;
            color: #ffffff;
            margin-bottom: 8px;
        }

        .card-desc-preview {
            font-size: 13px;
            color: var(--text-sub);
            line-height: 1.5;
            display: -webkit-box;
            -webkit-line-clamp: 3;
            -webkit-box-orient: vertical;
            overflow: hidden;
            flex: 1;
            margin-bottom: 16px;
        }

        .card-footer {
            padding-top: 14px;
            border-top: 1px solid var(--border-color);
            display: flex;
            align-items: center;
            justify-content: space-between;
            font-size: 13px;
            font-weight: 600;
            color: var(--primary);
        }

        .card-footer:hover {
            color: #93c5fd;
        }

        /* Loading Sentinel */
        .sentinel {
            text-align: center;
            padding: 32px 0;
            color: var(--text-muted);
            font-size: 14px;
        }

        /* =====================================================================
           MODAL / COURSE DETAIL DRAWER
           ===================================================================== */
        .modal-overlay {
            position: fixed;
            top: 0;
            left: 0;
            width: 100vw;
            height: 100vh;
            background: rgba(5, 8, 15, 0.85);
            backdrop-filter: blur(8px);
            -webkit-backdrop-filter: blur(8px);
            z-index: 1000;
            display: flex;
            justify-content: center;
            align-items: flex-start;
            padding: 32px 16px;
            overflow-y: auto;
            opacity: 0;
            pointer-events: none;
            transition: opacity 0.25s ease;
        }

        .modal-overlay.open {
            opacity: 1;
            pointer-events: auto;
        }

        .modal-container {
            background: var(--bg-card);
            border: 1px solid var(--border-color);
            border-radius: 18px;
            width: 100%;
            max-width: 1160px;
            box-shadow: 0 30px 60px -15px rgba(0, 0, 0, 0.8);
            overflow: hidden;
            position: relative;
            transform: translateY(20px) scale(0.98);
            transition: transform 0.25s cubic-bezier(0.16, 1, 0.3, 1);
            margin-bottom: 60px;
        }

        .modal-overlay.open .modal-container {
            transform: translateY(0) scale(1);
        }

        .modal-close-btn {
            position: absolute;
            top: 20px;
            right: 20px;
            width: 40px;
            height: 40px;
            background: rgba(255, 255, 255, 0.08);
            border: 1px solid rgba(255, 255, 255, 0.1);
            border-radius: 50%;
            color: #ffffff;
            display: flex;
            align-items: center;
            justify-content: center;
            cursor: pointer;
            z-index: 10;
            transition: all 0.2s;
        }

        .modal-close-btn:hover {
            background: rgba(255, 255, 255, 0.2);
            transform: rotate(90deg);
        }

        .modal-header {
            background: linear-gradient(180deg, #182239 0%, var(--bg-card) 100%);
            padding: 36px 36px 28px;
            border-bottom: 1px solid var(--border-color);
        }

        .modal-badges {
            display: flex;
            align-items: center;
            gap: 10px;
            flex-wrap: wrap;
            margin-bottom: 14px;
        }

        .badge-tag {
            background: rgba(59, 130, 246, 0.18);
            color: #60a5fa;
            border: 1px solid rgba(59, 130, 246, 0.4);
            font-size: 13px;
            font-weight: 700;
            padding: 4px 12px;
            border-radius: 20px;
        }

        .modal-title {
            font-size: clamp(22px, 3.5vw, 32px);
            font-weight: 800;
            color: #ffffff;
            line-height: 1.3;
            margin-bottom: 12px;
            max-width: 90%;
        }

        .modal-desc {
            font-size: 15px;
            color: var(--text-sub);
            line-height: 1.6;
            margin-bottom: 22px;
            max-width: 940px;
        }

        .modal-actions {
            display: flex;
            align-items: center;
            gap: 12px;
            flex-wrap: wrap;
        }

        .btn {
            display: inline-flex;
            align-items: center;
            gap: 8px;
            font-weight: 600;
            padding: 10px 18px;
            border-radius: 8px;
            text-decoration: none;
            cursor: pointer;
            border: none;
            transition: all 0.2s;
            font-size: 14px;
        }

        .btn-guidebook {
            background: #0284c7;
            color: #ffffff;
        }

        .btn-guidebook:hover {
            background: #0369a1;
        }

        .btn-secondary {
            background: #1b2438;
            color: #e2e8f0;
            border: 1px solid #334155;
        }

        .btn-secondary:hover {
            background: #2b3957;
            color: #ffffff;
        }

        .btn-play {
            background: var(--primary);
            color: #ffffff;
        }

        .btn-play:hover {
            background: var(--primary-hover);
        }

        .btn-sm {
            padding: 6px 12px;
            font-size: 12px;
            border-radius: 6px;
        }

        .modal-body {
            padding: 32px 36px 40px;
        }

        .lectures-controls {
            display: flex;
            align-items: center;
            justify-content: space-between;
            margin-bottom: 24px;
            gap: 16px;
            flex-wrap: wrap;
        }

        .lectures-count-label {
            font-size: 18px;
            font-weight: 700;
            color: #ffffff;
        }

        .lecture-filter-input {
            background: var(--bg-card-inner);
            border: 1px solid var(--border-color);
            color: #ffffff;
            padding: 8px 14px;
            border-radius: 8px;
            font-size: 13px;
            width: 260px;
            outline: none;
        }

        .lecture-filter-input:focus {
            border-color: var(--primary);
        }

        .lectures-grid {
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(310px, 1fr));
            gap: 20px;
        }

        .lec-card {
            background: var(--bg-card-inner);
            border: 1px solid var(--border-color);
            border-radius: var(--radius-md);
            overflow: hidden;
            display: flex;
            flex-direction: column;
            transition: all 0.2s;
        }

        .lec-card:hover {
            border-color: #3b82f6aa;
            transform: translateY(-3px);
            box-shadow: 0 10px 24px -10px rgba(0,0,0,0.5);
        }

        .lec-card.hidden {
            display: none !important;
        }

        .lec-thumb-container {
            position: relative;
            width: 100%;
            padding-top: 56.25%;
            background: #020617;
            cursor: pointer;
            overflow: hidden;
        }

        .lec-thumb-container img {
            position: absolute;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            object-fit: cover;
            transition: transform 0.3s ease;
        }

        .lec-card:hover .lec-thumb-container img {
            transform: scale(1.06);
        }

        .lec-thumb-overlay {
            position: absolute;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            background: rgba(10, 14, 23, 0.55);
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            opacity: 0;
            transition: opacity 0.2s ease;
            gap: 8px;
        }

        .lec-card:hover .lec-thumb-overlay {
            opacity: 1;
        }

        .play-circle {
            width: 48px;
            height: 48px;
            background: var(--primary);
            border-radius: 50%;
            display: flex;
            align-items: center;
            justify-content: center;
            box-shadow: 0 4px 14px rgba(59, 130, 246, 0.6);
        }

        .play-circle svg {
            width: 22px;
            height: 22px;
            fill: #ffffff;
            margin-left: 2px;
        }

        .lec-badge-num {
            position: absolute;
            top: 8px;
            left: 8px;
            background: rgba(10, 14, 23, 0.85);
            backdrop-filter: blur(4px);
            color: #ffffff;
            font-size: 11px;
            font-weight: 700;
            padding: 3px 8px;
            border-radius: 4px;
            border: 1px solid rgba(255, 255, 255, 0.1);
        }

        .lec-badge-dur {
            position: absolute;
            bottom: 8px;
            right: 8px;
            background: rgba(10, 14, 23, 0.85);
            backdrop-filter: blur(4px);
            color: #ffffff;
            font-size: 11px;
            font-weight: 600;
            padding: 3px 8px;
            border-radius: 4px;
        }

        .lec-card-body {
            padding: 16px;
            display: flex;
            flex-direction: column;
            flex: 1;
        }

        .lec-sku-text {
            font-size: 11px;
            color: var(--primary);
            font-weight: 700;
            margin-bottom: 6px;
        }

        .lec-title {
            font-size: 15px;
            font-weight: 700;
            color: #ffffff;
            line-height: 1.35;
            margin-bottom: 8px;
            cursor: pointer;
        }

        .lec-title:hover {
            color: var(--primary);
        }

        .lec-desc {
            font-size: 13px;
            color: var(--text-sub);
            line-height: 1.5;
            display: -webkit-box;
            -webkit-line-clamp: 4;
            -webkit-box-orient: vertical;
            overflow: hidden;
            flex: 1;
            margin-bottom: 14px;
        }

        .lec-footer {
            padding-top: 12px;
            border-top: 1px solid var(--border-color);
            display: flex;
            align-items: center;
            gap: 6px;
            flex-wrap: wrap;
        }

        /* Toast Popup */
        .toast {
            position: fixed;
            bottom: 28px;
            right: 28px;
            background: #10b981;
            color: #ffffff;
            padding: 12px 20px;
            border-radius: 10px;
            font-size: 14px;
            font-weight: 600;
            box-shadow: 0 10px 25px rgba(0, 0, 0, 0.5);
            transform: translateY(100px);
            opacity: 0;
            transition: all 0.3s cubic-bezier(0.16, 1, 0.3, 1);
            z-index: 9999;
        }

        .toast.show {
            transform: translateY(0);
            opacity: 1;
        }
    </style>
</head>
<body>

    <!-- TOP BAR -->
    <header class="site-header">
        <div class="header-container">
            <div class="brand-box" onclick="resetToHome()">
                <div class="brand-logo-icon">TGC</div>
                <div class="brand-text">
                    <h1>The Great Courses</h1>
                    <p>Standalone Media Library & Player (SPA)</p>
                </div>
            </div>

            <div class="search-area">
                <svg class="search-icon" width="18" height="18" viewBox="0 0 24 24">
                    <path d="M15.5 14h-.79l-.28-.27A6.471 6.471 0 0 0 16 9.5 6.5 6.5 0 1 0 9.5 16c1.61 0 3.09-.59 4.23-1.57l.27.28v.79l5 4.99L20.49 19l-4.99-5zm-6 0C7.01 14 5 11.99 5 9.5S7.01 5 9.5 5 14 7.01 14 9.5 11.99 14 9.5 14z"/>
                </svg>
                <input type="text" id="searchInput" class="search-input" placeholder="Cari judul, topik, atau SKU (tekan '/' untuk cari)..." autocomplete="off" />
                <button id="clearSearchBtn" class="clear-search-btn" onclick="clearSearch()">&times;</button>
            </div>

            <div class="filter-controls">
                <select id="sortSelect" class="select-filter" onchange="handleSortChange()">
                    <option value="newest" selected>Rilis Terbaru (Default)</option>
                    <option value="oldest">Rilis Terlama</option>
                    <option value="title_asc">Judul (A &rarr; Z)</option>
                    <option value="title_desc">Judul (Z &rarr; A)</option>
                    <option value="sku_asc">SKU Kursus (A &rarr; Z)</option>
                    <option value="cid_asc">Course ID (Kecil &rarr; Besar)</option>
                    <option value="cid_desc">Course ID (Besar &rarr; Kecil)</option>
                </select>

                <button id="guidebookFilterBtn" class="btn-filter-tag" onclick="toggleGuidebookFilter()">
                    <span>📄 Ada Guide Book</span>
                </button>
            </div>
        </div>
    </header>

    <!-- STATS BAR -->
    <div class="stats-bar">
        <div>
            Menampilkan <span id="visibleCountText" class="stats-highlight">0</span> dari 
            <span class="stats-highlight">952</span> Kursus 
            (<span id="totalLecturesCountText">21212</span> Total Episode)
        </div>
        <div id="filterStatusHint"></div>
    </div>

    <!-- MAIN GRID CONTAINER -->
    <main class="main-container">
        <div class="courses-grid" id="coursesGrid"></div>
        <div id="sentinel" class="sentinel">Memuat lebih banyak kursus...</div>
    </main>

    <!-- COURSE DETAIL MODAL -->
    <div id="courseModal" class="modal-overlay" onclick="handleModalBackdropClick(event)">
        <div class="modal-container">
            <button class="modal-close-btn" onclick="closeCourseModal()" title="Tutup (ESC)">&times;</button>
            
            <div class="modal-header">
                <div class="modal-badges" id="modalBadges"></div>
                <h2 class="modal-title" id="modalTitle"></h2>
                <p class="modal-desc" id="modalDesc"></p>
                <div class="modal-actions" id="modalActions"></div>
            </div>

            <div class="modal-body">
                <div class="lectures-controls">
                    <div class="lectures-count-label" id="modalLecturesCount">Daftar Kuliah</div>
                    <input type="text" id="modalLecSearch" class="lecture-filter-input" placeholder="Saring kuliah di kursus ini..." oninput="filterModalLectures()" />
                </div>
                <div class="lectures-grid" id="modalLecturesGrid"></div>
            </div>
        </div>
    </div>

    <!-- TOAST NOTIFICATION -->
    <div id="toast" class="toast">Teks disalin ke clipboard!</div>

    <script>
        // RAW DATABASE KURSUS
        const COURSES = __COURSES_DATA__;

        // APPLICATION STATE
        let filteredCourses = [...COURSES];
        let currentRenderLimit = 36;
        const RENDER_BATCH_SIZE = 36;
        let onlyWithGuidebook = false;
        let currentSort = "newest";
        let activeCourse = null;

        // DOM ELEMENTS
        const searchInput = document.getElementById('searchInput');
        const clearSearchBtn = document.getElementById('clearSearchBtn');
        const coursesGrid = document.getElementById('coursesGrid');
        const sentinel = document.getElementById('sentinel');
        const visibleCountText = document.getElementById('visibleCountText');
        const courseModal = document.getElementById('courseModal');
        const sortSelect = document.getElementById('sortSelect');
        const guidebookFilterBtn = document.getElementById('guidebookFilterBtn');
        const toastEl = document.getElementById('toast');

        // INITIALIZATION
        function initApp() {
            applyFilters();
            setupIntersectionObserver();
            setupKeyboardShortcuts();
            handleInitialRoute();
        }

        if (document.readyState === 'loading') {
            document.addEventListener('DOMContentLoaded', initApp);
        } else {
            initApp();
        }

        window.addEventListener('hashchange', handleHashChange);

        function setupIntersectionObserver() {
            const observer = new IntersectionObserver((entries) => {
                if (entries[0].isIntersecting && currentRenderLimit < filteredCourses.length) {
                    currentRenderLimit += RENDER_BATCH_SIZE;
                    renderCoursesCards();
                }
            }, { rootMargin: '400px' });

            observer.observe(sentinel);
        }

        function setupKeyboardShortcuts() {
            window.addEventListener('keydown', (e) => {
                if (e.key === '/' && document.activeElement !== searchInput) {
                    e.preventDefault();
                    searchInput.focus();
                }
                if (e.key === 'Escape') {
                    if (courseModal.classList.contains('open')) {
                        closeCourseModal();
                    } else if (searchInput.value) {
                        clearSearch();
                    }
                }
            });

            searchInput.addEventListener('input', () => {
                clearSearchBtn.style.display = searchInput.value ? 'block' : 'none';
                applyFilters();
            });
        }

        function clearSearch() {
            searchInput.value = '';
            clearSearchBtn.style.display = 'none';
            searchInput.focus();
            applyFilters();
        }

        function resetToHome() {
            clearSearch();
            if (onlyWithGuidebook) toggleGuidebookFilter();
            sortSelect.value = "newest";
            handleSortChange();
            window.scrollTo({ top: 0, behavior: 'smooth' });
        }

        function toggleGuidebookFilter() {
            onlyWithGuidebook = !onlyWithGuidebook;
            guidebookFilterBtn.classList.toggle('active', onlyWithGuidebook);
            applyFilters();
        }

        function handleSortChange() {
            currentSort = sortSelect.value;
            applyFilters();
        }

        function applyFilters() {
            const q = searchInput.value.toLowerCase().trim();

            filteredCourses = COURSES.filter(c => {
                if (onlyWithGuidebook && !c.g) return false;
                if (!q) return true;
                const matchTitle = c.t && c.t.toLowerCase().includes(q);
                const matchSku = c.k && c.k.toLowerCase().includes(q);
                const matchCid = c.i && c.i.includes(q);
                const matchDesc = c.s && c.s.toLowerCase().includes(q);
                return matchTitle || matchSku || matchCid || matchDesc;
            });

            // Sorting
            filteredCourses.sort((a, b) => {
                if (currentSort === "newest") return (a.r || 9999) - (b.r || 9999);
                if (currentSort === "oldest") return (b.r || 0) - (a.r || 0);
                const titleA = a.t || '';
                const titleB = b.t || '';
                if (currentSort === "title_asc") return titleA.localeCompare(titleB);
                if (currentSort === "title_desc") return titleB.localeCompare(titleA);
                if (currentSort === "sku_asc") return (a.k || "").localeCompare(b.k || "");
                if (currentSort === "cid_asc") return (parseInt(a.i || 0) || 0) - (parseInt(b.i || 0) || 0);
                if (currentSort === "cid_desc") return (parseInt(b.i || 0) || 0) - (parseInt(a.i || 0) || 0);
                return 0;
            });

            currentRenderLimit = 36;
            renderCoursesCards();
            updateStatsBar();
        }

        function updateStatsBar() {
            visibleCountText.textContent = filteredCourses.length;
            sentinel.style.display = currentRenderLimit >= filteredCourses.length ? 'none' : 'block';
        }

        function renderCoursesCards() {
            const slice = filteredCourses.slice(0, currentRenderLimit);
            let html = '';

            for (let i = 0; i < slice.length; i++) {
                const c = slice[i];
                const cid = c.i || '';
                const sku = c.k || `ZV${cid}`;
                const title = c.t || 'Kursus';
                const desc = c.s || '';
                const lecsCount = c.l ? c.l.length : 0;
                const thumb = `https://secureimages.teach12.com/tgc/images/m2/wondrium/courses/${cid}/${cid}.jpg`;
                const gbBadge = c.g ? `<div class="badge-overlay-guide">PDF Guide</div>` : '';

                html += `
                <div class="course-card" onclick="openCourseModalBySku('${sku}')">
                    <div class="thumb-box">
                        <img src="${thumb}" alt="${escapeHtml(title)}" loading="lazy"
                             onerror="this.onerror=null; this.src='https://secureimages.teach12.com/tgc/images/m2/wondrium/courses/plh/plh.jpg';" />
                        <div class="badge-overlay-sku">${sku}</div>
                        ${gbBadge}
                        <div class="thumb-hover-overlay">
                            <div class="hover-btn-badge">
                                <svg viewBox="0 0 24 24" fill="currentColor" width="16" height="16"><path d="M8 5v14l11-7z"/></svg>
                                Buka Kuliah
                            </div>
                        </div>
                    </div>
                    <div class="card-body">
                        <div class="card-badges-row">
                            <span class="badge-cid">ID: ${cid}</span>
                            <span class="badge-count">${lecsCount} Kuliah</span>
                        </div>
                        <h2 class="card-title">${escapeHtml(title)}</h2>
                        <p class="card-desc-preview">${escapeHtml(desc)}</p>
                        <div class="card-footer">
                            <span>Jelajahi & Putar Video</span>
                            <span>&rarr;</span>
                        </div>
                    </div>
                </div>
                `;
            }

            coursesGrid.innerHTML = html;
        }

        // =====================================================================
        // MODAL DETAIL VIEW (SINGLE-PAGE APPLICATION)
        // =====================================================================
        function openCourseModalBySku(sku) {
            const course = COURSES.find(c => c.k === sku || c.i === sku || `ZV${c.i}` === sku);
            if (!course) return;

            activeCourse = course;
            window.location.hash = `course/${course.k || course.i}`;

            // Populate Modal Header
            document.getElementById('modalTitle').textContent = course.t;
            document.getElementById('modalDesc').textContent = course.s || 'Sinopsis kursus ini belum tersedia.';

            const cid = course.i || '';
            const csku = course.k || `ZV${cid}`;
            const lecs = course.l || [];

            document.getElementById('modalBadges').innerHTML = `
                <span class="badge-tag">${csku}</span>
                <span class="badge-tag">Course ID: ${cid}</span>
                <span class="badge-tag">${lecs.length} Episode</span>
            `;

            let actionsHtml = '';
            if (course.g) {
                actionsHtml += `
                    <a href="${course.g}" target="_blank" class="btn btn-guidebook">
                        <svg viewBox="0 0 24 24" fill="currentColor" width="18" height="18"><path d="M19 3H5c-1.1 0-2 .9-2 2v14c0 1.1.9 2 2 2h14c1.1 0 2-.9 2-2V5c0-1.1-.9-2-2-2zm-5 14H7v-2h7v2zm3-4H7v-2h10v2zm0-4H7V7h10v2z"/></svg>
                        Unduh Course Guide Book (PDF)
                    </a>
                `;
            }

            document.getElementById('modalActions').innerHTML = actionsHtml;
            document.getElementById('modalLecturesCount').textContent = `Daftar Kuliah (${lecs.length} Episode)`;
            document.getElementById('modalLecSearch').value = '';

            renderModalLectures(lecs, cid);

            courseModal.classList.add('open');
            document.body.style.overflow = 'hidden';
        }

        function renderModalLectures(lectures, cid) {
            const grid = document.getElementById('modalLecturesGrid');
            let html = '';

            for (let i = 0; i < lectures.length; i++) {
                const lec = lectures[i];
                const num = lec.n || (i + 1);
                const title = lec.t || `Kuliah ${num}`;
                const dur = lec.d || '';
                const desc = lec.s || '';
                const sku = lec.k || `ZV${cid}-L${String(num).padStart(2, '0')}`;
                const thumb = `https://secureimages.teach12.com/tgc/images/m2/wondrium/courses/${cid}/${cid}-L${String(num).padStart(2, '0')}.jpg`;
                const streamUrl = `https://link.theplatform.com/s/jESqeC/media/guid/2661884195/${sku}?formats=m3u`;

                html += `
                <div class="lec-card" data-search="${escapeHtml((title + ' ' + desc + ' ' + sku).toLowerCase())}">
                    <div class="lec-thumb-container" onclick="playLecture(${i})">
                        <img src="${thumb}" alt="${escapeHtml(title)}" loading="lazy"
                             onerror="this.onerror=null; this.src='https://secureimages.teach12.com/tgc/images/m2/wondrium/courses/plh/plh.jpg';" />
                        <div class="lec-badge-num">${String(num).padStart(2, '0')}</div>
                        ${dur ? `<div class="lec-badge-dur">${dur}</div>` : ''}
                        <div class="lec-thumb-overlay">
                            <div class="play-circle">
                                <svg viewBox="0 0 24 24"><path d="M8 5v14l11-7z"/></svg>
                            </div>
                            <span style="font-size: 12px; font-weight: 700; color: #fff;">Putar Video</span>
                        </div>
                    </div>
                    <div class="lec-card-body">
                        <div class="lec-sku-text">${sku}</div>
                        <h4 class="lec-title" onclick="playLecture(${i})">
                            ${String(num).padStart(2, '0')}: ${escapeHtml(title)}
                        </h4>
                        <p class="lec-desc">${escapeHtml(desc)}</p>
                        <div class="lec-footer">
                            <button class="btn btn-sm btn-play" onclick="playLecture(${i})">
                                <svg viewBox="0 0 24 24" fill="currentColor" width="14" height="14"><path d="M8 5v14l11-7z"/></svg>
                                Putar
                            </button>
                            <button class="btn btn-sm btn-secondary" onclick="copyText('${streamUrl}', 'Link M3U8 disalin!')" title="Salin Tautan Master M3U8">
                                M3U8
                            </button>
                            <button class="btn btn-sm btn-secondary" onclick="copyFfmpeg('${streamUrl}', '${sku}', '${escapeJs(title)}')" title="Salin Perintah FFmpeg">
                                FFmpeg
                            </button>
                        </div>
                    </div>
                </div>
                `;
            }

            grid.innerHTML = html;
        }

        function playLecture(i) {
            if (!activeCourse || !activeCourse.l || !activeCourse.l[i]) return;
            openPlayerWindow(activeCourse, i);
        }

        function filterModalLectures() {
            const q = document.getElementById('modalLecSearch').value.toLowerCase().trim();
            const cards = document.querySelectorAll('.lec-card');
            cards.forEach(card => {
                const d = card.getAttribute('data-search') || '';
                card.classList.toggle('hidden', !d.includes(q));
            });
        }

        function closeCourseModal() {
            courseModal.classList.remove('open');
            document.body.style.overflow = '';
            activeCourse = null;
            if (window.location.hash.startsWith('#course/')) {
                history.pushState("", document.title, window.location.pathname + window.location.search);
            }
        }

        function handleModalBackdropClick(e) {
            if (e.target === courseModal) {
                closeCourseModal();
            }
        }

        function handleHashChange() {
            const hash = window.location.hash;
            if (hash.startsWith('#course/')) {
                const sku = hash.replace('#course/', '');
                openCourseModalBySku(sku);
            } else {
                if (courseModal.classList.contains('open')) {
                    closeCourseModal();
                }
            }
        }

        function handleInitialRoute() {
            const hash = window.location.hash;
            if (hash.startsWith('#course/')) {
                const sku = hash.replace('#course/', '');
                openCourseModalBySku(sku);
            }
        }

        // =====================================================================
        // VIDEO PLAYER WINDOW (HLS.JS AUTOPLAY)
        // =====================================================================
        function openPlayerWindow(course, startIndex) {
            const w = window.open('', '_blank');
            if (!w) {
                alert('Pop-up browser terblokir. Harap izinkan pop-up untuk memutar video.');
                return;
            }

            const courseTitle = course.t || 'The Great Courses';
            const cid = course.i || '';
            const lectures = course.l || [];
            const lecturesJson = JSON.stringify(lectures);

            const playerDoc = `<!DOCTYPE html>
<html lang="id">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title id="playerPageTitle">Pemutar Video ? ${escapeHtml(courseTitle)}</title>
    <script src="https://cdn.jsdelivr.net/npm/hls.js@1.5.8/dist/hls.min.js"><\/script>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet">
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body {
            background: #0a0e17;
            color: #f8fafc;
            font-family: 'Inter', -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            min-height: 100vh;
            display: flex;
            flex-direction: column;
            align-items: center;
            padding: 24px 16px;
        }
        .player-wrap {
            width: 100%;
            max-width: 1100px;
            background: #141b2d;
            border-radius: 14px;
            overflow: hidden;
            box-shadow: 0 25px 50px -12px rgba(0, 0, 0, 0.7);
            border: 1px solid #242f49;
        }
        .video-box {
            position: relative;
            width: 100%;
            padding-top: 56.25%;
            background: #000;
        }
        video {
            position: absolute;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            outline: none;
        }
        .meta-box {
            padding: 24px;
        }
        .meta-top-row {
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 12px;
            margin-bottom: 12px;
            flex-wrap: wrap;
        }
        .badges-group {
            display: flex;
            align-items: center;
            gap: 8px;
            flex-wrap: wrap;
        }
        .badge {
            display: inline-block;
            background: rgba(59, 130, 246, 0.2);
            color: #60a5fa;
            border: 1px solid rgba(59, 130, 246, 0.4);
            padding: 4px 10px;
            border-radius: 6px;
            font-size: 13px;
            font-weight: 700;
        }
        .autoplay-toggle {
            display: inline-flex;
            align-items: center;
            gap: 8px;
            font-size: 13px;
            font-weight: 600;
            color: #94a3b8;
            cursor: pointer;
            user-select: none;
            background: #1e293b;
            padding: 6px 14px;
            border-radius: 20px;
            border: 1px solid #334155;
            transition: all 0.2s;
        }
        .autoplay-toggle.active {
            background: rgba(16, 185, 129, 0.18);
            border-color: #10b981;
            color: #34d399;
        }
        .autoplay-toggle input {
            cursor: pointer;
            accent-color: #10b981;
        }
        h1 {
            font-size: 22px;
            font-weight: 700;
            color: #ffffff;
            margin-bottom: 8px;
            line-height: 1.3;
        }
        .sub-meta {
            font-size: 14px;
            color: #94a3b8;
            margin-bottom: 16px;
        }
        .desc {
            font-size: 15px;
            line-height: 1.65;
            color: #cbd5e1;
            margin-bottom: 22px;
        }
        .actions {
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 12px;
            flex-wrap: wrap;
            padding-top: 18px;
            border-top: 1px solid #242f49;
        }
        .actions-nav, .actions-copy {
            display: flex;
            align-items: center;
            gap: 10px;
            flex-wrap: wrap;
        }
        .btn {
            padding: 9px 16px;
            border-radius: 8px;
            font-size: 13px;
            font-weight: 600;
            text-decoration: none;
            cursor: pointer;
            border: none;
            transition: all 0.2s;
            display: inline-flex;
            align-items: center;
            gap: 6px;
        }
        .btn-primary {
            background: #2563eb;
            color: #ffffff;
        }
        .btn-primary:hover {
            background: #1d4ed8;
        }
        .btn-secondary {
            background: #1e293b;
            color: #e2e8f0;
            border: 1px solid #334155;
        }
        .btn-secondary:hover:not(:disabled) {
            background: #334155;
        }
        .btn:disabled {
            opacity: 0.35;
            cursor: not-allowed;
        }
        .hls-note {
            font-size: 12px;
            color: #64748b;
            margin-top: 16px;
        }
    </style>
</head>
<body>
    <div class="player-wrap">
        <div class="video-box">
            <video id="videoPlayer" controls autoplay playsinline></video>
        </div>
        <div class="meta-box">
            <div class="meta-top-row">
                <div class="badges-group">
                    <span class="badge" id="badgeSku"></span>
                    <span class="badge" id="badgeEpisode"></span>
                    <span class="badge" id="badgeTotal">${lectures.length} Total Episode</span>
                </div>
                <label class="autoplay-toggle active" id="autoplayLabel" title="Saat video selesai dalam keadaan play aktif, otomatis putar kuliah berikutnya">
                    <input type="checkbox" id="autoplayCheckbox" checked onchange="toggleAutoplay(this.checked)" />
                    <span>Auto-Next Episode: ON</span>
                </label>
            </div>
            <h1 id="lecTitle"></h1>
            <div class="sub-meta" id="lecSubMeta"></div>
            <p class="desc" id="lecDesc"></p>

            <div class="actions">
                <div class="actions-nav">
                    <button class="btn btn-secondary" id="btnPrev" onclick="prevLecture()" title="Episode Sebelumnya">
                        &larr; Kuliah Sebelumnya
                    </button>
                    <button class="btn btn-secondary" id="btnNext" onclick="nextLecture()" title="Episode Berikutnya">
                        Kuliah Berikutnya &rarr;
                    </button>
                </div>
                <div class="actions-copy">
                    <a class="btn btn-primary" id="btnRawM3u8" href="#" target="_blank">Buka Raw M3U8</a>
                    <button class="btn btn-secondary" onclick="copyCurrentM3u8()">Salin M3U8</button>
                    <button class="btn btn-secondary" onclick="copyCurrentFfmpeg()">Salin FFmpeg</button>
                </div>
            </div>
            <div class="hls-note">* Video diputar langsung via Hls.js dengan resolusi adaptif otomatis (1080p/720p). Jika status pemutaran aktif saat video berakhir, episode berikutnya akan diputar otomatis.</div>
        </div>
    </div>

    <script>
        const LECTURES = ${lecturesJson};
        const COURSE_TITLE = ${JSON.stringify(courseTitle)};
        const COURSE_ID = ${JSON.stringify(cid)};
        let currentIndex = ${startIndex};
        let currentHls = null;
        let isPlayActive = true;
        let autoplayEnabled = true;

        const video = document.getElementById('videoPlayer');

        function toggleAutoplay(val) {
            autoplayEnabled = !!val;
            const lbl = document.getElementById('autoplayLabel');
            lbl.classList.toggle('active', autoplayEnabled);
            lbl.querySelector('span').textContent = autoplayEnabled ? 'Auto-Next Episode: ON' : 'Auto-Next Episode: OFF';
        }

        video.addEventListener('play', () => {
            isPlayActive = true;
        });

        video.addEventListener('playing', () => {
            isPlayActive = true;
        });

        video.addEventListener('pause', () => {
            if (!video.ended) {
                isPlayActive = false;
            }
        });

        video.addEventListener('ended', () => {
            // Putar next video otomatis bila status play sedang on
            if (isPlayActive && autoplayEnabled) {
                if (currentIndex + 1 < LECTURES.length) {
                    console.log('Video selesai dengan status play aktif. Memutar episode berikutnya...');
                    loadLecture(currentIndex + 1);
                } else {
                    console.log('Semua episode dalam kursus ini telah selesai diputar.');
                }
            }
        });

        function loadLecture(idx) {
            if (idx < 0 || idx >= LECTURES.length) return;
            currentIndex = idx;
            const lec = LECTURES[idx];
            const num = lec.n || (idx + 1);
            const title = lec.t || ('Kuliah ' + num);
            const dur = lec.d || '';
            const desc = lec.s || 'Deskripsi kuliah ini belum tersedia.';
            const sku = lec.k || ('ZV' + COURSE_ID + '-L' + String(num).padStart(2, '0'));
            const thumb = 'https://secureimages.teach12.com/tgc/images/m2/wondrium/courses/' + COURSE_ID + '/' + COURSE_ID + '-L' + String(num).padStart(2, '0') + '.jpg';
            const streamUrl = 'https://link.theplatform.com/s/jESqeC/media/guid/2661884195/' + sku + '?formats=m3u';

            document.getElementById('playerPageTitle').textContent = num + ': ' + title + ' ? ' + COURSE_TITLE;
            document.getElementById('badgeSku').textContent = sku;
            document.getElementById('badgeEpisode').textContent = 'Kuliah ' + num + ' / ' + LECTURES.length;
            document.getElementById('lecTitle').textContent = num + ': ' + title;
            document.getElementById('lecSubMeta').textContent = (dur ? 'Durasi: ' + dur + ' ? ' : '') + 'Kursus: ' + COURSE_TITLE;
            document.getElementById('lecDesc').textContent = desc;

            document.getElementById('btnRawM3u8').href = streamUrl;
            document.getElementById('btnPrev').disabled = (idx === 0);
            document.getElementById('btnNext').disabled = (idx === LECTURES.length - 1);

            video.poster = thumb;

            if (currentHls) {
                currentHls.destroy();
                currentHls = null;
            }

            if (Hls.isSupported()) {
                currentHls = new Hls({
                    enableWorker: true,
                    lowLatencyMode: true
                });
                currentHls.loadSource(streamUrl);
                currentHls.attachMedia(video);
                currentHls.on(Hls.Events.MANIFEST_PARSED, function() {
                    video.play().then(() => {
                        isPlayActive = true;
                    }).catch(e => console.log('Autoplay ditahan browser:', e));
                });
            } else if (video.canPlayType('application/vnd.apple.mpegurl')) {
                video.src = streamUrl;
                video.play().then(() => {
                    isPlayActive = true;
                }).catch(e => console.log('Autoplay ditahan browser:', e));
            }
        }

        function prevLecture() {
            if (currentIndex > 0) {
                isPlayActive = true;
                loadLecture(currentIndex - 1);
            }
        }

        function nextLecture() {
            if (currentIndex + 1 < LECTURES.length) {
                isPlayActive = true;
                loadLecture(currentIndex + 1);
            }
        }

        function copyCurrentM3u8() {
            const lec = LECTURES[currentIndex];
            const num = lec.n || (currentIndex + 1);
            const sku = lec.k || ('ZV' + COURSE_ID + '-L' + String(num).padStart(2, '0'));
            const streamUrl = 'https://link.theplatform.com/s/jESqeC/media/guid/2661884195/' + sku + '?formats=m3u';
            navigator.clipboard.writeText(streamUrl).then(() => {
                alert('Tautan Master M3U8 disalin ke clipboard!');
            });
        }

        function copyCurrentFfmpeg() {
            const lec = LECTURES[currentIndex];
            const num = lec.n || (currentIndex + 1);
            const sku = lec.k || ('ZV' + COURSE_ID + '-L' + String(num).padStart(2, '0'));
            const streamUrl = 'https://link.theplatform.com/s/jESqeC/media/guid/2661884195/' + sku + '?formats=m3u';
            const cleanTitle = (lec.t || '').replace(/[^a-zA-Z0-9]/g, '_');
            const cmd = 'ffmpeg -hide_banner -loglevel error -stats -http_persistent 1 -http_multiple 1 -multiple_requests 1 -reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5 -i "' + streamUrl + '" -c copy -bsf:a aac_adtstoasc "' + sku + '_' + cleanTitle + '.mp4"';
            navigator.clipboard.writeText(cmd).then(() => {
                alert('Perintah FFmpeg disalin ke clipboard!');
            });
        }

        loadLecture(currentIndex);
    <\/script>
</body>
</html>`;

            w.document.open();
            w.document.write(playerDoc);
            w.document.close();
        }

        // HELPERS
        function copyText(text, msg) {
            navigator.clipboard.writeText(text).then(() => {
                showToast(msg || 'Disalin ke clipboard!');
            });
        }

        function copyFfmpeg(url, sku, title) {
            const cleanTitle = title.replace(/[^a-zA-Z0-9]/g, '_');
            const cmd = `ffmpeg -hide_banner -loglevel error -stats -http_persistent 1 -http_multiple 1 -multiple_requests 1 -reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5 -i "${url}" -c copy -bsf:a aac_adtstoasc "${sku}_${cleanTitle}.mp4"`;
            copyText(cmd, `Perintah FFmpeg untuk ${sku} disalin!`);
        }

        function showToast(msg) {
            toastEl.textContent = msg;
            toastEl.classList.add('show');
            setTimeout(() => {
                toastEl.classList.remove('show');
            }, 2400);
        }

        function escapeHtml(str) {
            if (!str) return '';
            return String(str)
                .replace(/&/g, '&amp;')
                .replace(/</g, '&lt;')
                .replace(/>/g, '&gt;')
                .replace(/"/g, '&quot;')
                .replace(/'/g, '&#039;');
        }

        function escapeJs(str) {
            if (!str) return '';
            return String(str)
                .replace(/\\/g, '\\\\')
                .replace(/'/g, "\\'")
                .replace(/"/g, '\\"')
                .replace(/\n/g, ' ')
                .replace(/\r/g, '');
        }
    </script>
</body>
</html>
"""

if __name__ == "__main__":
    main()
