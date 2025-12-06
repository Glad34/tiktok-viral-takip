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

# --- AYARLAR VE ŞİFRELER ---
CREDENTIALS_FILE = "credentials.json"
MASTER_SHEET_NAME = "Viral_Hunter_Master"

if "APIFY_TOKEN" in st.secrets:
    APIFY_TOKEN = st.secrets["APIFY_TOKEN"]
else:
    APIFY_TOKEN = "" # Yerel test için token buraya (GitHub'da boş bırak)

client = ApifyClient(APIFY_TOKEN)

# --- ARAMA STRATEJİLERİ (TÜRKİYE) ---
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
        # 1. Takip Listesi
        try: sh.worksheet("List")
        except: 
            ws = sh.add_worksheet(title="List", rows="100", cols="10")
            ws.append_row(["ID", "Urun_Adi", "Rakipler_Sekme_Adi", "Performans_Sekme_Adi", "Son_Analiz_Tarihi", "Sonraki_Analiz_Tarihi", "Son_Viral_Skor", "Durum", "URL", "Arama_Sorgusu"])
        # 2. Hızlı Kayıtlar
        try: sh.worksheet("Bookmarks")
        except:
            ws = sh.add_worksheet(title="Bookmarks", rows="100", cols="10")
            ws.append_row(["Tarih", "Aciklama", "Izlenme", "Viral_Skor", "Etkilesim", "Video_URL", "Resim_URL"])
        # 3. Tedarikçiler
        try: sh.worksheet("Suppliers")
        except:
            ws = sh.add_worksheet(title="Suppliers", rows="100", cols="10")
            ws.append_row(["ID", "Tarih", "Urun_Adi", "Tedarikci_Baslik", "Web_Sitesi", "Aciklama", "Arama_Terimi"])
        # 4. Meta Sonuçları
        try: sh.worksheet("Meta_Results")
        except:
            ws = sh.add_worksheet(title="Meta_Results", rows="100", cols="10")
            ws.append_row(["ID", "Tarih", "Urun_Adi", "Baslik", "Link", "Aciklama", "Kaynak"])
            
        return sh
    except Exception as e:
        st.error(f"Google Sheet Hatası: '{MASTER_SHEET_NAME}' dosyası bulunamadı!")
        st.stop()

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
    run_input = {"searchQueries": [query], "resultsPerPage": limit}
    run = client.actor("clockworks/tiktok-scraper").call(run_input=run_input)
    if run.get("defaultDatasetId"):
        items = client.dataset(run["defaultDatasetId"]).list_items().items
        return pd.DataFrame(items)
    return pd.DataFrame()

# GOOGLE SEARCH (Düzeltilmiş)
def run_google_scraper(query, limit=20):
    run_input = {
        "queries": query, 
        "resultsPerPage": limit,
        "countryCode": "tr",
        "languageCode": "tr",
        "mobileResults": False,
        "csvFriendlyOutput": False
    }
    run = client.actor("apify/google-search-scraper").call(run_input=run_input)
    if run.get("defaultDatasetId"):
        items = client.dataset(run["defaultDatasetId"]).list_items().items
        all_results = []
        for item in items:
            if 'organicResults' in item:
                all_results.extend(item['organicResults'])
        return pd.DataFrame(all_results)
    return pd.DataFrame()

# --- GELİŞMİŞ TEDARİKÇİ FİLTRESİ (STRICT) ---
def filter_suppliers_strict(df, search_term):
    if df.empty: return df
    
    # 1. Zorunlu Kelimeler (Bunlardan biri yoksa toptancı değildir)
    mandatory_keywords = [
        "toptan", "wholesale", "imalat", "üretici", "ithalat", 
        "toptancı", "supplier", "manufacturer", "distribütör", 
        "istoç", "tahtakale", "merter", "bayi", "koli", 
        "adetli", "toplu satış", "fabrikadan", "b2b"
    ]
    
    # 2. Yasaklı Siteler (Perakende ve Sosyal Medya)
    banned_domains = ["trendyol.com", "hepsiburada.com", "amazon.com", "ciceksepeti.com", "sikayetvar.com", "youtube.com", "tiktok.com", "instagram.com", "facebook.com", "pinterest.com", "twitter.com", "n11.com", "pttavm.com"]

    filtered_rows = []
    
    for _, row in df.iterrows():
        title = str(row.get('title', '')).lower()
        desc = str(row.get('description', '')).lower()
        url = str(row.get('url', '')).lower()
        full_text = f"{title} {desc}"
        
        # A. Yasaklı site kontrolü
        if any(ban in url for ban in banned_domains):
            continue
            
        # B. Toptan Kelime Kontrolü
        # Arama terimi (ürün adı) de geçmeli
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

