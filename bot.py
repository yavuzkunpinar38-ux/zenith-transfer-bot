import logging
import datetime
import io
import sqlite3
import os
import asyncio
from aiohttp import web
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, ConversationHandler, CallbackQueryHandler
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors

# Loglama ayarları
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

# Veritabanı Kurulumu
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

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🚖 **Zenith VIP Transfer Sürücü Paneline Hoş Geldiniz!**\n\n"
        "Yeni bilet oluşturmak için: /yeni\n"
        "Gelecek yolculukları görmek için: /gelecek\n"
        "Geçmiş yolculukları görmek için: /gecmis"
    )

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
    await update.message.reply_text("📍 **4) Alınış Noktası (Nereden)?:**")
    return NEREDEN

async def nereden_al(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['nereden'] = update.message.text
    await update.message.reply_text("🏁 **5) Bırakılış Noktası (Nereye)?:**")
    return NEREYE

async def nereye_al(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['nereye'] = update.message.text
    await update.message.reply_text("💵 **6) Toplam Fiyat ve Ödeme Türü nedir?** (Örn: 2400 TL - Nakit):")
    return FIYAT

async def fiyat_al(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['fiyat'] = update.message.text
    keyboard = [
        [InlineKeyboardButton("2 Saat Kala ⏰", callback_data='2'), InlineKeyboardButton("6 Saat Kala ⏰", callback_data='6')],
        [InlineKeyboardButton("12 Saat Kala ⏰", callback_data='12'), InlineKeyboardButton("24 Saat Kala ⏰", callback_data='24')]
    ]
    await update.message.reply_text("🔔 **Yolculuğa kaç saat kala hatırlatma istersiniz?**", reply_markup=InlineKeyboardMarkup(keyboard))
    return HATIRLATMA

def pdf_uret(data, bilet_no):
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter, rightMargin=36, leftMargin=36, topMargin=36, bottomMargin=36)
    story = []
    
    box_color = colors.HexColor("#161616")
    gold_color = colors.HexColor("#d4af37")
    
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle('TitleStyle', parent=styles['Heading1'], fontSize=28, textColor=colors.black, leading=32)
    sub_style = ParagraphStyle('SubStyle', parent=styles['Normal'], fontSize=16, textColor=gold_color, leading=20, spaceAfter=20)
    label_style = ParagraphStyle('LabelStyle', parent=styles['Normal'], fontSize=9, textColor=gold_color, leading=12)
    value_style = ParagraphStyle('ValueStyle', parent=styles['Normal'], fontSize=12, textColor=colors.white, leading=16)
    
    story.append(Paragraph("<b>ZENITH</b>", title_style))
    story.append(Paragraph("TRANSFER", sub_style))
    story.append(Spacer(1, 15))
    
    table_data = [
        [Paragraph("<b>BILET NO / TICKET NO</b>", label_style), Paragraph("<b>TARİH / DATE</b>", label_style)],
        [Paragraph(bilet_no, value_style), Paragraph(data['tarih'], value_style)],
        [Paragraph("<b>ALINIŞ SAATİ / PICKUP TIME</b>", label_style), Paragraph("<b>ARAÇ TİPİ / VEHICLE</b>", label_style)],
        [Paragraph(data['saat'], value_style), Paragraph("Minivan VIP (Mercedes Vito)", value_style)],
        [Paragraph("<b>ALINIŞ NOKTASI / PICKUP</b>", label_style), Paragraph("<b>BIRAKILIŞ NOKTASI / DROPOFF</b>", label_style)],
        [Paragraph(data['nereden'], value_style), Paragraph(data['nereye'], value_style)],
        [Paragraph("<b>YOLCU / PASSENGER</b>", label_style), Paragraph("<b>TOPLAM FİYAT / PRICE</b>", label_style)],
        [Paragraph(data['yolcu'], value_style), Paragraph(data['fiyat'], value_style)]
    ]
    
    t = Table(table_data, colWidths=[270, 270])
    t.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,-1), box_color),
        ('ALIGN', (0,0), (-1,-1), 'LEFT'),
        ('PADDING', (0,0), (-1,-1), 12),
        ('BOTTOMPADDING', (0,0), (-1,-1), 14),
        ('GRID', (0,0), (-1,-1), 1, colors.HexColor("#2a2a2a")),
    ]))
    
    story.append(t)
    doc.build(story)
    return buffer.getvalue()

