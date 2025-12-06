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

# --- AYARLAR ---
CREDENTIALS_FILE = "credentials.json"
MASTER_SHEET_NAME = "Viral_Hunter_Master"

if "APIFY_TOKEN" in st.secrets:
    APIFY_TOKEN = st.secrets["APIFY_TOKEN"]
else:
    APIFY_TOKEN = "" 

client = ApifyClient(APIFY_TOKEN)

# --- GOOGLE SHEETS BAĞLANTISI ---
def get_gspread_client():
    scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
    if "gcp_service_account" in st.secrets:
        creds_dict = st.secrets["gcp_service_account"]
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    elif os.path.exists(CREDENTIALS_FILE):
        creds = ServiceAccountCredentials.from_json_keyfile_name(CREDENTIALS_FILE, scope)
    else:
        st.error("🚨 Hata: Secrets veya credentials.json bulunamadı.")
        st.stop()
    return gspread.authorize(creds)

def init_master_sheet():
    gc = get_gspread_client()
    try:
        sh = gc.open(MASTER_SHEET_NAME)
        # Sekmeleri kontrol et
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
            ws.append_row(["ID", "Tarih", "Urun_Adi", "Tedarikci_Baslik", "Web_Sitesi", "Aciklama", "Kanal_Tipi"])
        try: sh.worksheet("Meta_Results")
        except:
            ws = sh.add_worksheet(title="Meta_Results", rows="100", cols="10")
            ws.append_row(["ID", "Tarih", "Urun_Adi", "Baslik", "Link", "Aciklama", "Kaynak"])
        return sh
    except Exception as e:
        st.error(f"Google Sheet Hatası: {e}")
        st.stop()

# --- YARDIMCI FONKSİYONLAR ---
def clean_text_for_query(text):
    if not text: return ""
    text = re.sub(r'#\w+', '', text)
    text = re.sub(r'[^\w\sğüşıöçĞÜŞİÖÇ]', '', text)
    words = text.split()
    return " ".join(words[:4]).strip()

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

# --- GOOGLE SCRAPER (DERİN ARAMA İÇİN AYARLANDI) ---
def run_google_scraper(query, limit=40):
    # Limit 40 yapıldı (Yaklaşık 4 sayfa)
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

# --- TEDARİKÇİ FİLTRELEME (İSTEĞİNE GÖRE DÜZENLENDİ) ---
def filter_suppliers_strict(df):
    if df.empty: return df
    
    # 1. Aradığımız Sihirli Kelimeler (Bunlardan biri varsa alıyoruz)
    target_keywords = [
        "toptan", "wholesale", "imalat", "üretici", "ithalat", "ithalatçı",
        "toptancı", "supplier", "manufacturer", "distribütör", 
        "istoç", "tahtakale", "merter", "bayi", "koli", "adetli alım", 
        "fabrikadan", "b2b", "kurumsal satış"
    ]
    
    # 2. İstemediğimiz Siteler (Perakende Devleri)
    # Not: Facebook/Instagram'ı engellemiyorum, bazen üreticiler orada oluyor.
    banned_domains = ["trendyol.com", "hepsiburada.com", "amazon.com.tr", "ciceksepeti.com", "sikayetvar.com", "youtube.com", "pinterest.com", "twitter.com", "n11.com", "pttavm.com", "kizlarsoruyor.com", "eksisozluk.com"]

    filtered_rows = []
    
    for _, row in df.iterrows():
        title = str(row.get('title', '')).lower()
        desc = str(row.get('description', '')).lower()
        url = str(row.get('url', '')).lower()
        
        # Meta Title ve Description birleşimi
        full_text = f"{title} {desc}"
        
        # A. Yasaklı site kontrolü
        if any(ban in url for ban in banned_domains):
            continue
            
        # B. Kelime Kontrolü
        # Eğer başlıkta veya açıklamada toptan/imalat geçiyorsa listeye ekle
        if any(keyword in full_text for keyword in target_keywords):
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
        sh.worksheet("List").append_row([uid, urun_adi, f"R_{uid}", f"P_{uid}", str(datetime.now().date()), next_check_date, avg_viral_score, status, url, query])
        return True
    except: return False

def update_product_data(rakipler_tab, performans_tab, df, analysis_text, avg_viral_score, next_check_date):
    try:
        sh = init_master_sheet()
        sh.worksheet(rakipler_tab).clear()
        clean = df.fillna("").astype(str)
        sh.worksheet(rakipler_tab).update([clean.columns.values.tolist()] + clean.values.tolist())
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