# --- KAYDETME FONKSİYONLARI ---
def quick_save_bookmark(desc, views, viral_score, engagement, url, image_url):
    try:
        sh = init_master_sheet()
        ws = sh.worksheet("Bookmarks")
        ws.append_row([str(datetime.now().date()), desc, views, float(viral_score), float(engagement), url, image_url])
        return True
    except Exception as e:
        st.error(f"Hata: {e}")
        return False

def save_to_tracking_sheet(urun_adi, url, query, df, analysis_text, avg_viral_score, status, next_check_date):
    try:
        sh = init_master_sheet()
        unique_id = uuid.uuid4().hex[:6]
        rakipler_tab_name = f"R_{unique_id}"
        performans_tab_name = f"P_{unique_id}"
        ws_rakipler = sh.add_worksheet(title=rakipler_tab_name, rows="100", cols="20")
        clean_df = df.fillna("").astype(str)
        ws_rakipler.update([clean_df.columns.values.tolist()] + clean_df.values.tolist())
        ws_perf = sh.add_worksheet(title=performans_tab_name, rows="100", cols="10")
        ws_perf.append_row(["Tarih", "Ort_Viral_Skor", "Toplam_Izlenme", "Winner_Sayisi", "Analiz_Notu"])
        ws_perf.append_row([str(datetime.now().date()), float(avg_viral_score), int(df['playCount'].sum()), int(df[df['Karar_Puani'] >= 60].shape[0]), analysis_text])
        master_ws = sh.worksheet("List")
        master_ws.append_row([unique_id, urun_adi, rakipler_tab_name, performans_tab_name, str(datetime.now().date()), next_check_date, avg_viral_score, status, url, query])
        return True
    except Exception as e:
        st.error(f"Hata: {e}")
        return False

def update_product_data(rakipler_tab_name, performans_tab_name, df, analysis_text, avg_viral_score, next_check_date):
    try:
        sh = init_master_sheet()
        ws_rakipler = sh.worksheet(rakipler_tab_name)
        ws_rakipler.clear()
        clean_df = df.fillna("").astype(str)
        ws_rakipler.update([clean_df.columns.values.tolist()] + clean_df.values.tolist())
        ws_perf = sh.worksheet(performans_tab_name)
        ws_perf.append_row([str(datetime.now().date()), float(avg_viral_score), int(df['playCount'].sum()), int(df[df['Karar_Puani'] >= 60].shape[0]), analysis_text])
        return True
    except Exception as e:
        st.error(f"Hata: {e}")
        return False

def save_extra_results(sheet_name, data_list):
    try:
        sh = init_master_sheet()
        ws = sh.worksheet(sheet_name)
        for row in data_list: ws.append_row(row)
        return True
    except Exception as e:
        st.error(f"Kayıt Hatası: {e}")
        return False

# --- SAYFA YAPILANDIRMASI ---
st.set_page_config(page_title="Tiktok Viral Takip", layout="wide")
st.markdown("""<style>.stButton>button { width: 100%; border-radius: 5px; } .stDeployButton {display:none;} footer {visibility: hidden;} #MainMenu {visibility: visible;}</style>""", unsafe_allow_html=True)

if 'analyzed_data' not in st.session_state: st.session_state.analyzed_data = None
if 'analysis_meta' not in st.session_state: st.session_state.analysis_meta = {}
if 'transfer_url' not in st.session_state: st.session_state.transfer_url = ""
if 'auto_start' not in st.session_state: st.session_state.auto_start = False
if 'discovery_results' not in st.session_state: st.session_state.discovery_results = None
if 'supplier_results' not in st.session_state: st.session_state.supplier_results = None

# Sidebar
st.sidebar.title("Tiktok Viral Takip 🤖")
menu_options = ["🔭 Viral Ürün Bulucu", "🚀 Ürün Analizi", "📈 Takip Edilenler", "📌 Kaydedilenler", "──────────", "🏭 Tedarikçi Bulucu", "🗃️ Tedarikçi Veritabanı"]
if 'page' not in st.session_state: st.session_state.page = "🔭 Viral Ürün Bulucu"

