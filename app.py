import streamlit as st
import pandas as pd
from apify_client import ApifyClient
from datetime import datetime, timedelta
import re
import os
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import uuid
import time
import numpy as np
import random 
import ast

# --- SAYFA YAPILANDIRMASI (EN BAŞTA) ---
st.set_page_config(page_title="Tiktok Viral Takip", layout="wide")
st.markdown("""
<style>
    .stButton>button { width: 100%; border-radius: 5px; } 
    .stDeployButton {display:none;} 
    footer {visibility: hidden;} 
    #MainMenu {visibility: visible;} 
    [data-testid="stSidebar"] {min-width: 350px; max-width: 350px;}
    div[role="radiogroup"] > label:nth-child(2),
    div[role="radiogroup"] > label:nth-child(4),
    div[role="radiogroup"] > label:nth-child(6),
    div[role="radiogroup"] > label:nth-child(8) {
        border-bottom: 1px solid rgba(255, 255, 255, 0.2); 
        margin-bottom: 10px !important; 
        padding-bottom: 10px !important;
    }
</style>
""", unsafe_allow_html=True)

# --- SESSION STATE ---
if 'page' not in st.session_state: st.session_state.page = "Viral"
if 'analyzed_data' not in st.session_state: st.session_state.analyzed_data = None
if 'analysis_meta' not in st.session_state: st.session_state.analysis_meta = {}
if 'transfer_url' not in st.session_state: st.session_state.transfer_url = ""
if 'auto_start' not in st.session_state: st.session_state.auto_start = False
if 'discovery_results' not in st.session_state: st.session_state.discovery_results = None
if 'supplier_results' not in st.session_state: st.session_state.supplier_results = None
if 'meta_results' not in st.session_state: st.session_state.meta_results = None

# --- AYARLAR ---
CREDENTIALS_FILE = "credentials.json"
MASTER_SHEET_NAME = "Viral_Hunter_Master"

if "APIFY_TOKEN" in st.secrets:
    APIFY_TOKEN = st.secrets["APIFY_TOKEN"]
else:
    APIFY_TOKEN = "" 

client = ApifyClient(APIFY_TOKEN)

# --- ARAMA STRATEJİLERİ ---
SEARCH_STRATEGIES_TR = {
    "🔥 Türkiye Geneli (Viral)": ["#tiktokzamanı", "kargo bedava", "kapıda ödeme", "#aldım", "#öneri", "#trendyol", "link profilde", "bunu almalısın"],
    "🏠 Ev & Mutfak & Çeyiz": ["#mutfaksırları", "#pratikbilgiler", "çeyiz alışverişi", "#düzen", "mutfak aletleri", "#temizlikfikirleri", "akıllı ev ürünleri"],
    "💄 Güzellik & Bakım": ["#makyajvideoları", "#ciltbakımı", "güzellik sırları", "#bakımrutini", "uygun fiyatlı ürünler", "#kombinönerileri"],
    "🚗 Araç & Teknoloji": ["#arabaaksesuar", "oto aksesuar", "telefon aksesuarları", "teknolojik ürünler", "ofis masası"],
    "👶 Anne & Bebek": ["#bebekvideolari", "anne tavsiyesi", "bebek ihtiyaçları", "oyuncak inceleme", "#hamilelik"]
}

# --- GOOGLE SHEETS BAĞLANTISI ---
def get_gspread_client():
    scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
    if "gcp_service_account" in st.secrets:
        creds_dict = st.secrets["gcp_service_account"]
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    elif os.path.exists(CREDENTIALS_FILE):
        creds = ServiceAccountCredentials.from_json_keyfile_name(CREDENTIALS_FILE, scope)
    else:
        st.error("🚨 Kimlik doğrulama başarısız! Secrets eksik.")
        st.stop()
    return gspread.authorize(creds)

def init_master_sheet():
    gc = get_gspread_client()
    try:
        sh = gc.open(MASTER_SHEET_NAME)
        try: sh.worksheet("List")
        except: 
            ws = sh.add_worksheet(title="List", rows="100", cols="10")
            ws.append_row(["ID", "Urun_Adi", "Rakipler_Sekme_Adi", "Performans_Sekme_Adi", "Son_Analiz_Tarihi", "Sonraki_Analiz_Tarihi", "Son_Viral_Skor", "Durum", "URL", "Arama_Sorgusu"])
        try: sh.worksheet("Bookmarks")
        except:
            ws = sh.add_worksheet(title="Bookmarks", rows="100", cols="10")
            ws.append_row(["Tarih", "Aciklama", "Izlenme", "Viral_Skor", "Etkilesim", "Video_URL", "Resim_URL"])
        try: sh.worksheet("Suppliers")
        except:
            ws = sh.add_worksheet(title="Suppliers", rows="100", cols="10")
            ws.append_row(["ID", "Tarih", "Urun_Adi", "Tedarikci_Baslik", "Web_Sitesi", "Aciklama", "Arama_Terimi"])
        try: sh.worksheet("Meta_Results")
        except:
            ws = sh.add_worksheet(title="Meta_Results", rows="100", cols="10")
            ws.append_row(["ID", "Tarih", "Urun_Adi", "Baslik", "Link", "Aciklama", "Kaynak"])
        return sh
    except Exception as e:
        st.error(f"Google Sheet Hatası: '{MASTER_SHEET_NAME}' dosyası bulunamadı!")
        st.stop()

