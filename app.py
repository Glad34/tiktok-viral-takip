import streamlit as st
import pandas as pd
from apify_client import ApifyClient
from datetime import datetime, timedelta
import numpy as np

# --- SAYFA AYARLARI (GENİŞ EKRAN) ---
st.set_page_config(page_title="Kalodata TR - Viral Analiz", layout="wide", page_icon="🔥")

# --- CSS İLE KALODATA TARZI GÖRÜNÜM ---
st.markdown("""
<style>
    /* Tablo Başlıkları */
    thead tr th:first-child {display:none}
    tbody th {display:none}
    
    /* Metrik Kutuları */
    div[data-testid="stMetricValue"] {
        font-size: 1.2rem;
        color: #007bff;
    }
    
    /* Buton Stili */
    .stButton>button {
        background-color: #007bff;
        color: white;
        border-radius: 8px;
        height: 3em;
        font-weight: bold;
        border: none;
    }
    .stButton>button:hover {
        background-color: #0056b3;
        color: white;
    }
    
    /* Progress Bar Rengi (Viral Skor) */
    .stProgress > div > div > div > div {
        background-color: #ff4b4b;
    }
</style>
""", unsafe_allow_html=True)

# --- APIFY AYARLARI ---
# .streamlit/secrets.toml dosyasında APIFY_TOKEN tanımlı olmalı
if "APIFY_TOKEN" in st.secrets:
    APIFY_TOKEN = st.secrets["APIFY_TOKEN"]
else:
    st.error("🚨 Hata: .streamlit/secrets.toml dosyasında APIFY_TOKEN bulunamadı.")
    st.stop()

client = ApifyClient(APIFY_TOKEN)

# --- KATEGORİ STRATEJİLERİ (HASHTAG BAZLI) ---
CATEGORIES = {
    "Tümü": [],
    "🏠 Ev & Yaşam": ["mutfak", "düzen", "temizlik", "dekorasyon", "evim", "çeyiz"],
    "💄 Güzellik & Bakım": ["makyaj", "ciltbakımı", "güzellik", "sacmodelleri", "bakım"],
    "👗 Moda & Giyim": ["kombin", "moda", "tesettür", "giyim", "stil", "butik"],
    "💻 Teknoloji & Aksesuar": ["teknoloji", "telefonkilifi", "akıllısaat", "aksesuar", "kulaklık"],
    "👶 Anne & Bebek": ["bebek", "anne", "hamile", "oyuncak", "bebekgiyim"],
    "🚗 Oto & Araç": ["araba", "modifiye", "otoaksesuar", "detailing"]
}

# --- FONKSİYONLAR ---

def fetch_tiktok_data(query, limit=50):
    """
    Apify üzerinden veri çeker.
    Bölgeyi TR olarak zorlar.
    """
    try:
        run_input = {
            "searchQueries": [query],
            "resultsPerPage": limit,
            "searchRegion": "TR",      # Sadece Türkiye bölgesi
            "searchLanguage": "tr-TR", # Türkçe dil önceliği
        }
        
        # 'clockworks/free-tiktok-scraper' genelde daha stabil ve ücretsizdir.
        # Alternatif: 'clockworks/tiktok-scraper'
        actor_id = "clockworks/free-tiktok-scraper" 
        
        # Kullanıcıya bilgi verilebilir (opsiyonel)
        # st.toast(f"Veri çekiliyor: {query}...", icon="📡")
        
        run = client.actor(actor_id).call(run_input=run_input)
        
        if run.get("defaultDatasetId"):
            items = client.dataset(run["defaultDatasetId"]).list_items().items
            return pd.DataFrame(items)
        return pd.DataFrame()
        
    except Exception as e:
        st.error(f"⚠️ Apify Bağlantı Hatası: {e}")
        return pd.DataFrame()

