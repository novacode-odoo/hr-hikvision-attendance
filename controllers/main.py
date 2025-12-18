from odoo import http
from odoo.http import request
import json
import logging
import pytz
from datetime import datetime

_logger = logging.getLogger(__name__)


class HikvisionWebhookController(http.Controller):
    """
    Hikvision qurilmasidan real vaqtda hodisalarni qabul qilish uchun controller.
    
    Bu webhook Hikvision qurilmasida HTTP Host sifatida konfiguratsiya qilinishi kerak.
    URL: http://<odoo-ip>:<port>/hikvision/webhook
    """
    
    @http.route('/hikvision/webhook', type='json', auth='public', methods=['POST'], csrf=False)
    def receive_event(self, **kwargs):
        """
        Hikvision qurilmasidan kelgan Access Control hodisalarini qabul qilish.
        
        Hikvision quyidagi formatda JSON yuboradi:
        {
            "ipAddress": "192.168.1.64",
            "dateTime": "2025-12-06T10:30:00+05:00",
            "eventType": "AccessControlEvent",
            "eventState": "active",
            "eventDescription": "Face Recognition",
            "AccessControllerEvent": {
                "deviceName": "Access Controller",
                "majorEventType": 5,
                "subEventType": 1,
                "employeeNoString": "12345",
                "name": "Employee Name",
                ...
            }
        }
        """
        try:
            # Request JSON ma'lumotlarini olish
            data = request.jsonrequest
            
            if not data:
                _logger.warning("Hikvision webhook: Empty request received")
                return {'status': 'error', 'message': 'Empty request'}
            
            _logger.info(f"Hikvision webhook: Received event: {json.dumps(data)[:500]}")
            
            # Access Control Event ma'lumotlarini olish
            ac_event = data.get('AccessControllerEvent', {})
            
            employee_no = ac_event.get('employeeNoString')
            time_str = data.get('dateTime')
            major_type = ac_event.get('majorEventType')
            
            # Faqat davomat hodisalarini qayta ishlash (majorEventType = 5)
            if major_type != 5:
                _logger.info(f"Hikvision webhook: Ignoring non-attendance event (majorType={major_type})")
                return {'status': 'ignored', 'message': 'Not an attendance event'}
            
            if not employee_no or not time_str:
                _logger.warning(f"Hikvision webhook: Missing employee_no or time")
                return {'status': 'error', 'message': 'Missing required fields'}
            
            # Xodimni topish
            employee = request.env['hr.employee'].sudo().search([
                ('barcode', '=', employee_no)
            ], limit=1)
            
            if not employee:
                _logger.warning(f"Hikvision webhook: Employee not found for barcode {employee_no}")
                return {'status': 'error', 'message': f'Employee not found: {employee_no}'}
            
            # Vaqtni parse qilish
            local_tz = pytz.timezone('Asia/Tashkent')
            
            if '+' in time_str:
                log_time_local = datetime.fromisoformat(time_str)
            else:
                log_time_local = datetime.strptime(time_str[:19], '%Y-%m-%dT%H:%M:%S')
                log_time_local = local_tz.localize(log_time_local)
            
            # UTC ga o'tkazish
            log_time_utc = log_time_local.astimezone(pytz.UTC).replace(tzinfo=None)
            
            # Qurilmani topish (IP bo'yicha)
            ip_address = data.get('ipAddress')
            device = request.env['hikvision.device'].sudo().search([
                ('ip_address', '=', ip_address),
                ('state', '=', 'confirmed')
            ], limit=1)
            
            if not device:
                # Birinchi tasdiqlangan qurilmani olish
                device = request.env['hikvision.device'].sudo().search([
                    ('state', '=', 'confirmed')
                ], limit=1)
            
            if device:
                # Mavjud logni tekshirish
                existing_log = request.env['hikvision.log'].sudo().search([
                    ('device_id', '=', device.id),
                    ('timestamp', '=', log_time_utc),
                    ('employee_id', '=', employee.id)
                ])
                
                if not existing_log:
                    # Attendance turini qurilma nomidan aniqlash
                    attendance_type = device._get_device_attendance_type()
                    
                    # Agar qurilma nomidan aniqlanmasa, label'dan yoki avtomatik aniqlash
                    if not attendance_type:
                        label = ac_event.get('label', '')
                        attendance_type = device._get_attendance_type_from_label(label)
                    
                    # Agar hali ham aniqlanmasa - avtomatik aniqlash
                    if not attendance_type:
                        attendance_type = device._determine_attendance_type(employee, log_time_utc)
                    
                    # Bugungi kun uchun UTC vaqtlar
                    today_start_utc = log_time_utc.replace(hour=0, minute=0, second=0, microsecond=0)
                    today_end_utc = log_time_utc.replace(hour=23, minute=59, second=59, microsecond=0)
                    
                    # Ochiq attendance tekshirish
                    open_attendance = request.env['hr.attendance'].sudo().search([
                        ('employee_id', '=', employee.id),
                        ('check_in', '>=', today_start_utc),
                        ('check_in', '<', today_end_utc),
                        ('check_out', '=', False)
                    ], order='check_in desc', limit=1)
                    
                    # Qayta ishlash kerakligini tekshirish
                    if not device._should_process_log(attendance_type, open_attendance, employee.name):
                        _logger.info(f"Hikvision webhook: Skipped {attendance_type} for {employee.name} (already processed)")
                        return {
                            'status': 'skipped',
                            'message': f'{attendance_type} skipped - already processed',
                            'employee_id': employee.id
                        }
                    
                    # Hikvision logini yaratish
                    request.env['hikvision.log'].sudo().create({
                        'device_id': device.id,
                        'employee_id': employee.id,
                        'timestamp': log_time_utc,
                        'attendance_type': attendance_type,
                    })
                    
                    # HR Attendance'ga yozish
                    device._process_attendance(employee, log_time_utc, attendance_type)
                    
                    _logger.info(f"Hikvision webhook: Created {attendance_type} for {employee.name}")
                    
                    return {
                        'status': 'success',
                        'message': f'{attendance_type} recorded for {employee.name}',
                        'employee_id': employee.id,
                        'attendance_type': attendance_type
                    }
                else:
                    _logger.info(f"Hikvision webhook: Duplicate log ignored for {employee.name}")
                    return {'status': 'duplicate', 'message': 'Log already exists'}
            else:
                _logger.warning("Hikvision webhook: No confirmed device found")
                return {'status': 'error', 'message': 'No device configured'}
                
        except Exception as e:
            _logger.error(f"Hikvision webhook error: {str(e)}", exc_info=True)
            return {'status': 'error', 'message': str(e)}
    
    @http.route('/hikvision/webhook/test', type='http', auth='public', methods=['GET'])
    def test_webhook(self):
        """Webhook endpoint ishlayotganini tekshirish uchun"""
        return "Hikvision webhook is active!"
