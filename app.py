import streamlit as st
import pandas as pd
from apify_client import ApifyClient
from datetime import datetime, timedelta

# --- 1. SAYFA AYARLARI ---
st.set_page_config(
    page_title="TrendScope TR - Viral Analiz",
    layout="wide",
    page_icon="🚀",
    initial_sidebar_state="expanded"
)

# --- 2. CSS & TASARIM (KALODATA STİLİ - BEYAZ) ---
# --- CSS & TASARIM (DÜZELTİLMİŞ) ---
st.markdown("""
<style>
    /* 1. Sayfa Üst Boşluğu Ayarı (DÜZELTME BURADA) */
    /* 1rem yerine 4rem yapıyoruz ki Header'ın altında kalsın */
    .block-container {
        padding-top: 4rem !important; 
        padding-bottom: 1rem !important;
    }
    
    /* 2. Menü Butonlarının Tasarımı */
    div.stButton > button {
        border-radius: 20px;
        border: 1px solid #e0e0e0;
        background-color: #f8f9fa;
        color: #555;
        font-size: 14px;
        height: 40px; /* Buton yüksekliği */
        width: 100%;
        transition: all 0.3s ease;
        box-shadow: 0 1px 3px rgba(0,0,0,0.08);
    }
    
    /* Hover (Üzerine gelince) */
    div.stButton > button:hover {
        border-color: #007bff;
        color: #007bff;
        background-color: #fff;
        transform: translateY(-2px);
    }
    
    /* Aktif/Focus Durumu */
    div.stButton > button:focus:not(:active) {
        border-color: #007bff;
        color: #007bff;
    }

    /* 3. Genel Arka Plan ve Renkler (Light Mode Zorlama) */
    .stApp {
        background-color: #ffffff !important;
        color: #31333F !important;
    }
    
    /* 4. Sidebar Düzenlemesi */
    section[data-testid="stSidebar"] {
        background-color: #f8f9fa !important;
        padding-top: 3rem !important; /* Sidebar içeriğini de biraz aşağı alalım */
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

# --- 4. DATA YÖNETİMİ & NAVIGASYON ---

# Query Parametrelerini Yönetme (Navigation İçin)
query_params = st.query_params
current_tab = query_params.get("tab", "genel")  # Varsayılan tab: genel

# Header Navigasyon Butonları (HTML ile Pseudo-Linkleme)
# Streamlit butonları sayfayı yenilediği için query_params setleyip rerun yapıyoruz.
col_nav1, col_nav2, col_nav3, col_nav4, col_nav5 = st.columns(5)

def set_tab(tab_name):
    st.query_params["tab"] = tab_name
    # st.rerun() # Gerekirse sayfayı yeniletmek için açılabilir

with col_nav1:
    if st.button("🌐 Genel", use_container_width=True, type="primary" if current_tab == "genel" else "secondary"):
        set_tab("genel")
with col_nav2:
    if st.button("📢 Reklam", use_container_width=True, type="primary" if current_tab == "reklam" else "secondary"):
        set_tab("reklam")
with col_nav3:
    if st.button("📦 Ürün", use_container_width=True, type="primary" if current_tab == "urun" else "secondary"):
        set_tab("urun")
with col_nav4:
    if st.button("📝 Blog", use_container_width=True, type="primary" if current_tab == "blog" else "secondary"):
        set_tab("blog")
with col_nav5:
    if st.button("📞 İletişim", use_container_width=True, type="primary" if current_tab == "iletisim" else "secondary"):
        set_tab("iletisim")

# --- 5. KATEGORİLER ---
CATEGORIES = {
    "Tümü": [],
    "🏠 Ev & Yaşam": ["mutfak", "düzen", "temizlik", "dekorasyon", "evim", "çeyiz"],
    "💄 Güzellik & Bakım": ["makyaj", "ciltbakımı", "güzellik", "sacmodelleri", "bakım"],
    "👗 Moda & Giyim": ["kombin", "moda", "tesettür", "giyim", "stil", "butik"],
    "💻 Teknoloji & Aksesuar": ["teknoloji", "telefonkilifi", "akıllısaat", "aksesuar", "kulaklık"],
    "👶 Anne & Bebek": ["bebek", "anne", "hamile", "oyuncak", "bebekgiyim"],
    "🚗 Oto & Araç": ["araba", "modifiye", "otoaksesuar", "detailing"]
}

# --- 6. YARDIMCI FONKSİYONLAR ---

def turkce_tarih_format(date_obj):
    """Datetime objesini Türkçe formatına (7 Ara 2025) çevirir."""
    if pd.isna(date_obj): return ""
    aylar = {
        1: "Oca", 2: "Şub", 3: "Mar", 4: "Nis", 5: "May", 6: "Haz",
        7: "Tem", 8: "Ağu", 9: "Eyl", 10: "Eki", 11: "Kas", 12: "Ara"
    }
    return f"{date_obj.day} {aylar.get(date_obj.month)} {date_obj.year}"

def fetch_tiktok_data(query, limit=50):
    try:
        run_input = {
            "searchQueries": [query],
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
        st.error(f"⚠️ Apify Bağlantı Hatası: {e}")
        return pd.DataFrame()

def process_data(df, min_views, min_likes, date_limit):
    if df.empty: return df
    
    # Bölge Filtresi (TR)
    def get_region(meta):
        if isinstance(meta, dict): return meta.get('region', '')
        return ''

    if 'authorMeta' in df.columns:
        df['Region_Code'] = df['authorMeta'].apply(get_region)
        df = df[df['Region_Code'].isin(['TR', 'tr', 'Tr', 'TUR', ''])]
    
    if df.empty: return pd.DataFrame()

    # Sayısal Dönüşümler
    cols = ['playCount', 'diggCount', 'shareCount', 'collectCount', 'commentCount']
    for col in cols:
        if col not in df.columns: df[col] = 0
        df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)
    
    # Tarih İşlemleri
    if 'createTimeISO' in df.columns:
        df['createTimeISO'] = pd.to_datetime(df['createTimeISO'], errors='coerce', utc=True).dt.tz_localize(None)
        if date_limit:
            cutoff_date = datetime.now() - timedelta(days=date_limit)
            df = df[df['createTimeISO'] >= cutoff_date]
            
        # Görselleştirme için Türkçe Tarih Kolonu Ekle
        df['Tarih_Gorsel'] = df['createTimeISO'].apply(turkce_tarih_format)
    
    # Metrik Filtreleme
    df = df[df['playCount'] >= min_views]
    df = df[df['diggCount'] >= min_likes]
    
    if df.empty: return pd.DataFrame()

    # Hesaplamalar
    total_interact = df['diggCount'] + df['commentCount'] + df['shareCount']
    df['Etkilesim_Orani'] = (total_interact / df['playCount'].replace(0, 1)) * 100
    df['Viral_Skor'] = ((df['shareCount'] + df['collectCount']) / df['diggCount'].replace(0, 1)) * 100
    
    df['Etkilesim_Orani'] = df['Etkilesim_Orani'].round(2)
    df['Viral_Skor'] = df['Viral_Skor'].round(2)
    
    # Görsel Hazırlık
    df['Resim'] = df['videoMeta'].apply(lambda x: x.get('coverUrl', '') if isinstance(x, dict) else '')
    df['Hesap'] = df['authorMeta'].apply(lambda x: x.get('name', '') if isinstance(x, dict) else '')
    df['Urun_Tahmin'] = df['text'].apply(lambda x: " ".join(str(x).split()[:7]) + "..." if x else "Başlıksız")
    
    df = df.sort_values(by="Viral_Skor", ascending=False)
    return df

# --- 7. SIDEBAR VE ARAYÜZ ---

# Blog ve İletişim Sayfaları için Basit Yer Tutucu
if current_tab == "blog":
    st.title("📝 Blog Yazıları")
    st.info("Blog modülü yapım aşamasındadır.")
    st.stop()
elif current_tab == "iletisim":
    st.title("📞 İletişim")
    st.info("Bize ulasin: info@trendscope.tr")
    st.stop()

# ANA ANALİZ EKRANI (Genel / Reklam / Ürün)
with st.sidebar:
    st.markdown("### 🚀 TrendScope TR")
    st.caption(f"Mod: **{current_tab.upper()} ANALİZİ**")
    
    st.markdown("---")
    
    # Filtreler
    # 3. İSTEK: 180 Gün Eklendi
    date_opt = st.selectbox(
        "📅 Tarih Aralığı",
        options=[7, 30, 90, 180, 365],
        format_func=lambda x: f"Son {x} Gün",
        index=1
    )
    
    # 4. İSTEK: Adet Limiti
    limit_opt = st.number_input("🔢 Maks. Sonuç Adedi", min_value=10, max_value=200, value=50, step=10)
    
    cat_opt = st.selectbox("📂 Kategori", list(CATEGORIES.keys()))
    
    st.markdown("### 📊 Limitler")
    min_view_inp = st.number_input("👁️ Min. İzlenme", value=5000, step=1000)
    min_like_inp = st.number_input("❤️ Min. Beğeni", value=100, step=50)
    
    st.markdown("### 🏷️ Ekstra")
    hashtag_filter = st.text_input("Hashtag (#)", placeholder="örn: keşfet")
    
    st.info("💡 Veriler Türkiye konumlu videolardan çekilir.")

# Ana İçerik
col_search_area = st.container()

with col_search_area:
    st.title("Türkiye Pazar Analizi")
    if current_tab == "reklam":
        st.caption("Sadece 'işbirliği' ve 'sponsorlu' içeriklere odaklanılır.")
    elif current_tab == "urun":
        st.caption("Ürün satışı, fiyat ve sipariş odaklı videolara odaklanılır.")
        
    search_query = st.text_input("", placeholder="Ürün, Kelime veya Mağaza ara...", label_visibility="collapsed")

if st.button("🔎 ANALİZ ET VE LİSTELE", use_container_width=True):
    
    # Sorgu Mantığı (Tab'a göre değişen strateji)
    final_query = ""
    
    # 1. Kategori Bazlı
    if cat_opt != "Tümü":
        import random
        base_keyword = random.choice(CATEGORIES[cat_opt])
        final_query = f"{base_keyword}"
    
    # 2. Kullanıcı Araması
    if search_query:
        final_query = f"{search_query} {final_query}"
        
    # 3. SAYFA MODUNA GÖRE EKLEMELER (Navigation Logic)
    if current_tab == "reklam":
        final_query += " #işbirliği #reklam #sponsor"
    elif current_tab == "urun":
        final_query += " sipariş fiyat link kargo"
    
    # 4. Hashtag
    if hashtag_filter:
        clean_tag = hashtag_filter.replace('#','')
        final_query = f"{final_query} #{clean_tag}"
        
    if not final_query.strip():
        final_query = "inceleme öneri"

    with st.spinner(f"📡 '{final_query.strip()}' taranıyor ({current_tab.upper()} Modu)..."):
        # Limit kullanıcıdan geliyor
        raw_df = fetch_tiktok_data(final_query, limit=limit_opt) 
        clean_df = process_data(raw_df, min_view_inp, min_like_inp, date_opt)
        
        if not clean_df.empty:
            st.session_state.kalodata_results = clean_df
            st.success(f"✅ {len(clean_df)} video bulundu.")
        else:
            st.warning("⚠️ Kriterlere uygun sonuç bulunamadı.")
            st.session_state.kalodata_results = None

# --- SONUÇ TABLOSU ---
if 'kalodata_results' in st.session_state and st.session_state.kalodata_results is not None:
    df = st.session_state.kalodata_results
    
    # İstatistikler
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Toplam Video", len(df))
    m2.metric("Ort. İzlenme", f"{int(df['playCount'].mean()):,}")
    m3.metric("Ort. Viral Skor", f"{df['Viral_Skor'].mean():.1f}")
    m4.metric("En Yüksek Beğeni", f"{int(df['diggCount'].max()):,}")
    
    st.markdown("---")
    
    # TABLO
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
            "Tarih_Gorsel"  # Türkçe Tarih Sütunu
        ]],
        column_config={
            "Resim": st.column_config.ImageColumn("Video", width="small"),
            "Urun_Tahmin": st.column_config.TextColumn("Ürün / İçerik", width="medium"),
            "Hesap": st.column_config.TextColumn("Mağaza", width="small"),
            "Viral_Skor": st.column_config.ProgressColumn(
                "Viral Puanı", format="%.1f", min_value=0, max_value=100
            ),
            "Etkilesim_Orani": st.column_config.NumberColumn("Etkileşim %", format="%.2f %%"),
            "playCount": st.column_config.NumberColumn("İzlenme", format="%d"),
            "diggCount": st.column_config.NumberColumn("Beğeni", format="%d"),
            "shareCount": st.column_config.NumberColumn("Paylaşım", format="%d"),
            "webVideoUrl": st.column_config.LinkColumn("Link", display_text="İzle ▶️"),
            "Tarih_Gorsel": st.column_config.TextColumn("Yayın Tarihi") # Metin olarak gösteriyoruz
        },
        use_container_width=True,
        hide_index=True,
        height=700 
    )
else:
    # Boş Durum
    st.markdown(f"""
    <div style='text-align: center; color: #888; padding: 50px; background-color:#f9f9f9; border-radius:10px;'>
        <h3>Henüz veri yok ({current_tab.capitalize()})</h3>
        <p>Sol taraftan kriterleri seç ve <b>ANALİZ ET</b> butonuna bas.</p>
    </div>
    """, unsafe_allow_html=True)