# --- MALİYET HESAPLAMA ---
def get_apify_usage_stats():
    try:
        user_info = client.user().get()
        limits = user_info.get('limits', {})
        usage = user_info.get('usage', {})
        runs = client.runs().list(limit=15, desc=True).items
        
        run_data = []
        for run in runs:
            actor_name = run.get('actId', 'Bilinmeyen')
            if "clockworks" in actor_name or "tiktok" in actor_name: actor_name = "TikTok Scraper"
            elif "google" in actor_name: actor_name = "Google Search"
            
            stats = run.get('stats', {})
            compute_units = stats.get('computeUnits', 0)
            status = run.get('status')
            
            start_time = run.get('startedAt')
            if start_time and isinstance(start_time, str):
                try: start_time = datetime.strptime(start_time.split('.')[0], "%Y-%m-%dT%H:%M:%S")
                except: pass
            
            run_data.append({
                "Tarih": start_time,
                "Modül": actor_name,
                "Durum": status,
                "Maliyet (CU)": round(compute_units, 5)
            })
            
        return limits, usage, pd.DataFrame(run_data)
    except Exception as e:
        st.error(f"Apify Verisi Alınamadı: {e}")
        return None, None, pd.DataFrame()

# --- ANALİZ VE SCRAPE FONKSİYONLARI ---
def clean_text_for_query(text):
    if not text: return ""
    text = re.sub(r'#\w+', '', text)
    text = re.sub(r'[^\w\sğüşıöçĞÜŞİÖÇ]', '', text)
    stop_words = ["keşfet", "fyp", "viral", "kapıda", "ödeme", "sipariş", "link", "bio", "banyo", "mutfak", "için", "ve", "ile", "bir", "bu", "istanbul", "türkiye", "kargo", "bedava"]
    words = text.split()
    filtered_words = [w for w in words if w.lower() not in stop_words]
    filtered_words = [w for w in filtered_words if len(w) > 2]
    if len(filtered_words) < 1: return ""
    return " ".join(filtered_words[:4]).strip()

def clean_hashtags_display(hashtag_str):
    try:
        if isinstance(hashtag_str, str):
            tags_list = ast.literal_eval(hashtag_str)
            return ", ".join([f"#{tag['name']}" for tag in tags_list if 'name' in tag])
        return ""
    except: return ""

def fetch_video_info(video_url):
    run_input = {"postURLs": [video_url], "resultsPerPage": 1}
    run = client.actor("clockworks/tiktok-scraper").call(run_input=run_input)
    if not run.get("defaultDatasetId"): return None, None
    items = client.dataset(run["defaultDatasetId"]).list_items().items
    return (items[0].get('text', ''), items[0]) if items else (None, None)

def search_competitors(query, limit=15):
    run_input = {
        "searchQueries": [query],
        "resultsPerPage": limit,
        "searchSection": "/video", 
        "shouldDownloadCovers": True,  
        "proxyConfiguration": { "useApifyProxy": True } 
    }
    try:
        run = client.actor("clockworks/tiktok-scraper").call(run_input=run_input, memory_mbytes=1024, timeout_secs=120)
        if run.get("defaultDatasetId"):
            items = client.dataset(run["defaultDatasetId"]).list_items().items
            return pd.DataFrame(items)
        return pd.DataFrame()
    except Exception as e:
        st.warning(f"Apify Arama Hatası: {e}")
        return pd.DataFrame()

# --- YENİ: TÜRKÇE İÇERİK FİLTRESİ ---
def filter_turkish_content(df):
    if df.empty: return df
    
    # Türkçe Karakterler ve Kelimeler
    tr_chars = ['ı', 'ğ', 'ş', 'ö', 'ç', 'ü', 'İ', 'Ğ', 'Ş', 'Ö', 'Ç', 'Ü']
    tr_keywords = ["fiyat", "kargo", "sipariş", "ne kadar", "link", "profil", "bilgi", "dm", "satış", "bedava", "indirim"]
    
    filtered_rows = []
    
    for _, row in df.iterrows():
        text = str(row.get('text', '')).lower()
        
        # 1. Dil Kodu Kontrolü (Varsa)
        lang = str(row.get('textLanguage', '')).lower()
        if lang == 'tr':
            filtered_rows.append(row)
            continue
            
        # 2. Karakter/Kelime Kontrolü (Dil kodu yoksa veya hatalıysa)
        # Metinde Türkçe karakter VEYA Türkçe ticaret kelimesi geçiyor mu?
        has_tr_char = any(char in text for char in tr_chars)
        has_tr_keyword = any(kw in text for kw in tr_keywords)
        
        if has_tr_char or has_tr_keyword:
            filtered_rows.append(row)
            
    return pd.DataFrame(filtered_rows)

