import logging
import sqlite3
import os
import asyncio
from datetime import datetime
from threading import Thread
from flask import Flask
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes
)

# Render Port Ayarı (7/24 Aktif Web Server)
flask_app = Flask('')

@flask_app.route('/')
def home():
    return "Devran Döner Bot 7/24 Aktif!"

def run_flask():
    flask_app.run(host='0.0.0.0', port=8080)

def keep_alive():
    t = Thread(target=run_flask)
    t.daemon = True
    t.start()

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

DB_DOSYASI = "devran_doner.db"
ARSIV_DOSYASI = "devran_doner_tum_arsiv.txt"

def get_db_connection():
    conn = sqlite3.connect(DB_DOSYASI, timeout=15)
    conn.execute("PRAGMA journal_mode=WAL;")
    return conn

def init_db():
    conn = get_db_connection()
    c = conn.cursor()
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
            aktif_gun INTEGER DEFAULT 0,
            beklenen_islem TEXT DEFAULT NULL
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS personel_yemek (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            isim TEXT,
            porsiyon INTEGER
        )
    ''')
    c.execute("INSERT OR IGNORE INTO gunluk_durum (id, beklenen_islem) VALUES (1, NULL)")
    conn.commit()
    conn.close()

def get_veri():
    conn = get_db_connection()
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

def update_db(query, params=()):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute(query, params)
    conn.commit()
    conn.close()

init_db()

def ana_klavye():
    keyboard = [
        ["🍽 Salon Satışı", "📦 Paket Satışı"],
        ["🥖 Fırın Ekmek Ekle", "🥪 Personel Yemeği"],
        ["📊 Anlık Rapor", "🔴 Gün Sonu Kapat"]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    v = get_veri()
    update_db("UPDATE gunluk_durum SET beklenen_islem = NULL WHERE id = 1")
    
    if v['aktif_gun'] == 1:
        await update.message.reply_text(
            f"⚡️ *Günlük takip zaten aktif!* ({v['tarih']})\nAşağıdaki menüden işlem yapabilirsiniz.",
            reply_markup=ana_klavye(),
            parse_mode='Markdown'
        )
        return

    await update.message.reply_text(
        "👋 *Devran Döner Yönetim Botuna Hoş Geldiniz!*\n\n"
        "☀️ Yeni günü başlatmak için bugün takılan *Döner Kilosunu (kg)* giriniz:\n"
        "*(Örn: 25.5 veya 30)*",
        reply_markup=ReplyKeyboardRemove(),
        parse_mode='Markdown'
    )
    update_db("UPDATE gunluk_durum SET beklenen_islem = 'gun_basi' WHERE id = 1")

async def gun_sonu_kapat_komut(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await gun_sonu_kapat(update)

async def mesaj_yoneticisi(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    v = get_veri()
    bekleyen = v.get('beklenen_islem')

    # Esnek ve hızlı buton algılama
    if "salon satışı" in text.lower():
        update_db("UPDATE gunluk_durum SET beklenen_islem = 'salon' WHERE id = 1")
        await update.message.reply_text("🍽 Kaç adet *SALON* satışı yapıldı? (Sadece sayı girin)", reply_markup=ana_klavye(), parse_mode='Markdown')
        return
    elif "paket satışı" in text.lower():
        update_db("UPDATE gunluk_durum SET beklenen_islem = 'paket' WHERE id = 1")
        await update.message.reply_text("📦 Kaç adet *PAKET* satışı yapıldı? (Sadece sayı girin)", reply_markup=ana_klavye(), parse_mode='Markdown')
        return
    elif "fırın ekmek ekle" in text.lower():
        update_db("UPDATE gunluk_durum SET beklenen_islem = 'ekmek' WHERE id = 1")
        await update.message.reply_text("🥖 Fırından gelen *Ekmek Adedini* giriniz:", reply_markup=ana_klavye(), parse_mode='Markdown')
        return
    elif "personel yemeği" in text.lower():
        update_db("UPDATE gunluk_durum SET beklenen_islem = 'personel' WHERE id = 1")
        await update.message.reply_text("🥪 Personel yemeği formatı: *[İsim] [Adet]*\n*(Örn: Ahmet 2)*", reply_markup=ana_klavye(), parse_mode='Markdown')
        return
    elif "anlık rapor" in text.lower():
        await anlik_rapor_gonder(update)
        return
    elif "gün sonu kapat" in text.lower():
        await gun_sonu_kapat(update)
        return

    # Hızlı Satış Komutları (s 5 / p 3)
    parcalar = text.lower().split()
    if len(parcalar) == 2 and parcalar[0] in ['s', 'p']:
        try:
            adet = int(parcalar[1])
            if parcalar[0] == 's':
                update_db("UPDATE gunluk_durum SET salon_adet = salon_adet + ? WHERE id = 1", (adet,))
                guncel = get_veri()
                await update.message.reply_text(f"⚡️ Hızlı Eklendi: *{adet} Salon*\nToplam Salon: *{guncel['salon_adet']} Adet*", reply_markup=ana_klavye(), parse_mode='Markdown')
            elif parcalar[0] == 'p':
                update_db("UPDATE gunluk_durum SET paket_adet = paket_adet + ? WHERE id = 1", (adet,))
                guncel = get_veri()
                await update.message.reply_text(f"⚡️ Hızlı Eklendi: *{adet} Paket*\nToplam Paket: *{guncel['paket_adet']} Adet*", reply_markup=ana_klavye(), parse_mode='Markdown')
            return
        except ValueError:
            pass

    # Beklenen İşlem Girişleri
    if bekleyen == 'gun_basi':
        try:
            kilo = float(text.replace(',', '.'))
            tarih_str = datetime.now().strftime("%d.%m.%Y")
            update_db('''
                UPDATE gunluk_durum SET 
                    baslangic_kilo = ?, ekmek_adet = 0, salon_adet = 0, 
                    paket_adet = 0, tarih = ?, aktif_gun = 1, beklenen_islem = NULL 
                WHERE id = 1
            ''', (kilo, tarih_str))
            update_db("DELETE FROM personel_yemek")
            await update.message.reply_text(
                f"✅ *Gün Başlatıldı!*\n📅 Tarih: {tarih_str}\n🥩 Takılan Döner: *{kilo} kg*\n\n"
                "İşlem yapmak için aşağıdaki menüyü kullanabilirsiniz.",
                reply_markup=ana_klavye(), parse_mode='Markdown'
            )
        except ValueError:
            await update.message.reply_text("❌ Lütfen geçerli bir sayı giriniz (Örn: 25 veya 25.5):")
        return

    elif bekleyen == 'salon':
        try:
            adet = int(text)
            update_db("UPDATE gunluk_durum SET salon_adet = salon_adet + ?, beklenen_islem = NULL WHERE id = 1", (adet,))
            guncel = get_veri()
            await update.message.reply_text(
                f"✅ *{adet} Adet Salon Satışı Eklendi.*\n📊 Toplam Salon: *{guncel['salon_adet']} Adet* ({guncel['salon_adet'] * guncel['salon_fiyat']:.0f} TL)",
                reply_markup=ana_klavye(), parse_mode='Markdown'
            )
        except ValueError:
            await update.message.reply_text("❌ Lütfen geçerli bir sayı giriniz:")
        return

    elif bekleyen == 'paket':
        try:
            adet = int(text)
            update_db("UPDATE gunluk_durum SET paket_adet = paket_adet + ?, beklenen_islem = NULL WHERE id = 1", (adet,))
            guncel = get_veri()
            await update.message.reply_text(
                f"✅ *{adet} Adet Paket Satışı Eklendi.*\n📊 Toplam Paket: *{guncel['paket_adet']} Adet* ({guncel['paket_adet'] * guncel['paket_fiyat']:.0f} TL)",
                reply_markup=ana_klavye(), parse_mode='Markdown'
            )
        except ValueError:
            await update.message.reply_text("❌ Lütfen geçerli bir sayı giriniz:")
        return

    elif bekleyen == 'ekmek':
        try:
            adet = int(text)
            update_db("UPDATE gunluk_durum SET ekmek_adet = ekmek_adet + ?, beklenen_islem = NULL WHERE id = 1", (adet,))
            guncel = get_veri()
            await update.message.reply_text(
                f"✅ *{adet} Adet Ekmek Eklendi.*\n🥖 Toplam Fırın Ekmeği: *{guncel['ekmek_adet']} Adet*",
                reply_markup=ana_klavye(), parse_mode='Markdown'
            )
        except ValueError:
            await update.message.reply_text("❌ Lütfen geçerli bir sayı giriniz:")
        return

    elif bekleyen == 'personel':
        try:
            p = text.strip().split()
            isim = " ".join(p[:-1])
            adet = int(p[-1])
            update_db("INSERT INTO personel_yemek (isim, porsiyon) VALUES (?, ?)", (isim, adet))
            update_db("UPDATE gunluk_durum SET beklenen_islem = NULL WHERE id = 1")
            await update.message.reply_text(
                f"✅ *{isim}* için *{adet} porsiyon* yemek kaydedildi.",
                reply_markup=ana_klavye(), parse_mode='Markdown'
            )
        except Exception:
            await update.message.reply_text("❌ Hatalı format! Örnek format: *Ahmet 2*", reply_markup=ana_klavye(), parse_mode='Markdown')
        return

    await update.message.reply_text("Lütfen aşağıdaki menüden bir işlem seçin:", reply_markup=ana_klavye())

async def anlik_rapor_gonder(update: Update):
    v = get_veri()
    s_adet = v["salon_adet"]
    p_adet = v["paket_adet"]
    s_tutar = s_adet * v["salon_fiyat"]
    p_tutar = p_adet * v["paket_fiyat"]
    toplam_c = s_tutar + p_tutar
    toplam_porsiyon = s_adet + p_adet
    tarih = v.get('tarih', 'Bugün')

    rapor = f"📊 *DEVRAN DÖNER - ANLIK RAPOR ({tarih})*\n"
    rapor += f"-----------------------------------\n"
    rapor += f"🥩 Takılan Döner: *{v['baslangic_kilo']} kg*\n"
    rapor += f"🥖 Gelen Ekmek: *{v['ekmek_adet']} adet*\n\n"
    rapor += f"🍽 Salon Satışı: *{s_adet} adet* ({s_tutar:,.0f} TL)\n"
    rapor += f"📦 Paket Satışı: *{p_adet} adet* ({p_tutar:,.0f} TL)\n"
    rapor += f"-----------------------------------\n"
    rapor += f"📈 Toplam Satılan: *{toplam_porsiyon} porsiyon*\n"
    rapor += f"💰 *TOPLAM KASA: {toplam_c:,.0f} TL*\n"
    
    if v['personel']:
        rapor += f"\n🥪 *Personel Yemekleri:*\n"
        for p_isim, p_adet in v['personel'].items():
            rapor += f"  • {p_isim}: {p_adet} porsiyon\n"

    await update.message.reply_text(rapor, reply_markup=ana_klavye(), parse_mode='Markdown')

async def gun_sonu_kapat(update: Update):
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

    filename = f"gun_sonu_{tarih.replace('.', '_')}.txt"
    with open(filename, "w", encoding="utf-8") as f:
        f.write(rapor_metni)
        
    with open(ARSIV_DOSYASI, "a", encoding="utf-8") as f:
        f.write(rapor_metni + "\n\n")

    with open(filename, "rb") as doc_file:
        await update.message.reply_document(
            document=doc_file,
            filename=filename,
            caption=f"🏁 *{tarih} Gün Sonu Raporu Çıkarıldı ve Gün Kapatıldı!*\n💰 Toplam Kasa: *{toplam_c:,.0f} TL*",
            reply_markup=ana_klavye(),
            parse_mode='Markdown'
        )

    update_db('''
        UPDATE gunluk_durum SET 
            baslangic_kilo = 0, ekmek_adet = 0, salon_adet = 0, 
            paket_adet = 0, tarih = '', aktif_gun = 0, beklenen_islem = NULL 
        WHERE id = 1
    ''')
    update_db("DELETE FROM personel_yemek")
    
    if os.path.exists(filename):
        os.remove(filename)

def main():
    keep_alive()
    
    TOKEN = "8812573804:AAHkQqgBQUh68rdDP-M2RSmPEWBuHXBFd6c"
    
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("gunsonu", gun_sonu_kapat_komut))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, mesaj_yoneticisi))

    print("Devran Döner Güvenli ve Hızlı Bot Çalışıyor...")
    app.run_polling()

if __name__ == '__main__':
    main()
