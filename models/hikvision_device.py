# -*- coding: utf-8 -*-
"""
Hikvision Face ID Device Model

Bu modul Hikvision qurilmalari bilan integratsiya qiladi:
- Qurilmaga ulanish va test qilish
- Loglarni olish va qayta ishlash
- Xodimlarni qurilmaga sinxronizatsiya qilish
- Webhook orqali real-time loglarni qabul qilish
- Avtomatik check-out yaratish
"""

import json
import base64
import logging
import pytz
from datetime import datetime, timedelta
from urllib.parse import urlparse

import requests
from requests.auth import HTTPDigestAuth

from odoo import models, fields, api


# =====================================================
# KONSTANTALAR
# =====================================================
DEFAULT_TIMEZONE = 'Asia/Tashkent'
DEFAULT_PAGE_SIZE = 30
DEFAULT_WORK_END_TIME = "18:00"
DEFAULT_TIMEOUT = 10
MULTIPART_TIMEOUT = 30

# Hikvision Event Types
HIKVISION_MAJOR_ACCESS_CONTROL = 5  # Access Control Event
HIKVISION_MINOR_ALL = 0  # All sub-events

_logger = logging.getLogger(__name__)


class HikvisionDevice(models.Model):
    """Hikvision Face ID qurilmasini boshqarish modeli"""
    
    _name = 'hikvision.device'
    _description = 'Hikvision Face ID Device'

    # =====================================================
    # FIELDS
    # =====================================================
    name = fields.Char(string='Device Name', required=True)
    ip_address = fields.Char(string='IP Address', required=True)
    port = fields.Integer(string='Port', default=80, required=True)
    username = fields.Char(string='Username', required=True)
    password = fields.Char(string='Password', required=True)
    device_id = fields.Char(string='Device ID')
    state = fields.Selection([
        ('draft', 'Draft'),
        ('confirmed', 'Confirmed'),
        ('error', 'Error')
    ], string='Status', default='draft')
    last_fetch_time = fields.Datetime(string='Last Fetch Time')

    # =====================================================
    # HELPER METHODS
    # =====================================================
    
    def _notify(self, title, message, notif_type='success', sticky=False):
        """
        Foydalanuvchiga xabar ko'rsatish uchun helper method.
        
        Args:
            title: Xabar sarlavhasi
            message: Xabar matni
            notif_type: 'success', 'warning', 'danger', 'info'
            sticky: True bo'lsa, foydalanuvchi o'zi yopguncha turadi
        
        Returns:
            Odoo notification action dict
        """
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': title,
                'message': message,
                'type': notif_type,
                'sticky': sticky,
            }
        }
    
    def _get_local_timezone(self):
        """Lokal timezone ni olish"""
        return pytz.timezone(DEFAULT_TIMEZONE)
    
    def _get_today_range_utc(self):
        """
        Bugungi kunning boshi va oxirini UTC formatda qaytarish.
        
        Returns:
            tuple: (today_start_utc, today_end_utc)
        """
        local_tz = self._get_local_timezone()
        now = datetime.now(local_tz)
        
        start_time = now.replace(hour=0, minute=0, second=0, microsecond=0)
        end_time = now.replace(hour=23, minute=59, second=59, microsecond=0)
        
        today_start_utc = start_time.astimezone(pytz.UTC).replace(tzinfo=None)
        today_end_utc = end_time.astimezone(pytz.UTC).replace(tzinfo=None)
        
        return today_start_utc, today_end_utc
    
    def _parse_log_time(self, time_str):
        """
        Hikvision log vaqtini parse qilish.
        
        Args:
            time_str: ISO 8601 formatidagi vaqt string
        
        Returns:
            datetime: UTC formatidagi vaqt (tzinfo=None)
        """
        local_tz = self._get_local_timezone()
        
        if '+' in time_str:
            log_time_local = datetime.fromisoformat(time_str)
        else:
            log_time_local = datetime.strptime(time_str[:19], '%Y-%m-%dT%H:%M:%S')
            log_time_local = local_tz.localize(log_time_local)
        
        return log_time_local.astimezone(pytz.UTC).replace(tzinfo=None)
    
    def _get_device_attendance_type(self):
        """
        Qurilma nomidan attendance turini aniqlash.
        
        Returns:
            str or None: 'check_in', 'check_out', yoki None
        """
        device_name_lower = self.name.lower()
        
        if any(keyword in device_name_lower for keyword in ['check in', 'checkin', 'kirish']):
            return 'check_in'
        elif any(keyword in device_name_lower for keyword in ['check out', 'checkout', 'chiqish']):
            return 'check_out'
        return None

    # =====================================================
    # API REQUEST METHODS
    # =====================================================
    
    def _get_isapi_url(self, endpoint):
        """ISAPI endpoint URL'ini yaratish"""
        self.ensure_one()
        return f"http://{self.ip_address}:{self.port}/ISAPI/{endpoint}"

    def _make_request(self, method, endpoint, data=None, params=None):
        """
        Hikvision qurilmasiga HTTP so'rov yuborish.
        
        Args:
            method: 'GET', 'POST', 'PUT'
            endpoint: ISAPI endpoint (masalan: 'System/deviceInfo')
            data: Request body (string yoki dict)
            params: Query parameters
        
        Returns:
            requests.Response object
        
        Raises:
            Exception: Ulanish xatosi bo'lganda
        """
        self.ensure_one()
        
        url = self._get_isapi_url(endpoint)
        auth = HTTPDigestAuth(self.username, self.password)
        
        try:
            if method == 'GET':
                response = requests.get(url, auth=auth, params=params, timeout=DEFAULT_TIMEOUT)
            elif method == 'POST':
                response = requests.post(url, auth=auth, data=data, timeout=DEFAULT_TIMEOUT)
            elif method == 'PUT':
                response = requests.put(url, auth=auth, data=data, timeout=DEFAULT_TIMEOUT)
            else:
                raise ValueError(f"Unsupported HTTP method: {method}")
                
            response.raise_for_status()
            return response
            
        except requests.exceptions.RequestException as e:
            raise Exception(f"Connection failed: {str(e)}")
    
    def _make_request_multipart(self, method, endpoint, data=None, content_type=None):
        """
        Multipart so'rovlar uchun maxsus metod (fayllar yuklash uchun).
        
        Args:
            method: HTTP method
            endpoint: ISAPI endpoint
            data: Binary data
            content_type: Content-Type header
        
        Returns:
            requests.Response object
        """
        self.ensure_one()
        
        url = self._get_isapi_url(endpoint)
        auth = HTTPDigestAuth(self.username, self.password)
        
        headers = {}
        if content_type:
            headers['Content-Type'] = content_type
        
        try:
            response = requests.post(url, auth=auth, data=data, headers=headers, timeout=MULTIPART_TIMEOUT)
            response.raise_for_status()
            return response
        except requests.exceptions.RequestException as e:
            raise Exception(f"Upload error: {str(e)}")

    # =====================================================
    # DEVICE ACTIONS
    # =====================================================
    
    def action_test_connection(self):
        """Qurilma bilan ulanishni test qilish"""
        self.ensure_one()
        try:
            self._make_request('GET', 'System/deviceInfo')
            self.state = 'confirmed'
            return self._notify('Muvaffaqiyatli', 'Qurilmaga ulanish muvaffaqiyatli!')
        except Exception as e:
            self.state = 'error'
            return self._notify('Ulanish xatosi', str(e), 'danger', sticky=True)

    # =====================================================
    # LOG FETCHING METHODS
    # =====================================================
    
    def _build_log_search_payload(self, search_position, start_str, end_str):
        """
        Hikvision log qidirish uchun payload yaratish.
        
        Args:
            search_position: Pagination uchun pozitsiya
            start_str: Boshlanish vaqti (ISO 8601)
            end_str: Tugash vaqti (ISO 8601)
        
        Returns:
            dict: API payload
        """
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
    
    def _get_attendance_type_from_label(self, label):
        """
        Log label'dan attendance turini aniqlash.
        
        Args:
            label: Log label string
        
        Returns:
            str or None: 'check_in', 'check_out', yoki None
        """
        label_lower = label.lower()
        if 'check in' in label_lower:
            return 'check_in'
        elif 'check out' in label_lower:
            return 'check_out'
        return None
    
    def _should_process_log(self, attendance_type, open_attendance, employee_name):
        """
        Logni qayta ishlash kerakligini aniqlash.
        
        Args:
            attendance_type: 'check_in' yoki 'check_out'
            open_attendance: Mavjud ochiq attendance record
            employee_name: Xodim ismi (logging uchun)
        
        Returns:
            bool: True agar qayta ishlash kerak bo'lsa
        """
        if attendance_type == 'check_in':
            if not open_attendance:
                _logger.info(f"Hikvision: {employee_name} - CHECK IN qabul qilindi")
                return True
            else:
                _logger.debug(f"Hikvision: {employee_name} - CHECK IN o'tkazib yuborildi (ochiq attendance mavjud)")
                return False
                
        elif attendance_type == 'check_out':
            if open_attendance:
                _logger.info(f"Hikvision: {employee_name} - CHECK OUT qabul qilindi")
                return True
            else:
                _logger.debug(f"Hikvision: {employee_name} - CHECK OUT o'tkazib yuborildi (ochiq attendance yo'q)")
                return False
        
        return False
    
    def _process_single_log(self, log, device_attendance_type, today_start_utc, today_end_utc):
        """
        Bitta logni qayta ishlash.
        
        Args:
            log: Hikvision log dict
            device_attendance_type: Qurilma nomidan aniqlangan tur
            today_start_utc: Bugungi kun boshi (UTC)
            today_end_utc: Bugungi kun oxiri (UTC)
        
        Returns:
            str: 'created', 'skipped', yoki 'error'
        """
        try:
            employee_no = log.get('employeeNoString')
            time_str = log.get('time')
            
            if not employee_no or not time_str:
                return 'skipped'
            
            # Attendance type aniqlash
            if device_attendance_type:
                attendance_type = device_attendance_type
            else:
                label = log.get('label', '')
                attendance_type = self._get_attendance_type_from_label(label)
                if not attendance_type:
                    _logger.warning(f"Hikvision: Tur aniqlanmadi. Device: '{self.name}', Label: '{label}'")
                    return 'skipped'
            
            # Vaqtni parse qilish
            log_time_utc = self._parse_log_time(time_str)
            
            # Xodimni topish
            employee = self.env['hr.employee'].search([('barcode', '=', employee_no)], limit=1)
            if not employee:
                _logger.warning(f"Hikvision: Employee not found for barcode {employee_no}")
                return 'skipped'
            
            # Mavjud logni tekshirish
            existing_log = self.env['hikvision.log'].search([
                ('device_id', '=', self.id),
                ('timestamp', '=', log_time_utc),
                ('employee_id', '=', employee.id)
            ])
            if existing_log:
                return 'skipped'
            
            # Ochiq attendance tekshirish
            open_attendance = self.env['hr.attendance'].search([
                ('employee_id', '=', employee.id),
                ('check_in', '>=', today_start_utc),
                ('check_in', '<', today_end_utc),
                ('check_out', '=', False)
            ], order='check_in desc', limit=1)
            
            # Qayta ishlash kerakligini aniqlash
            if not self._should_process_log(attendance_type, open_attendance, employee.name):
                return 'skipped'
            
            # Hikvision logini saqlash
            self.env['hikvision.log'].create({
                'device_id': self.id,
                'employee_id': employee.id,
                'timestamp': log_time_utc,
                'attendance_type': attendance_type,
            })
            
            # HR Attendance yozuvini yaratish/yangilash
            self._process_attendance(employee, log_time_utc, attendance_type)
            
            return 'created'
            
        except Exception as e:
            _logger.error(f"Hikvision: Error processing log: {str(e)}")
            return 'error'
    
    def action_fetch_logs(self):
        """
        Hikvision qurilmasidan davomat loglarini olish va Odoo ga import qilish.
        
        Bu metod:
        1. Qurilma nomidan attendance type aniqlaydi
        2. Pagination orqali barcha bugungi loglarni oladi
        3. Har bir logni qayta ishlab, hr.attendance yaratadi/yangilaydi
        
        Returns:
            Odoo notification action dict
        """
        self.ensure_one()
        
        local_tz = self._get_local_timezone()
        now = datetime.now(local_tz)
        
        # Bugungi kunning vaqt oralig'i
        start_time = now.replace(hour=0, minute=0, second=0, microsecond=0)
        end_time = now.replace(hour=23, minute=59, second=59, microsecond=0)
        start_str = start_time.isoformat(timespec='seconds')
        end_str = end_time.isoformat(timespec='seconds')
        
        # Attendance type aniqlash
        device_attendance_type = self._get_device_attendance_type()
        _logger.info(f"Hikvision [{self.name}]: Fetching logs. Device type: {device_attendance_type or 'AUTO'}")
        
        # UTC vaqtlar
        today_start_utc, today_end_utc = self._get_today_range_utc()
        
        # Pagination sozlamalari
        search_position = 0
        total_matches = None
        
        # Hisoblagichlar
        created_count = 0
        skipped_count = 0
        error_count = 0
        total_fetched = 0
        
        try:
            while True:
                payload = self._build_log_search_payload(search_position, start_str, end_str)
                _logger.info(f"Hikvision [{self.name}]: Fetching page at position {search_position}")
                
                response = self._make_request('POST', 'AccessControl/AcsEvent?format=json', data=json.dumps(payload))
                
                try:
                    data = response.json()
                except Exception:
                    return self._notify('JSON xatosi', f'Javob JSON formatida emas: {response.text[:200]}', 'danger', sticky=True)
                
                # Total matches ni olish
                if total_matches is None:
                    total_matches = data.get('AcsEvent', {}).get('totalMatches', 0)
                    _logger.info(f"Hikvision [{self.name}]: Total logs today: {total_matches}")
                
                # Loglarni qayta ishlash
                if 'AcsEvent' in data and 'InfoList' in data['AcsEvent']:
                    logs = data['AcsEvent']['InfoList']
                    page_count = len(logs)
                    total_fetched += page_count
                    
                    _logger.info(f"Hikvision [{self.name}]: Got {page_count} logs (position {search_position})")
                    
                    # Vaqt bo'yicha tartiblash
                    logs_sorted = sorted(logs, key=lambda x: x.get('time', ''))
                    
                    for log in logs_sorted:
                        result = self._process_single_log(log, device_attendance_type, today_start_utc, today_end_utc)
                        if result == 'created':
                            created_count += 1
                        elif result == 'skipped':
                            skipped_count += 1
                        else:
                            error_count += 1
                    
                    # Keyingi sahifa
                    search_position += DEFAULT_PAGE_SIZE
                    
                    if search_position >= total_matches or page_count < DEFAULT_PAGE_SIZE:
                        break
                else:
                    if search_position == 0:
                        return self._notify('Log topilmadi', f'Bugun uchun loglar mavjud emas. Qurilma: {self.name}', 'warning')
                    break
            
            # Last fetch vaqtini yangilash
            self.last_fetch_time = now.astimezone(pytz.UTC).replace(tzinfo=None)
            
            _logger.info(f"Hikvision [{self.name}]: Fetch complete. Total: {total_matches}, Fetched: {total_fetched}, Created: {created_count}, Skipped: {skipped_count}")
            
            message = f"Jami loglar: {total_matches} ta, Olingan: {total_fetched} ta, Yaratildi: {created_count} ta, O'tkazib yuborildi: {skipped_count} ta"
            notif_type = 'success' if error_count == 0 else 'warning'
            return self._notify(f'Loglar muvaffaqiyatli yuklandi ({self.name})', message, notif_type)
            
        except Exception as e:
            return self._notify('Loglarni olishda xato', str(e), 'danger', sticky=True)

    # =====================================================
    # ATTENDANCE PROCESSING
    # =====================================================
    
    def _determine_attendance_type(self, employee, log_time):
        """
        Check-in yoki Check-out ekanligini aniqlash.
        
        Bu metod webhook controller tomonidan ishlatiladi.
        
        Args:
            employee: hr.employee record
            log_time: Log vaqti (UTC)
        
        Returns:
            str: 'check_in' yoki 'check_out'
        """
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
        """
        HR Attendance yozuvini yaratish yoki yangilash.
        
        Args:
            employee: hr.employee record
            log_time: Log vaqti (UTC)
            attendance_type: 'check_in' yoki 'check_out'
        """
        today_start = log_time.replace(hour=0, minute=0, second=0, microsecond=0)
        today_end = today_start + timedelta(days=1)
        
        if attendance_type == 'check_in':
            # Dublikat tekshirish
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

    # =====================================================
    # USER SYNC METHODS
    # =====================================================
    
    def action_sync_users(self):
        """Odoo xodimlarini Hikvision qurilmasiga sinxronizatsiya qilish"""
        self.ensure_one()
        
        employees = self.env['hr.employee'].search([
            ('barcode', '!=', False),
            ('active', '=', True)
        ])
        
        if not employees:
            return self._notify('Xodimlar topilmadi', 
                              "Sinxronizatsiya uchun barcode mavjud bo'lgan xodimlar topilmadi.", 
                              'warning')
        
        success_count = 0
        face_success_count = 0
        error_count = 0
        face_errors = []
        errors = []
        
        for emp in employees:
            try:
                self._upload_user_info(emp)
                success_count += 1
                
                if emp.image_1920:
                    try:
                        self._upload_face_data(emp)
                        face_success_count += 1
                    except Exception as face_err:
                        face_errors.append(f"{emp.name}: {str(face_err)}")
                        
            except Exception as e:
                error_count += 1
                errors.append(f"{emp.name}: {str(e)}")
        
        # Natija xabari
        msg_parts = [f'Foydalanuvchilar: {success_count} ta yuklandi']
        if face_success_count > 0:
            msg_parts.append(f'Yuz rasmlari: {face_success_count} ta yuklandi')
        if face_errors:
            msg_parts.append(f'Yuz xatolari: {len(face_errors)} ta')
            # Batafsil xatolikni ko'rsatish
            for fe in face_errors[:3]:  # Birinchi 3 ta xatolik
                msg_parts.append(f'  → {fe}')
        if error_count > 0:
            msg_parts.append(f'Xatolar: {error_count} ta')
            
        notif_type = 'success' if error_count == 0 and not face_errors else 'warning'
        sticky = error_count > 0 or len(face_errors) > 0
        
        return self._notify('Sinxronizatsiya yakunlandi', '. '.join(msg_parts), notif_type, sticky)
    
    def _upload_user_info(self, employee):
        """Xodim ma'lumotlarini Hikvision qurilmasiga yuklash"""
        user_data = {
            "UserInfo": {
                "employeeNo": employee.barcode,
                "name": employee.name,
                "userType": "normal",
                "Valid": {
                    "enable": True,
                    "beginTime": "2020-01-01T00:00:00",
                    "endTime": "2030-12-31T23:59:59",
                    "timeType": "local"
                },
                "doorRight": "1",
                "RightPlan": [{
                    "doorNo": 1,
                    "planTemplateNo": "1"
                }]
            }
        }
        
        self._make_request('POST', 'AccessControl/UserInfo/Record?format=json', data=json.dumps(user_data))
    
    def _upload_face_data(self, employee):
        """
        Xodim yuz rasmini Hikvision qurilmasiga yuklash.
        
        Args:
            employee: hr.employee record
        
        Raises:
            Exception: Yuklash xatosi bo'lganda
        """
        import io
        from PIL import Image
        
        _logger.info(f"Hikvision: Yuz rasmini yuklash boshlanmoqda - {employee.name} (barcode: {employee.barcode})")
        
        image_data = employee.image_1920
        
        if not image_data:
            raise Exception(f"Xodimda rasm mavjud emas")
        
        # Base64 string ni olish
        if isinstance(image_data, bytes):
            image_base64 = image_data.decode('utf-8')
        else:
            image_base64 = image_data
        
        # Rasmni decode qilish
        try:
            image_bytes = base64.b64decode(image_base64)
            _logger.debug(f"Hikvision: Rasm hajmi - {len(image_bytes)} bytes")
        except Exception as e:
            raise Exception(f"Base64 decode xatosi: {str(e)}")
        
        # Rasmni JPEG formatga convert qilish va o'lchamini optimallashtirish
        try:
            img = Image.open(io.BytesIO(image_bytes))
            _logger.debug(f"Hikvision: Rasm formati - {img.format}, o'lchami - {img.size}")
            
            # Agar RGBA (PNG) bo'lsa, RGB ga convert qilish
            if img.mode in ('RGBA', 'P'):
                img = img.convert('RGB')
            elif img.mode != 'RGB':
                img = img.convert('RGB')
            
            # Hikvision uchun rasm o'lchamini optimallashtirish (maksimum 640x480)
            max_size = (640, 480)
            if img.size[0] > max_size[0] or img.size[1] > max_size[1]:
                img.thumbnail(max_size, Image.Resampling.LANCZOS)
                _logger.debug(f"Hikvision: Rasm o'lchami o'zgartirildi - {img.size}")
            
            # JPEG formatga o'tkazish
            output_buffer = io.BytesIO()
            img.save(output_buffer, format='JPEG', quality=80)
            image_bytes = output_buffer.getvalue()
            _logger.info(f"Hikvision: JPEG hajmi - {len(image_bytes)} bytes, o'lcham - {img.size}")
            
        except Exception as e:
            raise Exception(f"Rasm konvertatsiya xatosi: {str(e)}")
        
        # Hikvision ISAPI multipart format
        boundary = "----HikvisionBoundaryABC123"
        
        # ============================================
        # Access Control qurilmalari uchun FaceInfo
        # employeeNo - xodimning barcode/ID raqami
        # ============================================
        face_info_ac = {
            "FaceInfo": {
                "employeeNo": str(employee.barcode),
                "faceDataURL": ""
            }
        }
        
        # Intelligent FDLib uchun format (boshqa qurilmalar uchun)
        face_info_fdlib = {
            "faceLibType": "blackFD",
            "FDID": "1",
            "FPID": str(employee.barcode),
            "name": employee.name
        }
        
        # Access Control uchun multipart body
        def build_multipart_body(face_json, img_field_name="img"):
            body = b''
            body += f'--{boundary}\r\n'.encode('utf-8')
            body += b'Content-Disposition: form-data; name="FaceDataRecord"\r\n'
            body += b'Content-Type: application/json\r\n\r\n'
            body += json.dumps(face_json).encode('utf-8')
            body += b'\r\n'
            body += f'--{boundary}\r\n'.encode('utf-8')
            body += f'Content-Disposition: form-data; name="{img_field_name}"; filename="face.jpg"\r\n'.encode('utf-8')
            body += b'Content-Type: image/jpeg\r\n\r\n'
            body += image_bytes
            body += b'\r\n'
            body += f'--{boundary}--\r\n'.encode('utf-8')
            return body
        
        content_type = f'multipart/form-data; boundary={boundary}'
        
        # Turli xil endpointlarni sinab ko'ramiz
        configs_to_try = [
            # Access Control qurilmalari uchun
            ('AccessControl/FaceDataRecord?format=json', face_info_ac, 'img'),
            # Access Control - boshqa field nomi bilan
            ('AccessControl/FaceDataRecord?format=json', face_info_ac, 'FaceImage'),
            # Intelligent FDLib (NVR/DVR uchun)
            ('Intelligent/FDLib/FaceDataRecord?format=json&FDID=1&faceLibType=blackFD', face_info_fdlib, 'FaceImage'),
        ]
        
        last_error = None
        for endpoint, face_json, img_field in configs_to_try:
            try:
                body = build_multipart_body(face_json, img_field)
                _logger.info(f"Hikvision: Sinayapti - {endpoint} (img field: {img_field})")
                response = self._make_request_multipart('POST', endpoint, data=body, content_type=content_type)
                
                # Response ni tekshirish
                try:
                    resp_text = response.text
                    _logger.info(f"Hikvision: Javob - {resp_text[:200]}")
                except:
                    pass
                
                _logger.info(f"Hikvision: Yuz rasmi muvaffaqiyatli yuklandi - {employee.name}")
                return
                
            except Exception as e:
                last_error = str(e)
                _logger.warning(f"Hikvision: {endpoint} ishlamadi - {last_error}")
                continue
        
        # Barcha konfiguratsiyalar ishlamadi
        raise Exception(f"Yuz yuklash muvaffaqiyatsiz: {last_error}")

    # =====================================================
    # DEVICE MANAGEMENT ACTIONS
    # =====================================================
    
    def action_delete_all_users(self):
        """Qurilmadagi barcha foydalanuvchilarni o'chirish"""
        self.ensure_one()
        
        delete_data = {
            "UserInfoDelCond": {
                "EmployeeNoList": [
                    {"employeeNo": "deleteAllUsers"}
                ]
            }
        }
        
        try:
            self._make_request('PUT', 'AccessControl/UserInfo/Delete?format=json', data=json.dumps(delete_data))
            return self._notify('Muvaffaqiyatli', "Qurilmadagi barcha foydalanuvchilar o'chirildi.")
        except Exception as e:
            return self._notify('Xato', str(e), 'danger', sticky=True)
    
    def action_get_device_users(self):
        """Qurilmadagi foydalanuvchilar sonini olish"""
        self.ensure_one()
        
        search_data = {
            "UserInfoSearchCond": {
                "searchID": "1",
                "searchResultPosition": 0,
                "maxResults": 1
            }
        }
        
        try:
            response = self._make_request('POST', 'AccessControl/UserInfo/Search?format=json', 
                                         data=json.dumps(search_data))
            data = response.json()
            total = data.get('UserInfoSearch', {}).get('totalMatches', 0)
            
            return self._notify("Qurilma ma'lumotlari", f'Qurilmada {total} ta foydalanuvchi mavjud.', 'info')
        except Exception as e:
            return self._notify('Xato', str(e), 'danger', sticky=True)

    # =====================================================
    # WEBHOOK CONFIGURATION
    # =====================================================
    
    def action_configure_webhook(self):
        """
        Hikvision qurilmasida HTTP Host konfiguratsiya qilish.
        Bu qurilmaga Odoo webhook URL'ini sozlaydi.
        """
        self.ensure_one()
        
        base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url')
        webhook_url = f"{base_url}/hikvision/webhook"
        
        parsed = urlparse(base_url)
        host_ip = parsed.hostname
        host_port = parsed.port or (443 if parsed.scheme == 'https' else 80)
        
        http_host_config = {
            "HttpHostNotification": {
                "id": "1",
                "url": "/hikvision/webhook",
                "protocolType": "HTTP",
                "parameterFormatType": "JSON",
                "addressingFormatType": "ipaddress",
                "ipAddress": host_ip,
                "portNo": host_port,
                "httpAuthenticationMethod": "none"
            }
        }
        
        try:
            self._make_request('PUT', 'Event/notification/httpHosts/1?format=json', 
                             data=json.dumps(http_host_config))
            return self._notify('Webhook sozlandi', f'Qurilma hodisalarni {webhook_url} ga yuboradi.')
        except Exception as e:
            return self._notify('Xato', f'Webhook sozlashda xato: {str(e)}', 'danger', sticky=True)

    # =====================================================
    # CRON JOBS
    # =====================================================
    
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
        Ochiq attendance'larni xodimning ish jadvali (resource.calendar) ga asosan
        avtomatik check-out qilish.
        """
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
        """
        Bitta ochiq attendance ni avtomatik yopish.
        
        Args:
            attendance: hr.attendance record
            now_local: Hozirgi vaqt (local timezone)
        
        Returns:
            str: 'closed' yoki 'skipped'
        """
        try:
            employee = attendance.employee_id
            calendar = employee.resource_calendar_id
            
            if not calendar:
                _logger.warning(f"Auto-close: {employee.name} uchun ish jadvali yo'q")
                return 'skipped'
            
            tz = pytz.timezone(calendar.tz or DEFAULT_TIMEZONE)
            
            # Check-in vaqtini local qilish
            check_in_utc = attendance.check_in
            if check_in_utc.tzinfo is None:
                check_in_aware = pytz.UTC.localize(check_in_utc)
            else:
                check_in_aware = check_in_utc
            check_in_local = check_in_aware.astimezone(tz)
            
            # Shu kunning boshi va oxiri
            day_start = tz.localize(datetime.combine(check_in_local.date(), datetime.min.time()))
            day_end = tz.localize(datetime.combine(check_in_local.date(), datetime.max.time()))
            
            # Ish vaqtlarini olish
            expected_end = self._get_expected_work_end(calendar, employee, day_start, day_end, tz, check_in_local)
            
            # Hozirgi vaqt ish vaqti tugashidan keyin bo'lsa yopamiz
            now_aware = now_local.astimezone(tz) if now_local.tzinfo else tz.localize(now_local)
            
            if now_aware >= expected_end:
                check_out_utc = expected_end.astimezone(pytz.UTC).replace(tzinfo=None)
                attendance.write({'check_out': check_out_utc})
                
                # Hikvision logini yaratish
                device = self.search([('state', '=', 'confirmed')], limit=1)
                if device:
                    self.env['hikvision.log'].create({
                        'device_id': device.id,
                        'employee_id': employee.id,
                        'timestamp': check_out_utc,
                        'attendance_type': 'check_out',
                    })
                
                _logger.info(f"Auto-close: {employee.name} avtomatik check-out qilindi ({expected_end.strftime('%H:%M')})")
                return 'closed'
            else:
                _logger.debug(f"Auto-close: {employee.name} ish vaqti hali tugamagan ({expected_end.strftime('%H:%M')})")
                return 'skipped'
                
        except Exception as e:
            _logger.error(f"Auto-close error for {attendance.employee_id.name}: {str(e)}")
            return 'skipped'
    
    def _get_expected_work_end(self, calendar, employee, day_start, day_end, tz, check_in_local):
        """
        Xodimning kutilgan ish tugash vaqtini aniqlash.
        
        Args:
            calendar: resource.calendar record
            employee: hr.employee record
            day_start: Kun boshi (tzinfo bilan)
            day_end: Kun oxiri (tzinfo bilan)
            tz: Timezone object
            check_in_local: Check-in vaqti (local)
        
        Returns:
            datetime: Kutilgan ish tugash vaqti (tzinfo bilan)
        """
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
            # Default: 18:00
            expected_end = tz.localize(datetime.combine(
                check_in_local.date(), 
                datetime.strptime(DEFAULT_WORK_END_TIME, "%H:%M").time()
            ))
            _logger.info(f"Auto-close: {employee.name} uchun default {DEFAULT_WORK_END_TIME} ishlatilmoqda")
        
        return expected_end

    # =====================================================
    # LEAVE SYNC METHODS
    # =====================================================
    
    def _disable_user_on_device(self, employee):
        """
        Xodimni qurilmada vaqtincha bloklash (ta'til uchun).
        
        Args:
            employee: hr.employee record
        
        Raises:
            Exception: API xatosi bo'lganda
        """
        self.ensure_one()
        
        if not employee.barcode:
            raise Exception(f"Xodimda barcode mavjud emas: {employee.name}")
        
        user_data = {
            "UserInfo": {
                "employeeNo": str(employee.barcode),
                "userType": "blackList"  # userType: blackList - to'liq bloklash (yuz tanish ham ishlamaydi)
            }
        }
        
        self._make_request('PUT', 'AccessControl/UserInfo/Modify?format=json', 
                          data=json.dumps(user_data))
        _logger.info(f"Hikvision [{self.name}]: {employee.name} bloklandi (barcode: {employee.barcode})")
    
    def _enable_user_on_device(self, employee):
        """
        Xodimni qurilmada qayta yoqish (ta'til tugagach).
        
        Args:
            employee: hr.employee record
        
        Raises:
            Exception: API xatosi bo'lganda
        """
        self.ensure_one()
        
        if not employee.barcode:
            raise Exception(f"Xodimda barcode mavjud emas: {employee.name}")
        
        user_data = {
            "UserInfo": {
                "employeeNo": str(employee.barcode),
                "userType": "normal",  # userType: normal - oddiy foydalanuvchi sifatida tiklash
                "Valid": {
                    "enable": True,
                    "beginTime": "2020-01-01T00:00:00",
                    "endTime": "2030-12-31T23:59:59",
                    "timeType": "local"
                }
            }
        }
        
        self._make_request('PUT', 'AccessControl/UserInfo/Modify?format=json', 
                          data=json.dumps(user_data))
        _logger.info(f"Hikvision [{self.name}]: {employee.name} yoqildi (barcode: {employee.barcode})")
    
    @api.model
    def _cron_sync_leave_status(self):
        """
        Kunlik cron job: Ta'til, davlat bayrami va dam olish kuniga ko'ra 
        xodimlarni qurilmada bloklash/yoqish.
        
        Prioritet tartibi:
        1. Shaxsiy ta'til (hr.leave)
        2. Davlat bayrami (resource.calendar.leaves - global)
        3. Dam olish kuni (resource.calendar - haftalik jadval)
        """
        today = fields.Date.today()
        weekday = today.weekday()  # 0=Dushanba, 6=Yakshanba
        
        _logger.info(f"Hikvision: Kirish huquqi sinxronizatsiyasi boshlandi ({today}, hafta kuni: {weekday})")
        
        # 1. Barcode mavjud barcha faol xodimlar (bitta query)
        employees = self.env['hr.employee'].search([
            ('barcode', '!=', False),
            ('active', '=', True)
        ])
        
        if not employees:
            _logger.info("Hikvision: Barcode mavjud xodimlar topilmadi")
            return
        
        # 2. Bugun TO'LIQ KUNLIK ta'tilda bo'lgan xodimlar ID larini olish
        # Yarim kunlik (half day) va soatlik ta'tillar bloklanmaydi
        active_leaves = self.env['hr.leave'].search([
            ('state', '=', 'validate'),
            ('date_from', '<=', today),
            ('date_to', '>=', today),
            ('request_unit_half', '=', False),   # Yarim kunlik emas
            ('request_unit_hours', '=', False),  # Soatlik emas
        ])
        employees_on_leave_ids = set(active_leaves.mapped('employee_id').ids)
        
        # 3. Bugun DAVLAT BAYRAMI bormi? (global - resource_id bo'sh)
        today_datetime = datetime.combine(today, datetime.min.time())
        public_holidays = self.env['resource.calendar.leaves'].search([
            ('date_from', '<=', today_datetime),
            ('date_to', '>=', today_datetime),
            ('resource_id', '=', False),  # Global bayram (barcha uchun)
        ])
        is_public_holiday = bool(public_holidays)
        if is_public_holiday:
            holiday_name = public_holidays[0].name
            _logger.info(f"Hikvision: Bugun davlat bayrami - {holiday_name}")
        
        # 4. Xodimlarni bloklash/yoqish ro'yxatlarini tayyorlash
        to_block = []  # Bloklanishi kerak bo'lgan xodimlar
        to_enable = []  # Yoqilishi kerak bo'lgan xodimlar
        
        for emp in employees:
            should_block = False
            reason = ""
            
            # Prioritet 1: Shaxsiy ta'til
            if emp.id in employees_on_leave_ids:
                should_block = True
                reason = "ta'til"
            
            # Prioritet 2: Davlat bayrami
            elif is_public_holiday:
                should_block = True
                reason = f"davlat bayrami ({holiday_name})"
            
            # Prioritet 3: Dam olish kuni
            elif not self._is_working_day(emp, weekday):
                should_block = True
                reason = "dam olish kuni"
            
            if should_block:
                to_block.append((emp, reason))
            else:
                to_enable.append(emp)
        
        # 4. Qurilmalarda sinxronlash (batch processing)
        devices = self.search([('state', '=', 'confirmed')])
        
        if not devices:
            _logger.warning("Hikvision: Tasdiqlangan qurilmalar topilmadi")
            return
        
        disabled_count = 0
        enabled_count = 0
        error_count = 0
        
        for device in devices:
            # Bloklash
            for emp, reason in to_block:
                try:
                    device._disable_user_on_device(emp)
                    disabled_count += 1
                    _logger.debug(f"Hikvision: {emp.name} bloklandi ({reason})")
                except Exception as e:
                    _logger.error(f"Hikvision: {emp.name} bloklashda xato: {str(e)}")
                    error_count += 1
            
            # Yoqish
            for emp in to_enable:
                try:
                    device._enable_user_on_device(emp)
                    enabled_count += 1
                except Exception as e:
                    _logger.error(f"Hikvision: {emp.name} yoqishda xato: {str(e)}")
                    error_count += 1
        
        _logger.info(f"Hikvision: Sinxronizatsiya yakunlandi. Bloklangan: {disabled_count}, Yoqilgan: {enabled_count}, Xatolar: {error_count}")
    
    def _is_working_day(self, employee, weekday):
        """
        Xodimning ish jadvali bo'yicha berilgan hafta kuni ish kunmi?
        
        Args:
            employee: hr.employee record
            weekday: Hafta kuni (0=Dushanba, 6=Yakshanba)
        
        Returns:
            bool: True agar ish kuni bo'lsa
        """
        calendar = employee.resource_calendar_id
        
        if not calendar:
            # Ish jadvali yo'q - default: ish kuni deb hisoblaymiz
            return True
        
        # Ish jadvalida shu hafta kuni bormi?
        return any(
            int(att.dayofweek) == weekday and att.day_period in ('morning', 'afternoon')
            for att in calendar.attendance_ids
        )
    
    def action_sync_leave_status(self):
        """Qo'lda ta'til va dam olish kunini sinxronlash tugmasi"""
        self.ensure_one()
        
        today = fields.Date.today()
        weekday = today.weekday()
        
        # Barcode mavjud barcha xodimlar
        employees = self.env['hr.employee'].search([
            ('barcode', '!=', False),
            ('active', '=', True)
        ])
        
        if not employees:
            return self._notify("Sinxronizatsiya", "Barcode mavjud xodimlar topilmadi.", 'warning')
        
        # TO'LIQ KUNLIK ta'tilda bo'lgan xodimlar (yarim kun va soatlik bloklanmaydi)
        active_leaves = self.env['hr.leave'].search([
            ('state', '=', 'validate'),
            ('date_from', '<=', today),
            ('date_to', '>=', today),
            ('request_unit_half', '=', False),   # Yarim kunlik emas
            ('request_unit_hours', '=', False),  # Soatlik emas
        ])
        employees_on_leave_ids = set(active_leaves.mapped('employee_id').ids)
        
        # Davlat bayrami tekshirish
        today_datetime = datetime.combine(today, datetime.min.time())
        public_holidays = self.env['resource.calendar.leaves'].search([
            ('date_from', '<=', today_datetime),
            ('date_to', '>=', today_datetime),
            ('resource_id', '=', False),
        ])
        is_public_holiday = bool(public_holidays)
        holiday_name = public_holidays[0].name if is_public_holiday else ""
        
        # Bloklanishi kerak bo'lgan xodimlar
        to_block = []
        for emp in employees:
            if emp.id in employees_on_leave_ids:
                to_block.append((emp, "ta'til"))
            elif is_public_holiday:
                to_block.append((emp, f"davlat bayrami ({holiday_name})"))
            elif not self._is_working_day(emp, weekday):
                to_block.append((emp, "dam olish kuni"))
        
        if not to_block:
            return self._notify("Sinxronizatsiya", "Bugun bloklanishi kerak bo'lgan xodimlar yo'q.", 'info')
        
        disabled_count = 0
        error_count = 0
        errors = []
        
        for emp, reason in to_block:
            try:
                self._disable_user_on_device(emp)
                disabled_count += 1
            except Exception as e:
                error_count += 1
                errors.append(f"{emp.name}: {str(e)}")
        
        if error_count == 0:
            return self._notify("Sinxronizatsiya muvaffaqiyatli", 
                              f"{disabled_count} ta xodim bloklandi.", 'success')
        else:
            msg = f"Bloklangan: {disabled_count}, Xatolar: {error_count}"
            if errors:
                msg += ". " + "; ".join(errors[:3])
            return self._notify("Sinxronizatsiya", msg, 'warning', sticky=True)
