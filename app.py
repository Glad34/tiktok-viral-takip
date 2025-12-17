import streamlit as st
import pandas as pd
from apify_client import ApifyClient
from datetime import datetime, timedelta

# --- 1. SAYFA AYARLARI ---
st.set_page_config(
    page_title="TrendScope TR - Ürün Analizi",
    layout="wide",
    page_icon="🛍️",
    initial_sidebar_state="expanded"
)

# --- 2. CSS & TASARIM (SADE & BEYAZ) ---
st.markdown("""
<style>
    /* Üst boşluk ayarı (Header'a yapışık) */
    .block-container {
        padding-top: 3rem !important;
        padding-bottom: 2rem !important;
    }

    /* Genel Renkler (Light Mode Zorlama) */
    .stApp {
        background-color: #ffffff !important;
        color: #31333F !important;
    }
    
    /* Sidebar */
    section[data-testid="stSidebar"] {
        background-color: #f8f9fa !important;
        border-right: 1px solid #eee;
    }
    
    /* Tablo ve Metinler */
    h1, h2, h3, p, span, div, label {
        color: #333 !important;
    }
    
    /* Input Alanları */
    .stTextInput input, .stNumberInput input, .stSelectbox div {
        background-color: #fff !important;
        color: #333 !important;
    }
    
    /* Buton */
    .stButton>button {
        background-color: #007bff;
        color: white;
        border: none;
        border-radius: 8px;
        height: 3em;
        font-weight: bold;
    }
    .stButton>button:hover {
        background-color: #0056b3;
    }
</style>
""", unsafe_allow_html=True)

# --- 3. APIFY AYARLARI ---
if "APIFY_TOKEN" in st.secrets:
    APIFY_TOKEN = st.secrets["APIFY_TOKEN"]
else:
    st.error("🚨 Hata: .streamlit/secrets.toml dosyasında APIFY_TOKEN bulunamadı.")
    st.stop()

client = ApifyClient(APIFY_TOKEN)

# --- 4. KELİME HAVUZLARI ---

CATEGORIES = {
    "Tümü": [],
    "🏠 Ev & Yaşam": ["mutfak gereçleri", "pratik ev ürünleri", "banyo düzenleyici", "dekorasyon", "çeyiz alışverişi", "temizlik ürünleri"],
    "💄 Güzellik & Bakım": ["makyaj trendleri", "cilt bakımı önerileri", "kozmetik", "güzellik sırları", "saç bakım"],
    "👗 Moda & Giyim": ["kombin önerileri", "moda trendleri", "tesettür giyim", "butik elbise", "ayakkabı çanta"],
    "💻 Teknoloji & Aksesuar": ["telefon kılıfı", "akıllı saat", "teknolojik ürünler", "kulaklık inceleme", "telefon aksesuarları"],
    "👶 Anne & Bebek": ["bebek ürünleri", "bebek oyuncakları", "bebek giyim", "hamilelik", "bebek bakım", "anne tavsiyesi"],
    "🚗 Oto & Araç": ["araba aksesuarları", "oto temizlik", "modifiye", "araç içi düzenleyici"]
}

# Türkçe Ürün/Satış Sinyalleri (Burası Pozitif Filtre)
PRODUCT_KEYWORDS = [
    "sipariş", "fiyat", "kargo", "satın al", "link", "profilde", "bioda", 
    "stok", "kampanya", "indirim", "kapıda ödeme", "şeffaf kargo", "whatsapp", 
    "dm", "iletişim", "beden", "kumaş", "model", "kalite", "iade", "değişim", 
    "takım", "adet", "tl", "₺", "magaza", "butik", "kod", "inceleme", "öneri",
    "kullandım", "aldım", "memnun", "tavsiye"
]

# Yabancı İçerik Engelleyici (Burası Negatif Filtre)
FOREIGN_KEYWORDS = [
    "price", "shipping", "link in bio", "order now", "free shipping", 
    "dollar", "usd", "euro", "shop now", "discount", "sale", "amazon find",
    "tiktokmademebuyit", "fypシ", "xyzbca"
]

# --- 5. FONKSİYONLAR ---