def run_google_scraper(query, limit=20):
    run_input = {
        "queries": query, 
        "resultsPerPage": limit,
        "countryCode": "tr",
        "languageCode": "tr",
        "mobileResults": False,
        "csvFriendlyOutput": False
    }
    try:
        run = client.actor("apify/google-search-scraper").call(run_input=run_input)
        if run.get("defaultDatasetId"):
            items = client.dataset(run["defaultDatasetId"]).list_items().items
            all_results = []
            for item in items:
                if 'organicResults' in item and isinstance(item['organicResults'], list):
                    all_results.extend(item['organicResults'])
                elif 'paidResults' in item and isinstance(item['paidResults'], list):
                    all_results.extend(item['paidResults'])
                elif 'title' in item and 'url' in item: 
                    all_results.append(item)
            return pd.DataFrame(all_results)
        return pd.DataFrame()
    except:
        return pd.DataFrame()

def filter_suppliers_strict(df, search_term):
    if df.empty: return df
    mandatory_keywords = ["toptan", "wholesale", "imalat", "üretici", "ithalat", "toptancı", "supplier", "manufacturer", "distribütör", "istoç", "tahtakale", "merter", "bayi", "koli", "adetli", "toplu satış", "fabrikadan", "b2b"]
    banned_domains = ["trendyol.com", "hepsiburada.com", "amazon.com", "ciceksepeti.com", "sikayetvar.com", "youtube.com", "tiktok.com", "instagram.com", "facebook.com", "pinterest.com", "twitter.com", "n11.com", "pttavm.com"]
    filtered_rows = []
    for _, row in df.iterrows():
        title = str(row.get('title', '')).lower()
        desc = str(row.get('description', '')).lower()
        url = str(row.get('url', '')).lower()
        full_text = f"{title} {desc}"
        if any(ban in url for ban in banned_domains): continue
        if search_term.lower() in full_text: 
            if any(keyword in full_text for keyword in mandatory_keywords):
                filtered_rows.append(row)
    return pd.DataFrame(filtered_rows)

def calculate_metrics(df):
    cols = ['playCount', 'diggCount', 'shareCount', 'collectCount', 'commentCount']
    for col in cols:
        if col not in df.columns: df[col] = 0
        df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)
    if 'createTimeISO' not in df.columns: df['createTimeISO'] = pd.NaT
    else: df['createTimeISO'] = pd.to_datetime(df['createTimeISO'], errors='coerce', utc=True).dt.tz_localize(None)
    df['Viral_Skor'] = ((df['shareCount'] + df['collectCount']) / df['diggCount'].replace(0, 1)) * 100
    total_interaction = df['diggCount'] + df['shareCount'] + df['collectCount'] + df['commentCount']
    df['Etkilesim_Orani'] = (total_interaction / df['playCount'].replace(0, 1)) * 100
    df['Viral_Skor'] = df['Viral_Skor'].round(2)
    df['Etkilesim_Orani'] = df['Etkilesim_Orani'].round(2)
    def score_row(row):
        score = 0
        if row['Viral_Skor'] > 10: score += 40
        if row['playCount'] > 100000: score += 20
        if row['Etkilesim_Orani'] > 3: score += 20
        if row['shareCount'] > 200: score += 20
        return score
    df['Karar_Puani'] = df.apply(score_row, axis=1)
    df['Durum'] = df['Karar_Puani'].apply(lambda x: "WINNER 🏆" if x >= 60 else ("TAKİPTE 🟡" if x >= 40 else "ÇÖP 🔴"))
    return df

def generate_smart_analysis(df):
    avg_score = df['Karar_Puani'].mean()
    winner_count = df[df['Karar_Puani'] >= 60].shape[0]
    total_views = df['playCount'].sum()
    today = datetime.now()
    valid_dates = df['createTimeISO'].dropna()
    if not valid_dates.empty: avg_age_days = (today - valid_dates).dt.days.mean()
    else: avg_age_days = 30 
    if avg_age_days < 7 and avg_score > 50:
        next_check_days = 1
        date_comment = "🔥 **ÇOK TAZE TREND:** Videolar ortalama 1 haftadan yeni."
    elif avg_age_days < 30:
        next_check_days = 3
        date_comment = "✅ **AKTİF TREND:** Videolar son 1 ay içinde."
    else:
        next_check_days = 7
        date_comment = "❄️ **ESKİ TREND:** Videolar biraz eski."
    next_check_date = today.date() + timedelta(days=next_check_days)
    analysis = f"📊 **Pazar Özeti ({today.date()}):**\n\n"
    analysis += f"- Toplam {len(df)} video. Kümülatif İzlenme: **{total_views:,.0f}**\n"
    analysis += f"- Winner Sayısı: **{winner_count}**\n"
    analysis += f"- {date_comment}\n"
    return analysis, str(next_check_date)

