import logging
import sqlite3
import os
from datetime import datetime
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
    ConversationHandler
)

# Logging ayarları
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# Konuşma Adımları (States)
GUN_BASI_DONER, ISLEM_SECIMI, EKMEK_GIR, SALON_GIR, PAKET_GIR, APERATIF_GIR = range(6)

DB_DOSYASI = "devran_doner.db"
ARSIV_DOSYASI = "devran_doner_tum_arsiv.txt"

# ------------------- VERİTABANI İŞLEMLERİ -------------------

def init_db():
    conn = sqlite3.connect(DB_DOSYASI)
    c = conn.cursor()
    # Günlük durum tablosu
    c.execute('''
        CREATE TABLE IF NOT EXISTS gunluk_durum (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            baslangic_kilo REAL DEFAULT 0,
            ekmek_adet INTEGER DEFAULT 0,
            salon_adet INTEGER DEFAULT 0,
            paket_adet INTEGER DEFAULT 0,
            salon_fiyat REAL DEFAULT 120,
            paket_fiyat REAL DEFAULT 140,
            tarih TEXT,
            aktif_gun INTEGER DEFAULT 0
        )
    ''')
    # Personel yemekleri tablosu
    c.execute('''
        CREATE TABLE IF NOT EXISTS personel_yemek (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            isim TEXT,
            porsiyon INTEGER
        )
    ''')
    # Veri yoksa varsayılan satırı ekle
    c.execute("INSERT OR IGNORE INTO gunluk_durum (id) VALUES (1)")
    conn.commit()
    conn.close()

def get_veri():
    conn = sqlite3.connect(DB_DOSYASI)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT * FROM gunluk_durum WHERE id = 1")
    row = dict(c.fetchone())
    
    c.execute("SELECT isim, SUM(porsiyon) as toplam FROM personel_yemek GROUP BY isim")
    personel_rows = c.fetchall()
    personel_dict = {r['isim']: r['toplam'] for r in personel_rows}
    row['personel'] = personel_dict
    
    conn.close()
    return row

def update_veri(field, value):
    conn = sqlite3.connect(DB_DOSYASI)
    c = conn.cursor()
    c.execute(f"UPDATE gunluk_durum SET {field} = ? WHERE id = 1", (value,))
    conn.commit()
    conn.close()

def increment_veri(field, amount):
    conn = sqlite3.connect(DB_DOSYASI)
    c = conn.cursor()
    c.execute(f"UPDATE gunluk_durum SET {field} = {field} + ? WHERE id = 1", (amount,))
    conn.commit()
    conn.close()

def add_personel_yemek(isim, porsiyon):
    conn = sqlite3.connect(DB_DOSYASI)
    c = conn.cursor()
    c.execute("INSERT INTO personel_yemek (isim, porsiyon) VALUES (?, ?)", (isim, porsiyon))
    conn.commit()
    conn.close()

def reset_db_day():
    conn = sqlite3.connect(DB_DOSYASI)
    c = conn.cursor()
    c.execute('''
        UPDATE gunluk_durum SET 
            baslangic_kilo = 0,
            ekmek_adet = 0,
            salon_adet = 0,
            paket_adet = 0,
            tarih = '',
            aktif_gun = 0
        WHERE id = 1
    ''')
    c.execute("DELETE FROM personel_yemek")
    conn.commit()
    conn.close()

init_db()

# ------------------- YARDIMCI FONKSİYONLAR -------------------

