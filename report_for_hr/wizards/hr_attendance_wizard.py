# -*- coding: utf-8 -*-

from odoo import models, fields, api
from datetime import datetime, timedelta
import pytz


class HrAttendanceWizard(models.TransientModel):
    _name = 'hr.attendance.wizard'
    _description = 'Attendance Creation Wizard'

    employee_ids = fields.Many2many(
        'hr.employee',
        string='Xodimlar',
        required=True
    )
    attendance_date = fields.Date(
        string='Sana',
        default=fields.Date.today,
        required=True
    )
    
    check_in_time = fields.Float(
        string='Kelish vaqti',
        default=8.0,
        help='Soat formatida (masalan: 8.5 = 8:30)'
    )
    check_out_time = fields.Float(
        string='Ketish vaqti', 
        default=17.0,
        help='Soat formatida (masalan: 17.0 = 17:00)'
    )

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        # Get selected employees from context
        active_ids = self._context.get('active_ids', [])
        if active_ids:
            res['employee_ids'] = [(6, 0, active_ids)]
        # Get date from context if passed
        attendance_date = self._context.get('default_attendance_date')
        if attendance_date:
            res['attendance_date'] = attendance_date
        return res

    def _get_user_timezone(self):
        """Get user's timezone or default to UTC"""
        tz_name = self.env.user.tz or 'UTC'
        return pytz.timezone(tz_name)

    def _float_to_utc_datetime(self, work_date, float_time):
        """Convert float time to UTC datetime considering user's timezone"""
        hours = int(float_time)
        minutes = int((float_time - hours) * 60)
        
        # Create naive datetime in local time
        local_dt = datetime.combine(work_date, datetime.min.time()) + timedelta(hours=hours, minutes=minutes)
        
        # Convert to user's timezone, then to UTC
        user_tz = self._get_user_timezone()
        local_dt = user_tz.localize(local_dt)
        utc_dt = local_dt.astimezone(pytz.UTC)
        
        # Return naive UTC datetime (Odoo stores naive UTC)
        return utc_dt.replace(tzinfo=None)

    def action_create_attendance(self):
        """Create attendance records for selected employees"""
        self.ensure_one()
        
        Attendance = self.env['hr.attendance']
        created_count = 0
        skipped_count = 0
        
        for employee in self.employee_ids:
            # Check if attendance already exists for this date (in UTC)
            user_tz = self._get_user_timezone()
            date_start_local = datetime.combine(self.attendance_date, datetime.min.time())
            date_end_local = datetime.combine(self.attendance_date, datetime.max.time())
            
            # Convert to UTC for search
            date_start_utc = user_tz.localize(date_start_local).astimezone(pytz.UTC).replace(tzinfo=None)
            date_end_utc = user_tz.localize(date_end_local).astimezone(pytz.UTC).replace(tzinfo=None)
            
            existing = Attendance.search([
                ('employee_id', '=', employee.id),
                ('check_in', '>=', date_start_utc),
                ('check_in', '<=', date_end_utc),
            ], limit=1)
            
            if existing:
                skipped_count += 1
                continue
            
            # Convert to UTC datetime
            check_in = self._float_to_utc_datetime(self.attendance_date, self.check_in_time)
            check_out = self._float_to_utc_datetime(self.attendance_date, self.check_out_time)
            
            # Create attendance
            Attendance.create({
                'employee_id': employee.id,
                'check_in': check_in,
                'check_out': check_out,
            })
            created_count += 1
        
        # Return notification
        message = f"{created_count} ta attendance yaratildi."
        if skipped_count:
            message += f" {skipped_count} ta xodimda allaqachon attendance bor edi."
        
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Natija',
                'message': message,
                'type': 'success',
                'sticky': False,
            }
        }