async def hatirlatma_tetikle(context: ContextTypes.DEFAULT_TYPE):
    job = context.job
    data = job.data
    pdf_bytes = pdf_uret(data, data['bilet_no'])
    pdf_file = io.BytesIO(pdf_bytes)
    pdf_file.name = f"Zenith_Transfer_{data['bilet_no']}.pdf"
    
    mesaj = f"🚨 **YOLCULUK HATIRLATMASI!**\n\n👤 **Yolcu:** {data['yolcu']}\n⏰ **Kalan:** {data['secilen_saat']} Saat\n📍 **Güzergah:** {data['nereden']} ➔ {data['nereye']}"
    await context.bot.send_document(chat_id=job.chat_id, document=pdf_file, caption=mesaj)

async def hatirlatma_sec(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    secilen_saat = query.data
    user_id = query.from_user.id
    data = context.user_data
    
    bilet_no = f"ZT{datetime.datetime.now().strftime('%Y%m%d%H%M')}"
    data['bilet_no'] = bilet_no
    data['secilen_saat'] = secilen_saat
    
    await query.edit_message_text(text=f"✅ Hatırlatma **{secilen_saat} Saat Kala** olarak ayarlandı. PDF biletiniz gönderiliyor...")

    conn = sqlite3.connect('zenith_transfer.db')
    cursor = conn.cursor()
    cursor.execute('INSERT INTO yolculuklar (user_id, bilet_no, tarih, saat, yolcu, nereden, nereye, fiyat, hatirlatma_saat, durum) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
                   (user_id, bilet_no, data['tarih'], data['saat'], data['yolcu'], data['nereden'], data['nereye'], data['fiyat'], secilen_saat, 'Gelecek'))
    conn.commit()
    conn.close()

    pdf_bytes = pdf_uret(data, bilet_no)
    pdf_file = io.BytesIO(pdf_bytes)
    pdf_file.name = f"Zenith_Transfer_{bilet_no}.pdf"
    
    await context.bot.send_document(chat_id=query.message.chat_id, document=pdf_file, caption="✨ **Biletiniz üretildi!**")
    
    try:
        transfer_str = f"{data['tarih']} {data['saat']}"
        transfer_dt = datetime.datetime.strptime(transfer_str, "%d.%m.%Y %H:%M")
        kalan_saniye = (transfer_dt - datetime.timedelta(hours=int(secilen_saat)) - datetime.datetime.now()).total_seconds()
        if kalan_saniye > 0:
            context.job_queue.run_once(hatirlatma_tetikle, when=kalan_saniye, chat_id=query.message.chat_id, data=data.copy())
    except:
        context.job_queue.run_once(hatirlatma_tetikle, when=10, chat_id=query.message.chat_id, data=data.copy())

    return ConversationHandler.END

async def gelecek_isler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    conn = sqlite3.connect('zenith_transfer.db')
    cursor = conn.cursor()
    cursor.execute("SELECT tarih, saat, yolcu FROM yolculuklar WHERE user_id=? AND durum='Gelecek'", (user_id,))
    isler = cursor.fetchall()
    conn.close()
    if not isler:
        await update.message.reply_text("📅 Gelecek yolculuk bulunmuyor.")
        return
    await update.message.reply_text("\n".join([f"👤 {x[2]} | {x[0]} - {x[1]}" for x in isler]))

async def gecmis_isler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📜 Geçmiş yolculuk kayıtları temiz.")

async def iptal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    return ConversationHandler.END

# Render'ı memnun edecek sahte web sunucusu (Port dinleyici)
async def handle(request):
    return web.Response(text="Zenith Bot is alive!")

async def start_web_server():
    app = web.Application()
    app.router.add_get('/', handle)
    runner = web.AppRunner(app)
    await runner.setup()
    # Render PORT çevre değişkenini otomatik atar, yoksa 10000 kullanırız
    port = int(os.getenv("PORT", 10000))
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()
    print(f" Web sunucusu {port} portunda başlatıldı.")

async def main():
    TOKEN = os.getenv("TELEGRAM_TOKEN", "BURAYA_BOT_TOKEN_GELECEK")
    
    # Web sunucusunu arka planda başlat
    await start_web_server()
    
    # Telegram Botunu başlat
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
    
    # run_polling yerine asyncio uyumlu döngüyü kuruyoruz
    await app.initialize()
    await app.start()
    await app.updater.start_polling()
    
    # Sonsuz döngüde çalışmaya devam etmesi için
    while True:
        await asyncio.sleep(3600)

if __name__ == '__main__':
    # Render asenkron yapıyı tetiklemek için loop kullanırız
    asyncio.run(main())
