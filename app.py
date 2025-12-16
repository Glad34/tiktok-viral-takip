import streamlit as st
import pandas as pd
from apify_client import ApifyClient
from datetime import datetime, timedelta
import random

# --- SAYFA AYARLARI ---
st.set_page_config(page_title="ViralRadar TR", layout="wide", page_icon="📡")

# --- CSS: KALODATA TARZI BEYAZ VE SIKI TASARIM ---
st.markdown("""
<style>
    /* 1. Sayfa Yapısı ve Arka Plan */
    .stApp {
        background-color: #FFFFFF;
        color: #31333F;
    }
    
    /* 2. Üst Boşlukları Azaltma (Ekrana sığdırma) */
    .block-container {
        padding-top: 1rem;
        padding-bottom: 1rem;
        padding-left: 2rem;
        padding-right: 2rem;
    }
    
    /* 3. Navbar (Menü) Stili */
    div.stButton > button {
        width: 100%;
        border: none;
        background-color: transparent;
        color: #555;
        font-weight: 600;
        border-bottom: 2px solid transparent;
        border-radius: 0;
    }
    div.stButton > button:hover {
        color: #007bff;
        background-color: #f8f9fa;
    }
    div.stButton > button:focus {
        color: #007bff;
        border-bottom: 2px solid #007bff;
        box-shadow: none;
    }
    
    /* 4. Tablo Stili */
    div[data-testid="stDataEditor"] {
        border: 1px solid #e0e0e0;
        border-radius: 8px;
    }
    
    /* 5. Metrikler */
    div[data-testid="stMetricValue"] {
        font-size: 1.1rem;
        color: #007bff;
    }
    
    /* Sidebar Düzeni */
    section[data-testid="stSidebar"] {
        background-color: #f8f9fa;
        border-right: 1px solid #e0e0e0;
    }
</style>
""", unsafe_allow_html=True)

# --- APIFY AYARLARI ---
if "APIFY_TOKEN" in st.secrets:
    APIFY_TOKEN = st.secrets["APIFY_TOKEN"]
else:
    st.error("🚨 Hata: .streamlit/secrets.toml içinde APIFY_TOKEN yok.")
    st.stop()

client = ApifyClient(APIFY_TOKEN)

# --- NAVIGATION STATE ---
if 'active_tab' not in st.session_state:
    st.session_state.active_tab = "Genel"

# --- YARDIMCI FONKSİYONLAR ---

def translate_date(date_obj):
    """
    Datetime objesini '7 Ara 2025' formatına çevirir.
    """
    if pd.isna(date_obj): return ""
    months = {
        1: "Oca", 2: "Şub", 3: "Mar", 4: "Nis", 5: "May", 6: "Haz",
        7: "Tem", 8: "Ağu", 9: "Eyl", 10: "Eki", 11: "Kas", 12: "Ara"
    }
    try:
        return f"{date_obj.day} {months[date_obj.month]} {date_obj.year}"
    except:
        return str(date_obj.date())

def fetch_tiktok_data(query, limit=50):
    try:
        # Arama stratejisine göre ek kelimeler ekle
        search_suffix = ""
        if st.session_state.active_tab == "Reklam":
            search_suffix = " işbirliği reklam tavsiye"
        elif st.session_state.active_tab == "Ürün":
            search_suffix = " inceleme kutu açılımı fiyat"
            
        full_query = f"{query} {search_suffix}".strip()
        
        run_input = {
            "searchQueries": [full_query],
            "resultsPerPage": limit,
            "searchRegion": "TR",
            "searchLanguage": "tr-TR",
        }
        
        actor_id = "clockworks/free-tiktok-scraper"
        run = client.actor(actor_id).call(run_input=run_input)
        
        if run.get("defaultDatasetId"):
            items = client.dataset(run["defaultDatasetId"]).list_items().items
            return pd.DataFrame(items)
        return pd.DataFrame()
    except Exception as e:
        st.error(f"Apify Hatası: {e}")
        return pd.DataFrame()