def calculate_commercial_score(viral_score, supplier_count, meta_count, engagement_rate):
    score = 0
    if viral_score > 100: score += 40
    elif viral_score > 50: score += 30
    elif viral_score > 20: score += 15
    if supplier_count > 5: score += 30
    elif supplier_count > 0: score += 20
    if meta_count > 0: score += 20
    if engagement_rate > 5: score += 10
    elif engagement_rate > 2: score += 5
    return score

# --- KAYDETME FONKSİYONLARI ---
def quick_save_bookmark(desc, views, viral_score, engagement, url, image_url):
    try:
        sh = init_master_sheet()
        ws = sh.worksheet("Bookmarks")
        ws.append_row([str(datetime.now().date()), desc, views, float(viral_score), float(engagement), url, image_url])
        return True
    except: return False

def save_to_tracking_sheet(urun_adi, url, query, df, analysis_text, avg_viral_score, status, next_check_date):
    try:
        sh = init_master_sheet()
        uid = uuid.uuid4().hex[:6]
        ws_r = sh.add_worksheet(title=f"R_{uid}", rows="100", cols="20")
        clean = df.fillna("").astype(str)
        ws_r.update([clean.columns.values.tolist()] + clean.values.tolist())
        ws_p = sh.add_worksheet(title=f"P_{uid}", rows="100", cols="10")
        ws_p.append_row(["Tarih", "Ort_Viral_Skor", "Toplam_Izlenme", "Winner_Sayisi", "Analiz_Notu"])
        ws_p.append_row([str(datetime.now().date()), float(avg_viral_score), int(df['playCount'].sum()), int(df[df['Karar_Puani'] >= 60].shape[0]), analysis_text])
        master_ws = sh.worksheet("List")
        master_ws.append_row([uid, urun_adi, f"R_{uid}", f"P_{uid}", str(datetime.now().date()), next_check_date, avg_viral_score, status, url, query])
        return True
    except Exception as e:
        st.error(f"Hata: {e}")
        return False

def update_product_data(rakipler_tab, performans_tab, df, analysis_text, avg_viral_score, next_check_date):
    try:
        sh = init_master_sheet()
        ws_rakipler = sh.worksheet(rakipler_tab)
        ws_rakipler.clear()
        clean = df.fillna("").astype(str)
        ws_rakipler.update([clean.columns.values.tolist()] + clean.values.tolist())
        sh.worksheet(performans_tab).append_row([str(datetime.now().date()), float(avg_viral_score), int(df['playCount'].sum()), int(df[df['Karar_Puani'] >= 60].shape[0]), analysis_text])
        return True
    except: return False

def save_extra_results(sheet_name, data_list):
    try:
        sh = init_master_sheet()
        ws = sh.worksheet(sheet_name)
        for row in data_list: ws.append_row(row)
        return True
    except Exception as e:
        st.error(f"Kayıt Hatası: {e}")
        return False

# --- MENÜ VE NAVİGASYON ---
st.sidebar.title("Tiktok Viral Takip 🤖")

MENU_MAP = {
    "🔭 Viral Ürün Bulucu (Gözcü)": "Viral",
    "🚀 Ürün Analizi (Avcı)": "Analiz",
    "📈 Takip Edilenler (Merkez)": "Takip",
    "📌 Kaydedilenler (Depo)": "Depo",
    "📢 Meta Reklam Gözcüsü": "Meta_Spy",
    "💾 Meta Kaydedilenler": "Meta_DB",
    "🏭 Tedarikçi Bulucu (İstihbarat)": "Tedarik",
    "🗃️ Tedarikçi Veritabanı (Arşiv)": "Arşiv",
    "💰 Bakiye & Maliyet (Muhasebe)": "Cost"
}

menu_keys = list(MENU_MAP.keys())
try:
    current_label = [k for k, v in MENU_MAP.items() if v == st.session_state.page][0]
    current_index = menu_keys.index(current_label)
except:
    current_index = 0

selected_label = st.sidebar.radio("Modüller:", menu_keys, index=current_index)
selection = MENU_MAP[selected_label]

if selection != st.session_state.page:
    st.session_state.page = selection
    st.session_state.auto_start = False
    st.rerun()

