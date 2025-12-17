import streamlit as st
import pandas as pd
from apify_client import ApifyClient
from datetime import datetime, timedelta
import numpy as np

# --- SAYFA AYARLARI ---
st.set_page_config(page_title="TrendScope - Ürün Dedektifi", layout="wide", page_icon="🛍️")

# --- CSS TASARIM ---
st.markdown("""
<style>
    /* Üst boşluk düzeltme */
    .block-container { padding-top: 3rem !important; }
    /* Genel ayarlar */
    .stApp { background-color: #ffffff !important; color: #333 !important; }
    section[data-testid="stSidebar"] { background-color: #f8f9fa !important; }
    h1, h2, h3, p, span, div, label { color: #333 !important; }
    /* Input ve Butonlar */
    .stTextInput input, .stNumberInput input, .stSelectbox div { background-color: #fff !important; color: #333 !important; }
    .stButton>button { background-color: #007bff; color: white; border-radius: 8px; border: none; font-weight: bold; width: 100%; }
    .stButton>button:hover { background-color: #0056b3; }
</style>
""", unsafe_allow_html=True)

# --- APIFY AYARLARI ---
if "APIFY_TOKEN" in st.secrets:
    APIFY_TOKEN = st.secrets["APIFY_TOKEN"]
else:
    st.error("🚨 Hata: .streamlit/secrets.toml dosyasında APIFY_TOKEN bulunamadı.")
    st.stop()

client = ApifyClient(APIFY_TOKEN)

# --- GELİŞMİŞ ÜRÜN TESPİT SİSTEMİ ---

# Türkçe karakter normalizasyonu (İ -> i, I -> ı sorunu için)
def normalize_turkish(text):
    if not isinstance(text, str): return ""
    replacements = {
        "İ": "i", "I": "ı", "Ş": "ş", "Ğ": "ğ", "Ü": "ü", "Ö": "ö", "Ç": "ç"
    }
    text = text.translate(str.maketrans(replacements))
    return text.lower()

COMMERCIAL_KEYWORDS = {
    # BU KELİMELERDEN 1 TANESİ BİLE VARSA KESİN ÜRÜNDÜR (Puan: 5)
    "critical": [
        "sipariş", "fiyat", "tl", "₺", "kargo", "stok", "satın al", "kapıda ödeme", 
        "şeffaf kargo", "whatsapp", "dm", "iletişim", "bioda", "profildeki link", 
        "mağaza", "dükkan", "butik", "satış", "kampanya", "indirim", "tükenmeden", 
        "sınırlı sayı", "kod", "kupon", "link", "shopier", "dolap", "gardrops", 
        "trendyol", "hepsiburada", "temu", "amazon"
    ],
    # BU KELİMELER DESTEKLEYİCİDİR (Puan: 1)
    "support": [
        "ürün", "inceleme", "öneri", "tavsiye", "denedim", "aldım", "kullandım", 
        "model", "kumaş", "beden", "renk", "kalite", "garanti", "iade", "değişim", 
        "marka", "muadil", "uygun", "performans", "detay", "kutu açılımı", "paket"
    ]
}

CATEGORIES = {
    "Tümü": [],
    "🏠 Ev & Yaşam": ["mutfak gereçleri", "pratik ev ürünleri", "banyo düzenleyici", "dekorasyon", "çeyiz", "temizlik"],
    "💄 Güzellik & Bakım": ["makyaj", "cilt bakımı", "kozmetik", "güzellik", "saç bakım"],
    "👗 Moda & Giyim": ["kombin", "moda", "tesettür", "giyim", "elbise", "ayakkabı", "çanta"],
    "💻 Teknoloji & Aksesuar": ["telefon kılıfı", "akıllı saat", "teknoloji", "kulaklık", "aksesuar"],
    "👶 Anne & Bebek": ["bebek ürünleri", "oyuncak", "bebek giyim", "hamile"],
    "🚗 Oto & Araç": ["oto aksesuar", "araba", "modifiye", "araç temizlik"]
}

# --- FONKSİYONLAR ---