def process_data(df, min_views, min_likes, date_limit):
    """
    Ham veriyi işler, temizler, hesaplamaları yapar ve filtreler.
    """
    if df.empty: return df
    
    # 1. TÜRKİYE FİLTRESİ (Strict Mode)
    # authorMeta verisi bazen string bazen dict gelebilir, kontrol ediyoruz.
    def get_region(meta):
        if isinstance(meta, dict):
            return meta.get('region', '')
        return ''

    if 'authorMeta' in df.columns:
        df['Region_Code'] = df['authorMeta'].apply(get_region)
        # Sadece TR olanları veya bölge bilgisi boş olanları (riske girip) alıyoruz.
        # Yabancı ülkeleri (US, DE, GB vs.) kesin eliyoruz.
        df = df[df['Region_Code'].isin(['TR', 'tr', 'Tr', 'TUR', ''])]
    
    if df.empty: return pd.DataFrame()

    # 2. Sayısal Dönüşümler
    cols = ['playCount', 'diggCount', 'shareCount', 'collectCount', 'commentCount']
    for col in cols:
        if col not in df.columns: df[col] = 0
        df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)
    
    # 3. Tarih Filtreleme
    if 'createTimeISO' in df.columns:
        df['createTimeISO'] = pd.to_datetime(df['createTimeISO'], errors='coerce', utc=True).dt.tz_localize(None)
        if date_limit:
            cutoff_date = datetime.now() - timedelta(days=date_limit)
            df = df[df['createTimeISO'] >= cutoff_date]
    
    # 4. Metrik Filtreleme (Thresholds)
    df = df[df['playCount'] >= min_views]
    df = df[df['diggCount'] >= min_likes]
    
    if df.empty: return pd.DataFrame()

    # 5. Performans Hesaplamaları
    # Etkileşim: (Beğeni+Yorum+Paylaşım) / İzlenme
    total_interact = df['diggCount'] + df['commentCount'] + df['shareCount']
    df['Etkilesim_Orani'] = (total_interact / df['playCount'].replace(0, 1)) * 100
    
    # Viral Skor: Paylaşım ve Kaydetme'nin, Beğeniye oranı (Yayılma gücü)
    # Çarpanı 100 ile ölçekliyoruz.
    df['Viral_Skor'] = ((df['shareCount'] + df['collectCount']) / df['diggCount'].replace(0, 1)) * 100
    
    # Yuvarlama işlemleri
    df['Etkilesim_Orani'] = df['Etkilesim_Orani'].round(2)
    df['Viral_Skor'] = df['Viral_Skor'].round(2)
    
    # 6. Görselleştirme Hazırlığı
    # Thumbnail (Kapak Resmi)
    df['Resim'] = df['videoMeta'].apply(lambda x: x.get('coverUrl', '') if isinstance(x, dict) else '')
    
    # Hesap Adı
    df['Hesap'] = df['authorMeta'].apply(lambda x: x.get('name', '') if isinstance(x, dict) else '')
    
    # Profil Linki
    df['Profil_Link'] = df['authorMeta'].apply(lambda x: f"https://www.tiktok.com/@{x.get('name','')}" if isinstance(x, dict) else '')
    
    # Ürün/İçerik Tahmini (Metnin ilk 7 kelimesi)
    df['Urun_Tahmin'] = df['text'].apply(lambda x: " ".join(str(x).split()[:7]) + "..." if x else "Başlıksız")
    
    # Sıralama (Varsayılan olarak Viral Skora göre en iyiler üstte)
    df = df.sort_values(by="Viral_Skor", ascending=False)
    
    return df

# --- ARAYÜZ (LAYOUT) ---

# SOL PANEL (FİLTRELER)
with st.sidebar:
    # Logo Yerine Başlık
    st.markdown("## 🇹🇷 Kalodata TR")
    st.caption("TikTok Viral Ürün Analizi")
    st.markdown("---")
    
    st.header("🔍 Filtreleme Seçenekleri")
    
    # 1. Tarih Filtresi
    date_opt = st.selectbox(
        "📅 Tarih Aralığı",
        options=[7, 30, 90, 365],
        format_func=lambda x: f"Son {x} Gün",
        index=1
    )
    
    # 2. Kategori Seçimi
    cat_opt = st.selectbox("📂 Kategori", list(CATEGORIES.keys()))
    
    # 3. Metrik Filtreleri
    st.markdown("### 📊 Performans Limitleri")
    min_view_inp = st.number_input("👁️ En Az İzlenme", min_value=0, value=5000, step=1000)
    min_like_inp = st.number_input("❤️ En Az Beğeni", min_value=0, value=100, step=50)
    
    # 4. Özel Filtreler
    st.markdown("### 🏷️ Gelişmiş Arama")
    hashtag_filter = st.text_input("Hashtag Filtrele (#)", placeholder="örn: keşfet, toptan")
    
    st.info("💡 **Bilgi:** Sonuçlar sadece **Türkiye** konumlu videolardan derlenmektedir.")

# ANA EKRAN (MAIN)
col_title, col_search = st.columns([2, 3])
with col_title:
    st.title("Türkiye Pazar Analizi")
    st.caption("Videoları analiz et, potansiyel 'Winner' ürünleri bul.")

with col_search:
    # Arama Barı (En üstte)
    st.write("") # Boşluk
    st.write("") 
    search_query = st.text_input("", placeholder="Ürün, Kelime veya Mağaza ara...", label_visibility="collapsed")