# ----------------- 1. GÖZCÜ -----------------
if st.session_state.page == "Viral":
    st.title("🔭 Viral Ürün Bulucu (Gözcü)")
    search_type = st.radio("Tip:", ["Kategori", "Manuel"], horizontal=True)
    c1, c2 = st.columns([3,1])
    if search_type == "Kategori": 
        with c1: cat = st.selectbox("Kategori:", list(SEARCH_STRATEGIES_TR.keys()))
    else: 
        with c1: query_inp = st.text_input("Arama:", placeholder="örn: kapıda ödeme")
    with c2: day_filter = st.selectbox("Zaman:", ["Son 7 Gün", "Son 30 Gün"], index=1)
    
    if st.button("🔍 Ürünleri Ara"):
        q = random.choice(SEARCH_STRATEGIES_TR[cat]) if search_type == "Kategori" else query_inp
        if q:
            with st.spinner(f"'{q}' taranıyor..."):
                # Limiti artırdık çünkü filtreleyince azalacak
                df = search_competitors(q, limit=60)
                if not df.empty:
                    df = calculate_metrics(df)
                    
                    # 1. TÜRKÇE FİLTRESİ (YENİ EKLENDİ)
                    df = filter_turkish_content(df)
                    
                    if not df.empty:
                        today = datetime.now()
                        days_num = 7 if day_filter == "Son 7 Gün" else 30
                        if 'createTimeISO' in df.columns: df = df[df['createTimeISO'] >= (today - timedelta(days=days_num))]
                        df = df[df['playCount'] > 1000]
                        st.session_state.discovery_results = df.sort_values(by='Viral_Skor', ascending=False).head(20)
                    else:
                        st.warning(f"'{q}' için içerik bulundu ama Türkçe filtresine takıldı. Başka terim deneyin.")
                else: st.warning("Bulunamadı.")
    
    if st.session_state.discovery_results is not None:
        st.success(f"✅ {len(st.session_state.discovery_results)} ürün.")
        for i, r in st.session_state.discovery_results.iterrows():
            with st.container():
                c1, c2, c3, c4 = st.columns([1,3,2,2])
                with c1: 
                    if r.get('videoMeta'): st.image(r['videoMeta'].get('coverUrl',''), use_column_width=True)
                with c2: 
                    st.write(f"**{r['text'][:90]}...**")
                    st.caption(f"Tarih: {r['createTimeISO'].date()}")
                    st.markdown(f"[🎥 Git]({r['webVideoUrl']})")
                with c3: 
                    st.metric("İzlenme", f"{int(r['playCount']):,}")
                    st.metric("Viral", f"{r['Viral_Skor']:.1f}")
                    st.metric("Etkileşim", f"%{r['Etkilesim_Orani']:.2f}")
                with c4:
                    if st.button("🚀 Analiz", key=f"a{i}"):
                        st.session_state.transfer_url = r['webVideoUrl']; st.session_state.auto_start = True; 
                        st.session_state.page = "Analiz" 
                        st.rerun()
                    if st.button("📌 Kaydet", key=f"s{i}"):
                        if quick_save_bookmark(r['text'][:100], int(r['playCount']), r['Viral_Skor'], r['Etkilesim_Orani'], r['webVideoUrl'], r['videoMeta'].get('coverUrl','')): st.toast("Kaydedildi")
            st.markdown("---")