# --- SEARCH STRATEGIES ---
SEARCH_STRATEGIES_TR = {
    "🔥 Türkiye Geneli": ["#tiktokzamanı", "kargo bedava", "kapıda ödeme", "#aldım", "#öneri", "#trendyol", "link profilde"],
    "🏠 Ev & Mutfak": ["#mutfaksırları", "#pratikbilgiler", "çeyiz alışverişi", "#düzen", "mutfak aletleri"],
    "💄 Güzellik & Bakım": ["#makyajvideoları", "#ciltbakımı", "güzellik sırları", "#bakımrutini"],
    "🚗 Araç & Teknoloji": ["#arabaaksesuar", "oto aksesuar", "teknolojik ürünler"],
    "👶 Anne & Bebek": ["#bebekvideolari", "anne tavsiyesi", "bebek ihtiyaçları"]
}

# --- SAYFA YAPILANDIRMASI ---
st.set_page_config(page_title="Tiktok Viral Takip", layout="wide")
st.markdown("""<style>.stButton>button { width: 100%; border-radius: 5px; } .stDeployButton {display:none;} footer {visibility: hidden;} #MainMenu {visibility: visible;}</style>""", unsafe_allow_html=True)

if 'analyzed_data' not in st.session_state: st.session_state.analyzed_data = None
if 'analysis_meta' not in st.session_state: st.session_state.analysis_meta = {}
if 'transfer_url' not in st.session_state: st.session_state.transfer_url = ""
if 'auto_start' not in st.session_state: st.session_state.auto_start = False
if 'discovery_results' not in st.session_state: st.session_state.discovery_results = None
if 'supplier_results' not in st.session_state: st.session_state.supplier_results = None

st.sidebar.title("Tiktok Viral Takip 🤖")
menu_options = ["🔭 Viral Ürün Bulucu", "🚀 Ürün Analizi", "📈 Takip Edilenler", "📌 Kaydedilenler", "──────────", "🏭 Tedarikçi Bulucu", "🗃️ Tedarikçi Veritabanı"]
if 'page' not in st.session_state: st.session_state.page = "🔭 Viral Ürün Bulucu"
selection = st.sidebar.radio("Modüller", menu_options, index=0 if st.session_state.page not in menu_options else menu_options.index(st.session_state.page))
if selection == "──────────": st.session_state.page = "🔭 Viral Ürün Bulucu"; st.rerun()
elif selection != st.session_state.page: st.session_state.page = selection; st.session_state.auto_start = False; st.rerun()

# ----------------- MODÜLLER 1-4 (AYNI) -----------------
# Bu bölümler V14.0 ile aynıdır, kodun uzamaması için buraya tam yazmadım ama sen paste ederken tam kodu kullanacaksın.
if st.session_state.page == "🔭 Viral Ürün Bulucu":
    st.title("🔭 Türkiye Viral Ürün Keşfi")
    search_type = st.radio("Tip:", ["Kategori", "Manuel"], horizontal=True)
    col1, col2 = st.columns([3,1])
    if search_type == "Kategori": 
        with col1: cat = st.selectbox("Kategori:", list(SEARCH_STRATEGIES_TR.keys()))
    else: 
        with col1: query_inp = st.text_input("Arama:", placeholder="örn: kapıda ödeme")
    with col2: day_filter = st.selectbox("Zaman:", ["Son 7 Gün", "Son 30 Gün"], index=1)
    
    if st.button("Ara"):
        q = random.choice(SEARCH_STRATEGIES_TR[cat]) if search_type == "Kategori" else query_inp
        if q:
            with st.spinner(f"'{q}' taranıyor..."):
                df = search_competitors(q, limit=50)
                if not df.empty:
                    df = calculate_metrics(df)
                    st.session_state.discovery_results = df.sort_values(by='Viral_Skor', ascending=False).head(20)
                else: st.warning("Bulunamadı.")
    
    if st.session_state.discovery_results is not None:
        for i, r in st.session_state.discovery_results.iterrows():
            with st.container():
                c1, c2, c3, c4 = st.columns([1,3,2,2])
                with c1: 
                    if r.get('videoMeta'): st.image(r['videoMeta'].get('coverUrl',''), use_column_width=True)
                with c2: st.write(f"**{r['text'][:90]}**"); st.markdown(f"[Link]({r['webVideoUrl']})")
                with c3: st.metric("İzlenme", f"{int(r['playCount']):,}"); st.metric("Viral", f"{r['Viral_Skor']:.1f}")
                with c4:
                    if st.button("🚀 Analiz", key=f"a{i}"):
                        st.session_state.transfer_url = r['webVideoUrl']; st.session_state.auto_start = True; st.session_state.page = "🚀 Ürün Analizi"; st.rerun()
                    if st.button("📌 Kaydet", key=f"s{i}"):
                        if quick_save_bookmark(r['text'], r['playCount'], r['Viral_Skor'], r['Etkilesim_Orani'], r['webVideoUrl'], r['videoMeta'].get('coverUrl','')): st.toast("Kaydedildi")
            st.markdown("---")