def score_product_intent(text):
    """
    Metni tarar ve ürün olma ihtimalini puanlar.
    """
    if not isinstance(text, str): return 0
    text = normalize_turkish(text) # Özel Türkçe çevirici
    score = 0
    
    # Kritik Kelimeler (Direkt Ürün)
    for word in COMMERCIAL_KEYWORDS["critical"]:
        if word in text:
            score += 5 # Bir tane bile bulsa yeterli
            
    # Destekleyici Kelimeler
    for word in COMMERCIAL_KEYWORDS["support"]:
        if word in text:
            score += 1
            
    return score

def fetch_tiktok_data(query, requested_limit):
    # Kullanıcı 10 adet isterse biz 50 adet çekiyoruz (Buffer)
    # Çünkü tarih filtresi ve ürün filtresi çok veri eleyecek.
    buffer_limit = requested_limit * 5
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
    if df.empty: return df, 0, 0
    
    # İstatistikler için sayaçlar
    total_fetched = len(df)
    
    # 1. Bölge Filtresi (TR)
    def get_region(meta):
        if isinstance(meta, dict): return meta.get('region', '')
        return ''

    if 'authorMeta' in df.columns:
        df['Region_Code'] = df['authorMeta'].apply(get_region)
        # Sadece kesin yabancıları atıyoruz, TR ve boşları tutuyoruz
        df = df[~df['Region_Code'].isin(['US', 'GB', 'DE', 'FR', 'IT', 'ES', 'BR', 'RU'])]
    
    # 2. ÜRÜN PUANLAMA (Kritik Adım)
    df['Product_Score'] = df['text'].apply(score_product_intent)
    
    # Eşik Değer: En az 1 puan. (Yani en az 1 destekleyici kelime veya 1 kritik kelime)
    # Kritik kelimeler 5 puan verdiği için direkt geçer.
    df_product = df[df['Product_Score'] >= 1].copy()
    count_after_product_filter = len(df_product) # Ürün filtresinden geçen sayısı
    
    if df_product.empty: return pd.DataFrame(), total_fetched, 0

    # 3. Sayısal Dönüşümler
    cols = ['playCount', 'diggCount', 'shareCount', 'collectCount', 'commentCount']
    for col in cols:
        df_product[col] = pd.to_numeric(df_product.get(col, 0), errors='coerce').fillna(0)
    
    # 4. Tarih Filtresi
    if 'createTimeISO' in df_product.columns:
        df_product['createTimeISO'] = pd.to_datetime(df_product['createTimeISO'], errors='coerce', utc=True).dt.tz_localize(None)
        if date_limit:
            cutoff_date = datetime.now() - timedelta(days=date_limit)
            df_product = df_product[df_product['createTimeISO'] >= cutoff_date]
            
    # 5. Metrik Filtreleri
    df_product = df_product[df_product['playCount'] >= min_views]
    df_product = df_product[df_product['diggCount'] >= min_likes]
    
    # 6. Görselleştirme Hazırlığı
    if not df_product.empty:
        # Viral Skor
        df_product['Viral_Skor'] = ((df_product['shareCount'] + df_product['collectCount']) / df_product['diggCount'].replace(0, 1)) * 100
        df_product['Viral_Skor'] = df_product['Viral_Skor'].round(1)
        
        # Sütunlar
        df_product['Resim'] = df_product['videoMeta'].apply(lambda x: x.get('coverUrl', '') if isinstance(x, dict) else '')
        df_product['Hesap'] = df_product['authorMeta'].apply(lambda x: x.get('name', '') if isinstance(x, dict) else '')
        df_product['Urun_Tahmin'] = df_product['text'].apply(lambda x: str(x)[:80] + "..." if x else "")
        
        # Türkçe Tarih
        def tr_date(d):
            if pd.isna(d): return ""
            m = {1:"Oca", 2:"Şub", 3:"Mar", 4:"Nis", 5:"May", 6:"Haz", 7:"Tem", 8:"Ağu", 9:"Eyl", 10:"Eki", 11:"Kas", 12:"Ara"}
            return f"{d.day} {m.get(d.month)} {d.year}"
        df_product['Tarih_Gorsel'] = df_product['createTimeISO'].apply(tr_date)
        
        # Sıralama
        df_product = df_product.sort_values(by="Viral_Skor", ascending=False)
        
        return df_product.head(target_limit), total_fetched, count_after_product_filter
    
    return pd.DataFrame(), total_fetched, count_after_product_filter

