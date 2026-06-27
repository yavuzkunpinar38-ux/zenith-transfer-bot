import logging
import datetime
import io
import sqlite3
import os
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler, filters,
    ContextTypes, ConversationHandler, CallbackQueryHandler
)
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.utils import ImageReader
import textwrap

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ── Veritabanı ──────────────────────────────────────────────────────────────
def db_kur():
    conn = sqlite3.connect('zenith_transfer.db')
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS yolculuklar (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            chat_id INTEGER,
            bilet_no TEXT,
            tarih TEXT,
            saat TEXT,
            yolcu_sayisi TEXT,
            yolcular TEXT,
            nereden TEXT,
            nereye TEXT,
            ucus_kodu TEXT,
            arac_tipi TEXT,
            telefon TEXT,
            fiyat TEXT,
            odeme_turu TEXT,
            hatirlatma_saat TEXT,
            durum TEXT DEFAULT 'Bekliyor'
        )
    ''')
    conn.commit()
    conn.close()

db_kur()

# ── Konuşma Durumları ────────────────────────────────────────────────────────
(TARIH, SAAT, YOLCU_SAYISI, YOLCULAR, NEREDEN, NEREYE,
 UCUS_KODU, ARAC_TIPI, TELEFON, FIYAT, ODEME_TURU, HATIRLATMA) = range(12)

ARAC_SECENEKLERI = [
    "Sedan VIP (Mercedes E-Class)",
    "Minivan VIP (Mercedes Vito)",
    "Minibüs (Ford Transit)",
    "VIP SUV (Mercedes GLE)",
]

# ── PDF Üretici ──────────────────────────────────────────────────────────────
GOLD   = colors.HexColor("#D4AF37")
DARK   = colors.HexColor("#0B0B0B")
PANEL  = colors.HexColor("#161616")
BORDER = colors.HexColor("#2A2A2A")
WHITE  = colors.white
GREEN  = colors.HexColor("#00CC66")

def wrap_text(text, max_chars=35):
    """Uzun metni satır satır böler."""
    return "\n".join(textwrap.wrap(str(text), max_chars))

def draw_box(c_obj, x, y, w, h, label, value, label_color=GOLD,
             value_color=WHITE, bg=PANEL, value_size=11, wrap_at=30):
    """Tek bir bilgi kutusu çizer."""
    c_obj.setFillColor(bg)
    c_obj.roundRect(x, y, w, h, 4*mm, fill=1, stroke=0)
    c_obj.setStrokeColor(BORDER)
    c_obj.setLineWidth(0.5)
    c_obj.roundRect(x, y, w, h, 4*mm, fill=0, stroke=1)

    # Etiket
    c_obj.setFillColor(label_color)
    c_obj.setFont("Helvetica-Bold", 7)
    c_obj.drawString(x + 3*mm, y + h - 6*mm, label.upper())

    # Değer (otomatik satır kırma)
    c_obj.setFillColor(value_color)
    c_obj.setFont("Helvetica-Bold", value_size)
    lines = wrap_text(value, wrap_at).split("\n")
    line_h = (value_size + 2) * 0.352778 * mm
    text_y = y + h - 12*mm
    for ln in lines:
        if text_y > y + 2*mm:
            c_obj.drawString(x + 3*mm, text_y, ln)
            text_y -= line_h

def pdf_uret(data: dict, bilet_no: str) -> bytes:
    buf = io.BytesIO()
    w, h = A4          # 595 x 842 pt
    c_obj = canvas.Canvas(buf, pagesize=A4)

    # ── Arka Plan ──
    c_obj.setFillColor(DARK)
    c_obj.rect(0, 0, w, h, fill=1, stroke=0)

    # Altın köşe dekorasyonu
    c_obj.setFillColor(colors.HexColor("#1A1600"))
    from reportlab.graphics.shapes import Polygon
    # Sağ üst üçgen dekor
    p = c_obj.beginPath()
    p.moveTo(w * 0.45, h)
    p.lineTo(w, h)
    p.lineTo(w, h * 0.75)
    p.close()
    c_obj.drawPath(p, fill=1, stroke=0)

    # İnce altın çizgi
    c_obj.setStrokeColor(GOLD)
    c_obj.setLineWidth(1)
    c_obj.line(15*mm, h - 38*mm, w - 15*mm, h - 38*mm)

    # ── Header: Logo + Bilet No ──
    c_obj.setFillColor(WHITE)
    c_obj.setFont("Helvetica-Bold", 26)
    c_obj.drawString(15*mm, h - 22*mm, "ZENITH")
    c_obj.setFillColor(GOLD)
    c_obj.setFont("Helvetica", 16)
    c_obj.setCharSpace(5)
    c_obj.drawString(15*mm, h - 31*mm, "TRANSFER")
    c_obj.setCharSpace(0)

    # Bilet No
    c_obj.setFillColor(GOLD)
    c_obj.setFont("Helvetica-Bold", 10)
    c_obj.drawRightString(w - 15*mm, h - 22*mm, "BİLET NO / TICKET NO")
    c_obj.setFont("Helvetica-Bold", 14)
    c_obj.drawRightString(w - 15*mm, h - 30*mm, bilet_no)

    margin = 15*mm
    box_gap = 3*mm
    usable_w = w - 2*margin
    row_h = 22*mm
    y = h - 50*mm

    # ── Satır 1: Tarih | Saat | Yolcu Sayısı ──
    col_w = (usable_w - 2*box_gap) / 3
    draw_box(c_obj, margin,              y, col_w, row_h, "TARİH / DATE",        data.get('tarih',''))
    draw_box(c_obj, margin+col_w+box_gap, y, col_w, row_h, "ALINIŞ SAATİ / PICKUP TIME", data.get('saat',''))
    draw_box(c_obj, margin+2*(col_w+box_gap), y, col_w, row_h, "YOLCU SAYISI / PAX", data.get('yolcu_sayisi',''))
    y -= row_h + box_gap

    # ── Satır 2: Araç Tipi | Uçuş Kodu ──
    half_w = (usable_w - box_gap) / 2
    draw_box(c_obj, margin,          y, half_w, row_h, "ARAÇ TİPİ / VEHICLE",   data.get('arac_tipi',''), wrap_at=25)
    draw_box(c_obj, margin+half_w+box_gap, y, half_w, row_h, "UÇUŞ KODU / FLIGHT CODE", data.get('ucus_kodu','—'))
    y -= row_h + box_gap

    # ── Satır 3: Nereden | Nereye ──
    draw_box(c_obj, margin,          y, half_w, row_h, "ALINIŞ NOKTASI / PICKUP POINT",   data.get('nereden',''), wrap_at=25)
    draw_box(c_obj, margin+half_w+box_gap, y, half_w, row_h, "BIRAKILIŞ NOKTASI / DROPOFF POINT", data.get('nereye',''), wrap_at=25)
    y -= row_h + box_gap

    # ── Yolcular (tam genişlik, çok satır) ──
    yolcular_list = data.get('yolcular', '').strip().split('\n')
    pax_h = max(22*mm, len(yolcular_list) * 6*mm + 14*mm)
    draw_box(c_obj, margin, y, usable_w, pax_h, "YOLCULAR / PASSENGERS",
             data.get('yolcular', ''), wrap_at=60, value_size=10)
    y -= pax_h + box_gap

    # ── Satır 4: Telefon | E-posta ──
    draw_box(c_obj, margin,          y, half_w, row_h, "İLETİŞİM / PHONE", data.get('telefon','—'))
    draw_box(c_obj, margin+half_w+box_gap, y, half_w, row_h, "E-POSTA / E-MAIL", "info@zenithtransfer.com")
    y -= row_h + box_gap

    # ── Satır 5: Fiyat (altın bg) | Ödeme | Durum ──
    third_w = (usable_w - 2*box_gap) / 3
    # Fiyat kutusu — altın arka plan
    draw_box(c_obj, margin, y, third_w, row_h,
             "TOPLAM FİYAT / TOTAL PRICE", data.get('fiyat',''),
             label_color=DARK, value_color=DARK, bg=GOLD, value_size=13)
    draw_box(c_obj, margin+third_w+box_gap, y, third_w, row_h,
             "ÖDEME YÖNTEMİ / PAYMENT", data.get('odeme_turu',''), wrap_at=20)
    # Durum kutusu
    draw_box(c_obj, margin+2*(third_w+box_gap), y, third_w, row_h,
             "DURUM / STATUS", "Ödenmedi",
             value_color=colors.HexColor("#FF6B6B"))
    y -= row_h + box_gap + 5*mm

    # ── Dipnot ──
    c_obj.setStrokeColor(BORDER)
    c_obj.setLineWidth(0.5)
    c_obj.line(15*mm, y + 3*mm, w - 15*mm, y + 3*mm)
    c_obj.setFillColor(colors.HexColor("#666666"))
    c_obj.setFont("Helvetica", 7)
    note = ("* Önemli Not: Havalimanı karşılamalarında uçuş takibi canlı olarak yapılmaktadır. "
            "Uçağınızda rötar olması durumunda transfer saatiniz otomatik olarak güncellenir. "
            "Sürücünüz sizi terminal çıkışında Zenith Transfer tabelası ile karşılayacaktır. "
            "İptal veya değişiklik taleplerinizi lütfen en geç 12 saat önce bildiriniz.")
    lines = textwrap.wrap(note, 100)
    note_y = y - 2*mm
    for ln in lines:
        c_obj.drawString(15*mm, note_y, ln)
        note_y -= 4*mm

    c_obj.save()
    return buf.getvalue()


# ── Konuşma Adımları ─────────────────────────────────────────────────────────
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🚖 *Zenith VIP Transfer — Sürücü Paneli*\n\n"
        "📋 Yeni bilet: /yeni\n"
        "📅 Gelecek işler: /gelecek\n"
        "📜 Geçmiş kayıtlar: /gecmis\n"
        "❌ İptal: /iptal",
        parse_mode="Markdown"
    )

async def yeni_rezervasyon(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text(
        "📅 *1) Transfer Tarihini* girin:\n_(Örn: 28.06.2026)_",
        parse_mode="Markdown"
    )
    return TARIH

async def tarih_al(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['tarih'] = update.message.text.strip()
    await update.message.reply_text("⏰ *2) Alınış Saati:*\n_(Örn: 14:30)_", parse_mode="Markdown")
    return SAAT

async def saat_al(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['saat'] = update.message.text.strip()
    await update.message.reply_text("👥 *3) Yolcu Sayısı:*\n_(Örn: 2)_", parse_mode="Markdown")
    return YOLCU_SAYISI

async def yolcu_sayisi_al(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['yolcu_sayisi'] = update.message.text.strip()
    await update.message.reply_text(
        "👤 *4) Yolcu Ad Soyad(lar)ı:*\n"
        "_Her yolcuyu yeni satıra yazın. Tek yolcu ise sadece bir isim yazın._\n"
        "_(Örn:\nAli Yılmaz\nAyşe Yılmaz)_",
        parse_mode="Markdown"
    )
    return YOLCULAR

async def yolcular_al(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['yolcular'] = update.message.text.strip()
    await update.message.reply_text(
        "📍 *5) Alınış Noktası:*\n_(Örn: AYT - Antalya Havalimanı T2)_",
        parse_mode="Markdown"
    )
    return NEREDEN

async def nereden_al(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['nereden'] = update.message.text.strip()
    await update.message.reply_text(
        "🏁 *6) Bırakılış Noktası:*\n_(Örn: Alanya / Blue Marlin Deluxe Hotel)_",
        parse_mode="Markdown"
    )
    return NEREYE

async def nereye_al(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['nereye'] = update.message.text.strip()
    await update.message.reply_text(
        "✈️ *7) Uçuş Kodu:* _(varsa, yoksa — yazın)_\n_(Örn: PC5066)_",
        parse_mode="Markdown"
    )
    return UCUS_KODU

async def ucus_kodu_al(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['ucus_kodu'] = update.message.text.strip()
    keyboard = [[InlineKeyboardButton(a, callback_data=f"arac:{a}")] for a in ARAC_SECENEKLERI]
    await update.message.reply_text(
        "🚗 *8) Araç Tipini Seçin:*",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return ARAC_TIPI

async def arac_tipi_al(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data['arac_tipi'] = query.data.replace("arac:", "")
    await query.edit_message_text(
        f"✅ Araç: *{context.user_data['arac_tipi']}*\n\n"
        "📞 *9) İletişim Telefon Numarası:*\n_(Örn: +90 532 379 47 85)_",
        parse_mode="Markdown"
    )
    return TELEFON

async def telefon_al(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['telefon'] = update.message.text.strip()
    await update.message.reply_text(
        "💵 *10) Toplam Fiyat:*\n_(Örn: 2.400 TRY)_",
        parse_mode="Markdown"
    )
    return FIYAT

async def fiyat_al(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['fiyat'] = update.message.text.strip()
    keyboard = [
        [InlineKeyboardButton("💳 Kredi Kartı", callback_data="odeme:Kredi Kartı"),
         InlineKeyboardButton("💵 Nakit", callback_data="odeme:Nakit")],
        [InlineKeyboardButton("🚗 Araçta Ödeme", callback_data="odeme:Araçta Ödeme"),
         InlineKeyboardButton("🏦 Banka Transferi", callback_data="odeme:Banka Transferi")],
    ]
    await update.message.reply_text(
        "💳 *11) Ödeme Türü:*",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return ODEME_TURU

async def odeme_turu_al(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data['odeme_turu'] = query.data.replace("odeme:", "")
    keyboard = [
        [InlineKeyboardButton("24 Saat Kala ⏰", callback_data='hat:24'),
         InlineKeyboardButton("12 Saat Kala ⏰", callback_data='hat:12')],
        [InlineKeyboardButton("6 Saat Kala ⏰",  callback_data='hat:6'),
         InlineKeyboardButton("2 Saat Kala ⏰",  callback_data='hat:2')],
        [InlineKeyboardButton("Hatırlatma İstemiyorum", callback_data='hat:0')],
    ]
    await query.edit_message_text(
        "🔔 *12) Kaç saat kala hatırlatma gönderelim?*",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return HATIRLATMA


# ── Hatırlatma İşi ───────────────────────────────────────────────────────────
async def hatirlatma_tetikle(context: ContextTypes.DEFAULT_TYPE):
    job = context.job
    row_id, chat_id = job.data

    conn = sqlite3.connect('zenith_transfer.db')
    c = conn.cursor()
    c.execute("SELECT * FROM yolculuklar WHERE id=?", (row_id,))
    row = c.fetchone()
    conn.close()

    if not row:
        return

    cols = ['id','user_id','chat_id','bilet_no','tarih','saat','yolcu_sayisi',
            'yolcular','nereden','nereye','ucus_kodu','arac_tipi','telefon',
            'fiyat','odeme_turu','hatirlatma_saat','durum']
    data = dict(zip(cols, row))

    pdf_bytes = pdf_uret(data, data['bilet_no'])
    pdf_file = io.BytesIO(pdf_bytes)
    pdf_file.name = f"Zenith_{data['bilet_no']}.pdf"

    mesaj = (
        f"🚨 *YOLCULUK HATIRLATMASI!*\n\n"
        f"👤 *Yolcu(lar):* {data['yolcular']}\n"
        f"📅 *Tarih/Saat:* {data['tarih']} — {data['saat']}\n"
        f"📍 *Güzergah:* {data['nereden']} ➜ {data['nereye']}\n"
        f"✈️ *Uçuş:* {data.get('ucus_kodu','—')}\n"
        f"⏰ *Yolculuğa {data['hatirlatma_saat']} saat kaldı!*"
    )
    await context.bot.send_document(
        chat_id=chat_id,
        document=pdf_file,
        caption=mesaj,
        parse_mode="Markdown"
    )


def job_planla(app, row_id: int, chat_id: int, data: dict, secilen_saat: str):
    """Hatırlatma zamanı hesaplayıp job kuyruğuna ekler."""
    if secilen_saat == '0':
        return
    try:
        transfer_dt = datetime.datetime.strptime(
            f"{data['tarih']} {data['saat']}", "%d.%m.%Y %H:%M"
        )
        hatirlatma_dt = transfer_dt - datetime.timedelta(hours=int(secilen_saat))
        kalan = (hatirlatma_dt - datetime.datetime.now()).total_seconds()
        if kalan > 0:
            app.job_queue.run_once(
                hatirlatma_tetikle,
                when=kalan,
                chat_id=chat_id,
                data=(row_id, chat_id),
                name=f"hat_{row_id}"
            )
            logger.info(f"Hatırlatma planlandı: {kalan:.0f} sn sonra (row={row_id})")
    except Exception as e:
        logger.error(f"Hatırlatma planlanamadı: {e}")


async def hatirlatma_sec(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    secilen_saat = query.data.replace("hat:", "")
    chat_id = query.message.chat_id
    user_id = query.from_user.id

    data = context.user_data.copy()
    bilet_no = f"ZT{datetime.datetime.now().strftime('%Y%m%d-%H%M')}"
    data['bilet_no']       = bilet_no
    data['hatirlatma_saat'] = secilen_saat

    # DB'ye kaydet
    conn = sqlite3.connect('zenith_transfer.db')
    c = conn.cursor()
    c.execute('''
        INSERT INTO yolculuklar
        (user_id, chat_id, bilet_no, tarih, saat, yolcu_sayisi, yolcular,
         nereden, nereye, ucus_kodu, arac_tipi, telefon, fiyat, odeme_turu,
         hatirlatma_saat, durum)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'Bekliyor')
    ''', (
        user_id, chat_id, bilet_no,
        data.get('tarih',''), data.get('saat',''),
        data.get('yolcu_sayisi',''), data.get('yolcular',''),
        data.get('nereden',''), data.get('nereye',''),
        data.get('ucus_kodu','—'), data.get('arac_tipi',''),
        data.get('telefon',''), data.get('fiyat',''),
        data.get('odeme_turu',''), secilen_saat
    ))
    row_id = c.lastrowid
    conn.commit()
    conn.close()

    await query.edit_message_text(
        f"✅ Bilet kaydedildi! PDF hazırlanıyor…",
        parse_mode="Markdown"
    )

    # PDF üret ve gönder
    pdf_bytes = pdf_uret(data, bilet_no)
    pdf_file = io.BytesIO(pdf_bytes)
    pdf_file.name = f"Zenith_{bilet_no}.pdf"

    hat_mesaj = (
        f" Yolculuğa *{secilen_saat} saat kala* otomatik hatırlatma alacaksınız."
        if secilen_saat != '0' else " Hatırlatma seçilmedi."
    )
    await context.bot.send_document(
        chat_id=chat_id,
        document=pdf_file,
        caption=(
            f"✨ *Bilet Oluşturuldu!*\n\n"
            f"🎫 *Bilet No:* `{bilet_no}`\n"
            f"👤 *Yolcu:* {data.get('yolcular','')}\n"
            f"📅 *{data.get('tarih','')}* — ⏰ *{data.get('saat','')}*\n"
            f"📍 {data.get('nereden','')} ➜ {data.get('nereye','')}\n"
            f"💵 {data.get('fiyat','')}\n\n"
            + hat_mesaj
        ),
        parse_mode="Markdown"
    )

    # Hatırlatma planla
    job_planla(context.application, row_id, chat_id, data, secilen_saat)
    return ConversationHandler.END


# ── /gelecek & /gecmis ───────────────────────────────────────────────────────
async def gelecek_isler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    conn = sqlite3.connect('zenith_transfer.db')
    c = conn.cursor()
    c.execute(
        "SELECT bilet_no,tarih,saat,yolcular,nereden,nereye,fiyat "
        "FROM yolculuklar WHERE user_id=? AND durum='Bekliyor' ORDER BY id DESC",
        (user_id,)
    )
    rows = c.fetchall()
    conn.close()

    if not rows:
        await update.message.reply_text("📅 Planlanmış yolculuğunuz yok.")
        return

    txt = "📅 *GELECEK YOLCULUKLAR*\n\n"
    for r in rows:
        txt += (f"🎫 `{r[0]}`\n"
                f"📅 {r[1]} — {r[2]}\n"
                f"👤 {r[3]}\n"
                f"📍 {r[4]} ➜ {r[5]}\n"
                f"💵 {r[6]}\n\n")
    await update.message.reply_text(txt, parse_mode="Markdown")

async def gecmis_isler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    conn = sqlite3.connect('zenith_transfer.db')
    c = conn.cursor()
    c.execute(
        "SELECT bilet_no,tarih,saat,yolcular,nereden,nereye,fiyat "
        "FROM yolculuklar WHERE user_id=? ORDER BY id DESC LIMIT 20",
        (user_id,)
    )
    rows = c.fetchall()
    conn.close()

    if not rows:
        await update.message.reply_text("📜 Kayıt bulunmuyor.")
        return

    txt = "📜 *TÜM YOLCULUK KAYITLARI*\n\n"
    for r in rows:
        txt += (f"🎫 `{r[0]}`\n"
                f"📅 {r[1]} — {r[2]} | 👤 {r[3]}\n"
                f"📍 {r[4]} ➜ {r[5]} | 💵 {r[6]}\n\n")
    await update.message.reply_text(txt, parse_mode="Markdown")

async def iptal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ İşlem iptal edildi.")
    return ConversationHandler.END


# ── Bot başladığında bekleyen hatırlatmaları yeniden yükle ───────────────────
async def post_init(app):
    """Render yeniden başladığında DB'deki hatırlatmaları tekrar planlar."""
    conn = sqlite3.connect('zenith_transfer.db')
    c = conn.cursor()
    c.execute(
        "SELECT id,chat_id,tarih,saat,hatirlatma_saat FROM yolculuklar "
        "WHERE durum='Bekliyor' AND hatirlatma_saat != '0'"
    )
    rows = c.fetchall()
    conn.close()

    now = datetime.datetime.now()
    yeniden = 0
    for row in rows:
        row_id, chat_id, tarih, saat, hat_saat = row
        try:
            transfer_dt = datetime.datetime.strptime(f"{tarih} {saat}", "%d.%m.%Y %H:%M")
            hat_dt = transfer_dt - datetime.timedelta(hours=int(hat_saat))
            kalan = (hat_dt - now).total_seconds()
            if kalan > 0:
                app.job_queue.run_once(
                    hatirlatma_tetikle,
                    when=kalan,
                    chat_id=chat_id,
                    data=(row_id, chat_id),
                    name=f"hat_{row_id}"
                )
                yeniden += 1
        except Exception as e:
            logger.warning(f"Hatırlatma yüklenemedi (id={row_id}): {e}")
    logger.info(f"Bot başladı — {yeniden} hatırlatma yeniden planlandı.")


# ── Ana Fonksiyon ─────────────────────────────────────────────────────────────
def main():
    TOKEN = os.getenv("TELEGRAM_TOKEN", "BURAYA_BOT_TOKEN_GELECEK")

    app = (
        Application.builder()
        .token(TOKEN)
        .post_init(post_init)
        .build()
    )

    conv = ConversationHandler(
        entry_points=[CommandHandler("yeni", yeni_rezervasyon)],
        states={
            TARIH:       [MessageHandler(filters.TEXT & ~filters.COMMAND, tarih_al)],
            SAAT:        [MessageHandler(filters.TEXT & ~filters.COMMAND, saat_al)],
            YOLCU_SAYISI:[MessageHandler(filters.TEXT & ~filters.COMMAND, yolcu_sayisi_al)],
            YOLCULAR:    [MessageHandler(filters.TEXT & ~filters.COMMAND, yolcular_al)],
            NEREDEN:     [MessageHandler(filters.TEXT & ~filters.COMMAND, nereden_al)],
            NEREYE:      [MessageHandler(filters.TEXT & ~filters.COMMAND, nereye_al)],
            UCUS_KODU:   [MessageHandler(filters.TEXT & ~filters.COMMAND, ucus_kodu_al)],
            ARAC_TIPI:   [CallbackQueryHandler(arac_tipi_al, pattern="^arac:")],
            TELEFON:     [MessageHandler(filters.TEXT & ~filters.COMMAND, telefon_al)],
            FIYAT:       [MessageHandler(filters.TEXT & ~filters.COMMAND, fiyat_al)],
            ODEME_TURU:  [CallbackQueryHandler(odeme_turu_al, pattern="^odeme:")],
            HATIRLATMA:  [CallbackQueryHandler(hatirlatma_sec, pattern="^hat:")],
        },
        fallbacks=[CommandHandler("iptal", iptal)],
        allow_reentry=True,
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("gelecek", gelecek_isler))
    app.add_handler(CommandHandler("gecmis", gecmis_isler))
    app.add_handler(conv)

    logger.info("🚀 Zenith VIP Transfer Botu Başlatılıyor…")
    app.run_polling(drop_pending_updates=True)

if __name__ == '__main__':
    main()