def turkce_tarih_format(date_obj):
    if pd.isna(date_obj): return ""
    aylar = {1: "Oca", 2: "Şub", 3: "Mar", 4: "Nis", 5: "May", 6: "Haz", 7: "Tem", 8: "Ağu", 9: "Eyl", 10: "Eki", 11: "Kas", 12: "Ara"}
    return f"{date_obj.day} {aylar.get(date_obj.month)} {date_obj.year}"

def check_is_product_safe(text):
    """
    1. Yabancı kelime var mı? Varsa False.
    2. Türkçe ürün kelimesi var mı? Varsa True.
    """
    if not isinstance(text, str): return False
    text_lower = text.lower()
    
    # 1. Yabancı Kontrolü (Kesin Red)
    for bad_word in FOREIGN_KEYWORDS:
        if bad_word in text_lower:
            if bad_word == "link": continue 
            if bad_word in ["price", "shipping", "order", "shop"]: 
                return False

    # 2. Ürün Kontrolü (Kabul)
    for keyword in PRODUCT_KEYWORDS:
        if keyword in text_lower:
            return True
            
    return False

# --- HATA DÜZELTİLEN FONKSİYON ---
def fetch_tiktok_data(query, limit): # Parametre adı 'limit' olarak düzeltildi
    """
    Kullanıcı 10 tane istiyorsa biz 50 tane çekelim ki (Buffer),
    filtrelerden sonra el boş dönmeyelim.
    """
    buffer_limit = limit * 5 
    if buffer_limit > 300: buffer_limit = 300 
    
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
    
    # 1. Bölge Filtresi (Katı TR Kontrolü)
    def get_region(meta):
        if isinstance(meta, dict): return meta.get('region', '')
        return ''
    
    if 'authorMeta' in df.columns:
        df['Region_Code'] = df['authorMeta'].apply(get_region)
        df = df[~df['Region_Code'].isin(['US', 'GB', 'DE', 'FR', 'IT', 'ES', 'BR', 'RU'])]
    
    # 2. Metin Analizi (Ürün mü? Türkçe mi?)
    df['is_valid_product'] = df['text'].apply(check_is_product_safe)
    df = df[df['is_valid_product'] == True]
    
    if df.empty: return pd.DataFrame()

    # 3. Sayısal Dönüşümler
    cols = ['playCount', 'diggCount', 'shareCount', 'collectCount', 'commentCount']
    for col in cols:
        df[col] = pd.to_numeric(df.get(col, 0), errors='coerce').fillna(0)
    
    # 4. Metrik Filtreleri
    df = df[df['playCount'] >= min_views]
    df = df[df['diggCount'] >= min_likes]
    
    # 5. Tarih Filtresi
    if 'createTimeISO' in df.columns:
        df['createTimeISO'] = pd.to_datetime(df['createTimeISO'], errors='coerce', utc=True).dt.tz_localize(None)
        if date_limit:
            cutoff_date = datetime.now() - timedelta(days=date_limit)
            df = df[df['createTimeISO'] >= cutoff_date]
        df['Tarih_Gorsel'] = df['createTimeISO'].apply(turkce_tarih_format)
    
    if df.empty: return pd.DataFrame()

    # 6. Hesaplamalar
    df['Viral_Skor'] = ((df['shareCount'] + df['collectCount']) / df['diggCount'].replace(0, 1)) * 100
    df['Viral_Skor'] = df['Viral_Skor'].round(1)
    
    # 7. Görsel Hazırlık
    df['Resim'] = df['videoMeta'].apply(lambda x: x.get('coverUrl', '') if isinstance(x, dict) else '')
    df['Hesap'] = df['authorMeta'].apply(lambda x: x.get('name', '') if isinstance(x, dict) else '')
    df['Urun_Tahmin'] = df['text'].apply(lambda x: " ".join(str(x).split()[:7]) + "..." if x else "")
    
    # 8. Sıralama ve Kesme
    df = df.sort_values(by="Viral_Skor", ascending=False)
    
    return df.head(target_limit)

# --- 6. ARAYÜZ (FİLTRELER VE LİSTE) ---

