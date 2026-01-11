# -*- coding: utf-8 -*-

from odoo import models, fields, api
from datetime import datetime, timedelta
from calendar import monthrange
import pytz
import logging

_logger = logging.getLogger(__name__)


class AttendanceDashboard(models.Model):
    _name = 'attendance.dashboard'
    _description = 'Davomat Dashboard'

    name = fields.Char(string="Nomi", default="Davomat Dashboard")

    @api.model
    def get_departments(self):
        """Barcha bo'limlar ro'yxati"""
        departments = self.env['hr.department'].search([])
        return [{'id': d.id, 'name': d.name} for d in departments]

    @api.model
    def get_today_attendance_stats(self, department_id=None):
        """Bugungi davomat statistikasi"""
        tz = self.env.user.tz or 'Asia/Tashkent'
        local_tz = pytz.timezone(tz)
        
        now_local = datetime.now(local_tz)
        today_start_local = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
        today_end_local = now_local.replace(hour=23, minute=59, second=59, microsecond=999999)
        
        today_start_utc = today_start_local.astimezone(pytz.UTC).replace(tzinfo=None)
        today_end_utc = today_end_local.astimezone(pytz.UTC).replace(tzinfo=None)
        
        # Employee domain
        emp_domain = [('active', '=', True)]
        if department_id:
            emp_domain.append(('department_id', '=', department_id))
        
        total_employees = self.env['hr.employee'].search_count(emp_domain)
        
        # Attendance domain
        att_domain = [
            ('check_in', '>=', today_start_utc),
            ('check_in', '<=', today_end_utc)
        ]
        if department_id:
            att_domain.append(('employee_id.department_id', '=', department_id))
        
        today_attendances = self.env['hr.attendance'].search(att_domain)
        present_employee_ids = today_attendances.mapped('employee_id').ids
        present_employees = len(set(present_employee_ids))
        absent_employees = total_employees - present_employees
        
        return {
            'total_employees': total_employees,
            'present_employees': present_employees,
            'absent_employees': absent_employees,
            'attendance_rate': round((present_employees / total_employees * 100) if total_employees else 0, 1),
        }

    @api.model
    def get_absent_employees(self, department_id=None):
        """Bugun kelmaganlar ro'yxati"""
        tz = self.env.user.tz or 'Asia/Tashkent'
        local_tz = pytz.timezone(tz)
        
        now_local = datetime.now(local_tz)
        today_start_local = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
        today_end_local = now_local.replace(hour=23, minute=59, second=59, microsecond=999999)
        
        today_start_utc = today_start_local.astimezone(pytz.UTC).replace(tzinfo=None)
        today_end_utc = today_end_local.astimezone(pytz.UTC).replace(tzinfo=None)
        
        # Barcha xodimlar
        emp_domain = [('active', '=', True)]
        if department_id:
            emp_domain.append(('department_id', '=', department_id))
        
        all_employees = self.env['hr.employee'].search(emp_domain)
        
        # Bugun kelganlar
        att_domain = [
            ('check_in', '>=', today_start_utc),
            ('check_in', '<=', today_end_utc)
        ]
        if department_id:
            att_domain.append(('employee_id.department_id', '=', department_id))
        
        today_attendances = self.env['hr.attendance'].search(att_domain)
        present_employee_ids = set(today_attendances.mapped('employee_id').ids)
        
        # Kelmaganlar
        absent_employees = []
        for emp in all_employees:
            if emp.id not in present_employee_ids:
                absent_employees.append({
                    'id': emp.id,
                    'name': emp.name,
                    'department': emp.department_id.name or '-',
                })
        
        return absent_employees

    @api.model
    def get_monthly_work_summary(self, department_id=None, month=None, year=None):
        """
        Oylik hisobot - har bir kun uchun
        
        Kun turlari:
        - Soat: Ishlangan soatlar
        - D: Dam olish kuni
        - T: Ta'til
        - U: Davlat bayrami
        - -: Kelmadi (ish kuni)
        """
        tz = self.env.user.tz or 'Asia/Tashkent'
        local_tz = pytz.timezone(tz)
        
        today = fields.Date.today()
        if not month:
            month = today.month
        if not year:
            year = today.year
        
        # Oyning birinchi va oxirgi kuni
        first_day = datetime(year, month, 1).date()
        days_in_month = monthrange(year, month)[1]
        last_day = datetime(year, month, days_in_month).date()
        
        # Davlat bayramlari
        first_day_dt = datetime.combine(first_day, datetime.min.time())
        last_day_dt = datetime.combine(last_day, datetime.max.time())
        
        public_holidays = self.env['resource.calendar.leaves'].search([
            ('date_from', '<=', last_day_dt),
            ('date_to', '>=', first_day_dt),
            ('resource_id', '=', False),
        ])
        holiday_dates = set()
        for holiday in public_holidays:
            # UTC vaqtni lokal vaqtga o'tkazish
            start_utc = holiday.date_from.replace(tzinfo=pytz.UTC)
            end_utc = holiday.date_to.replace(tzinfo=pytz.UTC)
            start_local = start_utc.astimezone(local_tz).date()
            end_local = end_utc.astimezone(local_tz).date()
            
            current = start_local
            while current <= end_local:
                holiday_dates.add(current)
                current += timedelta(days=1)
        
        # Ta'tillar - oy uchun
        leave_domain = [
            ('state', '=', 'validate'),
            ('date_from', '<=', last_day_dt),
            ('date_to', '>=', first_day_dt),
        ]
        all_leaves = self.env['hr.leave'].search(leave_domain)
        
        # Xodimlar
        emp_domain = [('active', '=', True)]
        if department_id:
            emp_domain.append(('department_id', '=', department_id))
        
        employees = self.env['hr.employee'].search(emp_domain, order='name')
        
        data = []
        for emp in employees:
            # Xodimning ish jadvali
            calendar = emp.resource_calendar_id
            
            # Xodimning ta'tillari
            emp_leaves = all_leaves.filtered(lambda l: l.employee_id.id == emp.id)
            leave_dates = set()
            for leave in emp_leaves:
                current = leave.date_from.date()
                end = leave.date_to.date()
                while current <= end:
                    leave_dates.add(current)
                    current += timedelta(days=1)
            
            # Ish kunlari (calendar'dan)
            work_days = set()
            if calendar:
                for att in calendar.attendance_ids:
                    work_days.add(int(att.dayofweek))
            else:
                # Agar jadval yo'q bo'lsa, Dushanba-Juma
                work_days = {0, 1, 2, 3, 4}
            
            # Har bir kun uchun
            days = []
            total_hours = 0.0
            total_work_days = 0
            
            for day_num in range(1, days_in_month + 1):
                current_date = datetime(year, month, day_num).date()
                weekday = current_date.weekday()
                
                day_data = {'day': day_num, 'value': '', 'type': ''}
                
                # 1. Davlat bayrami tekshirish
                if current_date in holiday_dates:
                    day_data['value'] = 'U'
                    day_data['type'] = 'holiday'
                
                # 2. Ta'til tekshirish
                elif current_date in leave_dates:
                    day_data['value'] = 'T'
                    day_data['type'] = 'leave'
                
                # 3. Dam olish kuni tekshirish
                elif weekday not in work_days:
                    day_data['value'] = 'D'
                    day_data['type'] = 'rest'
                
                # 4. Ish kuni - davomat tekshirish
                else:
                    total_work_days += 1
                    
                    # UTC vaqtga aylantirish
                    day_start_local = local_tz.localize(datetime.combine(current_date, datetime.min.time()))
                    day_end_local = local_tz.localize(datetime.combine(current_date, datetime.max.time()))
                    day_start_utc = day_start_local.astimezone(pytz.UTC).replace(tzinfo=None)
                    day_end_utc = day_end_local.astimezone(pytz.UTC).replace(tzinfo=None)
                    
                    attendances = self.env['hr.attendance'].search([
                        ('employee_id', '=', emp.id),
                        ('check_in', '>=', day_start_utc),
                        ('check_in', '<=', day_end_utc)
                    ])
                    
                    if attendances:
                        day_hours = sum(att.worked_hours or 0.0 for att in attendances if att.check_out)
                        total_hours += day_hours
                        day_data['value'] = str(round(day_hours, 1)) if day_hours > 0 else '-'
                        day_data['type'] = 'work' if day_hours > 0 else 'absent'
                    else:
                        # Agar kelajakdagi kun bo'lsa
                        if current_date > today:
                            day_data['value'] = ''
                            day_data['type'] = 'future'
                        else:
                            day_data['value'] = '-'
                            day_data['type'] = 'absent'
                
                days.append(day_data)
            
            data.append({
                'id': emp.id,
                'name': emp.name,
                'department': emp.department_id.name or '-',
                'days': days,
                'total_hours': round(total_hours, 1),
                'total_work_days': total_work_days,
            })
        
        # Oy nomi
        month_names = ['', 'Yanvar', 'Fevral', 'Mart', 'Aprel', 'May', 'Iyun',
                       'Iyul', 'Avgust', 'Sentabr', 'Oktabr', 'Noyabr', 'Dekabr']
        
        return {
            'employees': data,
            'days_in_month': days_in_month,
            'month': month,
            'year': year,
            'month_name': month_names[month],
        }

    @api.model
    def get_on_leave_employees(self, department_id=None):
        """Bugun ta'tilda bo'lgan xodimlar ro'yxati"""
        tz = self.env.user.tz or 'Asia/Tashkent'
        local_tz = pytz.timezone(tz)
        
        now_local = datetime.now(local_tz)
        today = now_local.date()
        
        # Today as datetime range for leave search
        today_start = datetime.combine(today, datetime.min.time())
        today_end = datetime.combine(today, datetime.max.time())
        
        # Ta'tillar
        leave_domain = [
            ('state', '=', 'validate'),
            ('date_from', '<=', today_end),
            ('date_to', '>=', today_start),
        ]
        if department_id:
            leave_domain.append(('employee_id.department_id', '=', department_id))
        
        leaves = self.env['hr.leave'].search(leave_domain)
        
        on_leave_employees = []
        for leave in leaves:
            emp = leave.employee_id
            if emp and emp.active:
                on_leave_employees.append({
                    'id': emp.id,
                    'name': emp.name,
                    'department': emp.department_id.name or '-',
                    'leave_type': leave.holiday_status_id.name or 'Ta\'til',
                })
        
        return on_leave_employees

    @api.model
    def get_all_dashboard_data(self, department_id=None):
        """Barcha dashboard ma'lumotlarini birdan olish"""
        today_stats = self.get_today_attendance_stats(department_id)
        on_leave = self.get_on_leave_employees(department_id)
        today_stats['on_leave_count'] = len(on_leave)
        
        return {
            'today_stats': today_stats,
            'absent_employees': self.get_absent_employees(department_id),
            'on_leave_employees': on_leave,
            'departments': self.get_departments(),
        }

