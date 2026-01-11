# -*- coding: utf-8 -*-
"""
Hikvision Cron Jobs Mixin

Bu mixin rejalashtirilgan vazifalar (cron jobs) uchun
metodlarni o'z ichiga oladi.
"""

import logging
import pytz
import threading
from datetime import datetime

from odoo import models, api, SUPERUSER_ID
from odoo.modules.registry import Registry
from .hikvision_logger import log_cron, log_info, log_error, log_debug, send_new_logs_to_telegram, cleanup_old_logs

DEFAULT_TIMEZONE = 'Asia/Tashkent'
DEFAULT_WORK_END_TIME = "18:00"

_logger = logging.getLogger(__name__)


class HikvisionCronMixin(models.AbstractModel):
    """Hikvision cron job metodlari uchun mixin"""
    
    _name = 'hikvision.cron.mixin'
    _description = 'Hikvision Cron Mixin'

    @api.model
    def _cron_fetch_logs(self):
        """
        Barcha qurilmalardan loglarni olish va birga qayta ishlash.
        
        MUHIM: Barcha qurilmalardan loglarni AVVAL yig'ib, 
        keyin VAQT bo'yicha tartiblash va qayta ishlash.
        Bu bir kunda bir necha kirish-chiqish bo'lganda 
        to'g'ri ishlashni ta'minlaydi.
        """
        devices = self.search([('state', '=', 'confirmed')])
        
        if not devices:
            _logger.info("Cron: Tasdiqlangan qurilmalar topilmadi")
            return
        
        device_names = ', '.join(devices.mapped('name'))
        log_cron('Fetch Logs', f"Boshlandi: {len(devices)} ta qurilma ({device_names})")
        
        all_logs = []  # Barcha qurilmalardan barcha loglar
        
        # 1-BOSQICH: Barcha qurilmalardan loglarni yig'ish
        for device in devices:
            try:
                _logger.info(f"Cron: Collecting logs from {device.name}")
                logs, device_attendance_type = device._fetch_all_logs_raw()
                
                # Har bir logga qurilma ma'lumotlarini qo'shish
                for log in logs:
                    log['_device_id'] = device.id
                    log['_device_name'] = device.name
                    log['_attendance_type'] = device_attendance_type
                
                all_logs.extend(logs)
                
                if logs:
                    log_cron('Fetch Logs', f"{device.name}: {len(logs)} ta log topildi")
                else:
                    log_cron('Fetch Logs', f"{device.name}: log yo'q")
                
            except Exception as e:
                _logger.error(f"Cron: {device.name} dan log olishda xato: {str(e)}")
                log_error(f"[CRON: Fetch Logs] {device.name} xatosi: {str(e)}")
        
        if not all_logs:
            return
        
        # 2-BOSQICH: Barcha loglarni VAQT bo'yicha tartiblash
        all_logs_sorted = sorted(all_logs, key=lambda x: x.get('time', ''))
        _logger.info(f"Cron: Jami {len(all_logs_sorted)} ta log vaqt bo'yicha tartiblandi")
        
        # 3-BOSQICH: Tartibda qayta ishlash
        today_start_utc, today_end_utc = devices[0]._get_today_range_utc()
        
        created_count = 0
        skipped_count = 0
        error_count = 0
        
        for log in all_logs_sorted:
            try:
                device = self.browse(log['_device_id'])
                attendance_type = log['_attendance_type']
                
                result = device._process_single_log(log, attendance_type, today_start_utc, today_end_utc)
                
                if result == 'created':
                    created_count += 1
                elif result == 'skipped':
                    skipped_count += 1
                else:
                    error_count += 1
                    
            except Exception as e:
                error_count += 1
                _logger.error(f"Cron: Log qayta ishlashda xato: {str(e)}")
        
        # Yakuniy natija
        result_msg = f"Yakunlandi: Yangi={created_count}, Skip={skipped_count}, Xato={error_count}"
        _logger.info(f"Cron: {result_msg}")
        log_cron('Fetch Logs', result_msg)

    @api.model
    def _cron_send_logs_to_telegram(self):
        """Har 1 daqiqada yangi loglarni Telegram ga yuborish"""
        try:
            send_new_logs_to_telegram()
        except Exception as e:
            _logger.error(f"Telegram log yuborishda xato: {str(e)}")

    @api.model
    def _cron_cleanup_logs(self):
        """Haftalik log tozalash (7 kundan eski loglarni o'chiradi)"""
        try:
            log_cron('Log Cleanup', "Haftalik log tozalash boshlandi")
            result = cleanup_old_logs(days_to_keep=7)
            log_cron('Log Cleanup', f"Natija: {result}")
        except Exception as e:
            _logger.error(f"Log tozalashda xato: {str(e)}")
            log_error(f"[CRON: Log Cleanup] Xato: {str(e)}")

    @api.model
    def _cron_auto_close_attendance(self):
        """
        Ochiq attendance'larni avtomatik check-out qilish.
        
        OPTIMIZATSIYA:
        - Background thread (timeout yo'q)
        - Calendar-based (har xodimning o'z jadvali)
        - Har bir xodim va calendar tekshiriladi
        - Har bir xodimdan keyin commit
        """
        local_tz = pytz.timezone(DEFAULT_TIMEZONE)
        now_local = datetime.now(local_tz)
        
        today_start_local = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
        today_start_utc = today_start_local.astimezone(pytz.UTC).replace(tzinfo=None)
        
        _logger.info(f"Auto-close cron: Boshlandi at {now_local.strftime('%Y-%m-%d %H:%M:%S')}")
        log_cron('Auto Close', f"Boshlandi: {now_local.strftime('%Y-%m-%d %H:%M:%S')}")
        
        # Faqat bugungi ochiq davomat yozuvlari
        open_attendances = self.env['hr.attendance'].search([
            ('check_in', '>=', today_start_utc),
            ('check_out', '=', False)
        ])
        
        if not open_attendances:
            _logger.info("Auto-close cron: Ochiq davomat yozuvlari topilmadi")
            log_cron('Auto Close', "Ochiq davomat yozuvlari topilmadi")
            return
        
        _logger.info(f"Auto-close cron: {len(open_attendances)} ta ochiq davomat topildi")
        log_cron('Auto Close', f"{len(open_attendances)} ta ochiq davomat topildi")
        
        # Background thread uchun tayyorlash
        db_name = self.env.cr.dbname
        attendance_ids = open_attendances.ids
        total = len(attendance_ids)
        
        def auto_close_in_background():
            """Background threadda avtomatik yopish"""
            try:
                db_registry = Registry(db_name)
                with db_registry.cursor() as cr:
                    env = api.Environment(cr, SUPERUSER_ID, {})
                    
                    # Hozirgi vaqt
                    now = datetime.now(pytz.UTC)
                    
                    closed_count = 0
                    skipped_count = 0
                    error_count = 0
                    
                    for idx, att_id in enumerate(attendance_ids, 1):
                        try:
                            attendance = env['hr.attendance'].browse(att_id)
                            
                            if not attendance.exists():
                                continue
                            
                            employee = attendance.employee_id
                            calendar = employee.resource_calendar_id
                            
                            # Calendar yo'qmi?
                            if not calendar:
                                skipped_count += 1
                                _logger.debug(f"Auto-close: {employee.name} - calendar yo'q, skip")
                                continue
                            
                            # Bugun bu xodim uchun ish kunmi?
                            today_weekday = datetime.now().weekday()
                            
                            is_working_day = calendar.attendance_ids.filtered(
                                lambda a: int(a.dayofweek) == today_weekday
                            )
                            
                            if not is_working_day:
                                skipped_count += 1
                                _logger.debug(f"Auto-close: {employee.name} - bugun dam olish kuni, skip")
                                continue
                            
                            # Ish tugash vaqtini hisoblash
                            tz = pytz.timezone(calendar.tz or DEFAULT_TIMEZONE)
                            
                            check_in_utc = attendance.check_in
                            if check_in_utc.tzinfo is None:
                                check_in_aware = pytz.UTC.localize(check_in_utc)
                            else:
                                check_in_aware = check_in_utc
                            check_in_local = check_in_aware.astimezone(tz)
                            
                            day_start = tz.localize(datetime.combine(check_in_local.date(), datetime.min.time()))
                            day_end = tz.localize(datetime.combine(check_in_local.date(), datetime.max.time()))
                            
                            # Expected work end
                            work_intervals = calendar._work_intervals_batch(
                                day_start, day_end, resources=employee.resource_id
                            )
                            
                            resource_id = employee.resource_id.id
                            expected_end = None
                            
                            if work_intervals and resource_id in work_intervals:
                                intervals = work_intervals[resource_id]
                                intervals_list = list(intervals) if intervals else []
                                
                                if intervals_list:
                                    last_interval = intervals_list[-1]
                                    expected_end = last_interval[1]
                                    
                                    if expected_end.tzinfo is None:
                                        expected_end = tz.localize(expected_end)
                            
                            if not expected_end:
                                expected_end = tz.localize(datetime.combine(
                                    check_in_local.date(),
                                    datetime.strptime(DEFAULT_WORK_END_TIME, "%H:%M").time()
                                ))
                            
                            # Ish vaqti tugaganmi?
                            now_aware = now.astimezone(tz)
                            
                            # DEBUG LOG
                            log_info(f"[AUTO-CLOSE DEBUG] {employee.name}: now={now_aware.strftime('%H:%M')}, expected_end={expected_end.strftime('%H:%M')}, result={now_aware >= expected_end}")
                            
                            if now_aware >= expected_end:
                                # Avtomatik yopish
                                try:
                                    check_out_utc = expected_end.astimezone(pytz.UTC).replace(tzinfo=None)
                                    log_info(f"[AUTO-CLOSE] {employee.name}: Yopilmoqda... check_out={check_out_utc}")
                                    
                                    # RAW SQL - Odoo constraint'larini bypass qilish
                                    cr.execute("""
                                        UPDATE hr_attendance 
                                        SET check_out = %s 
                                        WHERE id = %s AND check_out IS NULL
                                    """, (check_out_utc, attendance.id))
                                    log_info(f"[AUTO-CLOSE] {employee.name}: Write muvaffaqiyatli!")
                                    
                                    # Hikvision log yaratish
                                    device = env['hikvision.device'].search([('state', '=', 'confirmed')], limit=1)
                                    if device:
                                        env['hikvision.log'].create({
                                            'device_id': device.id,
                                            'employee_id': employee.id,
                                            'timestamp': check_out_utc,
                                            'attendance_type': 'check_out',
                                        })
                                    
                                    closed_count += 1
                                    log_info(f"[AUTO-CLOSE] {employee.name}: YOPILDI! (expected end: {expected_end.strftime('%H:%M')})")
                                    _logger.info(f"Auto-close: {employee.name} yopildi (expected end: {expected_end.strftime('%H:%M')})")
                                    
                                    # Har bir xodimdan keyin commit
                                    cr.commit()
                                    log_info(f"[AUTO-CLOSE] {employee.name}: Commit muvaffaqiyatli!")
                                except Exception as write_error:
                                    log_error(f"[AUTO-CLOSE] {employee.name}: Write/Commit XATO: {str(write_error)}")
                                    _logger.error(f"Auto-close write error: {str(write_error)}")
                                    cr.rollback()
                            else:
                                skipped_count += 1
                                _logger.debug(f"Auto-close: {employee.name} - ish vaqti tugamagan, skip")
                        
                        except Exception as e:
                            error_count += 1
                            _logger.error(f"Auto-close: Xato employee {att_id}: {str(e)}")
                            cr.rollback()
                        
                        # Progress log (har 50 ta)
                        if idx % 50 == 0:
                            _logger.info(f"Auto-close: Progress - {idx}/{total}")
                    
                    # Final log
                    _logger.info(
                        f"Auto-close yakunlandi: "
                        f"Yopildi={closed_count}, Skip={skipped_count}, Xato={error_count}"
                    )
                    
            except Exception as e:
                _logger.error(f"Auto-close: Background thread xatosi: {str(e)}")
        
        # Threadni ishga tushirish
        thread = threading.Thread(target=auto_close_in_background, daemon=True)
        thread.start()
        
        _logger.info(f"Auto-close: Background thread boshlandi - {total} ta davomat")
    
    def _get_expected_work_end(self, calendar, employee, day_start, day_end, tz, check_in_local):
        """Xodimning kutilgan ish tugash vaqtini aniqlash."""
        work_intervals = calendar._work_intervals_batch(
            day_start, day_end, resources=employee.resource_id
        )
        
        resource_id = employee.resource_id.id
        expected_end = None
        
        if work_intervals and resource_id in work_intervals:
            intervals = work_intervals[resource_id]
            intervals_list = list(intervals) if intervals else []
            
            if intervals_list:
                last_interval = intervals_list[-1]
                expected_end = last_interval[1]
                
                if expected_end.tzinfo is None:
                    expected_end = tz.localize(expected_end)
        
        if not expected_end:
            expected_end = tz.localize(datetime.combine(
                check_in_local.date(), 
                datetime.strptime(DEFAULT_WORK_END_TIME, "%H:%M").time()
            ))
        
        return expected_end