# SOL PANEL
with st.sidebar:
    st.header("🛍️ Ürün Analiz Filtreleri")
    st.markdown("---")
    
    date_opt = st.selectbox("📅 Tarih Aralığı", [7, 30, 90, 180, 365], index=1, format_func=lambda x: f"Son {x} Gün")
    limit_opt = st.number_input("🔢 Listelenecek Adet", min_value=5, max_value=50, value=10, step=5)
    cat_opt = st.selectbox("📂 Kategori", list(CATEGORIES.keys()))
    
    st.subheader("Limitler")
    min_view_inp = st.number_input("👁️ Min. İzlenme", value=1000, step=500, help="Daha düşük izlenmeler viral olmayanları getirir.")
    min_like_inp = st.number_input("❤️ Min. Beğeni", value=10, step=10)
    
    hashtag_filter = st.text_input("Hashtag (#)", placeholder="örn: ceyiz")

# ANA EKRAN
st.title("TrendScope TR - Ürün Keşfet")
st.caption("TikTok Türkiye üzerindeki potansiyel ürünleri ve fırsatları analiz et.")

search_query = st.text_input("", placeholder="Ürün, Kelime veya Mağaza ara...", label_visibility="collapsed")

if st.button("🔎 ÜRÜNLERİ BUL", use_container_width=True):
    
    # Arama Sorgusu Oluşturma
    final_query = ""
    if cat_opt != "Tümü":
        import random
        base_keyword = random.choice(CATEGORIES[cat_opt])
        final_query = f"{base_keyword}"
    
    if search_query:
        final_query = f"{search_query} {final_query}"
        
    if hashtag_filter:
        clean_tag = hashtag_filter.replace('#','')
        final_query = f"{final_query} #{clean_tag}"
        
    # Eğer sorgu çok boşsa varsayılan ekle
    if not final_query.strip():
        final_query = "inceleme öneri sipariş"

    with st.spinner(f"📡 '{final_query.strip()}' için veriler taranıyor..."):
        # Apify'dan veri çek
        # DÜZELTME BURADA YAPILDI: limit parametresi doğru gönderiliyor
        raw_df = fetch_tiktok_data(final_query, limit=limit_opt)
        
        # Veriyi işle
        clean_df = process_data(raw_df, min_view_inp, min_like_inp, date_opt, limit_opt)
        
        if not clean_df.empty:
            st.session_state.trendscope_results = clean_df
            st.success(f"✅ Toplam {len(clean_df)} adet Türkiye ürünü bulundu.")
        else:
            st.warning("⚠️ Kriterlere uygun ürün bulunamadı. (Yabancı içerikler veya ürün olmayan videolar filtrelendi). Limitleri düşürmeyi deneyin.")
            st.session_state.trendscope_results = None

# SONUÇ GÖSTERİMİ
if 'trendscope_results' in st.session_state and st.session_state.trendscope_results is not None:
    df = st.session_state.trendscope_results
    
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Sonuç Sayısı", len(df))
    m2.metric("Ort. İzlenme", f"{int(df['playCount'].mean()):,}")
    m3.metric("Ort. Viral Skor", f"{df['Viral_Skor'].mean():.1f}")
    m4.metric("En Yüksek Beğeni", f"{int(df['diggCount'].max()):,}")
    
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
            "Tarih_Gorsel"
        ]],
        column_config={
            "Resim": st.column_config.ImageColumn("Video", width="small"),
            "Urun_Tahmin": st.column_config.TextColumn("İçerik Özeti", width="medium"),
            "Hesap": st.column_config.TextColumn("Satıcı", width="small"),
            "Viral_Skor": st.column_config.ProgressColumn("Viral Gücü", format="%.1f", min_value=0, max_value=100),
            "playCount": st.column_config.NumberColumn("İzlenme", format="%d"),
            "diggCount": st.column_config.NumberColumn("Beğeni", format="%d"),
            "shareCount": st.column_config.NumberColumn("Paylaşım", format="%d"),
            "webVideoUrl": st.column_config.LinkColumn("Link", display_text="İzle ▶️"),
            "Tarih_Gorsel": st.column_config.TextColumn("Tarih")
        },
        use_container_width=True,
        hide_index=True,
        height=800
    )
else:
    st.markdown("""
    <div style='text-align: center; color: #999; padding: 50px;'>
        <h3>Henüz Analiz Yapılmadı</h3>
        <p>Arama yaparak veya kategori seçerek ürünleri listelemeye başlayın.</p>
    </div>
    """, unsafe_allow_html=True)