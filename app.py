import streamlit as st
import pandas as pd
from apify_client import ApifyClient
from datetime import datetime, timedelta

# --- 1. SAYFA AYARLARI ---
st.set_page_config(
    page_title="TrendScope TR - Ürün Analizi",
    layout="wide",
    page_icon="🚀",
    initial_sidebar_state="expanded"
)

# --- 2. CSS & TASARIM (BEYAZ TEMA & DÜZGÜN YERLEŞİM) ---
st.markdown("""
<style>
    /* 1. Sayfa Üst Boşluğu (Header'ın altına tam oturması için) */
    .block-container {
        padding-top: 4rem !important;
        padding-bottom: 2rem !important;
    }
    
    /* 2. Navigasyon Butonları */
    div.stButton > button {
        border-radius: 20px;
        border: 1px solid #e0e0e0;
        background-color: #f8f9fa;
        color: #555;
        font-size: 14px;
        height: 40px;
        width: 100%;
        transition: all 0.3s ease;
        box-shadow: 0 1px 3px rgba(0,0,0,0.05);
    }
    div.stButton > button:hover {
        border-color: #007bff;
        color: #007bff;
        background-color: #fff;
        transform: translateY(-2px);
    }
    div.stButton > button:focus:not(:active) {
        border-color: #007bff;
        color: #007bff;
    }

    /* 3. Genel Renkler (Light Mode Zorlama) */
    .stApp {
        background-color: #ffffff !important;
        color: #31333F !important;
    }
    h1, h2, h3, h4, p, span, div, label {
        color: #31333F !important;
    }
    
    /* 4. Sidebar */
    section[data-testid="stSidebar"] {
        background-color: #f8f9fa !important;
        padding-top: 3rem !important;
        border-right: 1px solid #eee;
    }
    
    /* 5. Input Alanları */
    .stTextInput input, .stNumberInput input, .stSelectbox div {
        background-color: #fff !important;
        color: #333 !important;
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

# --- 4. NAVIGASYON MANTIĞI ---
query_params = st.query_params
current_page = query_params.get("page", "analiz")

# Header Menüsü
col1, col2, col3, col4 = st.columns([1,1,1,3]) # Son kolon boşluk için
with col1:
    if st.button("🚀 Ürün Analizi", use_container_width=True, type="primary" if current_page == "analiz" else "secondary"):
        st.query_params["page"] = "analiz"
with col2:
    if st.button("📝 Blog", use_container_width=True, type="primary" if current_page == "blog" else "secondary"):
        st.query_params["page"] = "blog"
with col3:
    if st.button("📞 İletişim", use_container_width=True, type="primary" if current_page == "iletisim" else "secondary"):
        st.query_params["page"] = "iletisim"

# --- 5. KATEGORİ VE KELİME HAVUZU ---

CATEGORIES = {
    "Tümü": [],
    "🏠 Ev & Yaşam": ["mutfak", "düzen", "temizlik", "dekorasyon", "çeyiz", "banyo", "pratik"],
    "💄 Güzellik & Bakım": ["makyaj", "ciltbakımı", "güzellik", "kozmetik", "bakım"],
    "👗 Moda & Giyim": ["kombin", "moda", "tesettür", "giyim", "butik", "elbise", "ayakkabı"],
    "💻 Teknoloji & Aksesuar": ["teknoloji", "kılıf", "aksesuar", "kulaklık", "saat", "gadget"],
    "👶 Anne & Bebek": ["bebek", "oyuncak", "bebekgiyim", "hamile"],
    "🚗 Oto & Araç": ["otoaksesuar", "araba", "modifiye", "temizlik"]
}

# Ürün/Satış Sinyali Veren Genişletilmiş Kelime Listesi
PRODUCT_KEYWORDS = [
    # Satış İşlemi
    "sipariş", "fiyat", "kargo", "satın al", "link", "profilde", "bioda", 
    "stok", "tükenmeden", "kampanya", "indirim", "ücretsiz kargo", 
    "kapıda ödeme", "kapıda öde", "şeffaf kargo", "whatsapp", "dm", "iletişim", 
    # Ürün Özellikleri
    "beden", "renk", "kumaş", "model", "kalite", "garanti", "iade", 
    "değişim", "takım", "adet", "tl", "₺", "magaza", "butik", "showroom",
    # Eylem Çağrısı
    "linke tıkla", "profildeki link", "sipariş için", "bilgi için", "sipariş oluştur"
]

# --- 6. FONKSİYONLAR ---

def turkce_tarih_format(date_obj):
    if pd.isna(date_obj): return ""
    aylar = {1: "Oca", 2: "Şub", 3: "Mar", 4: "Nis", 5: "May", 6: "Haz", 7: "Tem", 8: "Ağu", 9: "Eyl", 10: "Eki", 11: "Kas", 12: "Ara"}
    return f"{date_obj.day} {aylar.get(date_obj.month)} {date_obj.year}"

def check_is_product(text):
    """Metin içinde satış/ürün sinyali veren kelimeler var mı kontrol eder."""
    if not isinstance(text, str): return False
    text_lower = text.lower()
    # Kelime listesinden en az 1 tanesi geçiyorsa True döner
    for keyword in PRODUCT_KEYWORDS:
        if keyword in text_lower:
            return True
    return False

def fetch_tiktok_data(query, limit):
    """
    Apify'dan veri çeker.
    ÖNEMLİ: Kullanıcı 10 adet istiyorsa, filtrelemelerden sonra azalacağı için
    Apify'dan 'limit * 3' kadar veri istiyoruz (Buffer Mantığı).
    """
    scrape_buffer = limit * 4 # Buffer katsayısını 4 yaptık (daha garanti olsun)
    if scrape_buffer > 200: scrape_buffer = 200 # Çok aşırı yüklenmeyi engellemek için tavan
    
    try:
        run_input = {
            "searchQueries": [query],
            "resultsPerPage": scrape_buffer, # Daha fazla çekiyoruz
            "searchRegion": "TR",
            "searchLanguage": "tr-TR",
        }
        # Not: free-tiktok-scraper bazen çok yoğun olabilir, alternatif gerekirse burası değişebilir.
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
    
    # 1. Bölge Filtresi (Sadece TR)
    def get_region(meta):
        if isinstance(meta, dict): return meta.get('region', '')
        return ''
    
    if 'authorMeta' in df.columns:
        df['Region_Code'] = df['authorMeta'].apply(get_region)
        df = df[df['Region_Code'].isin(['TR', 'tr', 'TUR', ''])]
    
    # 2. Ürün İçeriği Kontrolü (Gelişmiş Kelime Analizi)
    df['is_product'] = df['text'].apply(check_is_product)
    df = df[df['is_product'] == True] # Sadece ürün olanları tut
    
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

    # 6. Puanlama (Viral Skor)
    df['Viral_Skor'] = ((df['shareCount'] + df['collectCount']) / df['diggCount'].replace(0, 1)) * 100
    df['Etkilesim_Orani'] = ((df['diggCount'] + df['commentCount'] + df['shareCount']) / df['playCount'].replace(0, 1)) * 100
    
    df['Viral_Skor'] = df['Viral_Skor'].round(1)
    df['Etkilesim_Orani'] = df['Etkilesim_Orani'].round(2)
    
    # 7. Görselleştirme Sütunları
    df['Resim'] = df['videoMeta'].apply(lambda x: x.get('coverUrl', '') if isinstance(x, dict) else '')
    df['Hesap'] = df['authorMeta'].apply(lambda x: x.get('name', '') if isinstance(x, dict) else '')
    df['Urun_Tahmin'] = df['text'].apply(lambda x: " ".join(str(x).split()[:7]) + "..." if x else "")
    
    # 8. Sıralama ve Limit
    # En yüksek Viral Skora sahip olanları alıyoruz
    df = df.sort_values(by="Viral_Skor", ascending=False)
    
    # Kullanıcının istediği adet kadarını kesip veriyoruz (Örn: 10 tane)
    return df.head(target_limit)

# --- 7. SAYFA İÇERİKLERİ ---

if current_page == "blog":
    st.title("📝 TrendScope Blog")
    st.info("E-ticaret trendleri ve analiz ipuçları yakında burada olacak.")
    st.stop()
    
elif current_page == "iletisim":
    st.title("📞 İletişim")
    st.markdown("""
    **TrendScope TR Ekibi**  
    Sorularınız ve önerileriniz için:  
    📧 **info@trendscope.tr**
    """)
    st.stop()

# --- ANA ANALİZ SAYFASI ---
with st.sidebar:
    st.markdown("### 🔍 Filtreler")
    st.markdown("---")
    
    # Tarih
    date_opt = st.selectbox("📅 Tarih Aralığı", [7, 30, 90, 180, 365], index=1, format_func=lambda x: f"Son {x} Gün")
    
    # Adet
    limit_opt = st.number_input("🔢 Gösterilecek Sonuç", min_value=5, max_value=50, value=10, step=5, help="Listelenecek maksimum ürün sayısı.")
    
    # Kategori
    cat_opt = st.selectbox("📂 Kategori", list(CATEGORIES.keys()))
    
    st.markdown("### 📊 Limitler")
    min_view_inp = st.number_input("👁️ Min. İzlenme", value=1000, step=500)
    min_like_inp = st.number_input("❤️ Min. Beğeni", value=50, step=10)
    
    st.markdown("### 🏷️ Ekstra")
    hashtag_filter = st.text_input("Hashtag (#)", placeholder="örn: tesettur")
    
    st.info("ℹ️ Sadece satış/ürün odaklı videolar taranır.")

# Ana Ekran
st.title("Türkiye Pazar & Ürün Analizi")
st.write("TikTok üzerindeki potansiyel 'Winner' ürünleri, reklamları ve fırsatları keşfedin.")

search_query = st.text_input("", placeholder="Ürün, Kelime veya Mağaza ara... (Örn: Çanta, Abiye, Telefon)", label_visibility="collapsed")

if st.button("🔎 ÜRÜNLERİ BUL", use_container_width=True):
    
    # Sorgu Oluşturma
    final_query = ""
    
    # 1. Kategori
    if cat_opt != "Tümü":
        import random
        # Kategoriden rastgele bir anahtar kelime al
        base_keyword = random.choice(CATEGORIES[cat_opt])
        final_query = f"{base_keyword}"
    
    # 2. Kullanıcı Araması
    if search_query:
        final_query = f"{search_query} {final_query}"
        
    # 3. Ürün Odaklı Ek Kelimeler (Search Query'e eklemek zorunlu değil çünkü process_data içinde filtreliyoruz
    # Ancak aramayı daraltmak için "inceleme" veya "öneri" gibi genel terimler ekleyebiliriz.
    if not final_query.strip():
        final_query = "inceleme öneri sipariş" # Hiçbir şey yazılmazsa genel ürün araması
        
    # 4. Hashtag
    if hashtag_filter:
        clean_tag = hashtag_filter.replace('#','')
        final_query = f"{final_query} #{clean_tag}"

    with st.spinner(f"📡 '{final_query.strip()}' için ürünler taranıyor ve filtreleniyor..."):
        
        # Apify'a daha fazla istek atıyoruz (limit_opt * 4)
        raw_df = fetch_tiktok_data(final_query, limit=limit_opt)
        
        # Gelen fazla veriyi filtreleyip, kullanıcı limiti kadarını alıyoruz
        clean_df = process_data(raw_df, min_view_inp, min_like_inp, date_opt, limit_opt)
        
        if not clean_df.empty:
            st.session_state.trendscope_results = clean_df
            st.success(f"✅ Kriterlere uyan {len(clean_df)} adet ürün videosu bulundu.")
        else:
            st.warning("⚠️ Kriterlere uygun ürün bulunamadı. (Bulunan videolar ürün filtresine veya izlenme limitine takılmış olabilir).")
            st.session_state.trendscope_results = None

# --- SONUÇLARI GÖSTERME ---
if 'trendscope_results' in st.session_state and st.session_state.trendscope_results is not None:
    df = st.session_state.trendscope_results
    
    # Özet Bantı
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Listelenen", len(df))
    m2.metric("Ort. İzlenme", f"{int(df['playCount'].mean()):,}")
    m3.metric("Ort. Viral Skor", f"{df['Viral_Skor'].mean():.1f}")
    m4.metric("En Çok Paylaşım", f"{int(df['shareCount'].max()):,}")
    
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
            "Hesap": st.column_config.TextColumn("Satıcı/Mağaza", width="small"),
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
    <div style='text-align: center; color: #888; padding: 60px; background-color:#f9f9f9; border-radius:12px; margin-top:20px;'>
        <h3>Henüz Analiz Yapılmadı</h3>
        <p>Sol taraftan kategori seçin veya bir ürün adı yazın, ardından <b>ÜRÜNLERİ BUL</b> butonuna basın.</p>
    </div>
    """, unsafe_allow_html=True)