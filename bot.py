import logging
import datetime
import io
import sqlite3
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, ConversationHandler, CallbackQueryHandler
import weasyprint

# Loglama ayarları
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

# Veritabanı Kurulumu (Geçmiş ve Gelecek Yolculuklar İçin)
def db_kur():
    conn = sqlite3.connect('zenith_transfer.db')
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS yolculuklar (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            bilet_no TEXT,
            tarih TEXT,
            saat TEXT,
            yolcu TEXT,
            nereden TEXT,
            nereye TEXT,
            fiyat TEXT,
            hatirlatma_saat TEXT,
            durum TEXT
        )
    ''')
    conn.commit()
    conn.close()

db_kur()

# Durum Tanımlamaları
TARIH, SAAT, YOLCU, NEREDEN, NEREYE, FIYAT, HATIRLATMA = range(7)

# Komut: /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🚖 **Zenith VIP Transfer Sürücü Paneline Hoş Geldiniz!**\n\n"
        "Yeni bilet oluşturmak için: /yeni\n"
        "Gelecek yolculukları görmek için: /gelecek\n"
        "Geçmiş yolculukları görmek için: /gecmis"
    )

# Komut: /yeni (Soru-Cevap Başlangıcı)
async def yeni_rezervasyon(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📅 **1) Lütfen Transfer Tarihini girin** (Örn: 28.06.2026):")
    return TARIH

async def tarih_al(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['tarih'] = update.message.text
    await update.message.reply_text("⏰ **2) Alınış Saati kaçtır?** (Örn: 14:30):")
    return SAAT

async def saat_al(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['saat'] = update.message.text
    await update.message.reply_text("👤 **3) Yolcu Adı Soyadı nedir?:**")
    return YOLCU

async def yolcu_al(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['yolcu'] = update.message.text
    await update.message.reply_text("📍 **4) Alınış Noktası (Nereden)?:**\n(Örn: Antalya Havalimanı T1)")
    return NEREDEN

async def nereden_al(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['nereden'] = update.message.text
    await update.message.reply_text("🏁 **5) Bırakılış Noktası (Nereye)?:**\n(Örn: Alanya Blue Marlin Otel)")
    return NEREYE

async def nereye_al(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['nereye'] = update.message.text
    await update.message.reply_text("💵 **6) Toplam Fiyat ve Ödeme Türü nedir?**\n(Örn: 2.400 TRY - Nakit)")
    return FIYAT

async def fiyat_al(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['fiyat'] = update.message.text
    
    # Seçenek Butonları
    keyboard = [
        [InlineKeyboardButton("24 Saat Kala ⏰", callback_data='24'),
         InlineKeyboardButton("12 Saat Kala ⏰", callback_data='12')],
        [InlineKeyboardButton("6 Saat Kala ⏰", callback_data='6'),
         InlineKeyboardButton("2 Saat Kala ⏰", callback_data='2')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("🔔 **Yolculuğa kaç saat kala hatırlatma bildirimi ve PDF biletin tekrar gelmesini istersiniz?**", reply_markup=reply_markup)
    return HATIRLATMA

# PDF Üretme Fonksiyonu
def pdf_uret(data, bilet_no):
    html_template = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <style>
            @page {{ size: A4; margin: 0; background-color: #0b0b0b; }}
            body {{ margin: 0; padding: 0; background-color: #0b0b0b; color: #ffffff; -webkit-print-color-adjust: exact; font-family: Arial, sans-serif; }}
            .page-container {{ width: 210mm; height: 297mm; padding: 20mm 15mm; position: relative; }}
            .bg-accent-1 {{ position: absolute; top: 0; right: 0; width: 120mm; height: 60mm; background: linear-gradient(135deg, rgba(212, 175, 55, 0.15) 0%, rgba(0,0,0,0) 80%); z-index: 1; clip-path: polygon(0 0, 100% 0, 100% 100%, 40% 100%); }}
            .content {{ position: relative; z-index: 10; }}
            .header-table {{ width: 100%; border-collapse: collapse; margin-bottom: 25px; }}
            .logo-text-main {{ font-size: 28pt; font-weight: 800; letter-spacing: 2px; color: #ffffff; line-height: 1; margin: 0; }}
            .logo-text-sub {{ font-size: 18pt; font-weight: 400; letter-spacing: 6px; color: #d4af37; line-height: 1; margin: 4px 0 0 0; }}
            .ticket-cell {{ text-align: right; vertical-align: middle; }}
            .ticket-value {{ font-size: 14pt; font-weight: bold; color: #d4af37; }}
            .info-table {{ width: 100%; border-collapse: separate; border-spacing: 10px; margin-bottom: 10px; }}
            .info-box {{ background-color: #161616; border: 1px solid #2a2a2a; border-radius: 6px; padding: 12px 15px; }}
            .box-label {{ font-size: 8pt; color: #d4af37; text-transform: uppercase; font-weight: 600; margin-bottom: 5px; }}
            .box-value {{ font-size: 11pt; color: #ffffff; }}
            .full-box {{ background-color: #161616; border: 1px solid #2a2a2a; border-radius: 6px; padding: 14px 18px; margin: 0 10px 15px 10px; }}
            .price-box {{ background: linear-gradient(135deg, #d4af37 0%, #aa841c 100%); border-radius: 6px; padding: 15px 20px; }}
            .price-box .box-label {{ color: #000000; font-weight: 700; }}
            .price-box .box-value {{ color: #000000; font-size: 16pt; font-weight: 800; }}
            .company-notes {{ margin: 30px 10px 0 10px; border-top: 1px solid #2a2a2a; padding-top: 15px; font-size: 8.5pt; color: #666666; }}
        </style>
    </head>
    <body>
        <div class="page-container">
            <div class="bg-accent-1"></div>
            <div class="content">
                <table class="header-table">
                    <tr>
                        <td>
                            <div class="logo-text-main">ZENITH</div>
                            <div class="logo-text-sub">TRANSFER</div>
                        </td>
                        <td class="ticket-cell">
                            <div class="ticket-value">{bilet_no}</div>
                        </td>
                    </tr>
                </table>
                <table class="info-table">
                    <tr>
                        <td class="info-box" style="width: 33%;">
                            <div class="box-label">TARİH / DATE</div>
                            <div class="box-value">{data['tarih']}</div>
                        </td>
                        <td class="info-box" style="width: 33%;">
                            <div class="box-label">ALINIŞ SAATİ / PICKUP TIME</div>
                            <div class="box-value">{data['saat']}</div>
                        </td>
                        <td class="info-box" style="width: 34%;">
                            <div class="box-label">ARAÇ TİPİ / VEHICLE</div>
                            <div class="box-value">Minivan VIP (Mercedes Vito)</div>
                        </td>
                    </tr>
                </table>
                <table class="info-table">
                    <tr>
                        <td class="info-box" style="width: 50%;">
                            <div class="box-label">ALINIŞ NOKTASI / PICKUP POINT</div>
                            <div class="box-value">{data['nereden']}</div>
                        </td>
                        <td class="info-box" style="width: 50%;">
                            <div class="box-label">BIRAKILIŞ NOKTASI / DROPOFF POINT</div>
                            <div class="box-value">{data['nereye']}</div>
                        </td>
                    </tr>
                </table>
                <div class="full-box">
                    <div class="box-label">YOLCULAR / PASSENGERS</div>
                    <div style="font-size: 11pt;">1. {data['yolcu']}</div>
                </div>
                <table class="info-table">
                    <tr>
                        <td class="price-box" style="width: 50%;">
                            <div class="box-label">TOPLAM FİYAT / TOTAL PRICE</div>
                            <div class="box-value">{data['fiyat']}</div>
                        </td>
                        <td class="info-box" style="width: 50%;">
                            <div class="box-label">DURUM / STATUS</div>
                            <div class="box-value" style="color: #00ff00; font-weight: bold;">Onaylandı</div>
                        </td>
                    </tr>
                </table>
                <div class="company-notes">
                    * Önemli Not: Havalimanı karşılamalarında uçuş takibi canlı olarak yapılmaktadır. Sürücünüz sizi terminal çıkışında Zenith Transfer tabelası ile karşılayacaktır.
                </div>
            </div>
        </div>
    </body>
    </html>
    """
    return weasyprint.HTML(string=html_template).write_pdf()

# Dinamik Hatırlatma Bildirimi Tetikleyicisi
async def hatirlatma_tetikle(context: ContextTypes.DEFAULT_TYPE):
    job = context.job
    data = job.data
    
    pdf_bytes = pdf_uret(data, data['bilet_no'])
    pdf_file = io.BytesIO(pdf_bytes)
    pdf_file.name = f"Zenith_Transfer_{data['bilet_no']}.pdf"
    
    mesaj = (
        f"🚨 **YOLCULUK HATIRLATMASI!**\n\n"
        f"👤 **Yolcu:** {data['yolcu']}\n"
        f"⏰ **Kalan Süre:** {data['secilen_saat']} Saat\n"
        f"📍 **Güzergah:** {data['nereden']} ➔ {data['nereye']}\n\n"
        f"⚠️ Yolcunun alınmasına {data['secilen_saat']} saat kalmıştır! Güncel bilet dosyası aşağıdadır."
    )
    await context.bot.send_document(chat_id=job.chat_id, document=pdf_file, caption=mesaj)

# Hatırlatma Süresi Seçildiğinde Çalışan Kısım
async def hatirlatma_sec(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    secilen_saat = query.data
    user_id = query.from_user.id
    
    data = context.user_data
    bilet_no = f"ZT{datetime.datetime.now().strftime('%Y%m%d%H%M')}"
    data['bilet_no'] = bilet_no
    data['secilen_saat'] = secilen_saat
    
    await query.edit_message_text(text=f"✅ Hatırlatma süresi **{secilen_saat} Saat Kala** olarak başarıyla kaydedildi. PDF biletiniz hazırlanıyor...")

    # Veritabanına Kaydetme (Gelecek Yolculuk Olarak)
    conn = sqlite3.connect('zenith_transfer.db')
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO yolculuklar (user_id, bilet_no, tarih, saat, yolcu, nereden, nereye, fiyat, hatirlatma_saat, durum)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (user_id, bilet_no, data['tarih'], data['saat'], data['yolcu'], data['nereden'], data['nereye'], data['fiyat'], secilen_saat, 'Gelecek'))
    conn.commit()
    conn.close()

    # İlk PDF üretimini yapıp şoföre anında gönderme
    pdf_bytes = pdf_uret(data, bilet_no)
    pdf_file = io.BytesIO(pdf_bytes)
    pdf_file.name = f"Zenith_Transfer_{bilet_no}.pdf"
    
    await context.bot.send_document(
        chat_id=query.message.chat_id, 
        document=pdf_file, 
        caption=f"✨ **Biletiniz başarıyla üretildi!**\n\nMüşteriye iletmek için yukarıdaki PDF'i paylaşabilirsiniz.\n\nSeçtiğiniz üzere yolculuğa **{secilen_saat} saat kala** bu PDF size otomatik olarak tekrar hatırlatılacaktır."
    )
    
    # Zamanlayıcıyı Kurma (Simülasyon/Gerçek zamanlı hesaplama için altyapı)
    # Testleri hızlı görebilmek adına buraya gerçek zamanlama yerine job kuyruğu altyapısı entegre edilmiştir.
    try:
        transfer_str = f"{data['tarih']} {data['saat']}"
        transfer_dt = datetime.datetime.strptime(transfer_str, "%d.%m.%Y %H:%M")
        hatirlatma_dt = transfer_dt - datetime.timedelta(hours=int(secilen_saat))
        su_an = datetime.datetime.now()
        
        kalan_saniye = (hatirlatma_dt - su_an).total_seconds()
        if kalan_saniye > 0:
            context.job_queue.run_once(hatirlatma_tetikle, when=kalan_saniye, chat_id=query.message.chat_id, data=data.copy())
    except Exception as e:
        # Tarih formatı hatalıysa koruma amaçlı 10 saniye sonra test amaçlı tetikler
        context.job_queue.run_once(hatirlatma_tetikle, when=10, chat_id=query.message.chat_id, data=data.copy())

    return ConversationHandler.END

# Komut: /gelecek (Şoförün Yaklaşan İşleri)
async def gelecek_isler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    conn = sqlite3.connect('zenith_transfer.db')
    cursor = conn.cursor()
    cursor.execute("SELECT tarih, saat, yolcu, nereden, nereye, fiyat FROM yolculuklar WHERE user_id=? AND durum='Gelecek' ORDER BY id DESC", (user_id,))
    isler = cursor.fetchall()
    conn.close()
    
    if not isler:
        await update.message.reply_text("📅 Planlanmış gelecek bir yolculuğunuz bulunmuyor.")
        return
        
    mesaj = "📅 **GELECEK YOLCULUKLARINIZ**\n\n"
    for i, is_ in enumerate(isler, 1):
        mesaj += f"{i}) 👤 {is_[2]} | 📅 {is_[0]} - {is_[1]}\n📍 {is_[3]} ➔ {is_[4]}\n💵 {is_[5]}\n\n"
    await update.message.reply_text(mesaj)

# Komut: /gecmis (Şoförün Tamamlanan Eski İşleri)
async def gecmis_isler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    conn = sqlite3.connect('zenith_transfer.db')
    cursor = conn.cursor()
    # Test kolaylığı için verileri listeliyoruz, sistem çalıştıkça tamamlananlar buraya düşecek
    cursor.execute("SELECT tarih, saat, yolcu, nereden, nereye, fiyat FROM yolculuklar WHERE user_id=? ORDER BY id ASC", (user_id,))
    isler = cursor.fetchall()
    conn.close()
    
    if not isler:
        await update.message.reply_text("📜 Henüz geçmiş bir yolculuk kaydınız bulunmuyor.")
        return
        
    mesaj = "📜 **GEÇMİŞ YOLCULUK KAYITLARI**\n\n"
    for i, is_ in enumerate(isler, 1):
        mesaj += f"{i}) 👤 {is_[2]} | 📅 {is_[0]}\n🏁 {is_[3]} -> {is_[4]} | 💵 {is_[5]}\n\n"
    await update.message.reply_text(mesaj)

async def iptal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ İşlem şoför tarafından iptal edildi.")
    return ConversationHandler.END

def main():
    import os
    # Render üzerinde ortam değişkenlerinden tokenı çekeceğiz, güvenlik için en doğrusu budur
    TOKEN = os.getenv("TELEGRAM_TOKEN", "BURAYA_BOT_TOKEN_GELECEK")
    
    app = Application.builder().token(TOKEN).build()
    
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("yeni", yeni_rezervasyon)],
        states={
            TARIH: [MessageHandler(filters.TEXT & ~filters.COMMAND, tarih_al)],
            SAAT: [MessageHandler(filters.TEXT & ~filters.COMMAND, saat_al)],
            YOLCU: [MessageHandler(filters.TEXT & ~filters.COMMAND, yolcu_al)],
            NEREDEN: [MessageHandler(filters.TEXT & ~filters.COMMAND, nereden_al)],
            NEREYE: [MessageHandler(filters.TEXT & ~filters.COMMAND, nereye_al)],
            FIYAT: [MessageHandler(filters.TEXT & ~filters.COMMAND, fiyat_al)],
            HATIRLATMA: [CallbackQueryHandler(hatirlatma_sec)]
        },
        fallbacks=[CommandHandler("iptal", iptal)]
    )
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("gelecek", gelecek_isler))
    app.add_handler(CommandHandler("gecmis", gecmis_isler))
    app.add_handler(conv_handler)
    
    print("🚀 Zenith VIP Telegram Botu Çalışıyor...")
    app.run_polling()

if __name__ == '__main__':
    main()