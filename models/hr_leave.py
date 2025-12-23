# -*- coding: utf-8 -*-
"""
HR Leave Extension for Hikvision Integration

Ta'til tasdiqlanganda Hikvision qurilmasida xodimni avtomatik bloklash.
"""

import logging
from datetime import datetime
from odoo import models, fields, api

_logger = logging.getLogger(__name__)


class HrLeave(models.Model):
    """HR Leave modelini Hikvision integratsiyasi uchun kengaytirish"""
    
    _inherit = 'hr.leave'

    def action_validate(self):
        """
        Ta'til tasdiqlanganda Hikvision qurilmasida xodimni bloklash.
        
        Bu metod faqat bugun yoki kelajakda boshlanadigan ta'tillar uchun ishlaydi.
        Agar ta'til bugun boshlanayotgan bo'lsa, xodim darhol bloklanadi.
        """
        result = super().action_validate()
        
        today = fields.Date.today()
        
        for leave in self:
            # Faqat TO'LIQ KUNLIK, tasdiqlangan va bugun boshlanadigan ta'tillar
            # Yarim kunlik (half day) va soatlik ta'tillar bloklanmaydi
            is_full_day = not leave.request_unit_half and not leave.request_unit_hours
            if leave.state == 'validate' and is_full_day and leave.date_from.date() <= today <= leave.date_to.date():
                employee = leave.employee_id
                
                if not employee.barcode:
                    _logger.warning(f"Hikvision: {employee.name} - barcode mavjud emas, o'tkazib yuborildi")
                    continue
                
                # Barcha tasdiqlangan qurilmalarda xodimni bloklash
                devices = self.env['hikvision.device'].search([('state', '=', 'confirmed')])
                
                for device in devices:
                    try:
                        device._disable_user_on_device(employee)
                        _logger.info(f"Hikvision: {employee.name} - ta'til boshlandi, qurilmada bloklandi ({device.name})")
                    except Exception as e:
                        _logger.error(f"Hikvision: {employee.name} bloklashda xato ({device.name}): {str(e)}")
        
        return result

    def action_refuse(self):
        """
        Ta'til bekor qilinganda xodimni qayta yoqish.
        """
        # Bekor qilishdan oldin xodimlarni eslab qolamiz
        employees_to_enable = []
        today = fields.Date.today()
        
        for leave in self:
            # Faqat TO'LIQ KUNLIK ta'tillar uchun xodim yoqiladi
            is_full_day = not leave.request_unit_half and not leave.request_unit_hours
            if leave.state == 'validate' and is_full_day and leave.date_from.date() <= today <= leave.date_to.date():
                employees_to_enable.append(leave.employee_id)
        
        result = super().action_refuse()
        
        # Xodimlarni qayta yoqish
        devices = self.env['hikvision.device'].search([('state', '=', 'confirmed')])
        
        for employee in employees_to_enable:
            if not employee.barcode:
                continue
                
            for device in devices:
                try:
                    device._enable_user_on_device(employee)
                    _logger.info(f"Hikvision: {employee.name} - ta'til bekor qilindi, qurilmada yoqildi ({device.name})")
                except Exception as e:
                    _logger.error(f"Hikvision: {employee.name} yoqishda xato ({device.name}): {str(e)}")
        
        return result