elif st.session_state.page == "🚀 Ürün Analizi":
    st.title("🚀 Ürün Analizi")
    url_val = st.session_state.transfer_url
    c1, c2 = st.columns([2,1])
    with c1: url = st.text_input("URL:", value=url_val)
    with c2: name = st.text_input("Ürün Adı (Manuel):")
    
    def run_anl(u, n):
        q = n
        if not q:
            with st.spinner("İsim alınıyor..."):
                txt, _ = fetch_video_info(u)
                q = clean_text_for_query(txt) if txt else ""
        if q:
            with st.spinner(f"'{q}' taranıyor..."):
                df = search_competitors(q, limit=15)
                if not df.empty:
                    df = calculate_metrics(df)
                    ai, nxt = generate_smart_analysis(df)
                    st.session_state.analyzed_data = df
                    st.session_state.analysis_meta = {"q": q, "u": u, "ai": ai, "d": nxt, "sc": df['Karar_Puani'].mean(), "v": df['Viral_Skor'].mean(), "st": "WINNER" if df['Karar_Puani'].mean()>=60 else "NORMAL"}
                    st.session_state.transfer_url = ""; st.session_state.auto_start = False
                else: st.error("Rakip yok.")
    
    if st.button("Analiz Et"): run_anl(url, name)
    if st.session_state.auto_start: run_anl(url, name)
    
    if st.session_state.analyzed_data is not None:
        m = st.session_state.analysis_meta
        c1, c2 = st.columns([1,2])
        with c1:
            st.metric("Puan", f"{m['sc']:.1f}"); st.metric("Viral", f"{m['v']:.1f}")
            st.markdown(m['ai'])
            if st.button("💾 TAKİBE AL"):
                if save_to_tracking_sheet(m['q'], m['u'], m['q'], st.session_state.analyzed_data, m['ai'], m['v'], m['st'], m['d']):
                    st.success("Kaydedildi"); time.sleep(1); st.session_state.analyzed_data = None; st.rerun()
        with c2: st.dataframe(st.session_state.analyzed_data[['text', 'playCount', 'Viral_Skor']])

elif st.session_state.page == "📈 Takip Edilenler":
    st.title("📈 Takip Edilenler")
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
                    if not perf.empty:
                        last = perf.iloc[-1]
                        c1, c2, c3 = st.columns(3)
                        c1.metric("Viral", f"{float(last['Ort_Viral_Skor']):.1f}")
                        c2.metric("İzlenme", f"{int(last['Toplam_Izlenme']):,}")
                        c3.metric("Winner", last['Winner_Sayisi'])
                        st.info(last['Analiz_Notu'])
                    
                    if st.button("🔄 GÜNCELLE"):
                        with st.spinner("Güncelleniyor..."):
                            ndf = search_competitors(p['Arama_Sorgusu'], limit=20)
                            if not ndf.empty:
                                ndf = calculate_metrics(ndf)
                                ai, nxt = generate_smart_analysis(ndf)
                                update_product_data(p['Rakipler_Sekme_Adi'], p['Performans_Sekme_Adi'], ndf, ai, ndf['Viral_Skor'].mean(), nxt)
                                st.success("Tamam"); st.rerun()
                    
                    st.subheader("📋 Rakipler")
                    st.dataframe(rakipler[['text', 'playCount', 'Viral_Skor']])
                except: st.error("Veri hatası")
    except: st.error("Hata")

elif st.session_state.page == "📌 Kaydedilenler":
    st.title("📌 Hızlı Kaydedilenler")
    sh = init_master_sheet()
    try:
        data = sh.worksheet("Bookmarks").get_all_records()
        if data:
            st.data_editor(pd.DataFrame(data).iloc[::-1], column_config={"Resim_URL": st.column_config.ImageColumn("Resim"), "Video_URL": st.column_config.LinkColumn("Link", display_text="▶️")}, use_container_width=True, hide_index=True)
        else: st.info("Boş")
    except: st.error("Hata")

