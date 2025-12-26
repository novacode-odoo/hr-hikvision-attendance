# -*- coding: utf-8 -*-
"""
Hikvision Cron Jobs Mixin

Bu mixin rejalashtirilgan vazifalar (cron jobs) uchun
metodlarni o'z ichiga oladi.
"""

import logging
import pytz
from datetime import datetime

from odoo import models, api

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
        """Ochiq attendance'larni avtomatik check-out qilish."""
        local_tz = pytz.timezone(DEFAULT_TIMEZONE)
        now_local = datetime.now(local_tz)
        
        today_start_local = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
        today_start_utc = today_start_local.astimezone(pytz.UTC).replace(tzinfo=None)
        
        _logger.info(f"Auto-close cron: Checking open attendances at {now_local}")
        
        open_attendances = self.env['hr.attendance'].search([
            ('check_in', '>=', today_start_utc),
            ('check_out', '=', False)
        ])
        
        if not open_attendances:
            _logger.info("Auto-close cron: No open attendances found")
            return
        
        closed_count = 0
        skipped_count = 0
        
        for attendance in open_attendances:
            result = self._auto_close_single_attendance(attendance, now_local)
            if result == 'closed':
                closed_count += 1
            else:
                skipped_count += 1
        
        _logger.info(f"Auto-close cron completed: {closed_count} yopildi, {skipped_count} o'tkazib yuborildi")
    
    def _auto_close_single_attendance(self, attendance, now_local):
        """Bitta ochiq attendance ni avtomatik yopish."""
        try:
            employee = attendance.employee_id
            calendar = employee.resource_calendar_id
            
            if not calendar:
                return 'skipped'
            
            tz = pytz.timezone(calendar.tz or DEFAULT_TIMEZONE)
            
            check_in_utc = attendance.check_in
            if check_in_utc.tzinfo is None:
                check_in_aware = pytz.UTC.localize(check_in_utc)
            else:
                check_in_aware = check_in_utc
            check_in_local = check_in_aware.astimezone(tz)
            
            day_start = tz.localize(datetime.combine(check_in_local.date(), datetime.min.time()))
            day_end = tz.localize(datetime.combine(check_in_local.date(), datetime.max.time()))
            
            expected_end = self._get_expected_work_end(calendar, employee, day_start, day_end, tz, check_in_local)
            
            now_aware = now_local.astimezone(tz) if now_local.tzinfo else tz.localize(now_local)
            
            if now_aware >= expected_end:
                check_out_utc = expected_end.astimezone(pytz.UTC).replace(tzinfo=None)
                attendance.write({'check_out': check_out_utc})
                
                device = self.search([('state', '=', 'confirmed')], limit=1)
                if device:
                    self.env['hikvision.log'].create({
                        'device_id': device.id,
                        'employee_id': employee.id,
                        'timestamp': check_out_utc,
                        'attendance_type': 'check_out',
                    })
                
                _logger.info(f"Auto-close: {employee.name} avtomatik check-out qilindi")
                return 'closed'
            else:
                return 'skipped'
                
        except Exception as e:
            _logger.error(f"Auto-close error: {str(e)}")
            return 'skipped'
    
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
