# -*- coding: utf-8 -*-
"""
Hikvision Leave Sync Mixin

Bu mixin ta'til va dam olish kunlarini Hikvision qurilmasi bilan
sinxronizatsiya qilish uchun metodlarni o'z ichiga oladi.
"""

import json
import logging
from datetime import datetime

from odoo import models, fields, api

_logger = logging.getLogger(__name__)


class HikvisionLeaveSyncMixin(models.AbstractModel):
    """Hikvision leave sync metodlari uchun mixin"""
    
    _name = 'hikvision.leave.sync.mixin'
    _description = 'Hikvision Leave Sync Mixin'

    def _disable_user_on_device(self, employee):
        """Xodimni qurilmada vaqtincha bloklash (ta'til uchun)."""
        self.ensure_one()
        
        if not employee.barcode:
            raise Exception(f"Xodimda barcode mavjud emas: {employee.name}")
        
        user_data = {
            "UserInfo": {
                "employeeNo": str(employee.barcode),
                "userType": "blackList"
            }
        }
        
        self._make_request('PUT', 'AccessControl/UserInfo/Modify?format=json', 
                          data=json.dumps(user_data))
        _logger.info(f"Hikvision [{self.name}]: {employee.name} bloklandi")
    
    def _enable_user_on_device(self, employee):
        """Xodimni qurilmada qayta yoqish (ta'til tugagach)."""
        self.ensure_one()
        
        if not employee.barcode:
            raise Exception(f"Xodimda barcode mavjud emas: {employee.name}")
        
        user_data = {
            "UserInfo": {
                "employeeNo": str(employee.barcode),
                "userType": "normal",
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
        _logger.info(f"Hikvision [{self.name}]: {employee.name} yoqildi")
    
    @api.model
    def _cron_sync_leave_status(self):
        """Kunlik cron job: Ta'til va dam olish kuniga ko'ra xodimlarni bloklash/yoqish."""
        today = fields.Date.today()
        weekday = today.weekday()
        
        _logger.info(f"Hikvision: Kirish huquqi sinxronizatsiyasi boshlandi ({today})")
        
        employees = self.env['hr.employee'].search([
            ('barcode', '!=', False),
            ('active', '=', True)
        ])
        
        if not employees:
            return
        
        # TO'LIQ KUNLIK ta'tilda bo'lgan xodimlar
        active_leaves = self.env['hr.leave'].search([
            ('state', '=', 'validate'),
            ('date_from', '<=', today),
            ('date_to', '>=', today),
            ('request_unit_half', '=', False),
            ('request_unit_hours', '=', False),
        ])
        employees_on_leave_ids = set(active_leaves.mapped('employee_id').ids)
        
        # Davlat bayrami
        today_datetime = datetime.combine(today, datetime.min.time())
        public_holidays = self.env['resource.calendar.leaves'].search([
            ('date_from', '<=', today_datetime),
            ('date_to', '>=', today_datetime),
            ('resource_id', '=', False),
        ])
        is_public_holiday = bool(public_holidays)
        holiday_name = public_holidays[0].name if is_public_holiday else ""
        
        # Bloklash/yoqish ro'yxatlari
        to_block = []
        to_enable = []
        
        for emp in employees:
            should_block = False
            reason = ""
            
            if emp.id in employees_on_leave_ids:
                should_block = True
                reason = "ta'til"
            elif is_public_holiday:
                should_block = True
                reason = f"davlat bayrami ({holiday_name})"
            elif not self._is_working_day(emp, weekday):
                should_block = True
                reason = "dam olish kuni"
            
            if should_block:
                to_block.append((emp, reason))
            else:
                to_enable.append(emp)
        
        # Qurilmalarda sinxronlash
        devices = self.search([('state', '=', 'confirmed')])
        
        if not devices:
            return
        
        disabled_count = 0
        enabled_count = 0
        
        for device in devices:
            for emp, reason in to_block:
                try:
                    device._disable_user_on_device(emp)
                    disabled_count += 1
                except Exception as e:
                    _logger.error(f"Hikvision: {emp.name} bloklashda xato: {str(e)}")
            
            for emp in to_enable:
                try:
                    device._enable_user_on_device(emp)
                    enabled_count += 1
                except Exception as e:
                    _logger.error(f"Hikvision: {emp.name} yoqishda xato: {str(e)}")
        
        _logger.info(f"Hikvision: Sinxronizatsiya yakunlandi. Bloklangan: {disabled_count}, Yoqilgan: {enabled_count}")
    
    def _is_working_day(self, employee, weekday):
        """Xodimning ish jadvali bo'yicha berilgan hafta kuni ish kunmi?"""
        calendar = employee.resource_calendar_id
        
        if not calendar:
            return True
        
        return any(
            int(att.dayofweek) == weekday and att.day_period in ('morning', 'afternoon')
            for att in calendar.attendance_ids
        )
    
    def action_sync_leave_status(self):
        """Qo'lda ta'til va dam olish kunini sinxronlash tugmasi"""
        self.ensure_one()
        
        today = fields.Date.today()
        weekday = today.weekday()
        
        employees = self.env['hr.employee'].search([
            ('barcode', '!=', False),
            ('active', '=', True)
        ])
        
        if not employees:
            return self._notify("Sinxronizatsiya", "Barcode mavjud xodimlar topilmadi.", 'warning')
        
        # TO'LIQ KUNLIK ta'tilda bo'lgan xodimlar
        active_leaves = self.env['hr.leave'].search([
            ('state', '=', 'validate'),
            ('date_from', '<=', today),
            ('date_to', '>=', today),
            ('request_unit_half', '=', False),
            ('request_unit_hours', '=', False),
        ])
        employees_on_leave_ids = set(active_leaves.mapped('employee_id').ids)
        
        # Davlat bayrami
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
        
        for emp, reason in to_block:
            try:
                self._disable_user_on_device(emp)
                disabled_count += 1
            except Exception as e:
                error_count += 1
        
        if error_count == 0:
            return self._notify("Sinxronizatsiya muvaffaqiyatli", 
                              f"{disabled_count} ta xodim bloklandi.", 'success')
        else:
            return self._notify("Sinxronizatsiya", 
                              f"Bloklangan: {disabled_count}, Xatolar: {error_count}", 'warning', sticky=True)
