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

# --- AYARLAR VE ŞİFRELER ---
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
        try:
            ws = sh.worksheet("List")
        except:
            ws = sh.add_worksheet(title="List", rows="100", cols="10")
            ws.append_row(["ID", "Urun_Adi", "Rakipler_Sekme_Adi", "Performans_Sekme_Adi", "Son_Analiz_Tarihi", "Sonraki_Analiz_Tarihi", "Son_Viral_Skor", "Durum", "URL", "Arama_Sorgusu"])
        return sh
    except Exception as e:
        st.error(f"Google Sheet Hatası: '{MASTER_SHEET_NAME}' dosyası bulunamadı!")
        st.stop()

# --- ANALİZ FONKSİYONLARI ---
def clean_text_for_query(text):
    if not text: return ""
    text = re.sub(r'#\w+', '', text)
    text = re.sub(r'[^\w\sğüşıöçĞÜŞİÖÇ]', '', text)
    stop_words = ["keşfet", "fyp", "viral", "kapıda", "ödeme", "sipariş", "link", "bio", "banyo", "mutfak", "için", "ve", "ile", "bir", "bu"]
    words = text.split()
    filtered_words = [w for w in words if w.lower() not in stop_words]
    # En az 3 karakterden uzun kelimeleri al
    filtered_words = [w for w in filtered_words if len(w) > 2]
    return " ".join(filtered_words[:5]).strip()

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

def calculate_metrics(df):
    cols = ['playCount', 'diggCount', 'shareCount', 'collectCount', 'commentCount']
    for col in cols:
        if col not in df.columns: df[col] = 0
        df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)
    
    if 'createTimeISO' not in df.columns: 
        df['createTimeISO'] = pd.NaT
    else:
        df['createTimeISO'] = pd.to_datetime(df['createTimeISO'], errors='coerce', utc=True).dt.tz_localize(None)

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
    if not valid_dates.empty:
        avg_age_days = (today - valid_dates).dt.days.mean()
    else:
        avg_age_days = 30 

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
def save_to_existing_sheet(urun_adi, url, query, df, analysis_text, avg_viral_score, status, next_check_date):
    status_msg = st.empty()
    status_msg.info("⏳ Kaydediliyor...")
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
        
        total_views = int(df['playCount'].sum())
        winner_count = int(df[df['Karar_Puani'] >= 60].shape[0])
        avg_viral_score = float(avg_viral_score)
        ws_perf.append_row([str(datetime.now().date()), avg_viral_score, total_views, winner_count, analysis_text])
        
        master_ws = sh.worksheet("List")
        master_ws.append_row([unique_id, urun_adi, rakipler_tab_name, performans_tab_name, str(datetime.now().date()), next_check_date, avg_viral_score, status, url, query])
        
        status_msg.success(f"✅ Kaydedildi.")
        return True
    except Exception as e:
        st.error(f"KAYIT HATASI: {e}")
        return False

def update_product_data(rakipler_tab_name, performans_tab_name, df, analysis_text, avg_viral_score, next_check_date):
    try:
        sh = init_master_sheet()
        ws_rakipler = sh.worksheet(rakipler_tab_name)
        ws_rakipler.clear()
        clean_df = df.fillna("").astype(str)
        ws_rakipler.update([clean_df.columns.values.tolist()] + clean_df.values.tolist())
        
        ws_perf = sh.worksheet(performans_tab_name)
        total_views = int(df['playCount'].sum())
        winner_count = int(df[df['Karar_Puani'] >= 60].shape[0])
        avg_viral_score = float(avg_viral_score)
        ws_perf.append_row([str(datetime.now().date()), avg_viral_score, total_views, winner_count, analysis_text])
        return True
    except Exception as e:
        st.error(f"GÜNCELLEME HATASI: {e}")
        return False

# --- SAYFA YAPILANDIRMASI VE MENÜ ---
st.set_page_config(page_title="Tiktok Viral Takip", layout="wide")
st.markdown("""<style>.stButton>button { width: 100%; border-radius: 5px; } .stDeployButton {display:none;} footer {visibility: hidden;} #MainMenu {visibility: visible;}</style>""", unsafe_allow_html=True)

# Session State Başlatma
if 'page' not in st.session_state: st.session_state.page = "🔭 Viral Ürün Bulucu"
if 'analyzed_data' not in st.session_state: st.session_state.analyzed_data = None
if 'analysis_meta' not in st.session_state: st.session_state.analysis_meta = {}
if 'transfer_url' not in st.session_state: st.session_state.transfer_url = ""
if 'auto_start' not in st.session_state: st.session_state.auto_start = False

# Sidebar Navigasyon (State Kontrollü)
st.sidebar.title("Tiktok Viral Takip 🤖")

