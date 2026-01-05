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

DEFAULT_TIMEZONE = 'Asia/Tashkent'
DEFAULT_WORK_END_TIME = "18:00"

_logger = logging.getLogger(__name__)


class HikvisionCronMixin(models.AbstractModel):
    """Hikvision cron job metodlari uchun mixin"""
    
    _name = 'hikvision.cron.mixin'
    _description = 'Hikvision Cron Mixin'

    @api.model
    def _cron_fetch_logs(self):
        """Rejalashtirilgan ish: Barcha tasdiqlangan qurilmalardan loglarni olish"""
        devices = self.search([('state', '=', 'confirmed')])
        
        for device in devices:
            try:
                _logger.info(f"Cron: Fetching logs from device {device.name}")
                device.with_context(cron_mode=True).action_fetch_logs()
            except Exception as e:
                _logger.error(f"Cron: Failed to fetch logs from device {device.name}: {str(e)}")

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
        
        # Faqat bugungi ochiq davomat yozuvlari
        open_attendances = self.env['hr.attendance'].search([
            ('check_in', '>=', today_start_utc),
            ('check_out', '=', False)
        ])
        
        if not open_attendances:
            _logger.info("Auto-close cron: Ochiq davomat yozuvlari topilmadi")
            return
        
        _logger.info(f"Auto-close cron: {len(open_attendances)} ta ochiq davomat topildi")
        
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
                            
                            if now_aware >= expected_end:
                                # Avtomatik yopish
                                check_out_utc = expected_end.astimezone(pytz.UTC).replace(tzinfo=None)
                                attendance.write({'check_out': check_out_utc})
                                
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
                                _logger.info(f"Auto-close: {employee.name} yopildi (expected end: {expected_end.strftime('%H:%M')})")
                                
                                # Har bir xodimdan keyin commit
                                cr.commit()
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