def process_data(df, min_views, min_likes, date_limit):
    if df.empty: return df
    
    # 1. TR Filtresi
    def get_region(meta):
        if isinstance(meta, dict): return meta.get('region', '')
        return ''
    if 'authorMeta' in df.columns:
        df['Region_Code'] = df['authorMeta'].apply(get_region)
        df = df[df['Region_Code'].isin(['TR', 'tr', 'Tr', 'TUR', ''])]
    
    if df.empty: return pd.DataFrame()

    # 2. Sayısal Dönüşüm
    cols = ['playCount', 'diggCount', 'shareCount', 'collectCount', 'commentCount']
    for col in cols:
        if col not in df.columns: df[col] = 0
        df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)
    
    # 3. Tarih Filtresi
    if 'createTimeISO' in df.columns:
        df['createTimeISO'] = pd.to_datetime(df['createTimeISO'], errors='coerce', utc=True).dt.tz_localize(None)
        if date_limit:
            cutoff_date = datetime.now() - timedelta(days=date_limit)
            df = df[df['createTimeISO'] >= cutoff_date]
            
    # 4. Limit Filtreleri
    df = df[df['playCount'] >= min_views]
    df = df[df['diggCount'] >= min_likes]
    
    if df.empty: return pd.DataFrame()

    # 5. Skorlar
    df['Viral_Skor'] = ((df['shareCount'] + df['collectCount']) / df['diggCount'].replace(0, 1)) * 100
    total_interact = df['diggCount'] + df['commentCount'] + df['shareCount']
    df['Etkilesim_Orani'] = (total_interact / df['playCount'].replace(0, 1)) * 100
    
    df['Viral_Skor'] = df['Viral_Skor'].round(1)
    df['Etkilesim_Orani'] = df['Etkilesim_Orani'].round(2)
    
    # 6. Görüntüleme Sütunları
    df['Resim'] = df['videoMeta'].apply(lambda x: x.get('coverUrl', '') if isinstance(x, dict) else '')
    df['Hesap'] = df['authorMeta'].apply(lambda x: x.get('name', '') if isinstance(x, dict) else '')
    # Tarihi Türkçe String'e çeviriyoruz (Görsel için)
    df['Yayin_Tarihi_TR'] = df['createTimeISO'].apply(translate_date)
    
    # Ürün Tahmin
    df['Urun_Tahmin'] = df['text'].apply(lambda x: " ".join(str(x).split()[:6]) + "..." if x else "")
    
    return df.sort_values(by="Viral_Skor", ascending=False)

# --- HEADER / NAVBAR ---
col_brand, col_nav = st.columns([1, 4])

with col_brand:
    st.markdown("### 📡 ViralRadar")

with col_nav:
    # Navigasyon Butonları
    # Bunlara tıklayınca session_state güncellenir
    n1, n2, n3, n4, n5 = st.columns(5)
    if n1.button("Genel", use_container_width=True): st.session_state.active_tab = "Genel"
    if n2.button("Reklam", use_container_width=True): st.session_state.active_tab = "Reklam"
    if n3.button("Ürün", use_container_width=True): st.session_state.active_tab = "Ürün"
    if n4.button("Blog", use_container_width=True): st.toast("Blog yakında aktif!")
    if n5.button("İletişim", use_container_width=True): st.toast("info@viralradar.com")

st.markdown("---")