selection = st.sidebar.radio("Modüller", menu_options, index=0 if st.session_state.page not in menu_options else menu_options.index(st.session_state.page))
if selection == "──────────": st.session_state.page = "🔭 Viral Ürün Bulucu"; st.rerun()
elif selection != st.session_state.page: st.session_state.page = selection; st.session_state.auto_start = False; st.rerun()

# ----------------- 1. VİRAL ÜRÜN BULUCU -----------------
if st.session_state.page == "🔭 Viral Ürün Bulucu":
    st.title("🔭 Türkiye Viral Ürün Keşfi")
    search_type = st.radio("Arama Yöntemi:", ["Kategoriden Seç", "Manuel Hashtag/Kelime Ara"], horizontal=True)
    col_cat, col_day = st.columns([3, 1])
    final_query = ""
    if search_type == "Kategoriden Seç":
        with col_cat: category = st.selectbox("Kategori Seçiniz:", list(SEARCH_STRATEGIES_TR.keys()))
    else: 
        with col_cat: final_query = st.text_input("Aranacak Hashtag veya Kelime:", placeholder="Örn: kapıda ödeme")
    with col_day: days_filter = st.selectbox("Zaman:", ["Son 7 Gün", "Son 30 Gün"], index=1)
    if st.button("🔍 Ürünleri Ara"):
        selected_query = random.choice(SEARCH_STRATEGIES_TR[category]) if search_type == "Kategoriden Seç" else final_query
        if not selected_query: st.error("Arama terimi girin!")
        else:
            with st.spinner(f"'{selected_query}' taranıyor..."):
                df_discovery = search_competitors(selected_query, limit=50)
                if not df_discovery.empty:
                    df_discovery = calculate_metrics(df_discovery)
                    today = datetime.now()
                    days_num = 7 if days_filter == "Son 7 Gün" else 30
                    if 'createTimeISO' in df_discovery.columns: df_discovery = df_discovery[df_discovery['createTimeISO'] >= (today - timedelta(days=days_num))]
                    df_discovery = df_discovery[df_discovery['playCount'] > 5000] 
                    df_discovery = df_discovery.sort_values(by='Viral_Skor', ascending=False).head(20)
                    st.session_state.discovery_results = df_discovery
                else: st.warning("Veri bulunamadı."); st.session_state.discovery_results = None
    if st.session_state.discovery_results is not None:
        st.success(f"✅ {len(st.session_state.discovery_results)} ürün listeleniyor.")
        for index, row in st.session_state.discovery_results.iterrows():
            with st.container():
                c1, c2, c3, c4 = st.columns([1, 3, 2, 2])
                with c1:
                    if row.get('videoMeta'): st.image(row['videoMeta'].get('coverUrl', ''), use_column_width=True)
                with c2:
                    st.write(f"**{row['text'][:90]}...**")
                    st.caption(f"Tarih: {row['createTimeISO'].date()}")
                    st.markdown(f"[🎥 Videoya Git ↗️]({row['webVideoUrl']})", unsafe_allow_html=True)
                with c3:
                    st.metric("İzlenme", f"{int(row['playCount']):,}")
                    st.metric("Viral Skor", f"%{row['Viral_Skor']:.1f}") 
                with c4:
                    if st.button("🚀 Analiz Et", key=f"anl_{index}"):
                        st.session_state.transfer_url = row['webVideoUrl']; st.session_state.auto_start = True; st.session_state.page = "🚀 Ürün Analizi"; st.rerun()
                    if st.button("📌 Kaydet", key=f"sav_{index}"):
                        if quick_save_bookmark(row['text'][:100], int(row['playCount']), row['Viral_Skor'], row['Etkilesim_Orani'], row['webVideoUrl'], row['videoMeta'].get('coverUrl', '')): st.toast("Kaydedildi!", icon="📌")
            st.markdown("---")