# ----------------- 2. AVCI -----------------
elif st.session_state.page == "Analiz":
    st.title("🚀 Ürün Analizi (Avcı)")
    val = st.session_state.transfer_url
    c1, c2 = st.columns([2,1])
    with c1: url = st.text_input("URL:", value=val)
    with c2: name = st.text_input("Manuel İsim:")
    
    def run_anl(u, n):
        q = n
        if not q:
            with st.spinner("İsim alınıyor..."):
                txt, _ = fetch_video_info(u)
                q = clean_text_for_query(txt) if txt else ""
        if q:
            with st.spinner(f"'{q}' analiz ediliyor..."):
                df = search_competitors(q, limit=15)
                if not df.empty:
                    df = calculate_metrics(df)
                    # BURAYA DA TÜRKÇE FİLTRESİ EKLENDİ
                    df = filter_turkish_content(df)
                    
                    if not df.empty:
                        ai, nxt = generate_smart_analysis(df)
                        st.session_state.analyzed_data = df
                        st.session_state.analysis_meta = {"q": q, "u": u, "ai": ai, "date": nxt, "score": df['Karar_Puani'].mean(), "viral": df['Viral_Skor'].mean(), "status": "WINNER 🏆" if df['Karar_Puani'].mean()>=60 else "NORMAL"}
                        st.session_state.transfer_url = ""; st.session_state.auto_start = False
                    else: st.error("Rakip bulundu ama Türkçe değil.")
                else: st.error("Rakip bulunamadı.")
    
    if st.button("Analiz Et") and url: run_anl(url, name)
    if st.session_state.auto_start and url: run_anl(url, name)
    
    if st.session_state.analyzed_data is not None:
        if st.session_state.analyzed_data.empty:
            st.warning("Veri yok."); st.session_state.analyzed_data = None; st.rerun()
            
        df = st.session_state.analyzed_data
        curr_s = df['Karar_Puani'].mean()
        curr_v = df['Viral_Skor'].mean()
        st.session_state.analysis_meta.update({"score": curr_s, "viral": curr_v})
        m = st.session_state.analysis_meta
        
        c1, c2 = st.columns([1,2])
        with c1:
            st.metric("Puan", f"{curr_s:.1f}"); st.metric("Viral", f"%{curr_v:.1f}")
            st.info(f"Kontrol: {m['date']}") 
            st.markdown(m['ai'])
            if st.button("💾 TEMİZLENMİŞ KAYDET"):
                if save_to_tracking_sheet(m['query'], m['url'], m['query'], df, m['ai'], curr_v, m['status'], m['date']):
                    st.success("Kaydedildi!"); time.sleep(1); st.session_state.analyzed_data = None; st.rerun()
        with c2:
            st.subheader(f"📋 Analiz ({len(df)})")
            for i, r in df.iterrows():
                with st.container():
                    i1, i2, i3 = st.columns([3,1,1])
                    with i1: st.write(f"**{r['text'][:60]}...**"); st.markdown(f"[🎥 Git]({r['webVideoUrl']})")
                    with i2: st.caption(f"👁️ {int(r['playCount']):,}"); st.markdown(f"Viral: %{r['Viral_Skor']:.1f}")
                    with i3:
                        if st.button("🗑️ Sil", key=f"del_{i}"):
                            st.session_state.analyzed_data = df.drop(i); st.rerun()
                st.markdown("---")

# ----------------- 3. MERKEZ -----------------
elif st.session_state.page == "Takip":
    st.title("📈 Takip Edilenler (Merkez)")
    sh = init_master_sheet()
    try:
        data = sh.worksheet("List").get_all_records()
        if data:
            master = pd.DataFrame(data)
            prod = st.selectbox("Ürün:", master['Urun_Adi'].tolist())
            if prod:
                p = master[master['Urun_Adi'] == prod].iloc[0]
                try:
                    perf = pd.DataFrame(sh.worksheet(p['Performans_Sekme_Adi']).get_all_records())
                    rakipler = pd.DataFrame(sh.worksheet(p['Rakipler_Sekme_Adi']).get_all_records())
                    
                    st.info(f"Durum: {p['Durum']} | Sonraki Kontrol: {p['Sonraki_Analiz_Tarihi']}")
                    
                    if not rakipler.empty:
                        rakipler['Viral_Skor'] = pd.to_numeric(rakipler['Viral_Skor'], errors='coerce').fillna(0)
                        rakipler['Etkilesim_Orani'] = pd.to_numeric(rakipler['Etkilesim_Orani'], errors='coerce').fillna(0)
                        
                        live_viral = rakipler['Viral_Skor'].mean()
                        live_eng = rakipler['Etkilesim_Orani'].mean()
                        total_views = rakipler['playCount'].sum()
                        winner_count = len(rakipler[rakipler['Karar_Puani'] >= 60]) if 'Karar_Puani' in rakipler.columns else 0

                        # Karar Matrisi
                        try: supp_cnt = len(pd.DataFrame(sh.worksheet("Suppliers").get_all_records()).query(f'Urun_Adi == "{prod}"'))
                        except: supp_cnt = 0
                        try: meta_cnt = len(pd.DataFrame(sh.worksheet("Meta_Results").get_all_records()).query(f'Urun_Adi == "{prod}"'))
                        except: meta_cnt = 0
                        
                        comm_score = calculate_commercial_score(live_viral, supp_cnt, meta_cnt, live_eng)
                        
                        st.markdown("### 🧠 KARAR MOTORU")
                        sc1, sc2 = st.columns([1,2])
                        with sc1:
                            st.metric("GÜVEN SKORU", f"{comm_score}/100")
                            if comm_score>=75: st.success("ALIM EMRİ ✅")
                            elif comm_score>=50: st.warning("RİSKLİ ⚠️")
                            else: st.error("BEKLE ⛔")
                        with sc2:
                            st.caption(f"Tedarikçi: {supp_cnt} | Meta İzi: {meta_cnt} | Kalite: %{live_eng:.1f}")

                        st.markdown("---")
                        c1, c2, c3, c4 = st.columns(4)
                        c1.metric("Ort. Viral", f"%{live_viral:.2f}")
                        c2.metric("Ort. Etkileşim", f"%{live_eng:.2f}")
                        c3.metric("İzlenme", f"{int(total_views):,}")
                        c4.metric("Winner", winner_count)
                        if not perf.empty: st.info(perf.iloc[-1]['Analiz_Notu'])

                    st.markdown("---"); st.subheader("🕵️ İstihbarat")
                    cm, cs = st.columns(2)
                    with cm:
                        if st.button("📢 Meta Tara", use_container_width=True):
                            mq = f'"{p["Arama_Sorgusu"]}" site:facebook.com OR site:instagram.com "fiyat" OR "sipariş"'
                            dfm = run_google_scraper(mq, 10)
                            if not dfm.empty:
                                rows = [[str(p['ID']), str(datetime.now().date()), prod, r.get('title',''), r.get('url',''), r.get('description',''), "Meta"] for _, r in dfm.iterrows()]
                                save_extra_results("Meta_Results", rows); st.success("Bulundu!"); time.sleep(1); st.rerun()
                            else: st.warning("Yok.")
                    with cs:
                        if st.button("🏭 Tedarikçi Tara", use_container_width=True):
                            qs = [f'"{p["Arama_Sorgusu"]}" toptan satış', f'"{p["Arama_Sorgusu"]}" imalatçı firma']
                            all_raw = pd.DataFrame()
                            for q in qs:
                                df_part = run_google_scraper(q, limit=20)
                                if not df_part.empty: all_raw = pd.concat([all_raw, df_part], ignore_index=True)
                            
                            if not all_raw.empty:
                                all_raw = all_raw.drop_duplicates(subset=['url'])
                                final_df = filter_suppliers_strict(all_raw, p["Arama_Sorgusu"])
                                if not final_df.empty:
                                    rows = [[str(p['ID']), str(datetime.now().date()), prod, r.get('title',''), r.get('url',''), r.get('description',''), "Google"] for _, r in final_df.iterrows()]
                                    save_extra_results("Suppliers", rows); st.success(f"{len(final_df)} adet bulundu!"); time.sleep(1); st.rerun()
                                else: st.warning("Kriterlere uyan yok.")
                            else: st.warning("Sonuç yok.")
                    
                    st.markdown("---"); st.subheader("⚡ Veri Güncelleme")
                    limit = st.slider("Video Sayısı", 15, 50, 15)
                    if st.button("🔄 GÜNCELLE"):
                        with st.spinner("Güncelleniyor..."):
                            ndf = search_competitors(p['Arama_Sorgusu'], limit=limit)
                            if not ndf.empty:
                                ndf = calculate_metrics(ndf)
                                ai, nxt = generate_smart_analysis(ndf)
                                update_product_data(p['Rakipler_Sekme_Adi'], p['Performans_Sekme_Adi'], ndf, ai, ndf['Viral_Skor'].mean(), nxt)
                                st.success("Tamam"); st.rerun()
                    
                    st.subheader("📋 Rakipler")
                    wanted = ['text', 'playCount', 'Viral_Skor', 'Etkilesim_Orani', 'createTimeISO']
                    final = [c for c in wanted if c in rakipler.columns]
                    st.data_editor(rakipler[final], use_container_width=True, disabled=True)
                except: st.error("Veri okunamadı")
    except: st.error("Hata")

