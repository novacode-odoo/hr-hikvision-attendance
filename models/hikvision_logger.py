# -*- coding: utf-8 -*-
"""
Hikvision Custom Logger

Hikvision addoniga tegishli loglarni alohida faylga yozish uchun
custom logger setup.

Telegram integratsiyasi ham mavjud - yangi loglar guruhga yuboriladi.
"""

import os
import logging
import requests
import pytz
from logging.handlers import RotatingFileHandler
from datetime import datetime

# Timezone sozlamasi
LOCAL_TIMEZONE = pytz.timezone('Asia/Tashkent')


class TashkentFormatter(logging.Formatter):
    """Asia/Tashkent timezone bilan log formatlash"""
    
    def formatTime(self, record, datefmt=None):
        # UTC vaqtni lokal vaqtga o'tkazish
        ct = datetime.fromtimestamp(record.created, tz=pytz.UTC)
        local_time = ct.astimezone(LOCAL_TIMEZONE)
        if datefmt:
            return local_time.strftime(datefmt)
        return local_time.strftime('%Y-%m-%d %H:%M:%S')


# Telegram sozlamalari
TELEGRAM_BOT_TOKEN = "8299842546:AAGD-2a1hcicdy4awQCLfXGTmP0LyUo0gPI"
TELEGRAM_CHAT_ID = "-5220244709"

# Log fayli joylashuvi (addon ichida)
ADDON_PATH = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG_FILE = os.path.join(ADDON_PATH, 'logs', 'hikvision.log')
LAST_SENT_FILE = os.path.join(ADDON_PATH, 'logs', '.last_sent_line')

# Log papkasini yaratish
LOG_DIR = os.path.dirname(LOG_FILE)
if not os.path.exists(LOG_DIR):
    try:
        os.makedirs(LOG_DIR)
    except OSError:
        pass

# Custom Hikvision Logger
hikvision_logger = logging.getLogger('hikvision_custom')
hikvision_logger.setLevel(logging.DEBUG)