# --- SOL PANEL (FİLTRELER) ---
with st.sidebar:
    st.markdown(f"**Mod:** {st.session_state.active_tab} Analizi")
    
    st.subheader("Filtreler")
    
    # Tarih (180 Gün eklendi)
    date_opt = st.selectbox(
        "📅 Tarih Aralığı",
        options=[7, 30, 90, 180, 365],
        format_func=lambda x: f"Son {x} Gün",
        index=1
    )
    
    # Sonuç Sayısı (Limit)
    limit_opt = st.number_input("🔢 Maksimum Sonuç", min_value=10, max_value=200, value=50, step=10)
    
    st.markdown("### Performans")
    min_view = st.number_input("En Az İzlenme", value=1000, step=1000)
    min_like = st.number_input("En Az Beğeni", value=50, step=50)
    
    st.markdown("### Kategori")
    CATEGORIES = {
        "Tümü": [],
        "🏠 Ev & Yaşam": ["mutfak", "düzen", "temizlik"],
        "💄 Güzellik": ["makyaj", "ciltbakımı", "güzellik"],
        "👗 Moda": ["kombin", "moda", "giyim"],
        "💻 Teknoloji": ["teknoloji", "aksesuar", "kulaklık"],
    }
    cat_opt = st.selectbox("Kategori Seç", list(CATEGORIES.keys()))

# --- ANA İÇERİK ---

# Bilgilendirme Başlığı
st.caption(f"Aktif Bölüm: **{st.session_state.active_tab}** | Türkiye Pazarı 🇹🇷")

# Arama Alanı
col_search_inp, col_search_btn = st.columns([4, 1])
with col_search_inp:
    search_query = st.text_input("Arama", placeholder=f"{st.session_state.active_tab} içinde ara (Örn: Kulaklık, Ruj)...", label_visibility="collapsed")
with col_search_btn:
    search_clicked = st.button("🔍 ARA", type="primary", use_container_width=True)

if search_clicked:
    # Query Hazırlama
    final_query = ""
    if cat_opt != "Tümü":
        base_kw = random.choice(CATEGORIES[cat_opt])
        final_query = base_kw
    
    if search_query:
        final_query = f"{search_query} {final_query}"
        
    if not final_query.strip():
        final_query = "trend ürünler" # Fallback

    with st.spinner(f"📡 '{final_query}' taranıyor... ({limit_opt} Adet)"):
        raw_df = fetch_tiktok_data(final_query, limit=limit_opt)
        clean_df = process_data(raw_df, min_view, min_like, date_opt)
        
        if not clean_df.empty:
            st.session_state.results = clean_df
            st.success(f"✅ {len(clean_df)} video bulundu.")
        else:
            st.warning("Sonuç bulunamadı.")
            st.session_state.results = None

# --- SONUÇ TABLOSU ---
if 'results' in st.session_state and st.session_state.results is not None:
    df = st.session_state.results
    
    # Görselleştirilecek Sütunlar
    display_cols = [
        "Resim", "Hesap", "Viral_Skor", "Etkilesim_Orani", 
        "playCount", "diggCount", "shareCount", 
        "webVideoUrl", "Yayin_Tarihi_TR", "Urun_Tahmin"
    ]
    
    st.data_editor(
        df[display_cols],
        column_config={
            "Resim": st.column_config.ImageColumn("Video", width="small"),
            "Hesap": st.column_config.TextColumn("Mağaza/Kişi", width="small"),
            "Urun_Tahmin": st.column_config.TextColumn("İçerik Özeti", width="medium"),
            "Viral_Skor": st.column_config.ProgressColumn(
                "Viral Puanı", format="%.1f", min_value=0, max_value=100
            ),
            "Etkilesim_Orani": st.column_config.NumberColumn("Etkileşim %", format="%.2f %%"),
            "playCount": st.column_config.NumberColumn("İzlenme", format="%d"),
            "diggCount": st.column_config.NumberColumn("Beğeni", format="%d"),
            "shareCount": st.column_config.NumberColumn("Paylaşım", format="%d"),
            "webVideoUrl": st.column_config.LinkColumn("Link", display_text="İzle ▶️"),
            "Yayin_Tarihi_TR": st.column_config.TextColumn("Yayın Tarihi"),
        },
        use_container_width=True,
        hide_index=True,
        height=600 # Yükseklik sınırlandırması (Scroll içerde olur)
    )