# --- ARAYÜZ ---

# SIDEBAR
with st.sidebar:
    st.header("🔍 Gelişmiş Filtreler")
    st.markdown("---")
    
    # Tarih seçeneğine "Tümü" eklendi ki eski veri sorunu test edilebilsin
    date_opt = st.selectbox("📅 Tarih Aralığı", [7, 30, 90, 180, 365, 0], index=1, format_func=lambda x: "Tüm Zamanlar" if x==0 else f"Son {x} Gün")
    
    limit_user = st.number_input("🔢 İstenen Sonuç Sayısı", min_value=1, max_value=50, value=8, step=1)
    cat_opt = st.selectbox("📂 Kategori", list(CATEGORIES.keys()))
    
    st.markdown("### Limitler")
    min_view_inp = st.number_input("👁️ Min. İzlenme", value=0, step=500)
    min_like_inp = st.number_input("❤️ Min. Beğeni", value=0, step=10)
    
    hashtag_filter = st.text_input("Hashtag (#)", placeholder="örn: indirim")

# ANA EKRAN
st.title("TrendScope TR - Akıllı Ürün Analizi")
st.write("TikTok verilerini tarar, 'Ürün' ve 'Satış' odaklı olmayanları yapay zeka mantığıyla eler.")

search_query = st.text_input("", placeholder="Ürün adı, marka veya anahtar kelime...", label_visibility="collapsed")

if st.button("🚀 ÜRÜNLERİ BUL", use_container_width=True):
    
    # Sorgu
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
        
    if not final_query.strip():
        final_query = "inceleme fiyat sipariş"

    with st.spinner(f"📡 Veriler çekiliyor ve analiz ediliyor (Hedef: {limit_user} adet)..."):
        
        # 1. Apify'dan Veri Çek
        raw_df = fetch_tiktok_data(final_query, limit_user)
        
        # 2. İşle ve Filtrele
        clean_df, total_scraped, total_products = process_data(raw_df, min_view_inp, min_like_inp, date_opt, limit_user)
        
        if not clean_df.empty:
            st.session_state.results = clean_df
            st.success(f"✅ Başarılı! {len(clean_df)} adet nitelikli ürün videosu bulundu.")
            
            # Bilgilendirme Metni
            st.caption(f"🔎 Analiz Detayı: Toplam {total_scraped} video tarandı. Bunlardan {total_products} tanesi 'Ürün' olarak tespit edildi. Tarih ve limit filtrelerinden sonra {len(clean_df)} adet gösteriliyor.")
        
        else:
            st.warning("⚠️ Sonuç bulunamadı.")
            if total_scraped > 0:
                st.error(f"""
                **Analiz Raporu:**
                - Apify'dan **{total_scraped}** adet video çekildi.
                - Bu videolardan **{total_products}** tanesi 'Ürün' kriterine uydu.
                - Ancak **Tarih Filtresi ({date_opt if date_opt else 'Tümü'})** veya İzlenme Limiti sebebiyle hepsi elendi.
                
                **Öneri:** Sol taraftan 'Tarih Aralığı'nı artırın (örn: Son 180 Gün veya 365 Gün) çünkü Apify eski popüler videoları getiriyor olabilir.
                """)
            else:
                st.error("Apify kaynaklı veri gelmedi veya bağlantı sorunu var.")
            st.session_state.results = None

# TABLO
if 'results' in st.session_state and st.session_state.results is not None:
    df = st.session_state.results
    
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Listelenen", len(df))
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
            "Urun_Tahmin": st.column_config.TextColumn("Ürün / İçerik", width="medium"),
            "Hesap": st.column_config.TextColumn("Satıcı", width="small"),
            "Viral_Skor": st.column_config.ProgressColumn("Viral Puanı", format="%.1f", min_value=0, max_value=100),
            "playCount": st.column_config.NumberColumn("İzlenme"),
            "diggCount": st.column_config.NumberColumn("Beğeni"),
            "shareCount": st.column_config.NumberColumn("Paylaşım"),
            "webVideoUrl": st.column_config.LinkColumn("Link", display_text="İzle ▶️"),
            "Tarih_Gorsel": st.column_config.TextColumn("Yayın Tarihi")
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