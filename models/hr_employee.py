# -*- coding: utf-8 -*-
"""
HR Employee Extension for Hikvision Integration

Xodim ma'lumotlari o'zgarganda Hikvision qurilmasiga avtomatik sinxronlash.
"""

import logging
from odoo import models, api, fields

_logger = logging.getLogger(__name__)


class HrEmployeeHikvision(models.Model):
    """HR Employee modelini Hikvision integratsiyasi uchun kengaytirish"""
    
    _inherit = 'hr.employee'
    
    # Hikvision qurilmasidagi holat
    hikvision_status = fields.Selection([
        ('normal', 'Normal'),
        ('blocked', 'Bloklangan')
    ], string='Hikvision Holati', default='normal',
       help="Xodimning Hikvision qurilmasidagi hozirgi holati")

    @api.model_create_multi
    def create(self, vals_list):
        """
        Yangi xodim yaratilganda Hikvision qurilmasiga avtomatik sinxronlash.
        """
        employees = super().create(vals_list)
        
        # Faqat auto_sync yoqilgan va tasdiqlangan qurilmalar
        devices = self.env['hikvision.device'].search([
            ('state', '=', 'confirmed'),
            ('auto_sync_enabled', '=', True)
        ])
        
        if devices:
            for employee in employees:
                if not employee.barcode:
                    continue
                
                success_devices = []
                failed_devices = []
                    
                for device in devices:
                    try:
                        # Foydalanuvchi ma'lumotlarini yuklash
                        device._upload_user_info(employee)
                        _logger.info(f"Hikvision: {employee.name} - yangi xodim qurilmaga yuklandi")
                        
                        # Rasm mavjud bo'lsa yuklash
                        if employee.image_1920:
                            device._upload_face_data(employee)
                            _logger.info(f"Hikvision: {employee.name} - rasm qurilmaga yuklandi")
                        
                        success_devices.append(device.name)
                            
                    except Exception as e:
                        _logger.error(f"Hikvision: {employee.name} yangi xodim sinxronlashda xato: {str(e)}")
                        failed_devices.append(f"{device.name}: {str(e)}")
                
                # Foydalanuvchiga bildirishnoma yuborish
                if success_devices:
                    message = f"✅ {employee.name} Hikvision qurilmalariga muvaffaqiyatli yuklandi: {', '.join(success_devices)}"
                    self.env['bus.bus']._sendone(
                        self.env.user.partner_id,
                        'simple_notification',
                        {
                            'title': 'Hikvision Sinxronlash',
                            'message': message,
                            'type': 'success',
                            'sticky': False,
                        }
                    )
                
                if failed_devices:
                    # Rasm yo'qligini alohida ko'rsatish
                    image_warnings = [d for d in failed_devices if 'rasm' in d.lower() or 'image' in d.lower()]
                    real_errors = [d for d in failed_devices if d not in image_warnings]
                    
                    if real_errors:
                        error_message = f"⚠️ {employee.name} sinxronlashda muammolar:\n" + "\n".join(real_errors)
                        self.env['bus.bus']._sendone(
                            self.env.user.partner_id,
                            'simple_notification',
                            {
                                'title': 'Hikvision Xatolik',
                                'message': error_message,
                                'type': 'danger',
                                'sticky': True,
                            }
                        )
                    
                    if image_warnings:
                        # Rasm xatoliklari uchun yumshoqroq xabar
                        self.env['bus.bus']._sendone(
                            self.env.user.partner_id,
                            'simple_notification',
                            {
                                'title': 'Hikvision Info',
                                'message': f"ℹ️ {employee.name}: Rasm yuklanmadi (rasm yo'q yoki format noto'g'ri)",
                                'type': 'info',
                                'sticky': False,
                            }
                        )
        
        return employees

    def write(self, vals):
        """
        Xodim ma'lumotlari o'zgarganda Hikvision qurilmasiga sinxronlash.
        
        Kuzatiladigan fieldlar:
        - name (ism)
        - image_1920 (rasm)
        - barcode (ID raqam)
        """
        result = super().write(vals)
        
        # Agar muhim fieldlar o'zgargan bo'lsa
        sync_fields = {'name', 'image_1920', 'barcode'}
        changed_fields = set(vals.keys()) & sync_fields
        
        if changed_fields:
            for employee in self:
                if not employee.barcode:
                    continue
                    
                # Faqat auto_sync yoqilgan va tasdiqlangan qurilmalarga sinxronlash
                devices = self.env['hikvision.device'].search([
                    ('state', '=', 'confirmed'),
                    ('auto_sync_enabled', '=', True)
                ])
                
                if not devices:
                    continue
                
                success_devices = []
                failed_devices = []
                sync_type = []  # Qanday turdagi sinxronlash bo'lganini saqlash
                
                for device in devices:
                    try:
                        # Foydalanuvchi ma'lumotlarini yangilash
                        if 'name' in changed_fields or 'barcode' in changed_fields:
                            device._upload_user_info(employee)
                            _logger.info(f"Hikvision: {employee.name} - ma'lumotlar avtomatik yangilandi")
                            if "ma'lumotlar" not in sync_type:
                                sync_type.append("ma'lumotlar")
                        
                        # Rasm o'zgargan bo'lsa
                        if 'image_1920' in changed_fields:
                            if employee.image_1920:
                                # Yangi rasm yuklash
                                device._upload_face_data(employee)
                                _logger.info(f"Hikvision: {employee.name} - rasm avtomatik yangilandi")
                                if "rasm" not in sync_type:
                                    sync_type.append("rasm")
                            else:
                                # Rasm o'chirildi - qurilmadan ham o'chirish
                                device._delete_face_data(employee)
                                _logger.info(f"Hikvision: {employee.name} - rasm avtomatik o'chirildi")
                                if "rasm o'chirildi" not in sync_type:
                                    sync_type.append("rasm o'chirildi")
                        
                        success_devices.append(device.name)
                            
                    except Exception as e:
                        _logger.error(f"Hikvision: {employee.name} avtomatik sinxronlashda xato: {str(e)}")
                        failed_devices.append(f"{device.name}: {str(e)}")
                
                # Foydalanuvchiga bildirishnoma yuborish
                if success_devices:
                    sync_desc = ", ".join(sync_type) if sync_type else "ma'lumotlar"
                    message = f"✅ {employee.name} - {sync_desc} yangilandi: {', '.join(success_devices)}"
                    self.env['bus.bus']._sendone(
                        self.env.user.partner_id,
                        'simple_notification',
                        {
                            'title': 'Hikvision Yangilash',
                            'message': message,
                            'type': 'success',
                            'sticky': False,
                        }
                    )
                
                if failed_devices:
                    # Rasm yo'qligini alohida ko'rsatish
                    image_warnings = [d for d in failed_devices if 'rasm' in d.lower() or 'image' in d.lower()]
                    real_errors = [d for d in failed_devices if d not in image_warnings]
                    
                    if real_errors:
                        error_message = f"⚠️ {employee.name} sinxronlashda muammolar:\n" + "\n".join(real_errors)
                        self.env['bus.bus']._sendone(
                            self.env.user.partner_id,
                            'simple_notification',
                            {
                                'title': 'Hikvision Xatolik',
                                'message': error_message,
                                'type': 'danger',
                                'sticky': True,
                            }
                        )
                    
                    if image_warnings:
                        # Rasm xatoliklari uchun yumshoqroq xabar
                        self.env['bus.bus']._sendone(
                            self.env.user.partner_id,
                            'simple_notification',
                            {
                                'title': 'Hikvision Info',
                                'message': f"ℹ️ {employee.name}: Rasm yuklanmadi (rasm yo'q yoki format noto'g'ri)",
                                'type': 'info',
                                'sticky': False,
                            }
                        )
        
        return result

    def unlink(self):
        """
        Xodim o'chirilganda Hikvision qurilmasidan ham o'chirish.
        """
        # O'chirishdan oldin barcode va ismlarni saqlab olish
        employees_to_delete = []
        for employee in self:
            if employee.barcode:
                employees_to_delete.append({
                    'barcode': employee.barcode,
                    'name': employee.name
                })
        
        # Qurilmalardan o'chirish
        if employees_to_delete:
            devices = self.env['hikvision.device'].search([
                ('state', '=', 'confirmed'),
                ('auto_sync_enabled', '=', True)
            ])
            
            if devices:
                for emp_data in employees_to_delete:
                    success_devices = []
                    failed_devices = []
                    
                    for device in devices:
                        try:
                            # Foydalanuvchini qurilmadan o'chirish
                            device._delete_user_from_device(emp_data['barcode'])
                            _logger.info(f"Hikvision: {emp_data['name']} - qurilmadan o'chirildi")
                            success_devices.append(device.name)
                        except Exception as e:
                            _logger.error(f"Hikvision: {emp_data['name']} o'chirishda xato: {str(e)}")
                            failed_devices.append(f"{device.name}: {str(e)}")
                    
                    # Foydalanuvchiga bildirishnoma yuborish
                    if success_devices:
                        message = f"🗑️ {emp_data['name']} Hikvision qurilmalaridan o'chirildi: {', '.join(success_devices)}"
                        self.env['bus.bus']._sendone(
                            self.env.user.partner_id,
                            'simple_notification',
                            {
                                'title': "Hikvision O'chirish",
                                'message': message,
                                'type': 'warning',
                                'sticky': False,
                            }
                        )
                    
                    if failed_devices:
                        error_message = f"❌ {emp_data['name']} ba'zi qurilmalardan o'chirilmadi:\n" + "\n".join(failed_devices)
                        self.env['bus.bus']._sendone(
                            self.env.user.partner_id,
                            'simple_notification',
                            {
                                'title': 'Hikvision Xatolik',
                                'message': error_message,
                                'type': 'danger',
                                'sticky': True,
                            }
                        )
        
        return super().unlink()