# ----------------- 2. ÜRÜN ANALİZİ -----------------
elif st.session_state.page == "🚀 Ürün Analizi":
    st.title("🚀 Detaylı Ürün Analizi")
    url_val = st.session_state.transfer_url
    col1, col2 = st.columns([2, 1])
    with col1: url = st.text_input("TikTok Video URL:", value=url_val)
    with col2: manual_prod_name = st.text_input("Ürün Adı (Opsiyonel):")
    
    def run_analysis(target_url, manual_name):
        query = manual_name
        if not query:
            with st.spinner("İsim algılanıyor..."):
                txt, _ = fetch_video_info(target_url)
                if txt: query = clean_text_for_query(txt)
                else: st.error("Video çekilemedi"); return
        if not query: st.warning("Ürün adı bulunamadı, manuel girin."); return
        
        with st.spinner(f"'{query}' analiz ediliyor..."):
            df = search_competitors(query, limit=15)
            if not df.empty:
                df = calculate_metrics(df)
                ai, nxt = generate_smart_analysis(df)
                st.session_state.analyzed_data = df
                st.session_state.analysis_meta = {"query": query, "url": target_url, "ai": ai, "date": nxt, "score": df['Karar_Puani'].mean(), "viral": df['Viral_Skor'].mean(), "status": "WINNER 🏆" if df['Karar_Puani'].mean() >= 60 else "NORMAL"}
                st.session_state.transfer_url = ""
                st.session_state.auto_start = False
            else: st.error("Rakip bulunamadı.")

    if st.button("Analiz Et") and url: run_analysis(url, manual_prod_name)
    if st.session_state.auto_start and url: run_analysis(url, manual_prod_name)

    if st.session_state.analyzed_data is not None:
        meta = st.session_state.analysis_meta
        c1, c2 = st.columns([1, 2])
        with c1:
            st.metric("Puan", f"{meta['score']:.1f}"); st.metric("Viral", f"%{meta['viral']:.1f}")
            st.markdown(meta['ai']); st.info(f"Kontrol: {meta['date']}")
            if st.button("💾 TAKİBE AL"):
                if save_to_tracking_sheet(meta['query'], meta['url'], meta['query'], st.session_state.analyzed_data, meta['ai'], meta['viral'], meta['status'], meta['date']):
                    st.success("Kaydedildi!"); time.sleep(1); st.session_state.analyzed_data = None; st.rerun()
        with c2:
            st.dataframe(st.session_state.analyzed_data[['text', 'playCount', 'Viral_Skor', 'webVideoUrl']])

