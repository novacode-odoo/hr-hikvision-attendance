# -*- coding: utf-8 -*-

from odoo import models, fields, api
from datetime import datetime, timedelta
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
    def get_job_positions(self):
        """Barcha lavozimlar ro'yxati"""
        jobs = self.env['hr.job'].search([])
        return [{'id': j.id, 'name': j.name} for j in jobs]

    @api.model
    def get_today_attendance_stats(self, department_id=None, job_id=None):
        """Bugungi davomat statistikasi"""
        # Foydalanuvchi timezone'ini olish
        tz = self.env.user.tz or 'Asia/Tashkent'
        local_tz = pytz.timezone(tz)
        
        # Bugungi kunni local timezone'da olish
        now_local = datetime.now(local_tz)
        today_start_local = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
        today_end_local = now_local.replace(hour=23, minute=59, second=59, microsecond=999999)
        
        # UTC ga aylantirish (database query uchun)
        today_start_utc = today_start_local.astimezone(pytz.UTC).replace(tzinfo=None)
        today_end_utc = today_end_local.astimezone(pytz.UTC).replace(tzinfo=None)
        
        _logger.info(f"Dashboard: Searching attendance from {today_start_utc} to {today_end_utc} (UTC)")
        
        # Employee domain
        emp_domain = [('active', '=', True)]
        if department_id:
            emp_domain.append(('department_id', '=', department_id))
        if job_id:
            emp_domain.append(('job_id', '=', job_id))
        
        # Jami xodimlar soni
        total_employees = self.env['hr.employee'].search_count(emp_domain)
        
        # Attendance domain
        att_domain = [
            ('check_in', '>=', today_start_utc),
            ('check_in', '<=', today_end_utc)
        ]
        if department_id:
            att_domain.append(('employee_id.department_id', '=', department_id))
        if job_id:
            att_domain.append(('employee_id.job_id', '=', job_id))
        
        # Bugun kelgan xodimlar
        today_attendances = self.env['hr.attendance'].search(att_domain)
        _logger.info(f"Dashboard: Found {len(today_attendances)} attendance records")
        
        present_employees = len(today_attendances.mapped('employee_id'))
        absent_employees = total_employees - present_employees
        
        # Hozirda ishda (check_out bo'lmaganlar)
        working_domain = att_domain + [('check_out', '=', False)]
        currently_working = self.env['hr.attendance'].search_count(working_domain)
        
        # Kechikkanlar
        late_count = 0
        if 'is_late' in self.env['hr.attendance']._fields:
            late_domain = att_domain + [('is_late', '=', True)]
            late_count = self.env['hr.attendance'].search_count(late_domain)
        
        # Erta ketganlar
        early_leave_count = 0
        if 'is_early_leave' in self.env['hr.attendance']._fields:
            early_domain = [
                ('check_out', '>=', today_start_utc),
                ('check_out', '<=', today_end_utc),
                ('is_early_leave', '=', True)
            ]
            if department_id:
                early_domain.append(('employee_id.department_id', '=', department_id))
            if job_id:
                early_domain.append(('employee_id.job_id', '=', job_id))
            early_leave_count = self.env['hr.attendance'].search_count(early_domain)
        
        return {
            'total_employees': total_employees,
            'present_employees': present_employees,
            'absent_employees': absent_employees,
            'currently_working': currently_working,
            'late_count': late_count,
            'early_leave_count': early_leave_count,
            'attendance_rate': round((present_employees / total_employees * 100) if total_employees else 0, 1),
        }

    @api.model
    def get_weekly_attendance_data(self, department_id=None, job_id=None):
        """Haftalik davomat ma'lumotlari (oxirgi 7 kun)"""
        # Foydalanuvchi timezone'ini olish
        tz = self.env.user.tz or 'Asia/Tashkent'
        local_tz = pytz.timezone(tz)
        
        now_local = datetime.now(local_tz)
        today = now_local.date()
        data = []
        
        # Employee domain
        emp_domain = [('active', '=', True)]
        if department_id:
            emp_domain.append(('department_id', '=', department_id))
        if job_id:
            emp_domain.append(('job_id', '=', job_id))
        total_employees = self.env['hr.employee'].search_count(emp_domain)
        
        for i in range(6, -1, -1):
            date = today - timedelta(days=i)
            day_name = date.strftime('%a')
            
            # Local timezone'da kun boshi va oxiri
            day_start_local = local_tz.localize(datetime.combine(date, datetime.min.time()))
            day_end_local = local_tz.localize(datetime.combine(date, datetime.max.time()))
            
            # UTC ga aylantirish
            day_start_utc = day_start_local.astimezone(pytz.UTC).replace(tzinfo=None)
            day_end_utc = day_end_local.astimezone(pytz.UTC).replace(tzinfo=None)
            
            att_domain = [
                ('check_in', '>=', day_start_utc),
                ('check_in', '<=', day_end_utc)
            ]
            if department_id:
                att_domain.append(('employee_id.department_id', '=', department_id))
            if job_id:
                att_domain.append(('employee_id.job_id', '=', job_id))
            
            attendances = self.env['hr.attendance'].search(att_domain)
            present = len(attendances.mapped('employee_id'))
            rate = round((present / total_employees * 100) if total_employees else 0, 1)
            
            data.append({
                'day': day_name,
                'date': date.strftime('%d/%m'),
                'present': present,
                'rate': rate,
            })
        
        return data

    @api.model
    def get_department_attendance(self, job_id=None):
        """Bo'limlar bo'yicha davomat statistikasi"""
        today = fields.Date.today()
        departments = self.env['hr.department'].search([])
        
        data = []
        for dept in departments:
            emp_domain = [
                ('department_id', '=', dept.id),
                ('active', '=', True)
            ]
            if job_id:
                emp_domain.append(('job_id', '=', job_id))
            
            total = self.env['hr.employee'].search_count(emp_domain)
            
            if total == 0:
                continue
            
            att_domain = [
                ('check_in', '>=', datetime.combine(today, datetime.min.time())),
                ('check_in', '<=', datetime.combine(today, datetime.max.time())),
                ('employee_id.department_id', '=', dept.id)
            ]
            if job_id:
                att_domain.append(('employee_id.job_id', '=', job_id))
            
            attendances = self.env['hr.attendance'].search(att_domain)
            present = len(attendances.mapped('employee_id'))
            
            data.append({
                'department': dept.name,
                'department_id': dept.id,
                'total': total,
                'present': present,
                'absent': total - present,
                'rate': round((present / total * 100) if total else 0, 1),
            })
        
        data.sort(key=lambda x: x['rate'], reverse=True)
        return data[:10]

    @api.model
    def get_job_attendance(self, department_id=None):
        """Lavozimlar bo'yicha davomat statistikasi"""
        today = fields.Date.today()
        jobs = self.env['hr.job'].search([])
        
        data = []
        for job in jobs:
            emp_domain = [
                ('job_id', '=', job.id),
                ('active', '=', True)
            ]
            if department_id:
                emp_domain.append(('department_id', '=', department_id))
            
            total = self.env['hr.employee'].search_count(emp_domain)
            
            if total == 0:
                continue
            
            att_domain = [
                ('check_in', '>=', datetime.combine(today, datetime.min.time())),
                ('check_in', '<=', datetime.combine(today, datetime.max.time())),
                ('employee_id.job_id', '=', job.id)
            ]
            if department_id:
                att_domain.append(('employee_id.department_id', '=', department_id))
            
            attendances = self.env['hr.attendance'].search(att_domain)
            present = len(attendances.mapped('employee_id'))
            
            data.append({
                'job': job.name,
                'job_id': job.id,
                'total': total,
                'present': present,
                'absent': total - present,
                'rate': round((present / total * 100) if total else 0, 1),
            })
        
        data.sort(key=lambda x: x['rate'], reverse=True)
        return data[:10]

    @api.model
    def get_hourly_checkins(self, department_id=None, job_id=None):
        """Soatlik kirish statistikasi (bugun)"""
        today = fields.Date.today()
        data = []
        
        for hour in range(6, 22):
            start_time = datetime.combine(today, datetime.min.time()) + timedelta(hours=hour)
            end_time = start_time + timedelta(hours=1)
            
            domain = [
                ('check_in', '>=', start_time),
                ('check_in', '<', end_time)
            ]
            if department_id:
                domain.append(('employee_id.department_id', '=', department_id))
            if job_id:
                domain.append(('employee_id.job_id', '=', job_id))
            
            count = self.env['hr.attendance'].search_count(domain)
            
            data.append({
                'hour': f'{hour:02d}:00',
                'count': count,
            })
        
        return data

    @api.model
    def get_recent_checkins(self, limit=10, department_id=None, job_id=None):
        """Oxirgi kirishlar"""
        # Foydalanuvchi timezone'ini olish
        tz = self.env.user.tz or 'Asia/Tashkent'
        local_tz = pytz.timezone(tz)
        
        now_local = datetime.now(local_tz)
        today_start_local = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
        today_start_utc = today_start_local.astimezone(pytz.UTC).replace(tzinfo=None)
        
        domain = [
            ('check_in', '>=', today_start_utc),
        ]
        if department_id:
            domain.append(('employee_id.department_id', '=', department_id))
        if job_id:
            domain.append(('employee_id.job_id', '=', job_id))
        
        attendances = self.env['hr.attendance'].search(domain, order='check_in desc', limit=limit)
        
        data = []
        for att in attendances:
            check_in = att.check_in
            check_out = att.check_out
            
            if check_in:
                tz = self.env.user.tz or 'UTC'
                local_tz = pytz.timezone(tz)
                check_in_local = pytz.UTC.localize(check_in).astimezone(local_tz)
                check_in_str = check_in_local.strftime('%H:%M')
            else:
                check_in_str = '-'
            
            if check_out:
                tz = self.env.user.tz or 'UTC'
                local_tz = pytz.timezone(tz)
                check_out_local = pytz.UTC.localize(check_out).astimezone(local_tz)
                check_out_str = check_out_local.strftime('%H:%M')
            else:
                check_out_str = '-'
            
            data.append({
                'employee_name': att.employee_id.name,
                'department': att.employee_id.department_id.name or '-',
                'job': att.employee_id.job_id.name or '-',
                'check_in': check_in_str,
                'check_out': check_out_str,
                'is_late': getattr(att, 'is_late', False),
                'is_early_leave': getattr(att, 'is_early_leave', False),
            })
        
        return data

    @api.model
    def get_employee_list(self, department_id=None, job_id=None, status='all'):
        """Xodimlar ro'yxati (filter bilan)"""
        today = fields.Date.today()
        
        emp_domain = [('active', '=', True)]
        if department_id:
            emp_domain.append(('department_id', '=', department_id))
        if job_id:
            emp_domain.append(('job_id', '=', job_id))
        
        employees = self.env['hr.employee'].search(emp_domain)
        
        data = []
        for emp in employees:
            # Bugungi davomat
            att = self.env['hr.attendance'].search([
                ('employee_id', '=', emp.id),
                ('check_in', '>=', datetime.combine(today, datetime.min.time())),
                ('check_in', '<=', datetime.combine(today, datetime.max.time()))
            ], limit=1, order='check_in desc')
            
            is_present = bool(att)
            is_working = att and not att.check_out
            
            if status == 'present' and not is_present:
                continue
            elif status == 'absent' and is_present:
                continue
            elif status == 'working' and not is_working:
                continue
            
            check_in_str = '-'
            check_out_str = '-'
            
            if att and att.check_in:
                tz = self.env.user.tz or 'UTC'
                local_tz = pytz.timezone(tz)
                check_in_local = pytz.UTC.localize(att.check_in).astimezone(local_tz)
                check_in_str = check_in_local.strftime('%H:%M')
            
            if att and att.check_out:
                tz = self.env.user.tz or 'UTC'
                local_tz = pytz.timezone(tz)
                check_out_local = pytz.UTC.localize(att.check_out).astimezone(local_tz)
                check_out_str = check_out_local.strftime('%H:%M')
            
            data.append({
                'id': emp.id,
                'name': emp.name,
                'department': emp.department_id.name or '-',
                'job': emp.job_id.name or '-',
                'check_in': check_in_str,
                'check_out': check_out_str,
                'is_present': is_present,
                'is_working': is_working,
                'is_late': getattr(att, 'is_late', False) if att else False,
                'is_early_leave': getattr(att, 'is_early_leave', False) if att else False,
            })
        
        return data

    @api.model
    def get_monthly_work_summary(self, department_id=None, job_id=None, month=None, year=None):
        """Oylik ish statistikasi - har bir xodim uchun"""
        from calendar import monthrange
        
        # Joriy oy va yil (agar berilmagan bo'lsa)
        today = fields.Date.today()
        if not month:
            month = today.month
        if not year:
            year = today.year
        
        # Oyning birinchi va oxirgi kuni
        first_day = datetime(year, month, 1).date()
        last_day_num = monthrange(year, month)[1]
        last_day = datetime(year, month, last_day_num).date()
        
        # Bugungi kunga qadar hisoblash (agar joriy oy bo'lsa)
        if year == today.year and month == today.month:
            last_day = min(last_day, today)
        
        # Xodimlar ro'yxati
        emp_domain = [('active', '=', True)]
        if department_id:
            emp_domain.append(('department_id', '=', department_id))
        if job_id:
            emp_domain.append(('job_id', '=', job_id))
        
        employees = self.env['hr.employee'].search(emp_domain)
        
        data = []
        for emp in employees:
            # Ish jadvali
            calendar = emp.resource_calendar_id
            
            # Ish kunlarini va soatlarini hisoblash
            expected_days = 0
            worked_days = 0
            expected_hours = 0.0
            worked_hours = 0.0
            rest_days = []
            
            current = first_day
            while current <= last_day:
                is_work_day = False
                day_hours = 0.0
                
                if calendar:
                    # Ish jadvalidan kun hafta kuniga to'g'ri kelishini tekshirish
                    weekday = current.weekday()  # 0 = Dushanba, 6 = Yakshanba
                    
                    # Calendar attendance lar - bu ish kunlari
                    for attendance in calendar.attendance_ids:
                        if int(attendance.dayofweek) == weekday:
                            is_work_day = True
                            break
                    
                    # Agar ish kuni bo'lsa, calendar.hours_per_day dan soatni olish
                    # Bu tushlik vaqtini hisobga olmaydi
                    if is_work_day:
                        day_hours = calendar.hours_per_day or 8.0
                    
                    if is_work_day:
                        expected_days += 1
                        expected_hours += day_hours
                        
                        # Bu kun ishladimi?
                        day_start = datetime.combine(current, datetime.min.time())
                        day_end = datetime.combine(current, datetime.max.time())
                        
                        attendances = self.env['hr.attendance'].search([
                            ('employee_id', '=', emp.id),
                            ('check_in', '>=', day_start),
                            ('check_in', '<=', day_end)
                        ])
                        
                        if attendances:
                            worked_days += 1
                            # Ishlangan soatlarni hisoblash
                            for att in attendances:
                                if att.check_out:
                                    worked_hours += att.worked_hours or 0.0
                        else:
                            rest_days.append(current.strftime('%d'))
                else:
                    # Agar ish jadvali yo'q bo'lsa, faqat ishlagan soatlarni hisoblash
                    day_start = datetime.combine(current, datetime.min.time())
                    day_end = datetime.combine(current, datetime.max.time())
                    
                    attendances = self.env['hr.attendance'].search([
                        ('employee_id', '=', emp.id),
                        ('check_in', '>=', day_start),
                        ('check_in', '<=', day_end)
                    ])
                    
                    for att in attendances:
                        if att.check_out:
                            worked_hours += att.worked_hours or 0.0
                
                current += timedelta(days=1)
            
            # Ta'til soatlarini va kunlarini hisoblash
            leave_hours = 0.0
            leave_days = 0.0
            try:
                # hr.leave dan tasdiqlangan ta'tillarni olish
                leave_domain = [
                    ('employee_id', '=', emp.id),
                    ('state', '=', 'validate'),
                    ('date_from', '<=', datetime.combine(last_day, datetime.max.time())),
                    ('date_to', '>=', datetime.combine(first_day, datetime.min.time())),
                ]
                leaves = self.env['hr.leave'].search(leave_domain)
                for leave in leaves:
                    # Ta'til kunlarini olish
                    days = leave.number_of_days or 0.0
                    leave_days += days
                    
                    # Soatlarni hisoblash
                    # Agar number_of_hours maydoni bo'lsa, uni ishlatamiz
                    if hasattr(leave, 'number_of_hours_display') and leave.number_of_hours_display:
                        leave_hours += leave.number_of_hours_display
                    elif hasattr(leave, 'number_of_hours') and leave.number_of_hours:
                        leave_hours += leave.number_of_hours
                    else:
                        # Kunlarni soatga aylantirish (calendar.hours_per_day yoki 8 soat)
                        hours_per_day = calendar.hours_per_day if calendar else 8.0
                        leave_hours += days * hours_per_day
            except Exception as e:
                # Agar hr.leave modeli yo'q bo'lsa yoki xato bo'lsa
                _logger.warning(f"Ta'til hisoblashda xato: {str(e)}")
                pass
            
            # Foiz hisoblash
            rate = round((worked_days / expected_days * 100) if expected_days else 0, 1)
            
            data.append({
                'id': emp.id,
                'name': emp.name,
                'department': emp.department_id.name or '-',
                'job': emp.job_id.name or '-',
                'expected_days': expected_days,
                'worked_days': worked_days,
                'rest_count': len(rest_days),
                'rest_days': rest_days,
                'expected_hours': round(expected_hours, 1),
                'worked_hours': round(worked_hours, 1),
                'leave_days': round(leave_days, 1),
                'leave_hours': round(leave_hours, 1),
                'rate': rate,
            })
        
        # Davomat foizi bo'yicha tartiblash
        data.sort(key=lambda x: x['rate'], reverse=True)
        
        return {
            'employees': data,
            'month': month,
            'year': year,
            'month_name': datetime(year, month, 1).strftime('%B'),
        }

    @api.model
    def get_all_dashboard_data(self, department_id=None, job_id=None):
        """Barcha dashboard ma'lumotlarini birdan olish"""
        return {
            'today_stats': self.get_today_attendance_stats(department_id, job_id),
            'weekly_data': self.get_weekly_attendance_data(department_id, job_id),
            'department_data': self.get_department_attendance(job_id),
            'job_data': self.get_job_attendance(department_id),
            'hourly_data': self.get_hourly_checkins(department_id, job_id),
            'recent_checkins': self.get_recent_checkins(10, department_id, job_id),
            'monthly_summary': self.get_monthly_work_summary(department_id, job_id),
            'departments': self.get_departments(),
            'jobs': self.get_job_positions(),
        }
