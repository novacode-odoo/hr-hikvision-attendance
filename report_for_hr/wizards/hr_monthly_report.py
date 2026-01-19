# -*- coding: utf-8 -*-

from odoo import models, fields, api
from datetime import datetime, timedelta
from calendar import monthrange
import base64
import io
import pytz

try:
    import xlsxwriter
except ImportError:
    xlsxwriter = None


class HrMonthlyReport(models.TransientModel):
    _name = 'hr.monthly.report'
    _description = 'Oylik Ish Soatlari Hisoboti'

    month = fields.Selection([
        ('1', 'Yanvar'),
        ('2', 'Fevral'),
        ('3', 'Mart'),
        ('4', 'Aprel'),
        ('5', 'May'),
        ('6', 'Iyun'),
        ('7', 'Iyul'),
        ('8', 'Avgust'),
        ('9', 'Sentabr'),
        ('10', 'Oktabr'),
        ('11', 'Noyabr'),
        ('12', 'Dekabr'),
    ], string='Oy', required=True, default=lambda self: str(datetime.now().month))
    
    year = fields.Char(
        string='Yil',
        required=True,
        default=lambda self: str(datetime.now().year)
    )
    
    department_id = fields.Many2one(
        'hr.department',
        string="Bo'lim",
        help="Bo'limni tanlang (ixtiyoriy)"
    )
    
    line_ids = fields.One2many(
        'hr.monthly.report.line',
        'report_id',
        string='Hisobot qatorlari'
    )
    
    excel_file = fields.Binary(string='Excel fayl')
    excel_filename = fields.Char(string='Fayl nomi')
    
    days_in_month = fields.Integer(
        string='Oydagi kunlar soni',
        compute='_compute_days_in_month',
        store=True
    )
    
    @api.depends('month', 'year')
    def _compute_days_in_month(self):
        import calendar
        for record in self:
            if record.month and record.year:
                try:
                    month = int(record.month)
                    year = int(record.year)
                    record.days_in_month = calendar.monthrange(year, month)[1]
                except (ValueError, TypeError):
                    record.days_in_month = 31
            else:
                record.days_in_month = 31


    def action_generate_report(self):
        """Generate monthly report data"""
        self.ensure_one()
        
        # Clear existing lines
        self.line_ids.unlink()
        
        # Get date range for the month
        year = int(self.year)
        month = int(self.month)
        last_day_num = monthrange(year, month)[1]
        
        # Create dictionary of all dates in month
        month_dates = {}
        for day in range(1, last_day_num + 1):
            date_obj = datetime(year, month, day).date()
            month_dates[date_obj] = day
            
        first_date = datetime(year, month, 1).date()
        last_date = datetime(year, month, last_day_num).date()
        
        # Get employees
        domain = [('active', '=', True)]
        if self.department_id:
            domain.append(('department_id', '=', self.department_id.id))
        employees = self.env['hr.employee'].search(domain)
        
        # Helper to check global leaves (Public Holidays)
        # Assuming resource.calendar.leaves stores global leaves with resource_id=False
        public_holidays = self.env['resource.calendar.leaves'].search([
            ('resource_id', '=', False),
            ('date_from', '<=', datetime.combine(last_date, datetime.max.time())),
            ('date_to', '>=', datetime.combine(first_date, datetime.min.time())),
        ])
        
        def is_public_holiday(check_date):
            dt = datetime.combine(check_date, datetime.min.time())
            for holiday in public_holidays:
                if holiday.date_from <= dt <= holiday.date_to:
                    return True
            return False

        lines = []
        for emp in employees:
            # Get employee's calendar for schedule
            calendar = emp.resource_calendar_id or self.env.company.resource_calendar_id
            user_tz = pytz.timezone(self.env.user.tz or 'Asia/Tashkent')
            
            # 1. Get attendances for this employee in this month
            attendances = self.env['hr.attendance'].search([
                ('employee_id', '=', emp.id),
                ('check_in', '>=', datetime.combine(first_date, datetime.min.time())),
                ('check_in', '<=', datetime.combine(last_date, datetime.max.time())),
            ])
            
            # Get leaves for this employee FIRST (needed for attendance_map filtering)
            leaves = self.env['hr.leave'].search([
                ('employee_id', '=', emp.id),
                ('state', '=', 'validate'),
                ('date_from', '<=', last_date),
                ('date_to', '>=', first_date),
            ])
            
            leave_dates = set()
            for leave in leaves:
                # Iterate each day of leave
                current = leave.date_from.date()
                end = leave.date_to.date()
                while current <= end:
                    if first_date <= current <= last_date:
                        leave_dates.add(current)
                    current += timedelta(days=1)
            
            attendance_map = {}  # date -> scheduled hours only (not extra time)
            for att in attendances:
                if not att.check_in or not att.check_out:
                    continue
                    
                d = att.check_in.date()
                day_of_week = str(d.weekday())  # 0=Monday, 6=Sunday
                
                # Skip leave days - they will be counted as overtime if approved
                if d in leave_dates:
                    continue
                
                # Get schedule for this day (exclude lunch/break periods)
                schedule_lines = calendar.attendance_ids.filtered(
                    lambda a: a.dayofweek == day_of_week and a.day_period != 'lunch'
                )
                
                if not schedule_lines:
                    # No schedule for this day (non-work day) - skip adding to total hours
                    # This time will be counted as overtime if approved
                    continue
                
                # Convert check_in and check_out to local timezone
                check_in_utc = att.check_in.replace(tzinfo=pytz.UTC)
                check_in_local = check_in_utc.astimezone(user_tz)
                check_in_hour = check_in_local.hour + check_in_local.minute / 60.0
                
                check_out_utc = att.check_out.replace(tzinfo=pytz.UTC)
                check_out_local = check_out_utc.astimezone(user_tz)
                check_out_hour = check_out_local.hour + check_out_local.minute / 60.0
                
                # Convert grace periods from minutes to hours (read from settings)
                grace = self.env['hr.report.settings'].get_grace_minutes()
                late_grace_hours = grace['late'] / 60.0
                early_leave_grace_hours = grace['early'] / 60.0
                
                # Calculate worked hours for each schedule segment separately
                # This way lunch break is automatically excluded
                worked_within_schedule = 0.0
                for sched in schedule_lines:
                    seg_start = sched.hour_from
                    seg_end = sched.hour_to
                    
                    # Apply grace period for late arrival
                    # If employee arrived within grace period after segment start, count from segment start
                    if check_in_hour > seg_start and check_in_hour <= (seg_start + late_grace_hours):
                        effective_check_in = seg_start
                    else:
                        effective_check_in = check_in_hour
                    
                    # Apply grace period for early departure
                    # If employee left within grace period before segment end, count until segment end
                    if check_out_hour < seg_end and check_out_hour >= (seg_end - early_leave_grace_hours):
                        effective_check_out = seg_end
                    else:
                        effective_check_out = check_out_hour
                    
                    # Find overlap between attendance and this schedule segment
                    overlap_start = max(effective_check_in, seg_start)
                    overlap_end = min(effective_check_out, seg_end)
                    
                    if overlap_end > overlap_start:
                        worked_within_schedule += overlap_end - overlap_start
                
                attendance_map[d] = attendance_map.get(d, 0.0) + worked_within_schedule
            
            # 2. Get Work Days from Calendar (exclude lunch periods)
            work_days_of_week = set(int(d) for d in calendar.attendance_ids.filtered(lambda a: a.day_period != 'lunch').mapped('dayofweek'))
            
            total_hours = sum(attendance_map.values())
            
            # Calculate overtime - only LATE DEPARTURE (kech ketgan), not early arrival
            # Only count approved overtime
            total_overtime = 0.0
            
            # Get approved overtime records for this employee in this month
            overtime_records = self.env['hr.attendance.overtime.line'].search([
                ('employee_id', '=', emp.id),
                ('date', '>=', first_date),
                ('date', '<=', last_date),
                ('status', '=', 'approved'),  # Only approved
            ])
            
            for ot in overtime_records:
                if not ot.time_stop or not ot.time_start:
                    continue
                    
                # Get scheduled end time for this day from employee's calendar
                calendar = emp.resource_calendar_id or self.env.company.resource_calendar_id
                day_of_week = str(ot.date.weekday())  # 0=Monday, 6=Sunday
                
                # Find the scheduled times for this day (exclude lunch)
                schedule_lines = calendar.attendance_ids.filtered(
                    lambda a: a.dayofweek == day_of_week and a.day_period != 'lunch'
                )
                
                # Convert times from UTC to local timezone
                user_tz = pytz.timezone(self.env.user.tz or 'Asia/Tashkent')
                check_in_utc = ot.time_start.replace(tzinfo=pytz.UTC)
                check_in_local = check_in_utc.astimezone(user_tz)
                check_in_hour = check_in_local.hour + check_in_local.minute / 60.0
                
                check_out_utc = ot.time_stop.replace(tzinfo=pytz.UTC)
                check_out_local = check_out_utc.astimezone(user_tz)
                check_out_hour = check_out_local.hour + check_out_local.minute / 60.0
                
                if not schedule_lines or ot.date in leave_dates:
                    # Non-work day (dam olish kuni) - count worked time as overtime BUT deduct lunch
                    overtime_hours = check_out_hour - check_in_hour
                    
                    # Find lunch/break periods for this day (even if it's a non-work day, we check standard schedule)
                    lunch_lines = calendar.attendance_ids.filtered(
                        lambda a: a.dayofweek == day_of_week and a.day_period == 'lunch'
                    )
                    
                    # If no lunch found for this day (e.g. weekend), try fetching Monday's lunch schedule as fallback
                    if not lunch_lines:
                         lunch_lines = calendar.attendance_ids.filtered(
                            lambda a: a.dayofweek == '0' and a.day_period == 'lunch'
                        )
                    
                    # Deduct lunch duration if it overlaps with worked time
                    for lunch in lunch_lines:
                        # Find overlap between worked time and lunch time
                        overlap_start = max(check_in_hour, lunch.hour_from)
                        overlap_end = min(check_out_hour, lunch.hour_to)
                        
                        if overlap_end > overlap_start:
                            deduction = overlap_end - overlap_start
                            overtime_hours -= deduction
                            
                    if overtime_hours > 0:
                        total_overtime += overtime_hours
                else:
                    # Work day - only count late departure time
                    scheduled_end_hour = max(schedule_lines.mapped('hour_to'))
                    if check_out_hour > scheduled_end_hour:
                        late_hours = check_out_hour - scheduled_end_hour
                        total_overtime += late_hours
            
            worked_days = len(attendance_map)
            
            # Prepare line data
            line_data = {
                'report_id': self.id,
                'employee_id': emp.id,
                'department_id': emp.department_id.id,
                'worked_days': worked_days,
                'total_hours': total_hours,
                'total_overtime': total_overtime,
            }
            
            # Fill daily columns
            for current_date, day_num in month_dates.items():
                field_name = f'day_{day_num}'
                
                # Logic Priority:
                # 1. Attendance (Actual work done) -> Show Hours
                if current_date in attendance_map:
                    hours = attendance_map[current_date]
                    total_minutes = round(hours * 60)  # Convert to minutes and round
                    h = total_minutes // 60
                    m = total_minutes % 60
                    line_data[field_name] = f"{h:02d}:{m:02d}"
                    continue
                
                # 2. Public Holiday -> 'B'
                if is_public_holiday(current_date):
                    line_data[field_name] = 'B'
                    continue
                
                # 3. Employee Leave -> 'T'
                if current_date in leave_dates:
                    line_data[field_name] = 'T'
                    continue
                
                # 4. Day Off (Weekend/Not in schedule) -> 'D'
                # weekday(): Mon=0, Sun=6
                if current_date.weekday() not in work_days_of_week:
                    line_data[field_name] = 'D'
                    continue
                
                # 5. Absent (Work day, no attendance, no leave, no holiday) -> Empty
                line_data[field_name] = ''

            lines.append(line_data)
        
        self.env['hr.monthly.report.line'].create(lines)
        
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'hr.monthly.report',
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }

    def action_export_excel(self):
        """Export report to Excel"""
        self.ensure_one()
        
        if not xlsxwriter:
            raise Exception("xlsxwriter kutubxonasi o'rnatilmagan!")
        
        # Create Excel file in memory
        output = io.BytesIO()
        workbook = xlsxwriter.Workbook(output, {'in_memory': True})
        worksheet = workbook.add_worksheet('Hisobot')
        
        # Styles
        header_format = workbook.add_format({
            'bold': True,
            'bg_color': '#714B67',
            'font_color': 'white',
            'border': 1,
            'align': 'center',
            'valign': 'vcenter',
        })
        cell_format = workbook.add_format({
            'border': 1,
            'align': 'center', # Centered for status chars and times
            'valign': 'vcenter',
        })
        name_format = workbook.add_format({
            'border': 1,
            'align': 'left',
            'valign': 'vcenter',
        })
        
        # Title
        month_names = dict(self._fields['month'].selection)
        title = f"Oylik Ish Soatlari Hisoboti - {month_names[self.month]} {self.year}"
        # Adjust merge range based on columns (4 fixed + 31 days + 1 new overtime = 36 columns -> A to AJ)
        worksheet.merge_range('A1:AJ1', title, header_format)
        
        # Headers
        headers = ['#', 'Xodim', "Bo'lim"]
        # Add day headers 1-31
        days_in_month = monthrange(int(self.year), int(self.month))[1]
        for day in range(1, days_in_month + 1):
            headers.append(str(day))
        
        # Let's add Total columns at the end
        headers.extend(['Kunlar', 'Jami', "Qo'shimcha"])

        # Write headers
        for col, header in enumerate(headers):
            worksheet.write(2, col, header, header_format)
        
        # Column widths
        worksheet.set_column('A:A', 5) # #
        worksheet.set_column('B:B', 30) # Name
        worksheet.set_column('C:C', 20) # Dept
        worksheet.set_column('D:AH', 5) # Days 1-31 (approx)
        worksheet.set_column('AI:AK', 12) # Totals
        
        # Data rows
        row = 3
        for idx, line in enumerate(self.line_ids, 1):
            worksheet.write(row, 0, idx, cell_format)
            worksheet.write(row, 1, line.employee_id.name, name_format)
            worksheet.write(row, 2, line.department_id.name or '', name_format)
            
            col = 3
            # Write days 1 to days_in_month
            for day in range(1, days_in_month + 1):
                val = getattr(line, f'day_{day}') or ''
                worksheet.write(row, col, val, cell_format)
                col += 1
            
            # Works days
            worksheet.write(row, col, line.worked_days, cell_format)
            col += 1
            
            # Total Hours
            total_minutes = round(line.total_hours * 60)
            hours = total_minutes // 60
            minutes = total_minutes % 60
            worksheet.write(row, col, f"{hours}:{minutes:02d}", cell_format)
            col += 1
            
            # Total Overtime
            total_minutes = round(line.total_overtime * 60)
            hours = total_minutes // 60
            minutes = total_minutes % 60
            worksheet.write(row, col, f"{hours}:{minutes:02d}", cell_format)
            
            row += 1
        
        workbook.close()
        
        # Get Excel data
        output.seek(0)
        excel_data = output.read()
        
        # Save to record
        filename = f"oylik_hisobot_{month_names[self.month]}_{self.year}.xlsx"
        self.write({
            'excel_file': base64.b64encode(excel_data),
            'excel_filename': filename,
        })
        
        # Return download action
        return {
            'type': 'ir.actions.act_url',
            'url': f'/web/content/{self._name}/{self.id}/excel_file/{filename}?download=true',
            'target': 'self',
        }