# Manuel Menü Seçimi
selection = st.sidebar.radio("Modüller", ["🔭 Viral Ürün Bulucu", "🚀 Ürün Analizi", "📂 Kaydedilenler"], 
                             index=["🔭 Viral Ürün Bulucu", "🚀 Ürün Analizi", "📂 Kaydedilenler"].index(st.session_state.page))

# Eğer kullanıcı menüden elle değiştirirse state'i güncelle
if selection != st.session_state.page:
    st.session_state.page = selection
    st.rerun()

# ----------------- MODÜL 1: VİRAL ÜRÜN BULUCU -----------------
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
        if search_type == "Kategoriden Seç": selected_query = random.choice(SEARCH_STRATEGIES_TR[category])
        else: selected_query = final_query
            
        if not selected_query: st.error("Lütfen bir arama terimi girin!")
        else:
            with st.spinner(f"'{selected_query}' taranıyor..."):
                df_discovery = search_competitors(selected_query, limit=50)
                if not df_discovery.empty:
                    df_discovery = calculate_metrics(df_discovery)
                    today = datetime.now()
                    days_num = 7 if days_filter == "Son 7 Gün" else 30
                    if 'createTimeISO' in df_discovery.columns:
                         df_discovery = df_discovery[df_discovery['createTimeISO'] >= (today - timedelta(days=days_num))]
                    df_discovery = df_discovery[df_discovery['playCount'] > 5000] 
                    df_discovery = df_discovery.sort_values(by='Viral_Skor', ascending=False).head(20)
                    
                    st.success(f"✅ {len(df_discovery)} adet ürün bulundu!")
                    
                    for index, row in df_discovery.iterrows():
                        with st.container():
                            c1, c2, c3, c4 = st.columns([1, 3, 2, 2])
                            with c1:
                                if row.get('videoMeta') and isinstance(row['videoMeta'], dict):
                                    cover = row['videoMeta'].get('coverUrl', '')
                                    if cover: st.image(cover, use_column_width=True)
                            with c2:
                                st.write(f"**{row['text'][:90]}...**")
                                st.markdown(f"[🎥 Videoya Git ↗️]({row['webVideoUrl']})", unsafe_allow_html=True)
                            with c3:
                                st.metric("İzlenme", f"{int(row['playCount']):,}")
                                st.metric("Etkileşim", f"%{row['Etkilesim_Orani']:.2f}")
                            with c4:
                                # OTOPİLORT BUTONU
                                if st.button("🚀 Bunu Analiz Et", key=f"btn_{index}"):
                                    st.session_state.transfer_url = row['webVideoUrl']
                                    st.session_state.auto_start = True # Otopilotu aç
                                    st.session_state.page = "🚀 Ürün Analizi" # Sayfayı değiştir
                                    st.rerun() # Hemen yönlendir
                            st.markdown("---")
                else:
                    st.warning("Veri bulunamadı.")