def ana_klavye():
    keyboard = [
        ["🍽 Salon Satışı", "📦 Paket Satışı"],
        ["🥖 Fırın Ekmek Ekle", "🥪 Personel Yemeği"],
        ["📊 Anlık Rapor", "🔴 Gün Sonu Kapat"]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def adet_klavyesi():
    keyboard = [
        ["1", "2", "3", "4", "5"],
        ["6", "7", "8", "9", "10"],
        ["15", "20", "⬅️ İptal"]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

# ------------------- BOT ADIMLARI -------------------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    v = get_veri()
    if v['aktif_gun'] == 1:
        await update.message.reply_text(
            f"⚡️ Günlük takip zaten aktif! ({v['tarih']})\nAşağıdaki menüden işlem yapabilirsiniz.",
            reply_markup=ana_klavye()
        )
        return ISLEM_SECIMI

    await update.message.reply_text(
        "👋 **Devran Döner Yönetim Botuna Hoş Geldiniz!**\n\n"
        "☀️ Yeni günü başlatmak için bugün takılan **Döner Kilosunu (kg)** giriniz:\n"
        "*(Örn: 25.5 veya 30)*",
        reply_markup=ReplyKeyboardRemove()
    )
    return GUN_BASI_DONER

async def gun_basi_doner(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.replace(',', '.')
    try:
        kilo = float(text)
        tarih_str = datetime.now().strftime("%d.%m.%Y")
        
        conn = sqlite3.connect(DB_DOSYASI)
        c = conn.cursor()
        c.execute('''
            UPDATE gunluk_durum SET 
                baslangic_kilo = ?,
                ekmek_adet = 0,
                salon_adet = 0,
                paket_adet = 0,
                tarih = ?,
                aktif_gun = 1
            WHERE id = 1
        ''', (kilo, tarih_str))
        c.execute("DELETE FROM personel_yemek")
        conn.commit()
        conn.close()

        await update.message.reply_text(
            f"✅ **Gün Başlatıldı!**\n📅 Tarih: {tarih_str}\n🥩 Takılan Döner: **{kilo} kg**\n\n"
            "İşlem yapmak için aşağıdaki menüyü kullanabilirsiniz.",
            reply_markup=ana_klavye()
        )
        return ISLEM_SECIMI
    except ValueError:
        await update.message.reply_text("❌ Lütfen geçerli bir sayı giriniz (Örn: 25 veya 25.5):")
        return GUN_BASI_DONER

async def islem_secimi(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text

    if text == "🍽 Salon Satışı":
        await update.message.reply_text("🍽 Kaç adet **SALON** satışı yapıldı?", reply_markup=adet_klavyesi())
        return SALON_GIR

    elif text == "📦 Paket Satışı":
        await update.message.reply_text("📦 Kaç adet **PAKET** satışı yapıldı?", reply_markup=adet_klavyesi())
        return PAKET_GIR

    elif text == "🥖 Fırın Ekmek Ekle":
        await update.message.reply_text("🥖 Fırından gelen **Ekmek Adedini** giriniz:", reply_markup=ReplyKeyboardRemove())
        return EKMEK_GIR

    elif text == "🥪 Personel Yemeği":
        await update.message.reply_text(
            "🥪 Personel yemeği giriş formatı: **[İsim] [Adet]**\n"
            "*(Örn: Ahmet 2 veya Usta 1)*",
            reply_markup=ReplyKeyboardRemove()
        )
        return APERATIF_GIR

    elif text == "📊 Anlık Rapor":
        await anlik_rapor_gonder(update, context)
        return ISLEM_SECIMI

    elif text == "🔴 Gün Sonu Kapat":
        await gun_sonu_kapat(update, context)
        return ConversationHandler.END

    else:
        await update.message.reply_text("Lütfen menüdeki butonları kullanın veya 's 2', 'p 3' gibi hızlı komut girin.", reply_markup=ana_klavye())
        return ISLEM_SECIMI

async def salon_gir(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text == "⬅️ İptal":
        await update.message.reply_text("İşlem iptal edildi.", reply_markup=ana_klavye())
        return ISLEM_SECIMI
    try:
        adet = int(text)
        increment_veri('salon_adet', adet)
        v = get_veri()
        await update.message.reply_text(
            f"✅ **{adet} Adet Salon Satışı Eklendi.**\n"
            f"📊 Toplam Salon: **{v['salon_adet']} Adet** ({v['salon_adet'] * v['salon_fiyat']} TL)",
            reply_markup=ana_klavye()
        )
        return ISLEM_SECIMI
    except ValueError:
        await update.message.reply_text("❌ Lütfen geçerli bir adet giriniz veya İptal'e basınız:")
        return SALON_GIR

async def paket_gir(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text == "⬅️ İptal":
        await update.message.reply_text("İşlem iptal edildi.", reply_markup=ana_klavye())
        return ISLEM_SECIMI
    try:
        adet = int(text)
        increment_veri('paket_adet', adet)
        v = get_veri()
        await update.message.reply_text(
            f"✅ **{adet} Adet Paket Satışı Eklendi.**\n"
            f"📊 Toplam Paket: **{v['paket_adet']} Adet** ({v['paket_adet'] * v['paket_fiyat']} TL)",
            reply_markup=ana_klavye()
        )
        return ISLEM_SECIMI
    except ValueError:
        await update.message.reply_text("❌ Lütfen geçerli bir adet giriniz veya İptal'e basınız:")
        return PAKET_GIR

async def ekmek_gir(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        adet = int(update.message.text)
        increment_veri('ekmek_adet', adet)
        v = get_veri()
        await update.message.reply_text(
            f"✅ **{adet} Adet Ekmek Eklendi.**\n"
            f"🥖 Toplam Fırın Ekmeği: **{v['ekmek_adet']} Adet**",
            reply_markup=ana_klavye()
        )
        return ISLEM_SECIMI
    except ValueError:
        await update.message.reply_text("❌ Lütfen geçerli bir sayı giriniz:")
        return EKMEK_GIR

async def aperatif_gir(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        parçalar = update.message.text.strip().split()
        isim = " ".join(parçalar[:-1])
        adet = int(parçalar[-1])
        
        add_personel_yemek(isim, adet)
        
        await update.message.reply_text(
            f"✅ **{isim}** için **{adet} porsiyon** yemek kaydedildi.",
            reply_markup=ana_klavye()
        )
        return ISLEM_SECIMI
    except Exception:
        await update.message.reply_text("❌ Hatalı format! Örnek format: **Mehmet 2**", reply_markup=ana_klavye())
        return ISLEM_SECIMI

async def hizli_satis(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip().lower()
    parcalar = text.split()
    
    if len(parcalar) == 2:
        kod = parcalar[0]
        try:
            adet = int(parcalar[1])
            if kod == 's':
                increment_veri('salon_adet', adet)
                v = get_veri()
                await update.message.reply_text(f"⚡️ Hızlı Eklendi: **{adet} Salon**\nToplam Salon: **{v['salon_adet']} Adet**")
            elif kod == 'p':
                increment_veri('paket_adet', adet)
                v = get_veri()
                await update.message.reply_text(f"⚡️ Hızlı Eklendi: **{adet} Paket**\nToplam Paket: **{v['paket_adet']} Paket**")
        except ValueError:
            pass

async def anlik_rapor_gonder(update: Update, context: ContextTypes.DEFAULT_TYPE):
    v = get_veri()
    s_adet = v["salon_adet"]
    p_adet = v["paket_adet"]
    s_tutar = s_adet * v["salon_fiyat"]
    p_tutar = p_adet * v["paket_fiyat"]
    toplam_c = s_tutar + p_tutar
    toplam_porsiyon = s_adet + p_adet
    tarih = v.get('tarih', 'Bugün')

    rapor = f"📊 **DEVRAN DÖNER - ANLIK RAPOR ({tarih})**\n"
    rapor += f"-----------------------------------\n"
    rapor += f"🥩 Takılan Döner: **{v['baslangic_kilo']} kg**\n"
    rapor += f"🥖 Gelen Ekmek: **{v['ekmek_adet']} adet**\n\n"
    rapor += f"🍽 Salon Satışı: **{s_adet} adet** ({s_tutar:,.0f} TL)\n"
    rapor += f"📦 Paket Satışı: **{p_adet} adet** ({p_tutar:,.0f} TL)\n"
    rapor += f"-----------------------------------\n"
    rapor += f"📈 Toplam Satılan: **{toplam_porsiyon} porsiyon**\n"
    rapor += f"💰 **TOPLAM KASA: {toplam_c:,.0f} TL**\n"
    
    if v['personel']:
        rapor += f"\n🥪 **Personel Yemekleri:**\n"
        for p_isim, p_adet in v['personel'].items():
            rapor += f"  • {p_isim}: {p_adet} porsiyon\n"

    await update.message.reply_text(rapor, reply_markup=ana_klavye(), parse_mode='Markdown')

async def gun_sonu_kapat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    v = get_veri()
    s_adet = v["salon_adet"]
    p_adet = v["paket_adet"]
    s_tutar = s_adet * v["salon_fiyat"]
    p_tutar = p_adet * v["paket_fiyat"]
    toplam_c = s_tutar + p_tutar
    toplam_porsiyon = s_adet + p_adet
    tarih = v.get('tarih', datetime.now().strftime("%d.%m.%Y"))

    rapor_metni = f"===================================\n"
    rapor_metni += f"      DEVRAN DÖNER GÜN SONU RAPORU\n"
    rapor_metni += f"===================================\n"
    rapor_metni += f"Tarih          : {tarih}\n"
    rapor_metni += f"Takılan Döner  : {v['baslangic_kilo']} kg\n"
    rapor_metni += f"Fırın Ekmeği   : {v['ekmek_adet']} adet\n"
    rapor_metni += f"-----------------------------------\n"
    rapor_metni += f"Salon Satışı   : {s_adet} Adet ({s_tutar:,.0f} TL)\n"
    rapor_metni += f"Paket Satışı   : {p_adet} Adet ({p_tutar:,.0f} TL)\n"
    rapor_metni += f"-----------------------------------\n"
    rapor_metni += f"Toplam Porsiyon: {toplam_porsiyon} Adet\n"
    rapor_metni += f"GENEL TOPLAM   : {toplam_c:,.0f} TL\n"
    rapor_metni += f"-----------------------------------\n"
    
    if v['personel']:
        rapor_metni += f"Personel Yemekleri:\n"
        for p_isim, p_adet in v['personel'].items():
            rapor_metni += f"  - {p_isim}: {p_adet} porsiyon\n"
    rapor_metni += f"===================================\n"

    # Dosyaya kaydet
    filename = f"gun_sonu_{tarih.replace('.', '_')}.txt"
    with open(filename, "w", encoding="utf-8") as f:
        f.write(rapor_metni)
        
    with open(ARSIV_DOSYASI, "a", encoding="utf-8") as f:
        f.write(rapor_metni + "\n\n")

    # Telegram'a belge at
    await update.message.reply_document(
        document=open(filename, "rb"),
        filename=filename,
        caption=f"🏁 **{tarih} Gün Sonu Raporu Çıkarıldı ve Gün Kapatıldı!**\n💰 Toplam Kasa: **{toplam_c:,.0f} TL**",
        reply_markup=ReplyKeyboardRemove()
    )

    # Veritabanında günü sıfırla
    reset_db_day()
    if os.path.exists(filename):
        os.remove(filename)

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("İşlem iptal edildi.", reply_markup=ana_klavye())
    return ISLEM_SECIMI

# ------------------- MAIN -------------------

def main():
    TOKEN = "8898839173:AAG61BZ8R3RxCz3A29sDdCnYhSZwzETL5vE"
    
    app = ApplicationBuilder().token(TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('start', start)],
        states={
            GUN_BASI_DONER: [MessageHandler(filters.TEXT & ~filters.COMMAND, gun_basi_doner)],
            ISLEM_SECIMI: [
                MessageHandler(filters.Regex(r'^(s\s+\d+|p\s+\d+)$'), hizli_satis),
                MessageHandler(filters.TEXT & ~filters.COMMAND, islem_secimi)
            ],
            SALON_GIR: [MessageHandler(filters.TEXT & ~filters.COMMAND, salon_gir)],
            PAKET_GIR: [MessageHandler(filters.TEXT & ~filters.COMMAND, paket_gir)],
            EKMEK_GIR: [MessageHandler(filters.TEXT & ~filters.COMMAND, ekmek_gir)],
            APERATIF_GIR: [MessageHandler(filters.TEXT & ~filters.COMMAND, aperatif_gir)],
        },
        fallbacks=[CommandHandler('cancel', cancel)]
    )

    app.add_handler(conv_handler)

    print("Devran Döner SQLite Destekli VIP Bot Çalışıyor...")
    app.run_polling()

if __name__ == '__main__':
    main()
