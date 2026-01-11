# -*- coding: utf-8 -*-
"""
Hikvision Leave Sync Mixin

Bu mixin ta'til va dam olish kunlarini Hikvision qurilmasi bilan
sinxronizatsiya qilish uchun metodlarni o'z ichiga oladi.

OPTIMIZATSIYA:
- hikvision_status field orqali faqat o'zgargan xodimlarni yangilash
- Background thread orqali uzoq jarayonlarni bajarish
- Har bir xodimdan keyin commit qilish
"""

import json
import logging
import threading
from datetime import datetime

from odoo import models, fields, api, SUPERUSER_ID
from odoo.modules.registry import Registry
from .hikvision_logger import log_cron, log_sync, log_info, log_error

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
    
    def _get_expected_status(self, employee, today, weekday, employees_on_leave_ids, is_public_holiday):
        """Xodimning kutilgan holatini aniqlash."""
        if employee.id in employees_on_leave_ids:
            return 'blocked'
        elif is_public_holiday:
            return 'blocked'
        elif not self._is_working_day(employee, weekday):
            return 'blocked'
        return 'normal'
    
    @api.model
    def _cron_sync_leave_status(self):
        """
        OPTIMALLASHTIRILGAN kunlik cron job.
        
        Faqat hikvision_status O'ZGARGAN xodimlarni yangilaydi.
        Background thread ishlatadi.
        """
        today = fields.Date.today()
        weekday = today.weekday()
        
        _logger.info(f"Hikvision: Kirish huquqi sinxronizatsiyasi boshlandi ({today})")
        log_cron('Leave Sync', f"Boshlandi: {today}, Hafta kuni: {weekday}")
        
        employees = self.env['hr.employee'].search([
            ('barcode', '!=', False),
            ('active', '=', True)
        ])
        
        if not employees:
            _logger.info("Hikvision: Barcode mavjud xodimlar topilmadi")
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
        
        # FAQAT O'ZGARGAN xodimlarni aniqlash
        to_change = []  # [(employee_id, new_status), ...]
        
        for emp in employees:
            expected = self._get_expected_status(
                emp, today, weekday, employees_on_leave_ids, is_public_holiday
            )
            
            # Faqat o'zgargan bo'lsa
            if emp.hikvision_status != expected:
                to_change.append((emp.id, expected))
        
        if not to_change:
            _logger.info("Hikvision: Hech qanday o'zgarish yo'q, barcha xodimlar to'g'ri holatda")
            return
        
        _logger.info(f"Hikvision: {len(to_change)} ta xodim yangilanishi kerak")
        
        # Qurilmalar
        device_ids = self.search([('state', '=', 'confirmed')]).ids
        
        if not device_ids:
            _logger.warning("Hikvision: Tasdiqlangan qurilmalar topilmadi")
            return
        
        # Background threadda sinxronlash
        db_name = self.env.cr.dbname
        
        def sync_in_background():
            """Background threadda yangi DB ulanish bilan ishlash"""
            try:
                db_registry = Registry(db_name)
                with db_registry.cursor() as cr:
                    env = api.Environment(cr, SUPERUSER_ID, {})
                    
                    devices = env['hikvision.device'].browse(device_ids)
                    
                    success_count = 0
                    error_count = 0
                    
                    for emp_id, new_status in to_change:
                        emp = env['hr.employee'].browse(emp_id)
                        
                        if not emp.exists():
                            continue
                        
                        try:
                            for device in devices:
                                if new_status == 'blocked':
                                    device._disable_user_on_device(emp)
                                else:
                                    device._enable_user_on_device(emp)
                            
                            # DB da hikvision_status yangilash
                            emp.write({'hikvision_status': new_status})
                            success_count += 1
                            
                            # Har bir xodimdan keyin commit
                            cr.commit()
                            
                        except Exception as e:
                            error_count += 1
                            _logger.error(f"Hikvision: {emp.name} sinxronlashda xato: {str(e)}")
                            cr.rollback()
                    
                    _logger.info(f"Hikvision: Cron yakunlandi. Muvaffaqiyatli: {success_count}, Xatolar: {error_count}")
                    
            except Exception as e:
                _logger.error(f"Hikvision: Background sync xatosi: {str(e)}")
        
        # Threadni ishga tushirish
        thread = threading.Thread(target=sync_in_background, daemon=True)
        thread.start()
        
        _logger.info(f"Hikvision: Background sync boshlandi - {len(to_change)} ta xodim")
    
    def _is_working_day(self, employee, weekday):
        """Xodimning ish jadvali bo'yicha berilgan hafta kuni ish kunmi?"""
        calendar = employee.resource_calendar_id
        
        if not calendar:
            return True
        
        return any(
            int(att.dayofweek) == weekday and att.day_period in ('morning', 'afternoon')
            for att in calendar.attendance_ids
        )
    
    # =========================================================================
    # QO'LDA SINXRONLASH TUGMALARI
    # =========================================================================
    
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
                emp.hikvision_status = 'blocked'
                disabled_count += 1
            except Exception as e:
                error_count += 1
        
        if error_count == 0:
            return self._notify("Sinxronizatsiya muvaffaqiyatli", 
                              f"{disabled_count} ta xodim bloklandi.", 'success')
        else:
            return self._notify("Sinxronizatsiya", 
                              f"Bloklangan: {disabled_count}, Xatolar: {error_count}", 'warning', sticky=True)
    
    # =========================================================================
    # HAMMANI BLOKLASH / BLOKDAN CHIQARISH
    # =========================================================================
    
    def action_block_all_users(self):
        """
        Barcha xodimlarni bloklash.
        
        Background thread orqali ishlaydi - HTTP timeout bo'lmaydi.
        Har bir xodimdan keyin commit qiladi.
        """
        self.ensure_one()
        
        employees = self.env['hr.employee'].search([
            ('barcode', '!=', False),
            ('active', '=', True)
        ])
        
        if not employees:
            return self._notify("Xato", "Barcode mavjud xodimlar topilmadi.", 'warning')
        
        # Faqat normal holatdagilarni bloklash kerak
        to_block = employees.filtered(lambda e: e.hikvision_status != 'blocked')
        
        if not to_block:
            return self._notify("Ma'lumot", "Barcha xodimlar allaqachon bloklangan.", 'info')
        
        # Background threadda ishlash
        device_id = self.id
        db_name = self.env.cr.dbname
        user_id = self.env.user.id
        employee_ids = to_block.ids
        total = len(employee_ids)
        
        def block_in_background():
            """Background threadda barcha xodimlarni bloklash"""
            try:
                db_registry = Registry(db_name)
                with db_registry.cursor() as cr:
                    env = api.Environment(cr, user_id, {})
                    
                    device = env['hikvision.device'].browse(device_id)
                    
                    if not device.exists():
                        _logger.error("Hikvision: Qurilma topilmadi")
                        return
                    
                    # Barcha tasdiqlangan qurilmalar
                    all_devices = env['hikvision.device'].search([('state', '=', 'confirmed')])
                    
                    success_count = 0
                    error_count = 0
                    
                    for idx, emp_id in enumerate(employee_ids, 1):
                        emp = env['hr.employee'].browse(emp_id)
                        
                        if not emp.exists():
                            continue
                        
                        try:
                            # Barcha qurilmalarda bloklash
                            for dev in all_devices:
                                dev._disable_user_on_device(emp)
                            
                            # DB yangilash
                            emp.write({'hikvision_status': 'blocked'})
                            success_count += 1
                            
                            # Har bir xodimdan keyin commit
                            cr.commit()
                            
                            # Progress log (har 50 ta xodimda)
                            if idx % 50 == 0:
                                _logger.info(f"Hikvision: Bloklash progress - {idx}/{total}")
                            
                        except Exception as e:
                            error_count += 1
                            _logger.error(f"Hikvision: {emp.name} bloklashda xato: {str(e)}")
                            cr.rollback()
                    
                    # Notification yuborish
                    user = env['res.users'].browse(user_id)
                    notif_type = 'success' if error_count == 0 else 'warning'
                    
                    env['bus.bus']._sendone(
                        user.partner_id,
                        'simple_notification',
                        {
                            'title': '🔒 Bloklash yakunlandi',
                            'message': f"Bloklangan: {success_count} ta, Xatolar: {error_count} ta",
                            'type': notif_type,
                            'sticky': error_count > 0,
                        }
                    )
                    cr.commit()
                    
                    _logger.info(f"Hikvision: Bloklash yakunlandi - {success_count}/{total}")
                    
            except Exception as e:
                _logger.error(f"Hikvision: Background block xatosi: {str(e)}")
        
        # Threadni ishga tushirish
        thread = threading.Thread(target=block_in_background, daemon=True)
        thread.start()
        
        return self._notify(
            '🔒 Bloklash boshlandi',
            f"{total} ta xodim bloklanmoqda...\nJarayon orqa fonda davom etmoqda.",
            'info'
        )
    
    def action_unblock_all_users(self):
        """
        Barcha xodimlarni blokdan chiqarish.
        
        Background thread orqali ishlaydi - HTTP timeout bo'lmaydi.
        Har bir xodimdan keyin commit qiladi.
        """
        self.ensure_one()
        
        employees = self.env['hr.employee'].search([
            ('barcode', '!=', False),
            ('active', '=', True)
        ])
        
        if not employees:
            return self._notify("Xato", "Barcode mavjud xodimlar topilmadi.", 'warning')
        
        # Faqat bloklangan xodimlarni yoqish kerak
        to_unblock = employees.filtered(lambda e: e.hikvision_status != 'normal')
        
        if not to_unblock:
            return self._notify("Ma'lumot", "Barcha xodimlar allaqachon normal holatda.", 'info')
        
        # Background threadda ishlash
        device_id = self.id
        db_name = self.env.cr.dbname
        user_id = self.env.user.id
        employee_ids = to_unblock.ids
        total = len(employee_ids)
        
        def unblock_in_background():
            """Background threadda barcha xodimlarni blokdan chiqarish"""
            try:
                db_registry = Registry(db_name)
                with db_registry.cursor() as cr:
                    env = api.Environment(cr, user_id, {})
                    
                    device = env['hikvision.device'].browse(device_id)
                    
                    if not device.exists():
                        _logger.error("Hikvision: Qurilma topilmadi")
                        return
                    
                    # Barcha tasdiqlangan qurilmalar
                    all_devices = env['hikvision.device'].search([('state', '=', 'confirmed')])
                    
                    success_count = 0
                    error_count = 0
                    
                    for idx, emp_id in enumerate(employee_ids, 1):
                        emp = env['hr.employee'].browse(emp_id)
                        
                        if not emp.exists():
                            continue
                        
                        try:
                            # Barcha qurilmalarda yoqish
                            for dev in all_devices:
                                dev._enable_user_on_device(emp)
                            
                            # DB yangilash
                            emp.write({'hikvision_status': 'normal'})
                            success_count += 1
                            
                            # Har bir xodimdan keyin commit
                            cr.commit()
                            
                            # Progress log (har 50 ta xodimda)
                            if idx % 50 == 0:
                                _logger.info(f"Hikvision: Blokdan chiqarish progress - {idx}/{total}")
                            
                        except Exception as e:
                            error_count += 1
                            _logger.error(f"Hikvision: {emp.name} yoqishda xato: {str(e)}")
                            cr.rollback()
                    
                    # Notification yuborish
                    user = env['res.users'].browse(user_id)
                    notif_type = 'success' if error_count == 0 else 'warning'
                    
                    env['bus.bus']._sendone(
                        user.partner_id,
                        'simple_notification',
                        {
                            'title': '🔓 Blokdan chiqarish yakunlandi',
                            'message': f"Yoqilgan: {success_count} ta, Xatolar: {error_count} ta",
                            'type': notif_type,
                            'sticky': error_count > 0,
                        }
                    )
                    cr.commit()
                    
                    _logger.info(f"Hikvision: Blokdan chiqarish yakunlandi - {success_count}/{total}")
                    
            except Exception as e:
                _logger.error(f"Hikvision: Background unblock xatosi: {str(e)}")
        
        # Threadni ishga tushirish
        thread = threading.Thread(target=unblock_in_background, daemon=True)
        thread.start()
        
        return self._notify(
            '🔓 Blokdan chiqarish boshlandi',
            f"{total} ta xodim yoqilmoqda...\nJarayon orqa fonda davom etmoqda.",
            'info'
        )