# ----------------- 4. DEPO -----------------
elif st.session_state.page == "Depo":
    st.title("📌 Kaydedilenler (Depo)")
    sh = init_master_sheet()
    try:
        data = sh.worksheet("Bookmarks").get_all_records()
        if data:
            st.data_editor(pd.DataFrame(data).iloc[::-1], column_config={"Resim_URL": st.column_config.ImageColumn("Resim"), "Video_URL": st.column_config.LinkColumn("Link", display_text="▶️")}, use_container_width=True, hide_index=True)
        else: st.info("Boş")
    except: st.error("Hata")

# ----------------- 5. META SPY -----------------
elif st.session_state.page == "Meta_Spy":
    st.title("📢 Meta Reklam Gözcüsü")
    c1, c2 = st.columns([3,1])
    with c1: search_term = st.text_input("Ürün:", placeholder="akıllı saat")
    if st.button("🔍 Ara") and search_term:
        st.session_state.meta_results = None
        q = f'"{search_term}" site:facebook.com OR site:instagram.com "sponsorlu" OR "fiyat" OR "sipariş"'
        with st.status("Taranıyor..."):
            df = run_google_scraper(q, 20)
            st.session_state.meta_results = df if not df.empty else None
    
    if st.session_state.meta_results is not None:
        res = st.session_state.meta_results
        st.success(f"{len(res)} sonuç.")
        st.data_editor(res[['title', 'description', 'url']], column_config={"url": st.column_config.LinkColumn("Link", display_text="🔗")}, use_container_width=True)
        if st.button("💾 Kaydet"):
            rows = [[str(uuid.uuid4().hex[:8]), str(datetime.now().date()), search_term, r.get('title',''), r.get('url',''), r.get('description',''), "Meta Spy"] for _, r in res.iterrows()]
            if save_extra_results("Meta_Results", rows): st.success("Kaydedildi"); time.sleep(2)