# ----------------- MODÜL 2: ÜRÜN ANALİZİ (OTOPİLOTLU) -----------------
elif st.session_state.page == "🚀 Ürün Analizi":
    st.title("🚀 Detaylı Ürün Analizi")
    
    # URL'yi state'den al
    url_val = st.session_state.transfer_url if st.session_state.transfer_url else ""
    
    col_input1, col_input2 = st.columns([2, 1])
    with col_input1:
        url = st.text_input("TikTok Video URL:", value=url_val, placeholder="https://...")
    with col_input2:
        manual_prod_name = st.text_input("Ürün Adı (Opsiyonel):", help="Manuel giriş.")

    # ORTAK ANALİZ FONKSİYONU
    def run_analysis_flow(target_url, manual_query_input):
        smart_query = ""
        if manual_query_input:
            smart_query = manual_query_input
            st.info(f"✍️ Manuel Arama: **{smart_query}**")
        else:
            with st.spinner("Video ismi algılanıyor..."):
                raw_text, _ = fetch_video_info(target_url)
                if raw_text:
                    smart_query = clean_text_for_query(raw_text)
                    if smart_query:
                        st.info(f"🔎 Otomatik Sorgu: **{smart_query}**")
                    else:
                        st.warning("⚠️ Videoda spesifik ürün adı bulunamadı. Lütfen sağdaki kutuya ürün adını manuel girin.")
                        st.session_state.auto_start = False # Otopilotu durdur
                        return # İşlemi kes
                else:
                    st.error("Video bilgisi çekilemedi.")
                    st.session_state.auto_start = False
                    return

        # Sorgu varsa analize devam et
        if smart_query:
            with st.spinner(f"'{smart_query}' için rakipler taranıyor..."):
                related_df = search_competitors(smart_query, limit=15)
                
                if not related_df.empty:
                    analyzed = calculate_metrics(related_df)
                    ai_text, next_date = generate_smart_analysis(analyzed)
                    
                    st.session_state.analyzed_data = analyzed
                    st.session_state.analysis_meta = {
                        "query": smart_query, "url": target_url, "ai_text": ai_text, "next_date": next_date, 
                        "avg_viral": analyzed['Viral_Skor'].mean(), "avg_score": analyzed['Karar_Puani'].mean(),
                        "status": "WINNER 🏆" if analyzed['Karar_Puani'].mean() >= 60 else "NORMAL"
                    }
                    st.session_state.transfer_url = "" # URL'yi temizle
                    st.session_state.auto_start = False # Otopilotu kapat
                else:
                    st.error("Video bulunamadı.")
                    st.session_state.analyzed_data = None
                    st.session_state.auto_start = False

    # 1. MANUEL BUTON BASILIRSA
    if st.button("Analiz Et"):
        if url: run_analysis_flow(url, manual_prod_name)
        else: st.error("Lütfen URL girin!")

    # 2. OTOPİLOT AKTİFSE (Sayfa açılır açılmaz çalışır)
    if st.session_state.auto_start and url:
        run_analysis_flow(url, manual_prod_name)

    # SONUÇ GÖSTERİMİ
    if st.session_state.analyzed_data is not None:
        analyzed = st.session_state.analyzed_data
        meta = st.session_state.analysis_meta
        col1, col2 = st.columns([1, 2])
        with col1:
            st.metric("Ort. Puan", f"{meta['avg_score']:.1f}")
            st.metric("Ort. Viral Skor", f"%{meta['avg_viral']:.1f}")
            st.markdown(meta['ai_text'])
            st.info(f"📅 Sonraki Kontrol: **{meta['next_date']}**")
            st.markdown("---")
            if st.button("💾 BU ÜRÜNÜ KAYDET"):
                success = save_to_existing_sheet(meta['query'], meta['url'], meta['query'], analyzed, meta['ai_text'], meta['avg_viral'], meta['status'], meta['next_date'])
                if success:
                    st.session_state.analyzed_data = None
                    st.session_state.analysis_meta = {}
                    time.sleep(1)
                    st.rerun()
        with col2:
            st.subheader("Rakipler")
            if 'webVideoUrl' in analyzed.columns:
                 st.dataframe(analyzed[['text', 'playCount', 'Viral_Skor', 'createTimeISO', 'webVideoUrl']])
            else:
                 st.dataframe(analyzed)


# ----------------- MODÜL 3: KAYDEDİLENLER -----------------
elif st.session_state.page == "📂 Kaydedilenler":
    st.title("📂 Kaydedilen Ürünler")
    sh = init_master_sheet()
    try:
        data = sh.worksheet("List").get_all_records()
        if not data:
            st.warning("Henüz ürün yok.")
        else:
            master_df = pd.DataFrame(data)
            product_list = master_df['Urun_Adi'].tolist()
            selected_prod_name = st.selectbox("Ürün Seçin:", product_list)
            
            if selected_prod_name:
                prod_data = master_df[master_df['Urun_Adi'] == selected_prod_name].iloc[0]
                rakipler_tab = prod_data['Rakipler_Sekme_Adi']
                performans_tab = prod_data['Performans_Sekme_Adi']
                try:
                    perf_data = sh.worksheet(performans_tab).get_all_records()
                    perf_df = pd.DataFrame(perf_data)
                    rakipler_data = sh.worksheet(rakipler_tab).get_all_records()
                    rakipler_df = pd.DataFrame(rakipler_data)
                    st.info(f"Ürün: {selected_prod_name} | Durum: {prod_data['Durum']}")
                    st.warning(f"📅 Kontrol: {prod_data['Sonraki_Analiz_Tarihi']}")
                    col1, col2 = st.columns([2, 1])
                    with col1:
                        st.subheader("📈 Performans")
                        if not perf_df.empty:
                            st.dataframe(perf_df)
                            st.line_chart(perf_df['Toplam_Izlenme'])
                    with col2:
                        st.subheader("⚡ Aksiyonlar")
                        limit = st.slider("Video Sayısı", 15, 50, 15)
                        if st.button("🔄 ŞİMDİ GÜNCELLE"):
                            with st.spinner("Güncelleniyor..."):
                                new_df = search_competitors(prod_data['Arama_Sorgusu'], limit=limit)
                                if not new_df.empty:
                                    new_analyzed = calculate_metrics(new_df)
                                    new_ai_text, new_next_date = generate_smart_analysis(new_analyzed)
                                    new_avg_viral = new_analyzed['Viral_Skor'].mean()
                                    if update_product_data(rakipler_tab, performans_tab, new_analyzed, new_ai_text, new_avg_viral, new_next_date):
                                        st.success("Güncellendi!")
                                        time.sleep(1)
                                        st.rerun()
                    st.subheader("📋 Rakip Listesi")
                    st.dataframe(rakipler_df)
                except gspread.exceptions.WorksheetNotFound:
                    st.error("Sekmeler silinmiş.")
    except Exception as e:
        st.error(f"Veri Hatası: {e}")