# ----------------- 5. TEDARİKÇİ BULUCU (GÜNCELLENMİŞ VERSİYON) -----------------
elif st.session_state.page == "🏭 Tedarikçi Bulucu":
    st.title("🏭 Tedarikçi ve Toptancı Avcısı")
    st.markdown("Ürün adını girin, sistem **3 farklı stratejiyle** (Toptan, İmalat, Wholesale) 100+ sonucu tarasın ve sadece gerçek tedarikçileri getirsin.")
    
    col_inp, col_btn = st.columns([3, 1])
    with col_inp:
        search_term = st.text_input("Ürün Adı:", placeholder="Örn: ayetel kürsi bilekliği")
    
    if st.button("🚀 Tedarikçileri Ara"):
        if not search_term:
            st.error("Lütfen bir ürün adı girin!")
        else:
            st.session_state.supplier_results = None 
            
            # --- 3 AŞAMALI ARAMA STRATEJİSİ ---
            queries_to_run = [
                f"{search_term} toptan satış",
                f"{search_term} imalatçı firma",
                f"{search_term} wholesale supplier turkey",
                f"{search_term} eminönü tahtakale toptan"
            ]
            
            all_raw_results = pd.DataFrame()
            
            with st.status("🕵️ Tedarikçi ağı taranıyor...", expanded=True) as status:
                
                # Her bir sorguyu sırayla çalıştır
                for q in queries_to_run:
                    status.write(f"🔍 Google'da aranıyor: **{q}**")
                    # Limit 40 yapıldı (Derin arama)
                    df_part = run_google_scraper(q, limit=40)
                    if not df_part.empty:
                        df_part['Arama_Tipi'] = q
                        all_raw_results = pd.concat([all_raw_results, df_part], ignore_index=True)
                
                # SONUÇLARI İŞLE
                if not all_raw_results.empty:
                    status.write("🧠 Sonuçlar 'Toptancı' filtresinden geçiriliyor...")
                    
                    # 1. Tekrarlayanları (Duplicate) Sil
                    all_raw_results = all_raw_results.drop_duplicates(subset=['url'])
                    
                    # 2. Sıkı Filtreleme (Strict Filter)
                    final_df = filter_suppliers_strict(all_raw_results)
                    
                    if not final_df.empty:
                        st.session_state.supplier_results = final_df
                        status.update(label=f"✅ İşlem Tamam! {len(final_df)} net tedarikçi bulundu.", state="complete", expanded=False)
                    else:
                        status.update(label="❌ Toptancı kriterine uyan site bulunamadı.", state="error")
                else:
                    status.update(label="❌ Google sonuc vermedi.", state="error")

    # --- SONUÇLARI GÖSTERME ---
    if st.session_state.supplier_results is not None:
        df_res = st.session_state.supplier_results
        
        if df_res.empty:
            st.warning("Sonuç bulunamadı.")
        else:
            st.success(f"Filtreleme sonrası **{len(df_res)}** adet tedarikçi listelendi.")
            
            st.data_editor(
                df_res[['title', 'description', 'url', 'Arama_Tipi']],
                column_config={
                    "title": "Firma / Başlık",
                    "description": "Açıklama (Meta)",
                    "Arama_Tipi": "Bulunduğu Sorgu",
                    "url": st.column_config.LinkColumn("Web Sitesi", display_text="🌍 Siteye Git")
                },
                use_container_width=True,
                hide_index=True
            )
            
            if st.button("💾 Bu Listeyi Veritabanına Kaydet"):
                rows_to_save = []
                for _, row in df_res.iterrows():
                    rows_to_save.append([
                        str(uuid.uuid4().hex[:8]), # ID
                        str(datetime.now().date()), # Tarih
                        search_term, # Ürün Adı
                        row.get('title', ''), 
                        row.get('url', ''), 
                        row.get('description', ''), 
                        "Google Search"
                    ])
                
                if save_extra_results("Suppliers", rows_to_save):
                    st.success("✅ Kaydedildi!"); time.sleep(2)

# ----------------- 6. TEDARİKÇİ VERİTABANI -----------------
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
            
            st.data_editor(
                df_supp[['Tarih', 'Urun_Adi', 'Tedarikci_Baslik', 'Web_Sitesi', 'Aciklama']],
                column_config={"Web_Sitesi": st.column_config.LinkColumn("Link", display_text="🌍 Git")},
                use_container_width=True, hide_index=True
            )
            if st.button("⚠️ Temizle"): 
                ws.clear(); ws.append_row(["ID", "Tarih", "Urun_Adi", "Tedarikci_Baslik", "Web_Sitesi", "Aciklama", "Kanal_Tipi"])
                st.success("Temizlendi."); time.sleep(1); st.rerun()
    except Exception as e: st.error(f"Hata: {e}")