# Arama Butonu ve Logic
if st.button("🔎 ANALİZ ET VE LİSTELE", use_container_width=True):
    
    # Sorgu Oluşturma
    final_query = ""
    
    # 1. Kategori bazlı sorgu kelimesi
    if cat_opt != "Tümü":
        import random
        # Kategoriden rastgele bir kelime seçerek çeşitlilik sağla
        base_keyword = random.choice(CATEGORIES[cat_opt])
        final_query = f"{base_keyword}"
    
    # 2. Kullanıcı araması varsa ekle
    if search_query:
        final_query = f"{search_query} {final_query}"
    
    # 3. Hashtag varsa ekle
    if hashtag_filter:
        clean_tag = hashtag_filter.replace('#','')
        final_query = f"{final_query} #{clean_tag}"
        
    # Eğer hiçbiri yoksa genel trend araması
    if not final_query.strip():
        final_query = "inceleme öneri"

    with st.spinner(f"📡 '{final_query.strip()}' için Türkiye verileri taranıyor (Son {date_opt} gün)..."):
        # Veri Çekme (Limit artırılabilir, kredi durumuna göre)
        raw_df = fetch_tiktok_data(final_query, limit=60) 
        
        # Veri İşleme
        clean_df = process_data(raw_df, min_view_inp, min_like_inp, date_opt)
        
        if not clean_df.empty:
            st.session_state.kalodata_results = clean_df
            st.success(f"✅ Toplam {len(clean_df)} adet Türkiye kaynaklı video bulundu.")
        else:
            st.warning("⚠️ Kriterlere uygun Türkiye kaynaklı video bulunamadı. Filtreleri gevşetmeyi deneyin.")
            st.session_state.kalodata_results = None

# --- SONUÇLARI GÖSTERME (DATA GRID) ---
if 'kalodata_results' in st.session_state and st.session_state.kalodata_results is not None:
    df = st.session_state.kalodata_results
    
    # Üst İstatistik Bantları
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Toplam Video", len(df))
    m2.metric("Ort. İzlenme", f"{int(df['playCount'].mean()):,}")
    m3.metric("Ort. Viral Skor", f"{df['Viral_Skor'].mean():.1f}")
    m4.metric("En Yüksek Beğeni", f"{int(df['diggCount'].max()):,}")
    
    st.markdown("---")
    
    # TABLO GÖRÜNÜMÜ (Kalodata Benzeri)
    # Burada Pandas dataframe'i özelleştirilmiş sütunlarla gösteriyoruz
    
    st.data_editor(
        df[[
            "Resim", 
            "Urun_Tahmin", 
            "Hesap", 
            "Viral_Skor", 
            "Etkilesim_Orani", 
            "playCount", 
            "diggCount", 
            "shareCount", 
            "webVideoUrl",
            "createTimeISO"
        ]],
        column_config={
            "Resim": st.column_config.ImageColumn(
                "Video", 
                help="Video Kapak Resmi",
                width="small"
            ),
            "Urun_Tahmin": st.column_config.TextColumn(
                "Ürün / İçerik",
                help="Videonun açıklamasından tahmin edilen içerik",
                width="medium"
            ),
            "Hesap": st.column_config.TextColumn(
                "Mağaza / Yayıncı",
                width="small"
            ),
            "Viral_Skor": st.column_config.ProgressColumn(
                "Viral Puanı",
                help="Yayılma potansiyeli (0-100+)",
                format="%.1f",
                min_value=0,
                max_value=100,
            ),
            "Etkilesim_Orani": st.column_config.NumberColumn(
                "Etkileşim %",
                format="%.2f %%"
            ),
            "playCount": st.column_config.NumberColumn(
                "İzlenme",
                format="%d"
            ),
            "diggCount": st.column_config.NumberColumn(
                "Beğeni",
                format="%d"
            ),
            "shareCount": st.column_config.NumberColumn(
                "Paylaşım",
                format="%d"
            ),
            "webVideoUrl": st.column_config.LinkColumn(
                "Link",
                display_text="İzle ▶️"
            ),
            "createTimeISO": st.column_config.DatetimeColumn(
                "Yayın Tarihi",
                format="D MMM YYYY"
            )
        },
        use_container_width=True,
        hide_index=True,
        height=800  # Tablo yüksekliği
    )
else:
    # Boş durum (İlk açılış)
    st.markdown("""
    <div style='text-align: center; color: grey; padding: 50px;'>
        <h3>Henüz veri yok</h3>
        <p>Sol taraftan filtreleri ayarlayın, kategorinizi seçin ve <b>"ANALİZ ET"</b> butonuna basın.</p>
    </div>
    """, unsafe_allow_html=True)