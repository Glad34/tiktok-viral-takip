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
    }
    .stButton>button:hover {
        background-color: #0056b3;
        color: white;
    }
</style>
""", unsafe_allow_html=True)

# --- APIFY AYARLARI ---
# secrets.toml dosyasında APIFY_TOKEN tanımlı olmalı
if "APIFY_TOKEN" in st.secrets:
    APIFY_TOKEN = st.secrets["APIFY_TOKEN"]
else:
    st.error("Lütfen .streamlit/secrets.toml dosyasına APIFY_TOKEN ekleyin.")
    st.stop()

client = ApifyClient(APIFY_TOKEN)

# --- KATEGORİ STRATEJİLERİ (HASHTAG BAZLI) ---
CATEGORIES = {
    "Tümü": [],
    "🏠 Ev & Yaşam": ["mutfak", "düzen", "temizlik", "dekorasyon", "evim"],
    "💄 Güzellik & Bakım": ["makyaj", "ciltbakımı", "güzellik", "sacmodelleri"],
    "👗 Moda & Giyim": ["kombin", "moda", "tesettür", "giyim", "stil"],
    "💻 Teknoloji & Aksesuar": ["teknoloji", "telefonkilifi", "akıllısaat", "aksesuar"],
    "👶 Anne & Bebek": ["bebek", "anne", "hamile", "oyuncak"],
    "🚗 Oto & Araç": ["araba", "modifiye", "otoaksesuar"]
}

# --- YARDIMCI FONKSİYONLAR ---
def process_data(df, min_views, min_likes, date_limit):
    if df.empty: return df
    
    # 1. Sayısal Dönüşümler
    cols = ['playCount', 'diggCount', 'shareCount', 'collectCount', 'commentCount']
    for col in cols:
        df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)
    
    # 2. Tarih Filtreleme
    df['createTimeISO'] = pd.to_datetime(df['createTimeISO'], errors='coerce', utc=True).dt.tz_localize(None)
    if date_limit:
        cutoff_date = datetime.now() - timedelta(days=date_limit)
        df = df[df['createTimeISO'] >= cutoff_date]
    
    # 3. Metrik Filtreleme (Min İzlenme / Min Beğeni)
    df = df[df['playCount'] >= min_views]
    df = df[df['diggCount'] >= min_likes]
    
    if df.empty: return pd.DataFrame()

    # 4. Hesaplamalar (Viral Skor & Etkileşim)
    # Etkileşim Oranı = (Beğeni+Yorum+Paylaşım) / İzlenme * 100
    total_interact = df['diggCount'] + df['commentCount'] + df['shareCount']
    df['Etkilesim_Orani'] = (total_interact / df['playCount'].replace(0, 1)) * 100
    
    # Viral Skor = (Paylaşım + Kaydetme) / Beğeni * 100 (Beğeniye göre ne kadar yayıldığı)
    df['Viral_Skor'] = ((df['shareCount'] + df['collectCount']) / df['diggCount'].replace(0, 1)) * 100
    
    # Yuvarlama
    df['Etkilesim_Orani'] = df['Etkilesim_Orani'].round(2)
    df['Viral_Skor'] = df['Viral_Skor'].round(2)
    
    # 5. Görselleştirme için Sütun Düzenleme
    # Thumbnail ve Kullanıcı Adı çıkarma
    df['Resim'] = df['videoMeta'].apply(lambda x: x.get('coverUrl', '') if isinstance(x, dict) else '')
    df['Hesap'] = df['authorMeta'].apply(lambda x: x.get('name', '') if isinstance(x, dict) else '')
    df['Profil_Link'] = df['authorMeta'].apply(lambda x: f"https://www.tiktok.com/@{x.get('name','')}" if isinstance(x, dict) else '')
    
    # Ürün Adı (Açıklamanın ilk 5 kelimesi)
    df['Urun_Tahmin'] = df['text'].apply(lambda x: " ".join(x.split()[:5]) + "..." if x else "Başlıksız")
    
    # Sıralama (Varsayılan olarak Viral Skora göre)
    df = df.sort_values(by="Viral_Skor", ascending=False)
    
    return df

def fetch_tiktok_data(query, limit=50):
    run_input = {
        "searchQueries": [query],
        "resultsPerPage": limit,
    }
    # TikTok Scraper Actor'ünü çağır
    run = client.actor("clockworks/tiktok-scraper").call(run_input=run_input)
    if run.get("defaultDatasetId"):
        items = client.dataset(run["defaultDatasetId"]).list_items().items
        return pd.DataFrame(items)
    return pd.DataFrame()

# --- ARAYÜZ (LAYOUT) ---

# SOL PANEL (FİLTRELER)
with st.sidebar:
    st.image("https://kalodata.com/_nuxt/img/logo.3236e7b.svg", width=150, caption="Viral Analiz TR Modu") # Logo temsili
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
    st.markdown("---")
    st.subheader("📊 Performans Limitleri")
    min_view_inp = st.number_input("👁️ En Az İzlenme", min_value=0, value=5000, step=1000)
    min_like_inp = st.number_input("❤️ En Az Beğeni", min_value=0, value=100, step=50)
    
    # 4. Özel Filtreler
    st.markdown("---")
    st.subheader("🏷️ Gelişmiş Arama")
    hashtag_filter = st.text_input("Hashtag Filtrele (#)", placeholder="örn: keşfet, toptan")
    
    st.info("💡 Not: Türkiye'de TikTok Shop olmadığı için veriler Video Performansı üzerinden analiz edilir.")

# ANA EKRAN (MAIN)
col_title, col_search = st.columns([2, 3])
with col_title:
    st.title("Türkiye Pazar Analizi")
    st.caption("Videoları analiz et, potansiyel 'Winner' ürünleri bul.")

with col_search:
    # Arama Barı (En üstte)
    search_query = st.text_input("", placeholder="Ürün, Kelime veya Mağaza ara...", label_visibility="collapsed")

# Arama Butonu ve Logic
if st.button("🔎 ANALİZ ET VE LİSTELE", use_container_width=True):
    
    # Sorgu Oluşturma
    final_query = ""
    
    # 1. Kategori bazlı sorgu kelimesi seç (Randomize edilebilir veya birleştirilebilir)
    if cat_opt != "Tümü":
        # Kategoriden rastgele veya ilk kelimeyi alarak aramayı genişletiyoruz
        import random
        base_keyword = random.choice(CATEGORIES[cat_opt])
        final_query = f"{base_keyword}"
    
    # 2. Kullanıcı araması varsa onu ekle
    if search_query:
        final_query = f"{search_query} {final_query}"
    
    # 3. Hashtag varsa ekle
    if hashtag_filter:
        final_query = f"{final_query} #{hashtag_filter.replace('#','')}"
        
    # Eğer hiçbiri yoksa genel trend araması
    if not final_query.strip():
        final_query = "inceleme öneri"

    with st.spinner(f"📡 '{final_query.strip()}' için veriler taranıyor (Son {date_opt} gün)..."):
        # Veri Çekme
        raw_df = fetch_tiktok_data(final_query, limit=60) # Limit artırılabilir
        
        # Veri İşleme
        clean_df = process_data(raw_df, min_view_inp, min_like_inp, date_opt)
        
        if not clean_df.empty:
            st.session_state.kalodata_results = clean_df
            st.success(f"✅ Toplam {len(clean_df)} potansiyel ürün videosu bulundu.")
        else:
            st.warning("⚠️ Kriterlere uygun video bulunamadı. Filtreleri gevşetmeyi deneyin.")
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
        <p>Sol taraftan filtreleri ayarlayın ve "Analiz Et" butonuna basın.</p>
    </div>
    """, unsafe_allow_html=True)