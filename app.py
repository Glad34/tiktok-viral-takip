import streamlit as st
import pandas as pd
from apify_client import ApifyClient
from datetime import datetime, timedelta
import numpy as np

# --- SAYFA AYARLARI ---
st.set_page_config(page_title="TrendScope - Ürün Dedektifi", layout="wide", page_icon="🛍️")

# --- CSS TASARIM (KALODATA STİLİ) ---
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
        width: 100%;
    }
    .stButton>button:hover {
        background-color: #0056b3;
        color: white;
    }
    
    /* Progress Bar */
    .stProgress > div > div > div > div {
        background-color: #ff4b4b;
    }
</style>
""", unsafe_allow_html=True)

# --- APIFY AYARLARI ---
if "APIFY_TOKEN" in st.secrets:
    APIFY_TOKEN = st.secrets["APIFY_TOKEN"]
else:
    st.error("🚨 Hata: .streamlit/secrets.toml dosyasında APIFY_TOKEN bulunamadı.")
    st.stop()

client = ApifyClient(APIFY_TOKEN)

# --- E-TİCARET & ÜRÜN KELİME HAVUZU (AKILLI FİLTRE İÇİN) ---
COMMERCIAL_KEYWORDS = {
    # Yüksek Puanlı Kelimeler (Kesin Satış Sinyali) - Puan: 3
    "high": [
        "sipariş", "fiyat", "tl", "₺", "satın al", "link", "profilde", "bio", 
        "bioda", "stok", "kargo", "kapıda ödeme", "şeffaf kargo", "shopier", 
        "whatsapp", "dm", "iletişim", "kampanya", "indirim", "ücretsiz kargo",
        "tükenmeden", "sınırlı sayı", "kod", "kupon"
    ],
    # Orta Puanlı Kelimeler (Tanıtım/İnceleme Sinyali) - Puan: 1
    "medium": [
        "ürün", "inceleme", "denedim", "aldım", "öneri", "tavsiye", "kullandım",
        "beden", "kumaş", "model", "kalite", "garanti", "iade", "değişim", 
        "takım", "adet", "mağaza", "butik", "kombin", "marka", "muadil", "linki"
    ]
}

CATEGORIES = {
    "Tümü": [],
    "🏠 Ev & Yaşam": ["mutfak gereçleri", "pratik ürünler", "banyo düzeni", "dekorasyon", "çeyiz"],
    "💄 Güzellik & Bakım": ["makyaj malzemeleri", "cilt bakımı", "kozmetik", "saç şekillendirici"],
    "👗 Moda & Giyim": ["kombin", "moda", "tesettür giyim", "elbise", "çanta", "ayakkabı"],
    "💻 Teknoloji & Aksesuar": ["telefon kılıfı", "akıllı saat", "kulaklık", "aksesuar"],
    "👶 Anne & Bebek": ["bebek ürünleri", "oyuncak", "bebek giyim", "hamile giyim"],
    "🚗 Oto & Araç": ["oto aksesuar", "araç içi", "modifiye", "oto temizlik"]
}

# --- FONKSİYONLAR ---

def score_product_intent(text):
    """
    Metni tarar ve bir 'Ticari Skor' üretir.
    Eğer skor 0 ise muhtemelen eğlence videosudur.
    Skor ne kadar yüksekse o kadar net bir ürün satışıdır.
    """
    if not isinstance(text, str): return 0
    text = text.lower()
    score = 0
    
    # Yüksek Puanlı Kelimeler (Ağırlık: 3)
    for word in COMMERCIAL_KEYWORDS["high"]:
        if word in text:
            score += 3
            
    # Orta Puanlı Kelimeler (Ağırlık: 1)
    for word in COMMERCIAL_KEYWORDS["medium"]:
        if word in text:
            score += 1
            
    return score

def fetch_tiktok_data(query, requested_limit):
    """
    Apify'dan veri çeker. 
    Not: Ürün olmayanları eleyeceğimiz için istenen limitin 3 katı kadar veri çekeriz (Buffer).
    """
    buffer_limit = requested_limit * 3
    if buffer_limit > 200: buffer_limit = 200 # Maksimum güvenlik limiti
    
    try:
        run_input = {
            "searchQueries": [query],
            "resultsPerPage": buffer_limit,
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
        st.error(f"⚠️ Apify Hatası: {e}")
        return pd.DataFrame()

def process_data(df, min_views, min_likes, date_limit, target_limit):
    if df.empty: return df
    
    # 1. Bölge Filtresi (TR)
    def get_region(meta):
        if isinstance(meta, dict): return meta.get('region', '')
        return ''

    if 'authorMeta' in df.columns:
        df['Region_Code'] = df['authorMeta'].apply(get_region)
        df = df[df['Region_Code'].isin(['TR', 'tr', 'Tr', 'TUR', ''])]
    
    if df.empty: return pd.DataFrame()
    
    # 2. ÜRÜN FİLTRESİ (En Önemli Kısım)
    # Metin içeriğine göre puanlama yapıyoruz
    df['Product_Score'] = df['text'].apply(score_product_intent)
    
    # Eşik Değer (Threshold): En az 2 puan almalı.
    # Örn: Sadece "fiyat" (3 puan) geçerse al. Sadece "öneri" (1 puan) geçerse alma. 
    # "Öneri" ve "Link" geçerse (1+3=4 puan) al.
    df = df[df['Product_Score'] >= 2]
    
    if df.empty: return pd.DataFrame()

    # 3. Sayısal Dönüşümler
    cols = ['playCount', 'diggCount', 'shareCount', 'collectCount', 'commentCount']
    for col in cols:
        df[col] = pd.to_numeric(df.get(col, 0), errors='coerce').fillna(0)
    
    # 4. Tarih Filtresi
    if 'createTimeISO' in df.columns:
        df['createTimeISO'] = pd.to_datetime(df['createTimeISO'], errors='coerce', utc=True).dt.tz_localize(None)
        if date_limit:
            cutoff_date = datetime.now() - timedelta(days=date_limit)
            df = df[df['createTimeISO'] >= cutoff_date]
    
    # 5. Metrik Limitleri
    df = df[df['playCount'] >= min_views]
    df = df[df['diggCount'] >= min_likes]
    
    if df.empty: return pd.DataFrame()

    # 6. Viral Skor Hesaplama
    total_interact = df['diggCount'] + df['commentCount'] + df['shareCount']
    df['Etkilesim_Orani'] = (total_interact / df['playCount'].replace(0, 1)) * 100
    df['Viral_Skor'] = ((df['shareCount'] + df['collectCount']) / df['diggCount'].replace(0, 1)) * 100
    
    df['Etkilesim_Orani'] = df['Etkilesim_Orani'].round(2)
    df['Viral_Skor'] = df['Viral_Skor'].round(2)
    
    # 7. Görsel Hazırlık
    df['Resim'] = df['videoMeta'].apply(lambda x: x.get('coverUrl', '') if isinstance(x, dict) else '')
    df['Hesap'] = df['authorMeta'].apply(lambda x: x.get('name', '') if isinstance(x, dict) else '')
    # Ürün tahminini biraz daha temiz yapalım
    df['Urun_Tahmin'] = df['text'].apply(lambda x: str(x)[:60] + "..." if x else "Başlıksız")
    
    # 8. Sıralama ve Limit
    df = df.sort_values(by="Viral_Skor", ascending=False)
    
    return df.head(target_limit)

# --- ARAYÜZ (LAYOUT) ---

# SOL PANEL
with st.sidebar:
    st.markdown("## 🕵️‍♂️ TrendScope Ürün Bulucu")
    st.caption("Sadece ticari potansiyeli olan ürün videolarını filtreler.")
    st.markdown("---")
    
    date_opt = st.selectbox("📅 Tarih Aralığı", [7, 30, 90, 365], index=1, format_func=lambda x: f"Son {x} Gün")
    
    # Kullanıcı 10 adet isterse biz arka planda 30 çekip filtreliyoruz
    limit_user = st.number_input("🔢 Listelenecek Ürün Sayısı", min_value=5, max_value=50, value=10, step=5)
    
    cat_opt = st.selectbox("📂 Kategori", list(CATEGORIES.keys()))
    
    st.markdown("### 📊 Limitler")
    min_view_inp = st.number_input("👁️ Min. İzlenme", value=1000, step=500)
    min_like_inp = st.number_input("❤️ Min. Beğeni", value=50, step=50)
    
    st.markdown("### 🏷️ Ekstra")
    hashtag_filter = st.text_input("Hashtag (#)", placeholder="örn: tesettur")
    
    st.info("💡 Sistem, metin analizi yaparak ürün satışı olmayan videoları otomatik eler.")

# ANA EKRAN
col_title, col_search = st.columns([2, 3])
with col_title:
    st.title("Viral Ürün Analizi")
    st.caption("Dropshipping ve E-ticaret için kazandıran ürünleri bul.")

with col_search:
    st.write("") 
    st.write("") 
    search_query = st.text_input("", placeholder="Ürün adı, kelime veya marka ara...", label_visibility="collapsed")

if st.button("🚀 ÜRÜNLERİ TARAYIP GETİR", use_container_width=True):
    
    # Sorgu Oluşturma
    final_query = ""
    
    # Kategori seçildiyse oradan bir kelime al
    if cat_opt != "Tümü":
        import random
        base_keyword = random.choice(CATEGORIES[cat_opt])
        final_query = f"{base_keyword}"
    
    # Kullanıcı araması varsa ekle
    if search_query:
        final_query = f"{search_query} {final_query}"
        
    # Hashtag varsa ekle
    if hashtag_filter:
        clean_tag = hashtag_filter.replace('#','')
        final_query = f"{final_query} #{clean_tag}"
        
    # Eğer hiçbiri yoksa varsayılan ürün arama terimleri ekle
    if not final_query.strip():
        final_query = "inceleme sipariş fiyat"

    with st.spinner(f"📡 '{final_query.strip()}' için ürün videoları taranıyor ve filtreleniyor..."):
        
        # 1. Adım: Veri Çekme (Bufferlı)
        raw_df = fetch_tiktok_data(final_query, limit_user)
        
        # 2. Adım: İşleme ve Ürün Filtreleme (AI/Keyword Logic)
        clean_df = process_data(raw_df, min_view_inp, min_like_inp, date_opt, limit_user)
        
        if not clean_df.empty:
            st.session_state.kalodata_results = clean_df
            st.success(f"✅ Analiz tamamlandı! {len(clean_df)} adet potansiyel ürün videosu bulundu.")
        else:
            st.warning("⚠️ Kriterlere uygun 'ÜRÜN' videosu bulunamadı. (Videolar bulundu ancak ticari kelime içermediği için elendi).")
            st.session_state.kalodata_results = None

# SONUÇ GÖSTERİMİ
if 'kalodata_results' in st.session_state and st.session_state.kalodata_results is not None:
    df = st.session_state.kalodata_results
    
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Listelenen Ürün", len(df))
    m2.metric("Ort. İzlenme", f"{int(df['playCount'].mean()):,}")
    m3.metric("Ort. Viral Skor", f"{df['Viral_Skor'].mean():.1f}")
    m4.metric("Maks. Beğeni", f"{int(df['diggCount'].max()):,}")
    
    st.markdown("---")
    
    st.data_editor(
        df[[
            "Resim", 
            "Urun_Tahmin", 
            "Hesap", 
            "Viral_Skor", 
            "playCount", 
            "diggCount", 
            "shareCount", 
            "webVideoUrl",
            "createTimeISO"
        ]],
        column_config={
            "Resim": st.column_config.ImageColumn("Video", width="small"),
            "Urun_Tahmin": st.column_config.TextColumn("Ürün / İçerik Özeti", width="medium"),
            "Hesap": st.column_config.TextColumn("Satıcı/Yayıncı", width="small"),
            "Viral_Skor": st.column_config.ProgressColumn("Viral Potansiyeli", format="%.1f", min_value=0, max_value=100),
            "playCount": st.column_config.NumberColumn("İzlenme", format="%d"),
            "diggCount": st.column_config.NumberColumn("Beğeni", format="%d"),
            "shareCount": st.column_config.NumberColumn("Paylaşım", format="%d"),
            "webVideoUrl": st.column_config.LinkColumn("Link", display_text="İzle ▶️"),
            "createTimeISO": st.column_config.DatetimeColumn("Tarih", format="D MMM YYYY")
        },
        use_container_width=True,
        hide_index=True,
        height=800
    )
else:
    st.markdown("""
    <div style='text-align: center; color: grey; padding: 50px;'>
        <h3>Henüz Analiz Yapılmadı</h3>
        <p>Sol taraftan bir kategori seçin veya spesifik bir ürün adı yazın.</p>
    </div>
    """, unsafe_allow_html=True)