# ----------------- 3. TAKİP EDİLENLER -----------------
elif st.session_state.page == "📈 Takip Edilenler":
    st.title("📈 Takip Edilen Ürünler")
    sh = init_master_sheet()
    try:
        data = sh.worksheet("List").get_all_records()
        if not data: st.warning("Liste boş.")
        else:
            master = pd.DataFrame(data)
            prod = st.selectbox("Ürün Seçin:", master['Urun_Adi'].tolist())
            if prod:
                p_data = master[master['Urun_Adi'] == prod].iloc[0]
                product_query = p_data['Arama_Sorgusu']
                product_id = p_data['ID']
                try:
                    perf = pd.DataFrame(sh.worksheet(p_data['Performans_Sekme_Adi']).get_all_records())
                    rakipler_df = pd.DataFrame(sh.worksheet(p_data['Rakipler_Sekme_Adi']).get_all_records())
                    st.info(f"Durum: {p_data['Durum']} | Sonraki Kontrol: {p_data['Sonraki_Analiz_Tarihi']}")
                    if not perf.empty:
                        last = perf.iloc[-1]
                        c1, c2, c3 = st.columns(3)
                        c1.metric("Viral Skor", f"%{float(last['Ort_Viral_Skor']):.1f}")
                        c2.metric("İzlenme", f"{int(last['Toplam_Izlenme']):,}")
                        c3.metric("Winner", last['Winner_Sayisi'])
                        st.info(last['Analiz_Notu'])
                    
                    # TİCARİ AKSİYONLAR
                    st.markdown("---"); st.subheader("🕵️ Ticari İstihbarat")
                    col_meta, col_supp = st.columns(2)
                    
                    with col_meta:
                        if st.button("📢 Meta Reklam/Rakip Taraması Başlat", use_container_width=True):
                            with st.spinner("Meta izleri taranıyor..."):
                                meta_query = f'"{product_query}" site:facebook.com OR site:instagram.com "fiyat" OR "sipariş" OR "shop"'
                                df_meta = run_google_scraper(meta_query, limit=10)
                                if not df_meta.empty:
                                    rows = [[str(product_id), str(datetime.now().date()), prod, r.get('title',''), r.get('url',''), r.get('description',''), "Meta/Social"] for _, r in df_meta.iterrows()]
                                    save_extra_results("Meta_Results", rows)
                                    st.success(f"✅ {len(df_meta)} sonuç bulundu!")
                                else: st.warning("Bulunamadı.")

                    with col_supp:
                        if st.button("🏭 Tedarikçi & Toptancı Bul", use_container_width=True):
                            with st.spinner("Toptancılar taranıyor (TikTok Hariç)..."):
                                supp_query = f'"{product_query}" (fiyat OR satın al OR toptan OR bayi OR sipariş) -site:tiktok.com -site:instagram.com -site:facebook.com -site:youtube.com -site:pinterest.com'
                                df_supp = run_google_scraper(supp_query, limit=15)
                                if not df_supp.empty:
                                    rows = []
                                    for _, r in df_supp.iterrows():
                                        if "tiktok" not in r.get('url','').lower():
                                            rows.append([str(product_id), str(datetime.now().date()), prod, r.get('title',''), r.get('url',''), r.get('description',''), "Google Search"])
                                    if rows: save_extra_results("Suppliers", rows); st.success(f"✅ {len(rows)} tedarikçi bulundu!")
                                    else: st.warning("Uygun site bulunamadı.")
                                else: st.warning("Sonuç yok.")

                    st.markdown("---"); st.subheader("⚡ Veri Güncelleme")
                    limit = st.slider("Taranacak Video Sayısı", 15, 50, 15)
                    if st.button("🔄 GÜNCELLE"):
                        with st.spinner("Güncelleniyor..."):
                            new_df = search_competitors(p_data['Arama_Sorgusu'], limit=limit)
                            if not new_df.empty:
                                new_df = calculate_metrics(new_df)
                                ai, nxt = generate_smart_analysis(new_df)
                                update_product_data(p_data['Rakipler_Sekme_Adi'], p_data['Performans_Sekme_Adi'], new_df, ai, new_df['Viral_Skor'].mean(), nxt)
                                st.success("Güncellendi!"); time.sleep(1); st.rerun()
                    
                    st.subheader("📋 Rakip Listesi")
                    # TEMİZ TABLO GÖRÜNÜMÜ
                    wanted_cols = ['text', 'playCount', 'diggCount', 'Viral_Skor', 'Etkilesim_Orani', 'hashtags', 'createTimeISO']
                    final_cols = [c for c in wanted_cols if c in rakipler_df.columns]
                    df_clean = rakipler_df[final_cols].copy()
                    if 'hashtags' in df_clean.columns: df_clean['hashtags'] = df_clean['hashtags'].apply(clean_hashtags_display)
                    rename_map = {'text': 'Başlık', 'playCount': 'İzlenme', 'diggCount': 'Beğeni', 'Viral_Skor': 'Viral Skor', 'Etkilesim_Orani': 'Etkileşim %', 'createTimeISO': 'Tarih', 'hashtags': 'Etiketler'}
                    df_clean = df_clean.rename(columns=rename_map)
                    st.data_editor(df_clean, use_container_width=True, column_config={"İzlenme": st.column_config.NumberColumn(format="%d"), "Beğeni": st.column_config.NumberColumn(format="%d"), "Viral Skor": st.column_config.NumberColumn(format="%.1f"), "Etkileşim %": st.column_config.NumberColumn(format="%.2f")}, disabled=True)

                except: st.error("Veri okunamadı.")
    except: st.error("Hata.")

# ----------------- 4. KAYDEDİLENLER -----------------
elif st.session_state.page == "📌 Kaydedilenler":
    st.title("📌 Hızlı Kaydedilenler")
    sh = init_master_sheet()
    try:
        ws_bm = sh.worksheet("Bookmarks")
        data = ws_bm.get_all_records()
        if not data: st.info("Listeniz boş.")
        else:
            df_bm = pd.DataFrame(data).iloc[::-1]
            df_display = df_bm[['Resim_URL', 'Aciklama', 'Tarih', 'Izlenme', 'Viral_Skor', 'Etkilesim', 'Video_URL']]
            st.data_editor(
                df_display,
                column_config={
                    "Resim_URL": st.column_config.ImageColumn("Resim", width="small"),
                    "Aciklama": st.column_config.TextColumn("Ürün", width="medium"),
                    "Izlenme": st.column_config.NumberColumn(format="%d"),
                    "Viral_Skor": st.column_config.NumberColumn(format="%.1f"),
                    "Etkilesim": st.column_config.NumberColumn(format="%.2f"),
                    "Video_URL": st.column_config.LinkColumn("Link", display_text="▶️ Git")
                },
                hide_index=True, use_container_width=True, height=800, disabled=True
            )
    except Exception as e: st.error(f"Hata: {e}")