# Faylga yozish uchun handler (max 5MB, 3 backup)
try:
    file_handler = RotatingFileHandler(
        LOG_FILE, 
        maxBytes=5*1024*1024,  # 5 MB
        backupCount=3,
        encoding='utf-8'
    )
    file_handler.setLevel(logging.DEBUG)
    
    # Format - Lokal vaqt bilan
    formatter = TashkentFormatter(
        '%(asctime)s | %(levelname)s | %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    file_handler.setFormatter(formatter)
    
    # Handler qo'shish (agar mavjud bo'lmasa)
    if not hikvision_logger.handlers:
        hikvision_logger.addHandler(file_handler)
except Exception as e:
    print(f"Hikvision log file setup error: {e}")


def log_info(message):
    """INFO darajasida log yozish"""
    hikvision_logger.info(message)
    
def log_error(message):
    """ERROR darajasida log yozish"""
    hikvision_logger.error(message)
    
def log_warning(message):
    """WARNING darajasida log yozish"""
    hikvision_logger.warning(message)
    
def log_debug(message):
    """DEBUG darajasida log yozish"""
    hikvision_logger.debug(message)

def log_cron(cron_name, message):
    """Cron job loglari uchun"""
    hikvision_logger.info(f"[CRON: {cron_name}] {message}")

def log_sync(action, employee_name, status, device_name=None):
    """Sinxronizatsiya loglari uchun"""
    device_info = f" ({device_name})" if device_name else ""
    hikvision_logger.info(f"[SYNC] {action}: {employee_name} -> {status}{device_info}")

def log_api(method, endpoint, status, error=None):
    """API request loglari uchun"""
    if error:
        hikvision_logger.error(f"[API] {method} {endpoint} -> {status}: {error}")
    else:
        hikvision_logger.info(f"[API] {method} {endpoint} -> {status}")


# =============================================================================
# TELEGRAM YUBORISH
# =============================================================================

def send_telegram_message(message):
    """Telegram guruhga xabar yuborish"""
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = {
            'chat_id': TELEGRAM_CHAT_ID,
            'text': message,
            'parse_mode': 'HTML'
        }
        response = requests.post(url, json=payload, timeout=10)
        return response.status_code == 200
    except Exception as e:
        print(f"Telegram yuborishda xato: {e}")
        return False


def get_last_sent_line():
    """Oxirgi yuborilgan qator raqamini olish"""
    try:
        if os.path.exists(LAST_SENT_FILE):
            with open(LAST_SENT_FILE, 'r') as f:
                return int(f.read().strip())
    except:
        pass
    return 0


def save_last_sent_line(line_number):
    """Oxirgi yuborilgan qator raqamini saqlash"""
    try:
        with open(LAST_SENT_FILE, 'w') as f:
            f.write(str(line_number))
    except:
        pass


def send_new_logs_to_telegram():
    """Yangi loglarni Telegram ga yuborish (cron job orqali chaqiriladi)"""
    try:
        if not os.path.exists(LOG_FILE):
            return
        
        last_sent = get_last_sent_line()
        
        with open(LOG_FILE, 'r', encoding='utf-8') as f:
            lines = f.readlines()
        
        total_lines = len(lines)
        
        # Log fayli rotate bo'lgan bo'lsa (yangi fayl eski pozitsiyadan kichik)
        # avtomatik reset qilish
        if last_sent > total_lines:
            last_sent = 0
            save_last_sent_line(0)
        
        if total_lines <= last_sent:
            return  # Yangi log yo'q
        
        # Yangi loglar
        new_logs = lines[last_sent:]
        
        if new_logs:
            # Xabar tayyorlash
            header = f"📋 <b>Hikvision Logs</b>\n"
            header += f"🕐 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
            header += f"📊 Yangi: {len(new_logs)} ta log\n"
            header += "━" * 25 + "\n\n"
            
            # Loglarni formatlash
            log_text = ""
            for log in new_logs:
                log = log.strip()
                if not log:
                    continue
                
                # Emoji qo'shish
                if "ERROR" in log:
                    log_text += f"🔴 {log}\n"
                elif "WARNING" in log:
                    log_text += f"🟡 {log}\n"
                else:
                    log_text += f"🟢 {log}\n"
            
            message = header + log_text
            
            # Telegram xabar limiti (4096 belgi)
            if len(message) > 4000:
                message = message[:4000] + "\n... (qisqartirildi)"
            
            # Yuborish
            if send_telegram_message(message):
                save_last_sent_line(total_lines)
                
    except Exception as e:
        print(f"Telegram log yuborishda xato: {e}")


def cleanup_old_logs(days_to_keep=7):
    """
    Eski loglarni tozalash (standart: 7 kundan eski loglarni o'chirish)
    
    Args:
        days_to_keep: Necha kunlik loglarni saqlash (standart: 7 kun)
    
    Bu funksiya haftalik cron job orqali chaqiriladi.
    """
    from datetime import timedelta
    
    try:
        if not os.path.exists(LOG_FILE):
            log_info("[CLEANUP] Log fayl topilmadi, tozalash kerak emas")
            return {'status': 'skipped', 'reason': 'file_not_found'}
        
        cutoff_date = datetime.now() - timedelta(days=days_to_keep)
        
        with open(LOG_FILE, 'r', encoding='utf-8') as f:
            lines = f.readlines()
        
        original_count = len(lines)
        
        # Saqlanadigan loglarni filtrlash
        kept_lines = []
        for line in lines:
            try:
                # Log formati: "2026-01-07 11:30:00 | INFO | ..."
                if ' | ' in line:
                    date_str = line.split(' | ')[0].strip()
                    log_date = datetime.strptime(date_str, '%Y-%m-%d %H:%M:%S')
                    
                    if log_date >= cutoff_date:
                        kept_lines.append(line)
                else:
                    # Formati boshqacha bo'lsa, saqlab qolamiz
                    kept_lines.append(line)
            except (ValueError, IndexError):
                # Parse qilolmasak, saqlab qolamiz
                kept_lines.append(line)
        
        removed_count = original_count - len(kept_lines)
        
        if removed_count > 0:
            # Yangi kontentni yozish
            with open(LOG_FILE, 'w', encoding='utf-8') as f:
                f.writelines(kept_lines)
            
            # Telegram tracker ni ham yangilash
            if os.path.exists(LAST_SENT_FILE):
                try:
                    current_last = get_last_sent_line()
                    new_last = max(0, current_last - removed_count)
                    save_last_sent_line(new_last)
                except:
                    pass
            
            log_info(f"[CLEANUP] {removed_count} ta eski log o'chirildi, {len(kept_lines)} ta qoldi")
            
            # Telegram ga xabar
            send_telegram_message(
                f"🧹 <b>Log Cleanup</b>\n"
                f"📅 {days_to_keep} kundan eski loglar o'chirildi\n"
                f"❌ O'chirildi: {removed_count} ta\n"
                f"✅ Qoldi: {len(kept_lines)} ta"
            )
            
            return {
                'status': 'success',
                'removed': removed_count,
                'kept': len(kept_lines)
            }
        else:
            log_info(f"[CLEANUP] O'chiriladigan eski log topilmadi")
            return {'status': 'skipped', 'reason': 'no_old_logs'}
            
    except Exception as e:
        log_error(f"[CLEANUP] Log tozalashda xato: {e}")
        return {'status': 'error', 'error': str(e)}