class HrMonthlyReportLine(models.TransientModel):
    _name = 'hr.monthly.report.line'
    _description = 'Oylik Hisobot Qatori'

    report_id = fields.Many2one(
        'hr.monthly.report',
        string='Hisobot',
        ondelete='cascade'
    )
    employee_id = fields.Many2one(
        'hr.employee',
        string='Xodim',
        required=True
    )
    department_id = fields.Many2one(
        'hr.department',
        string="Bo'lim"
    )
    worked_days = fields.Integer(string='Ish kunlari')
    total_hours = fields.Float(string='Jami soat')
    total_overtime = fields.Float(string="Qo'shimcha ish")
    
    total_hours_display = fields.Char(
        string='Jami soat',
        compute='_compute_hours_display'
    )
    total_overtime_display = fields.Char(
        string="Qo'shimcha ish",
        compute='_compute_hours_display'
    )
    
    # Daily fields - Char for status chars or time string
    day_1 = fields.Char(string='1')
    day_2 = fields.Char(string='2')
    day_3 = fields.Char(string='3')
    day_4 = fields.Char(string='4')
    day_5 = fields.Char(string='5')
    day_6 = fields.Char(string='6')
    day_7 = fields.Char(string='7')
    day_8 = fields.Char(string='8')
    day_9 = fields.Char(string='9')
    day_10 = fields.Char(string='10')
    day_11 = fields.Char(string='11')
    day_12 = fields.Char(string='12')
    day_13 = fields.Char(string='13')
    day_14 = fields.Char(string='14')
    day_15 = fields.Char(string='15')
    day_16 = fields.Char(string='16')
    day_17 = fields.Char(string='17')
    day_18 = fields.Char(string='18')
    day_19 = fields.Char(string='19')
    day_20 = fields.Char(string='20')
    day_21 = fields.Char(string='21')
    day_22 = fields.Char(string='22')
    day_23 = fields.Char(string='23')
    day_24 = fields.Char(string='24')
    day_25 = fields.Char(string='25')
    day_26 = fields.Char(string='26')
    day_27 = fields.Char(string='27')
    day_28 = fields.Char(string='28')
    day_29 = fields.Char(string='29')
    day_30 = fields.Char(string='30')
    day_31 = fields.Char(string='31')
    
    # Related field for dynamic visibility of day columns
    days_in_month = fields.Integer(
        related='report_id.days_in_month',
        store=True
    )

    @api.depends('total_hours', 'total_overtime')
    def _compute_hours_display(self):
        for record in self:
            # Hours
            total_minutes = round(record.total_hours * 60)
            hours = total_minutes // 60
            minutes = total_minutes % 60
            record.total_hours_display = f"{hours}:{minutes:02d}"
            
            # Overtime
            total_minutes = round(record.total_overtime * 60)
            hours = total_minutes // 60
            minutes = total_minutes % 60
            record.total_overtime_display = f"{hours}:{minutes:02d}"