# ----------------- 6. META ARŞİV -----------------
elif st.session_state.page == "Meta_DB":
    st.title("💾 Meta Kaydedilenler")
    sh = init_master_sheet()
    try:
        data = sh.worksheet("Meta_Results").get_all_records()
        if data:
            df = pd.DataFrame(data)
            filt = st.selectbox("Filtre:", ["Tümü"] + list(df['Urun_Adi'].unique()))
            if filt != "Tümü": df = df[df['Urun_Adi'] == filt]
            st.data_editor(df[['Tarih', 'Urun_Adi', 'Baslik', 'Link', 'Aciklama']], column_config={"Link": st.column_config.LinkColumn("Link", display_text="🔗")}, use_container_width=True)
            if st.button("⚠️ Temizle"): 
                ws = sh.worksheet("Meta_Results"); ws.clear(); ws.append_row(["ID", "Tarih", "Urun_Adi", "Baslik", "Link", "Aciklama", "Kaynak"]); st.rerun()
        else: st.info("Boş")
    except: st.error("Hata")

# ----------------- 7. TEDARİK -----------------
elif st.session_state.page == "Tedarik":
    st.title("🏭 Tedarikçi Bulucu (İstihbarat)")
    c1, c2 = st.columns([3,1])
    with c1: search_term = st.text_input("Ürün:", placeholder="ayetel kürsi bileklik")
    
    if st.button("🚀 Ara") and search_term:
        st.session_state.supplier_results = None 
        qs = [f'"{search_term}" toptan satış', f'"{search_term}" imalatçı', f'"{search_term}" istoç toptan']
        all_raw = pd.DataFrame()
        with st.status("Taranıyor..."):
            for q in qs:
                df = run_google_scraper(q, 40)
                if not df.empty:
                    df['Arama_Tipi'] = q
                    all_raw = pd.concat([all_raw, df], ignore_index=True)
            if not all_raw.empty:
                all_raw = all_raw.drop_duplicates(subset=['url'])
                final = filter_suppliers_strict(all_raw, search_term)
                st.session_state.supplier_results = final if not final.empty else None
    
    if st.session_state.supplier_results is not None:
        res = st.session_state.supplier_results
        st.success(f"{len(res)} sonuç.")
        st.data_editor(res[['title', 'description', 'url', 'Arama_Tipi']], column_config={"url": st.column_config.LinkColumn("Site", display_text="🌍 Git")}, use_container_width=True)
        if st.button("💾 Kaydet"):
            rows = [[str(uuid.uuid4().hex[:8]), str(datetime.now().date()), search_term, r.get('title',''), r.get('url',''), r.get('description',''), "Search"] for _, r in res.iterrows()]
            if save_extra_results("Suppliers", rows): st.success("Tamam"); time.sleep(2)

# ----------------- 8. ARŞİV -----------------
elif st.session_state.page == "Arşiv":
    st.title("🗃️ Tedarikçi Arşivi")
    sh = init_master_sheet()
    try:
        data = sh.worksheet("Suppliers").get_all_records()
        if data:
            df = pd.DataFrame(data)
            filt = st.selectbox("Filtre:", ["Tümü"] + list(df['Urun_Adi'].unique()))
            if filt != "Tümü": df = df[df['Urun_Adi'] == filt]
            st.data_editor(df[['Tarih', 'Urun_Adi', 'Tedarikci_Baslik', 'Web_Sitesi', 'Aciklama']], column_config={"Web_Sitesi": st.column_config.LinkColumn("Link", display_text="🌍 Git")}, use_container_width=True)
            if st.button("⚠️ Temizle"): 
                ws = sh.worksheet("Suppliers"); ws.clear(); ws.append_row(["ID", "Tarih", "Urun_Adi", "Tedarikci_Baslik", "Web_Sitesi", "Aciklama", "Kanal_Tipi"]); st.rerun()
        else: st.info("Boş")
    except: st.error("Hata")

# ----------------- 9. MUHASEBE -----------------
elif st.session_state.page == "Cost":
    st.title("💰 Bakiye & Maliyet (Muhasebe)")
    limits, usage, df_runs = get_apify_usage_stats()
    if limits:
        c1, c2, c3 = st.columns(3)
        total = limits.get('actorComputeUnits', 0)
        used = usage.get('actorComputeUnits', 0)
        c1.metric("Kullanılan", f"{used:.2f} CU")
        c2.metric("Kalan", f"{total-used:.2f} CU")
        c3.metric("Doluluk", f"{(used/total)*100:.1f}%")
        st.progress(min((used/total), 1.0))
    st.subheader("📉 Son Harcamalar")
    if not df_runs.empty: st.dataframe(df_runs, use_container_width=True)
    else: st.info("Kayıt yok.")