# ----------------- 5. TEDARİKÇİ BULUCU (YENİ) -----------------
elif st.session_state.page == "🏭 Tedarikçi Bulucu":
    st.title("🏭 Tedarikçi ve Toptancı Avcısı")
    st.markdown("Ürün adını girin, 3 farklı stratejiyle (Toptan, İmalat, Wholesale) taranır.")
    
    col_inp, col_btn = st.columns([3, 1])
    with col_inp: search_term = st.text_input("Ürün Adı:", placeholder="Örn: ayetel kürsi bilekliği")
    depth_option = st.radio("Derinlik:", ["Hızlı", "Derin"], horizontal=True, index=1)
    limit_val = 20 if depth_option == "Hızlı" else 60

    if st.button("🚀 Ara"):
        if not search_term: st.error("Ürün adı girin!")
        else:
            st.session_state.supplier_results = None 
            queries = [f'"{search_term}" toptan satış fiyatları', f'"{search_term}" imalatçı firma iletişim', f'"{search_term}" wholesale supplier turkey', f'"{search_term}" ithalatçı firma istoç']
            all_raw = pd.DataFrame()
            
            with st.status("🕵️ Tedarikçi ağı taranıyor...", expanded=True) as status:
                for q in queries:
                    status.write(f"🔍 Aranıyor: **{q}**")
                    df_part = run_google_scraper(q, limit=limit_val)
                    if not df_part.empty:
                        df_part['Arama_Tipi'] = q
                        all_raw = pd.concat([all_raw, df_part], ignore_index=True)
                
                if not all_raw.empty:
                    status.write("🧠 Filtreleniyor...")
                    all_raw = all_raw.drop_duplicates(subset=['url'])
                    final_df = filter_suppliers_strict(all_raw, search_term)
                    if not final_df.empty:
                        st.session_state.supplier_results = final_df
                        status.update(label=f"✅ {len(final_df)} tedarikçi bulundu.", state="complete", expanded=False)
                    else: status.update(label="❌ Toptancı bulunamadı.", state="error")
                else: status.update(label="❌ Sonuç yok.", state="error")

    if st.session_state.supplier_results is not None:
        df_res = st.session_state.supplier_results
        st.success(f"**{len(df_res)}** tedarikçi listelendi.")
        st.data_editor(
            df_res[['title', 'description', 'url', 'Arama_Tipi']],
            column_config={"title": "Firma", "url": st.column_config.LinkColumn("Web Sitesi", display_text="🌍 Git")},
            use_container_width=True, hide_index=True
        )
        if st.button("💾 Veritabanına Kaydet"):
            rows = [[str(uuid.uuid4().hex[:8]), str(datetime.now().date()), search_term, r.get('title',''), r.get('url',''), r.get('description',''), "Google Search"] for _, r in df_res.iterrows()]
            if save_extra_results("Suppliers", rows): st.success("✅ Kaydedildi!"); time.sleep(2)

# ----------------- 6. TEDARİKÇİ VERİTABANI (YENİ) -----------------
elif st.session_state.page == "🗃️ Tedarikçi Veritabanı":
    st.title("🗃️ Tedarikçi Veritabanı")
    sh = init_master_sheet()
    try:
        ws = sh.worksheet("Suppliers")
        data = ws.get_all_records()
        if not data: st.info("Boş.")
        else:
            df_supp = pd.DataFrame(data)
            prods = df_supp['Urun_Adi'].unique()
            filt = st.selectbox("Filtrele:", ["Tümü"] + list(prods))
            if filt != "Tümü": df_supp = df_supp[df_supp['Urun_Adi'] == filt]
            st.data_editor(df_supp[['Tarih', 'Urun_Adi', 'Tedarikci_Baslik', 'Web_Sitesi', 'Aciklama']], column_config={"Web_Sitesi": st.column_config.LinkColumn("Link", display_text="🌍 Git")}, use_container_width=True, hide_index=True)
            if st.button("⚠️ Temizle"): ws.clear(); ws.append_row(["ID", "Tarih", "Urun_Adi", "Tedarikci_Baslik", "Web_Sitesi", "Aciklama", "Kanal_Tipi"]); st.success("Temizlendi."); time.sleep(1); st.rerun()
    except Exception as e: st.error(f"Hata: {e}")