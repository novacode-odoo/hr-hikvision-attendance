# -*- coding: utf-8 -*-
"""
Hikvision User/Face Sync Mixin

Bu mixin xodimlarni Hikvision qurilmasiga sinxronizatsiya qilish,
yuz rasmlarini yuklash va boshqarish uchun metodlarni o'z ichiga oladi.
"""

import json
import base64
import logging
import threading

from odoo import models, api, SUPERUSER_ID
from odoo.modules.registry import Registry

_logger = logging.getLogger(__name__)


class HikvisionSyncMixin(models.AbstractModel):
    """Hikvision user/face sync metodlari uchun mixin"""
    
    _name = 'hikvision.sync.mixin'
    _description = 'Hikvision Sync Mixin'

    def action_sync_users(self):
        """
        Odoo xodimlarini Hikvision qurilmasiga sinxronizatsiya qilish.
        
        Background thread orqali ishga tushiriladi - HTTP timeout muammosini hal qiladi.
        Foydalanuvchi kutmaydi, jarayon orqa fonda davom etadi.
        """
        self.ensure_one()
        
        employees = self.env['hr.employee'].search([
            ('barcode', '!=', False),
            ('active', '=', True)
        ])
        
        if not employees:
            return self._notify('Xodimlar topilmadi', 
                              "Sinxronizatsiya uchun barcode mavjud bo'lgan xodimlar topilmadi.", 
                              'warning')
        
        # Qurilmadagi mavjud xodimlarni tekshirish
        existing_employee_nos = self._get_existing_employees()
        
        # Yangi xodimlarni aniqlash
        new_employees = employees.filtered(lambda e: str(e.barcode) not in existing_employee_nos)
        skipped_count = len(employees) - len(new_employees)
        
        if not new_employees:
            return self._notify('Sinxronizatsiya yakunlandi', 
                              f"Barcha {skipped_count} ta xodim allaqachon qurilmada mavjud.", 
                              'info')
        
        # Background threadda ishga tushirish
        device_id = self.id
        db_name = self.env.cr.dbname
        user_id = self.env.user.id
        employee_ids = new_employees.ids
        
        def sync_in_background():
            """Background threadda xodimlarni yuklash"""
            try:
                db_registry = Registry(db_name)
                with db_registry.cursor() as cr:
                    env = api.Environment(cr, user_id, {})
                    device = env['hikvision.device'].browse(device_id)
                    
                    if not device.exists():
                        _logger.error("Hikvision: Qurilma topilmadi")
                        return
                    
                    employees_to_sync = env['hr.employee'].browse(employee_ids)
                    
                    success_count = 0
                    face_success_count = 0
                    error_count = 0
                    face_errors = []
                    
                    total = len(employees_to_sync)
                    _logger.info(f"Hikvision: Background sync boshlandi - {total} ta xodim")
                    
                    for idx, emp in enumerate(employees_to_sync, 1):
                        try:
                            device._upload_user_info_new(emp)
                            success_count += 1
                            
                            if emp.image_1920:
                                try:
                                    device._upload_face_data_new(emp)
                                    face_success_count += 1
                                except Exception as face_err:
                                    face_errors.append(f"{emp.name}: {str(face_err)}")
                            
                            # Har 10 ta xodimdan keyin progress log
                            if idx % 10 == 0:
                                _logger.info(f"Hikvision: Progress - {idx}/{total} ({int(idx/total*100)}%)")
                                    
                        except Exception as e:
                            error_count += 1
                            _logger.error(f"Hikvision: {emp.name} xatosi - {str(e)}")
                    
                    # Yakuniy natija
                    _logger.info(f"Hikvision: Sync yakunlandi - Yuklandi: {success_count}, Yuzlar: {face_success_count}, Xatolar: {error_count}")
                    
                    # Foydalanuvchiga notification yuborish
                    msg_parts = []
                    if skipped_count > 0:
                        msg_parts.append(f'Mavjud: {skipped_count} ta')
                    if success_count > 0:
                        msg_parts.append(f'Yangi yuklandi: {success_count} ta')
                    if face_success_count > 0:
                        msg_parts.append(f'Yuz rasmlari: {face_success_count} ta')
                    if face_errors:
                        msg_parts.append(f'Yuz xatolari: {len(face_errors)} ta')
                    if error_count > 0:
                        msg_parts.append(f'Xatolar: {error_count} ta')
                    
                    notif_type = 'success' if error_count == 0 and not face_errors else 'warning'
                    
                    # Bus notification yuborish
                    user = env['res.users'].browse(user_id)
                    env['bus.bus']._sendone(
                        user.partner_id,
                        'simple_notification',
                        {
                            'title': '✅ Sinxronizatsiya yakunlandi',
                            'message': '. '.join(msg_parts),
                            'type': notif_type,
                            'sticky': error_count > 0,
                        }
                    )
                    
                    cr.commit()
                    
            except Exception as e:
                _logger.error(f"Hikvision: Background sync xatosi - {str(e)}")
        
        # Threadni ishga tushirish
        thread = threading.Thread(target=sync_in_background, daemon=True)
        thread.start()
        
        _logger.info(f"Hikvision: Background sync boshlandi - {len(new_employees)} ta yangi xodim")
        
        # Foydalanuvchiga darhol javob qaytarish
        return self._notify(
            '🔄 Sinxronizatsiya boshlandi', 
            f"{len(new_employees)} ta yangi xodim yuklanmoqda (mavjud: {skipped_count} ta).\n"
            "Jarayon orqa fonda davom etmoqda. Tugaganda xabar keladi.",
            'info'
        )
    
    def action_sync_users_sync(self):
        """
        Xodimlarni sinxron (kutib) yuklash - test uchun.
        
        Bu eski usul - HTTP timeout bo'lishi mumkin.
        """
        self.ensure_one()
        
        employees = self.env['hr.employee'].search([
            ('barcode', '!=', False),
            ('active', '=', True)
        ])
        
        if not employees:
            return self._notify('Xodimlar topilmadi', 
                              "Sinxronizatsiya uchun barcode mavjud bo'lgan xodimlar topilmadi.", 
                              'warning')
        
        existing_employee_nos = self._get_existing_employees()
        
        success_count = 0
        face_success_count = 0
        skipped_count = 0
        error_count = 0
        face_errors = []
        
        for emp in employees:
            try:
                if str(emp.barcode) in existing_employee_nos:
                    skipped_count += 1
                    continue
                
                self._upload_user_info_new(emp)
                success_count += 1
                
                if emp.image_1920:
                    try:
                        self._upload_face_data_new(emp)
                        face_success_count += 1
                    except Exception as face_err:
                        face_errors.append(f"{emp.name}: {str(face_err)}")
                        
            except Exception as e:
                error_count += 1
        
        msg_parts = []
        if skipped_count > 0:
            msg_parts.append(f'Mavjud: {skipped_count} ta (o\'tkazib yuborildi)')
        if success_count > 0:
            msg_parts.append(f'Yangi yuklandi: {success_count} ta')
        if face_success_count > 0:
            msg_parts.append(f'Yuz rasmlari: {face_success_count} ta')
        if face_errors:
            msg_parts.append(f'Yuz xatolari: {len(face_errors)} ta')
            for fe in face_errors[:3]:
                msg_parts.append(f'  → {fe}')
        if error_count > 0:
            msg_parts.append(f'Xatolar: {error_count} ta')
        
        if not msg_parts:
            msg_parts.append('Hech narsa yuklanmadi')
            
        notif_type = 'success' if error_count == 0 and not face_errors else 'warning'
        sticky = error_count > 0 or len(face_errors) > 0
        
        return self._notify('Sinxronizatsiya yakunlandi', '. '.join(msg_parts), notif_type, sticky)
    
    def _get_existing_employees(self):
        """
        Qurilmadagi mavjud xodimlar ro'yxatini olish.
        
        Returns:
            set: Mavjud employeeNo'lar to'plami
        """
        import json
        
        existing = set()
        position = 0
        batch_size = 100
        
        try:
            while True:
                search_data = {
                    "UserInfoSearchCond": {
                        "searchID": "sync_check",
                        "searchResultPosition": position,
                        "maxResults": batch_size
                    }
                }
                
                response = self._make_request('POST', 'AccessControl/UserInfo/Search?format=json', 
                                             data=json.dumps(search_data))
                data = response.json()
                
                user_info_search = data.get('UserInfoSearch', {})
                total_matches = user_info_search.get('totalMatches', 0)
                user_info_list = user_info_search.get('UserInfo', [])
                
                if not user_info_list:
                    break
                
                for user in user_info_list:
                    emp_no = user.get('employeeNo')
                    if emp_no:
                        existing.add(str(emp_no))
                
                position += len(user_info_list)
                
                if position >= total_matches:
                    break
                    
        except Exception as e:
            _logger.warning(f"Hikvision: Mavjud xodimlarni olishda xato: {str(e)}")
        
        return existing
    
    def _upload_user_info_new(self, employee):
        """
        Yangi xodim ma'lumotlarini Hikvision qurilmasiga yuklash.
        
        Faqat POST (Record) ishlatadi - PUT (Modify) o'tkazib yuboriladi.
        Bu har bir xodim uchun 10 sekund tejaydi.
        """
        import json
        
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
        _logger.info(f"Hikvision: {employee.name} - yangi xodim yaratildi")
    
    def _upload_face_data_new(self, employee):
        """
        Yangi xodim yuz rasmini Hikvision qurilmasiga yuklash.
        
        Faqat POST (yaratish) ishlatadi - DELETE va PUT o'tkazib yuboriladi.
        Bu har bir xodim uchun 40-60 sekund tejaydi.
        """
        import io
        import json
        from PIL import Image
        
        _logger.info(f"Hikvision: Yangi yuz rasmi yuklash - {employee.name}")
        
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
        except Exception as e:
            raise Exception(f"Base64 decode xatosi: {str(e)}")
        
        # Rasmni JPEG formatga convert qilish
        try:
            img = Image.open(io.BytesIO(image_bytes))
            
            if img.mode in ('RGBA', 'P'):
                img = img.convert('RGB')
            elif img.mode != 'RGB':
                img = img.convert('RGB')
            
            max_size = (640, 480)
            if img.size[0] > max_size[0] or img.size[1] > max_size[1]:
                img.thumbnail(max_size, Image.Resampling.LANCZOS)
            
            output_buffer = io.BytesIO()
            img.save(output_buffer, format='JPEG', quality=80)
            image_bytes = output_buffer.getvalue()
            
        except Exception as e:
            raise Exception(f"Rasm konvertatsiya xatosi: {str(e)}")
        
        # Multipart body yaratish
        boundary = "----HikvisionBoundaryABC123"
        
        # FDLib uchun JSON
        face_info_fdlib = {
            "faceLibType": "blackFD",
            "FDID": "1",
            "FPID": str(employee.barcode),
            "name": employee.name,
            "gender": "male"
        }
        
        # Access Control uchun JSON
        face_info_ac = {
            "FaceInfo": {
                "employeeNo": str(employee.barcode),
                "faceDataURL": ""
            }
        }
        
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
        
        # Faqat yaratish endpointlarini sinash (PUT/Modify o'tkazib yuboriladi)
        configs_to_try = [
            {
                'method': 'POST',
                'endpoint': 'Intelligent/FDLib/FaceDataRecord?format=json&FDID=1&faceLibType=blackFD',
                'face_json': face_info_fdlib,
                'img_field': 'FaceImage',
                'description': 'FaceDataRecord'
            },
            {
                'method': 'POST',
                'endpoint': 'AccessControl/FaceDataRecord?format=json',
                'face_json': face_info_ac,
                'img_field': 'img',
                'description': 'AccessControl'
            },
        ]
        
        last_error = None
        for config in configs_to_try:
            try:
                body = build_multipart_body(config['face_json'], config['img_field'])
                response = self._make_request_multipart('POST', config['endpoint'], data=body, content_type=content_type)
                _logger.info(f"Hikvision: Yuz rasmi yuklandi - {employee.name} ({config['description']})")
                return
                
            except Exception as e:
                last_error = str(e)
                _logger.warning(f"Hikvision: {config['description']} ishlamadi - {last_error}")
                continue
        
        raise Exception(f"Yuz yuklash muvaffaqiyatsiz: {last_error}")
    
    def _upload_user_info(self, employee):
        """
        Xodim ma'lumotlarini Hikvision qurilmasiga yuklash yoki yangilash.
        
        Avval PUT (Modify) bilan yangilashga harakat qiladi,
        ishlamasa POST (Record) bilan yaratadi.
        """
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
        
        # Avval PUT (Modify) bilan yangilashga harakat qilamiz
        try:
            self._make_request('PUT', 'AccessControl/UserInfo/Modify?format=json', data=json.dumps(user_data))
            _logger.info(f"Hikvision: {employee.name} - ma'lumotlar yangilandi (Modify)")
            return
        except Exception as e:
            _logger.warning(f"Hikvision: Modify ishlamadi, Record sinab ko'rilmoqda - {str(e)}")
        
        # Modify ishlamasa, POST (Record) bilan yaratamiz
        self._make_request('POST', 'AccessControl/UserInfo/Record?format=json', data=json.dumps(user_data))
        _logger.info(f"Hikvision: {employee.name} - ma'lumotlar yaratildi (Record)")
    
    def _delete_face_data(self, employee):
        """
        Xodim yuz rasmini Hikvision qurilmasidan o'chirish.
        
        Turli qurilma turlari uchun turli endpointlar sinab ko'riladi.
        """
        employee_no = str(employee.barcode)
        
        delete_configs = [
            # Intelligent FDLib uchun
            {
                'endpoint': 'Intelligent/FDLib/FDSearch/Delete?format=json&FDID=1&faceLibType=blackFD',
                'data': {
                    "FPID": [
                        {"value": employee_no}
                    ]
                }
            },
            # Access Control qurilmalari uchun
            {
                'endpoint': 'AccessControl/FaceDataRecord/Delete?format=json',
                'data': {
                    "FaceDataDelCond": {
                        "employeeNo": employee_no
                    }
                }
            },
        ]
        
        for config in delete_configs:
            try:
                _logger.info(f"Hikvision: Yuz o'chirish sinayapti - {config['endpoint']}")
                self._make_request('PUT', config['endpoint'], data=json.dumps(config['data']))
                _logger.info(f"Hikvision: Eski yuz rasmi o'chirildi - {employee.name} (barcode: {employee_no})")
                return
            except Exception as e:
                _logger.warning(f"Hikvision: {config['endpoint']} ishlamadi - {str(e)}")
                continue
        
        _logger.warning(f"Hikvision: Yuz o'chirish muvaffaqiyatsiz yoki rasm mavjud emas - {employee.name}")
    
    def _delete_user_from_device(self, barcode):
        """
        Foydalanuvchini Hikvision qurilmasidan to'liq o'chirish (user + face).
        
        Args:
            barcode: Xodimning barcode/employeeNo raqami
        """
        employee_no = str(barcode)
        
        # 1. Avval yuz rasmini o'chirish
        face_delete_configs = [
            {
                'endpoint': 'Intelligent/FDLib/FDSearch/Delete?format=json&FDID=1&faceLibType=blackFD',
                'data': {"FPID": [{"value": employee_no}]}
            },
            {
                'endpoint': 'AccessControl/FaceDataRecord/Delete?format=json',
                'data': {"FaceDataDelCond": {"employeeNo": employee_no}}
            },
        ]
        
        for config in face_delete_configs:
            try:
                self._make_request('PUT', config['endpoint'], data=json.dumps(config['data']))
                _logger.info(f"Hikvision: Yuz rasmi o'chirildi - barcode: {employee_no}")
                break
            except Exception as e:
                _logger.warning(f"Hikvision: Yuz o'chirish - {config['endpoint']} ishlamadi")
                continue
        
        # 2. Foydalanuvchi ma'lumotlarini o'chirish
        user_delete_data = {
            "UserInfoDelCond": {
                "EmployeeNoList": [
                    {"employeeNo": employee_no}
                ]
            }
        }
        
        try:
            self._make_request('PUT', 'AccessControl/UserInfo/Delete?format=json', 
                              data=json.dumps(user_delete_data))
            _logger.info(f"Hikvision: Foydalanuvchi o'chirildi - barcode: {employee_no}")
        except Exception as e:
            _logger.error(f"Hikvision: Foydalanuvchi o'chirishda xato - {str(e)}")
    
    def _upload_face_data(self, employee):
        """
        Xodim yuz rasmini Hikvision qurilmasiga yuklash yoki yangilash.
        
        Hikvision dokumentatsiyasiga ko'ra:
        - Yangilash: PUT /ISAPI/Intelligent/FDLib/FDModify?format=json
        - Yaratish: POST /ISAPI/Intelligent/FDLib/FaceDataRecord?format=json
        """
        import io
        from PIL import Image
        
        _logger.info(f"Hikvision: Yuz rasmini yuklash boshlanmoqda - {employee.name} (barcode: {employee.barcode})")
        
        # MUHIM: Avval eski rasmni o'chirishga harakat qilamiz
        # Bu FDModify ishlamasa ham rasmni yangilashni ta'minlaydi
        self._delete_face_data(employee)
        
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
        except Exception as e:
            raise Exception(f"Base64 decode xatosi: {str(e)}")
        
        # Rasmni JPEG formatga convert qilish
        try:
            img = Image.open(io.BytesIO(image_bytes))
            
            if img.mode in ('RGBA', 'P'):
                img = img.convert('RGB')
            elif img.mode != 'RGB':
                img = img.convert('RGB')
            
            max_size = (640, 480)
            if img.size[0] > max_size[0] or img.size[1] > max_size[1]:
                img.thumbnail(max_size, Image.Resampling.LANCZOS)
            
            output_buffer = io.BytesIO()
            img.save(output_buffer, format='JPEG', quality=80)
            image_bytes = output_buffer.getvalue()
            _logger.info(f"Hikvision: JPEG hajmi - {len(image_bytes)} bytes, o'lcham - {img.size}")
            
        except Exception as e:
            _logger.warning(f"Hikvision: Rasm formati noto'g'ri - {employee.name}")
            raise Exception(f"Rasm formati noto'g'ri yoki buzilgan")
        
        # Multipart body yaratish
        boundary = "----HikvisionBoundaryABC123"
        
        # FDLib uchun JSON (yangilash va yaratish uchun)
        # Hikvision dokumentatsiyasiga ko'ra barcha fieldlar kerak
        face_info_fdlib = {
            "faceLibType": "blackFD",
            "FDID": "1",
            "FPID": str(employee.barcode),
            "name": employee.name,
            "gender": "male"  # Majburiy field - Hikvision dokumentatsiyasidan
        }
        
        # Access Control uchun JSON
        face_info_ac = {
            "FaceInfo": {
                "employeeNo": str(employee.barcode),
                "faceDataURL": ""
            }
        }
        
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
        
        # Endpointlar ro'yxati - birinchi yangilash (PUT), keyin yaratish (POST)
        configs_to_try = [
            # 1. FDModify - mavjud rasmni YANGILASH (PUT) - Hikvision dokumentatsiyasidan
            {
                'method': 'PUT',
                'endpoint': 'Intelligent/FDLib/FDModify?format=json',
                'face_json': face_info_fdlib,
                'img_field': 'img',
                'description': 'FDModify (yangilash)'
            },
            # 2. FaceDataRecord - yangi rasm YARATISH (POST)
            {
                'method': 'POST',
                'endpoint': 'Intelligent/FDLib/FaceDataRecord?format=json&FDID=1&faceLibType=blackFD',
                'face_json': face_info_fdlib,
                'img_field': 'FaceImage',
                'description': 'FaceDataRecord (yaratish)'
            },
            # 3. Access Control uchun (zaxira)
            {
                'method': 'POST',
                'endpoint': 'AccessControl/FaceDataRecord?format=json',
                'face_json': face_info_ac,
                'img_field': 'img',
                'description': 'AccessControl (zaxira)'
            },
        ]
        
        last_error = None
        for config in configs_to_try:
            try:
                body = build_multipart_body(config['face_json'], config['img_field'])
                _logger.info(f"Hikvision: Sinayapti - {config['description']} ({config['method']} {config['endpoint']})")
                
                # PUT yoki POST ga qarab so'rov yuborish
                if config['method'] == 'PUT':
                    response = self._make_request_multipart_put(config['endpoint'], data=body, content_type=content_type)
                else:
                    response = self._make_request_multipart('POST', config['endpoint'], data=body, content_type=content_type)
                
                try:
                    resp_text = response.text
                    _logger.info(f"Hikvision: Javob - {resp_text[:200]}")
                except:
                    pass
                
                _logger.info(f"Hikvision: Yuz rasmi muvaffaqiyatli yuklandi - {employee.name} ({config['description']})")
                return
                
            except Exception as e:
                last_error = str(e)
                _logger.warning(f"Hikvision: {config['description']} ishlamadi - {last_error}")
                continue
        
        raise Exception(f"Yuz yuklash muvaffaqiyatsiz: {last_error}")

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
