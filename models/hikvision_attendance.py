# -*- coding: utf-8 -*-
"""
Hikvision Attendance Mixin

Bu mixin davomat loglarini olish va qayta ishlash
uchun metodlarni o'z ichiga oladi.
"""

import json
import logging
import pytz
from datetime import datetime, timedelta

from odoo import models

# Konstantalar
DEFAULT_TIMEZONE = 'Asia/Tashkent'
DEFAULT_PAGE_SIZE = 30
HIKVISION_MAJOR_ACCESS_CONTROL = 5
HIKVISION_MINOR_ALL = 0

_logger = logging.getLogger(__name__)


class HikvisionAttendanceMixin(models.AbstractModel):
    """Hikvision attendance metodlari uchun mixin"""
    
    _name = 'hikvision.attendance.mixin'
    _description = 'Hikvision Attendance Mixin'

    def _get_local_timezone(self):
        """Lokal timezone ni olish"""
        return pytz.timezone(DEFAULT_TIMEZONE)
    
    def _get_today_range_utc(self):
        """Bugungi kunning boshi va oxirini UTC formatda qaytarish."""
        local_tz = self._get_local_timezone()
        now = datetime.now(local_tz)
        
        start_time = now.replace(hour=0, minute=0, second=0, microsecond=0)
        end_time = now.replace(hour=23, minute=59, second=59, microsecond=0)
        
        today_start_utc = start_time.astimezone(pytz.UTC).replace(tzinfo=None)
        today_end_utc = end_time.astimezone(pytz.UTC).replace(tzinfo=None)
        
        return today_start_utc, today_end_utc
    
    def _parse_log_time(self, time_str):
        """Hikvision log vaqtini parse qilish."""
        local_tz = self._get_local_timezone()
        
        if '+' in time_str:
            log_time_local = datetime.fromisoformat(time_str)
        else:
            log_time_local = datetime.strptime(time_str[:19], '%Y-%m-%dT%H:%M:%S')
            log_time_local = local_tz.localize(log_time_local)
        
        return log_time_local.astimezone(pytz.UTC).replace(tzinfo=None)
    
    def _get_device_attendance_type(self):
        """Qurilma nomidan attendance turini aniqlash."""
        device_name_lower = self.name.lower()
        
        if any(keyword in device_name_lower for keyword in ['check in', 'checkin', 'kirish']):
            return 'check_in'
        elif any(keyword in device_name_lower for keyword in ['check out', 'checkout', 'chiqish']):
            return 'check_out'
        return None
    
    def _build_log_search_payload(self, search_position, start_str, end_str):
        """Hikvision log qidirish uchun payload yaratish."""
        return {
            "AcsEventCond": {
                "searchID": "1",
                "searchResultPosition": search_position,
                "maxResults": DEFAULT_PAGE_SIZE,
                "major": HIKVISION_MAJOR_ACCESS_CONTROL,
                "minor": HIKVISION_MINOR_ALL,
                "startTime": start_str,
                "endTime": end_str,
                "isAttendanceInfo": True,
                "timeReverseOrder": True
            }
        }
    
    def _fetch_all_logs_raw(self):
        """
        Qurilmadan barcha loglarni olish (qayta ishlamasdan).
        
        Barcha sahifalarni yig'ib, birga qaytaradi.
        Cron job tomonidan ishlatiladi.
        
        Returns:
            tuple: (logs_list, device_attendance_type)
        """
        self.ensure_one()
        
        local_tz = self._get_local_timezone()
        now = datetime.now(local_tz)
        
        # Bugungi kun chegaralari
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        today_end = now.replace(hour=23, minute=59, second=59, microsecond=0)
        
        # Incremental sync - oxirgi olingan vaqtdan
        start_time = today_start
        if self.last_fetch_time:
            last_fetch_local = pytz.UTC.localize(self.last_fetch_time).astimezone(local_tz)
            if last_fetch_local.date() == now.date():
                start_time = last_fetch_local - timedelta(minutes=1)
        
        start_str = start_time.isoformat(timespec='seconds')
        end_str = today_end.isoformat(timespec='seconds')
        
        device_attendance_type = self._get_device_attendance_type()
        
        all_logs = []
        search_position = 0
        total_matches = None
        
        while True:
            payload = self._build_log_search_payload(search_position, start_str, end_str)
            response = self._make_request('POST', 'AccessControl/AcsEvent?format=json', 
                                          data=json.dumps(payload))
            data = response.json()
            
            if total_matches is None:
                total_matches = data.get('AcsEvent', {}).get('totalMatches', 0)
            
            logs = data.get('AcsEvent', {}).get('InfoList', [])
            
            if not logs:
                break
            
            all_logs.extend(logs)
            search_position += DEFAULT_PAGE_SIZE
            
            if search_position >= total_matches or len(logs) < DEFAULT_PAGE_SIZE:
                break
        
        # last_fetch_time yangilash
        self.last_fetch_time = now.astimezone(pytz.UTC).replace(tzinfo=None)
        
        _logger.info(f"Hikvision [{self.name}]: {len(all_logs)} ta log olindi")
        
        return all_logs, device_attendance_type
    
    def _get_attendance_type_from_label(self, label):
        """Log label'dan attendance turini aniqlash."""
        label_lower = label.lower()
        if 'check in' in label_lower:
            return 'check_in'
        elif 'check out' in label_lower:
            return 'check_out'
        return None
    
    def _should_process_log(self, attendance_type, open_attendance, employee_name):
        """Logni qayta ishlash kerakligini aniqlash."""
        if attendance_type == 'check_in':
            if not open_attendance:
                _logger.info(f"Hikvision: {employee_name} - CHECK IN qabul qilindi")
                return True
            else:
                _logger.debug(f"Hikvision: {employee_name} - CHECK IN o'tkazib yuborildi")
                return False
                
        elif attendance_type == 'check_out':
            if open_attendance:
                _logger.info(f"Hikvision: {employee_name} - CHECK OUT qabul qilindi")
                return True
            else:
                _logger.debug(f"Hikvision: {employee_name} - CHECK OUT o'tkazib yuborildi")
                return False
        
        return False
    
    def _process_single_log(self, log, device_attendance_type, today_start_utc, today_end_utc):
        """Bitta logni qayta ishlash."""
        try:
            employee_no = log.get('employeeNoString')
            time_str = log.get('time')
            
            if not employee_no or not time_str:
                return 'skipped'
            
            if device_attendance_type:
                attendance_type = device_attendance_type
            else:
                label = log.get('label', '')
                attendance_type = self._get_attendance_type_from_label(label)
                if not attendance_type:
                    return 'skipped'
            
            log_time_utc = self._parse_log_time(time_str)
            
            employee = self.env['hr.employee'].search([('barcode', '=', employee_no)], limit=1)
            if not employee:
                return 'skipped'
            
            existing_log = self.env['hikvision.log'].search([
                ('device_id', '=', self.id),
                ('timestamp', '=', log_time_utc),
                ('employee_id', '=', employee.id)
            ])
            if existing_log:
                return 'skipped'
            
            open_attendance = self.env['hr.attendance'].search([
                ('employee_id', '=', employee.id),
                ('check_in', '>=', today_start_utc),
                ('check_in', '<', today_end_utc),
                ('check_out', '=', False)
            ], order='check_in desc', limit=1)
            
            if not self._should_process_log(attendance_type, open_attendance, employee.name):
                return 'skipped'
            
            self.env['hikvision.log'].create({
                'device_id': self.id,
                'employee_id': employee.id,
                'timestamp': log_time_utc,
                'attendance_type': attendance_type,
            })
            
            self._process_attendance(employee, log_time_utc, attendance_type)
            
            return 'created'
            
        except Exception as e:
            _logger.error(f"Hikvision: Error processing log: {str(e)}")
            return 'error'
    
    def action_fetch_logs(self):
        """
        Hikvision qurilmasidan davomat loglarini olish.
        
        OPTIMIZATSIYA:
        - Incremental Sync: Faqat oxirgi olingan vaqtdan keyingi loglarni oladi.
        - Buffer: 1 minutlik orqaga qaytish (safety margin).
        - Daily Reset: Yangi kun boshlanganda 00:00 dan boshlaydi.
        """
        self.ensure_one()
        
        local_tz = self._get_local_timezone()
        now = datetime.now(local_tz)
        
        # Bugungi kun chegaralari
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        today_end = now.replace(hour=23, minute=59, second=59, microsecond=0)
        
        # Boshlang'ich vaqtni aniqlash (Logika)
        start_time = today_start
        fetch_mode = "full_day"
        
        if self.last_fetch_time:
            # last_fetch_time UTC da saqlanadi, uni localga o'tkazamiz
            last_fetch_local = pytz.UTC.localize(self.last_fetch_time).astimezone(local_tz)
            
            # Agar oxirgi marta bugun olingan bo'lsa
            if last_fetch_local.date() == now.date():
                # 1 daqiqa buffer bilan olish (xavfsizlik uchun)
                start_time = last_fetch_local - timedelta(minutes=1)
                fetch_mode = "incremental"
        
        # Hikvision formati uchun string
        start_str = start_time.isoformat(timespec='seconds')
        end_str = today_end.isoformat(timespec='seconds')
        
        device_attendance_type = self._get_device_attendance_type()
        today_start_utc, today_end_utc = self._get_today_range_utc()
        
        _logger.info(f"Hikvision: Fetch logs ({self.name}) - Mode: {fetch_mode}, Start: {start_str}")
        
        search_position = 0
        total_matches = None
        created_count = 0
        skipped_count = 0
        error_count = 0
        total_fetched = 0
        
        try:
            while True:
                payload = self._build_log_search_payload(search_position, start_str, end_str)
                response = self._make_request('POST', 'AccessControl/AcsEvent?format=json', data=json.dumps(payload))
                
                try:
                    data = response.json()
                except Exception:
                    return self._notify('JSON xatosi', f'Javob JSON formatida emas', 'danger', sticky=True)
                
                if total_matches is None:
                    total_matches = data.get('AcsEvent', {}).get('totalMatches', 0)
                
                if 'AcsEvent' in data and 'InfoList' in data['AcsEvent']:
                    logs = data['AcsEvent']['InfoList']
                    page_count = len(logs)
                    total_fetched += page_count
                    
                    logs_sorted = sorted(logs, key=lambda x: x.get('time', ''))
                    
                    for log in logs_sorted:
                        result = self._process_single_log(log, device_attendance_type, today_start_utc, today_end_utc)
                        if result == 'created':
                            created_count += 1
                        elif result == 'skipped':
                            skipped_count += 1
                        else:
                            error_count += 1
                    
                    search_position += DEFAULT_PAGE_SIZE
                    
                    if search_position >= total_matches or page_count < DEFAULT_PAGE_SIZE:
                        break
                else:
                    if search_position == 0 and fetch_mode == 'full_day':
                        return self._notify('Log topilmadi', f'Bugun uchun loglar mavjud emas', 'warning')
                    break
            
            # Muvaffaqiyatli yakunlandi - vaqtni yangilash
            self.last_fetch_time = now.astimezone(pytz.UTC).replace(tzinfo=None)
            
            # Agar incremental bo'lsa va yangi log bo'lmasa - jim turamiz (loglarni to'ldirmaslik uchun)
            if fetch_mode == 'incremental' and created_count == 0 and error_count == 0:
                 return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {'title': 'Sinxronizatsiya', 'message': 'Yangi loglar yo\'q', 'type': 'success', 'sticky': False}
                }

            message = f"Mode: {fetch_mode}, Jami: {total_matches}, Yangi: {created_count}"
            notif_type = 'success' if error_count == 0 else 'warning'
            return self._notify(f'Loglar yuklandi ({self.name})', message, notif_type)
            
        except Exception as e:
            return self._notify('Loglarni olishda xato', str(e), 'danger', sticky=True)

    def _determine_attendance_type(self, employee, log_time):
        """Check-in yoki Check-out ekanligini aniqlash."""
        today_start = log_time.replace(hour=0, minute=0, second=0, microsecond=0)
        today_end = today_start + timedelta(days=1)
        
        last_attendance = self.env['hr.attendance'].search([
            ('employee_id', '=', employee.id),
            ('check_in', '>=', today_start),
            ('check_in', '<', today_end)
        ], order='check_in desc', limit=1)
        
        if not last_attendance:
            return 'check_in'
        elif not last_attendance.check_out:
            return 'check_out'
        else:
            return 'check_in'
    
    def _process_attendance(self, employee, log_time, attendance_type):
        """HR Attendance yozuvini yaratish yoki yangilash."""
        today_start = log_time.replace(hour=0, minute=0, second=0, microsecond=0)
        today_end = today_start + timedelta(days=1)
        
        if attendance_type == 'check_in':
            existing = self.env['hr.attendance'].search([
                ('employee_id', '=', employee.id),
                ('check_in', '=', log_time)
            ])
            
            if not existing:
                self.env['hr.attendance'].create({
                    'employee_id': employee.id,
                    'check_in': log_time,
                })
                _logger.info(f"Attendance: {employee.name} - CHECK IN yaratildi ({log_time})")
                
        elif attendance_type == 'check_out':
            open_attendance = self.env['hr.attendance'].search([
                ('employee_id', '=', employee.id),
                ('check_in', '>=', today_start),
                ('check_in', '<', today_end),
                ('check_out', '=', False)
            ], order='check_in desc', limit=1)
            
            if open_attendance:
                open_attendance.write({'check_out': log_time})
                _logger.info(f"Attendance: {employee.name} - CHECK OUT belgilandi ({log_time})")
