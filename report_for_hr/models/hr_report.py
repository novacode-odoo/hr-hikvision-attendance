# -*- coding: utf-8 -*-

from odoo import models, fields, api
from datetime import datetime, date


class HrDailyReportLine(models.Model):
    _name = 'hr.daily.report.line'
    _description = 'HR Daily Report Line'
    _order = 'employee_id'

    daily_report_id = fields.Many2one('hr.daily.report', string='Daily Report', ondelete='cascade')
    employee_id = fields.Many2one('hr.employee', string='Xodim', required=True)
    department_id = fields.Many2one(related='employee_id.department_id', string='Bo\'lim', store=True)
    job_id = fields.Many2one(related='employee_id.job_id', string='Lavozim', store=True)
    work_phone = fields.Char(related='employee_id.work_phone', string='Telefon')
    status = fields.Selection([
        ('present', 'Kelgan'),
        ('absent', 'Kelmagan'),
        ('leave', "Ta'tilda"),
    ], string='Holat', required=True)


class HrDailyReport(models.Model):
    _name = 'hr.daily.report'
    _description = 'HR Daily Report Dashboard'
    _order = 'report_date desc'

    name = fields.Char(string='Name', compute='_compute_name', store=True)
    report_date = fields.Date(string='Sana', default=fields.Date.today, required=True)
    
    # Statistics - computed directly from data
    total_employees = fields.Integer(string='Jami xodimlar', compute='_compute_live_statistics')
    present_count = fields.Integer(string='Kelganlar', compute='_compute_live_statistics')
    absent_count = fields.Integer(string='Kelmaganlar', compute='_compute_live_statistics')
    on_leave_count = fields.Integer(string="Ta'tildagilar", compute='_compute_live_statistics')
    
    # Report lines (for backward compatibility)
    line_ids = fields.One2many('hr.daily.report.line', 'daily_report_id', string='Xodimlar')
    
    # Computed employee lists for tabs - direct from attendance/leave data
    absent_employee_ids = fields.Many2many(
        'hr.employee', string='Kelmagan xodimlar',
        compute='_compute_employee_lists'
    )
    leave_ids = fields.Many2many(
        'hr.leave', string="Ta'tillar",
        compute='_compute_employee_lists'
    )
    present_employee_ids = fields.Many2many(
        'hr.employee', string='Kelgan xodimlar',
        compute='_compute_employee_lists'
    )

    @api.depends('report_date')
    def _compute_name(self):
        for record in self:
            record.name = f"HR Hisoboti - {record.report_date}"

    @api.depends('report_date')
    def _compute_live_statistics(self):
        """Compute statistics directly from attendance and leave data"""
        for record in self:
            report_date = record.report_date or date.today()
            
            # Get all active employees
            all_employees = self.env['hr.employee'].search([('active', '=', True)])
            record.total_employees = len(all_employees)
            
            # Get employees on leave for this date
            leaves = self.env['hr.leave'].search([
                ('state', '=', 'validate'),
                ('date_from', '<=', report_date),
                ('date_to', '>=', report_date),
            ])
            on_leave_employee_ids = leaves.mapped('employee_id').ids
            record.on_leave_count = len(on_leave_employee_ids)
            
            # Get employees who checked in on this date
            date_start = datetime.combine(report_date, datetime.min.time())
            date_end = datetime.combine(report_date, datetime.max.time())
            
            attendances = self.env['hr.attendance'].search([
                ('check_in', '>=', date_start),
                ('check_in', '<=', date_end),
            ])
            present_employee_ids = attendances.mapped('employee_id').ids
            record.present_count = len(set(present_employee_ids))
            
            # Absent = Total - Present (includes those on leave)
            record.absent_count = record.total_employees - record.present_count

    @api.depends('report_date')
    def _compute_employee_lists(self):
        """Compute employee lists directly from attendance and leave data"""
        for record in self:
            report_date = record.report_date or date.today()
            
            # Get all active employees
            all_employees = self.env['hr.employee'].search([('active', '=', True)])
            all_employee_ids = set(all_employees.ids)
            
            # Get employees on leave for this date
            leaves = self.env['hr.leave'].search([
                ('state', '=', 'validate'),
                ('date_from', '<=', report_date),
                ('date_to', '>=', report_date),
            ])
            on_leave_employee_ids = set(leaves.mapped('employee_id').ids)
            
            # Get employees who checked in on this date
            date_start = datetime.combine(report_date, datetime.min.time())
            date_end = datetime.combine(report_date, datetime.max.time())
            
            attendances = self.env['hr.attendance'].search([
                ('check_in', '>=', date_start),
                ('check_in', '<=', date_end),
            ])
            present_employee_ids = set(attendances.mapped('employee_id').ids)
            
            # Absent = All - Present (includes those on leave)
            absent_employee_ids = all_employee_ids - present_employee_ids
            
            # Set computed fields
            record.present_employee_ids = [(6, 0, list(present_employee_ids))]
            record.leave_ids = [(6, 0, leaves.ids)]
            record.absent_employee_ids = [(6, 0, list(absent_employee_ids))]

    @api.onchange('report_date')
    def _onchange_report_date(self):
        """Auto-refresh lines when date is changed"""
        if self.report_date:
            # Clear existing lines first
            self.line_ids = [(5, 0, 0)]
            
            report_date = self.report_date
            
            all_employees = self.env['hr.employee'].search([('active', '=', True)])
            
            leaves = self.env['hr.leave'].search([
                ('state', '=', 'validate'),
                ('date_from', '<=', report_date),
                ('date_to', '>=', report_date),
            ])
            on_leave_employee_ids = leaves.mapped('employee_id').ids
            
            date_start = datetime.combine(report_date, datetime.min.time())
            date_end = datetime.combine(report_date, datetime.max.time())
            
            attendances = self.env['hr.attendance'].search([
                ('check_in', '>=', date_start),
                ('check_in', '<=', date_end),
            ])
            present_employee_ids = attendances.mapped('employee_id').ids
            
            lines = []
            for emp in all_employees:
                if emp.id in on_leave_employee_ids:
                    status = 'leave'
                elif emp.id in present_employee_ids:
                    status = 'present'
                else:
                    status = 'absent'
                
                lines.append((0, 0, {
                    'employee_id': emp.id,
                    'status': status,
                }))
            
            self.line_ids = lines

    def _generate_report_lines_onchange(self):
        """Generate report lines for onchange (works with virtual records)"""
        pass  # Moved logic to _onchange_report_date

    def _generate_report_lines(self):
        """Generate report lines for saved records"""
        self.ensure_one()
        report_date = self.report_date or date.today()
        
        self.line_ids.unlink()
        
        all_employees = self.env['hr.employee'].search([('active', '=', True)])
        
        leaves = self.env['hr.leave'].search([
            ('state', '=', 'validate'),
            ('date_from', '<=', report_date),
            ('date_to', '>=', report_date),
        ])
        on_leave_employee_ids = leaves.mapped('employee_id').ids
        
        date_start = datetime.combine(report_date, datetime.min.time())
        date_end = datetime.combine(report_date, datetime.max.time())
        
        attendances = self.env['hr.attendance'].search([
            ('check_in', '>=', date_start),
            ('check_in', '<=', date_end),
        ])
        present_employee_ids = attendances.mapped('employee_id').ids
        
        lines_vals = []
        for emp in all_employees:
            if emp.id in on_leave_employee_ids:
                status = 'leave'
            elif emp.id in present_employee_ids:
                status = 'present'
            else:
                status = 'absent'
            
            lines_vals.append({
                'daily_report_id': self.id,
                'employee_id': emp.id,
                'status': status,
            })
        
        self.env['hr.daily.report.line'].create(lines_vals)

    @api.model
    def get_today_dashboard(self):
        """Get or create today's dashboard record"""
        today = fields.Date.today()
        dashboard = self.search([('report_date', '=', today)], limit=1)
        if not dashboard:
            dashboard = self.create({'report_date': today})
            dashboard._generate_report_lines()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Bugungi Hisobot',
            'res_model': 'hr.daily.report',
            'res_id': dashboard.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def _get_employee_ids_by_status(self, status):
        """Get employee IDs by status for the selected date"""
        report_date = self.report_date or date.today()
        
        all_employees = self.env['hr.employee'].search([('active', '=', True)])
        
        # Get employees on leave
        leaves = self.env['hr.leave'].search([
            ('state', '=', 'validate'),
            ('date_from', '<=', report_date),
            ('date_to', '>=', report_date),
        ])
        on_leave_employee_ids = set(leaves.mapped('employee_id').ids)
        
        # Get employees who checked in
        date_start = datetime.combine(report_date, datetime.min.time())
        date_end = datetime.combine(report_date, datetime.max.time())
        
        attendances = self.env['hr.attendance'].search([
            ('check_in', '>=', date_start),
            ('check_in', '<=', date_end),
        ])
        present_employee_ids = set(attendances.mapped('employee_id').ids)
        
        if status == 'all':
            return all_employees.ids
        elif status == 'present':
            return list(present_employee_ids)
        elif status == 'leave':
            return list(on_leave_employee_ids)
        elif status == 'absent':
            # Absent = All - Present (includes those on leave)
            absent_ids = set(all_employees.ids) - present_employee_ids
            return list(absent_ids)
        return []

    def action_view_all(self):
        """Open all employees list"""
        self.ensure_one()
        employee_ids = self._get_employee_ids_by_status('all')
        return {
            'type': 'ir.actions.act_window',
            'name': 'Barcha xodimlar',
            'res_model': 'hr.employee',
            'view_mode': 'list,form',
            'domain': [('id', 'in', employee_ids)],
            'context': {'create': False},
            'target': 'current',
        }

    def action_view_absent(self):
        """Open absent employees list"""
        self.ensure_one()
        employee_ids = self._get_employee_ids_by_status('absent')
        return {
            'type': 'ir.actions.act_window',
            'name': 'Kelmagan xodimlar',
            'res_model': 'hr.employee',
            'view_mode': 'list,form',
            'domain': [('id', 'in', employee_ids)],
            'context': {'create': False},
            'target': 'current',
        }

    def action_view_on_leave(self):
        """Open on leave records with details"""
        self.ensure_one()
        report_date = self.report_date
        
        # Get leave records for this date
        leaves = self.env['hr.leave'].search([
            ('state', '=', 'validate'),
            ('date_from', '<=', report_date),
            ('date_to', '>=', report_date),
        ])
        
        return {
            'type': 'ir.actions.act_window',
            'name': "Ta'tildagi xodimlar",
            'res_model': 'hr.leave',
            'view_mode': 'list,form',
            'domain': [('id', 'in', leaves.ids)],
            'context': {'create': False},
            'target': 'current',
        }

    def action_view_present(self):
        """Open present employees list"""
        self.ensure_one()
        employee_ids = self._get_employee_ids_by_status('present')
        return {
            'type': 'ir.actions.act_window',
            'name': 'Kelgan xodimlar',
            'res_model': 'hr.employee',
            'view_mode': 'list,form',
            'domain': [('id', 'in', employee_ids)],
            'context': {'create': False},
            'target': 'current',
        }


class HrReportAnalysis(models.Model):
    _name = 'hr.report.analysis'
    _description = 'HR Report Analysis'
    _order = 'date desc'

    name = fields.Char(string='Report Name', required=True)
    date = fields.Date(string='Report Date', default=fields.Date.today)
    date_from = fields.Date(string='Date From', required=True)
    date_to = fields.Date(string='Date To', required=True)
    
    employee_ids = fields.Many2many('hr.employee', string='Employees')
    department_id = fields.Many2one('hr.department', string='Department')
    
    report_type = fields.Selection([
        ('attendance', 'Attendance Report'),
        ('timeoff', 'Time Off Report'),
        ('combined', 'Combined Report'),
    ], string='Report Type', default='combined', required=True)
    
    state = fields.Selection([
        ('draft', 'Draft'),
        ('generated', 'Generated'),
    ], string='Status', default='draft')
    
    total_employees = fields.Integer(string='Total Employees', compute='_compute_statistics', store=True)
    total_worked_hours = fields.Float(string='Total Worked Hours', compute='_compute_statistics', store=True)
    total_leave_days = fields.Float(string='Total Leave Days', compute='_compute_statistics', store=True)
    
    notes = fields.Text(string='Notes')

    @api.depends('date_from', 'date_to', 'employee_ids', 'department_id', 'state')
    def _compute_statistics(self):
        for record in self:
            if record.state != 'generated':
                record.total_employees = 0
                record.total_worked_hours = 0.0
                record.total_leave_days = 0.0
                continue
                
            domain = []
            if record.department_id:
                domain.append(('department_id', '=', record.department_id.id))
            
            employees = record.employee_ids or self.env['hr.employee'].search(domain)
            record.total_employees = len(employees)
            
            attendances = self.env['hr.attendance'].search([
                ('employee_id', 'in', employees.ids),
                ('check_in', '>=', record.date_from),
                ('check_in', '<=', record.date_to),
            ])
            record.total_worked_hours = sum(attendances.mapped('worked_hours'))
            
            leaves = self.env['hr.leave'].search([
                ('employee_id', 'in', employees.ids),
                ('date_from', '>=', record.date_from),
                ('date_to', '<=', record.date_to),
                ('state', '=', 'validate'),
            ])
            record.total_leave_days = sum(leaves.mapped('number_of_days'))

    def action_generate_report(self):
        self.ensure_one()
        self.state = 'generated'
        return True

    def action_reset_to_draft(self):
        self.ensure_one()
        self.state = 'draft'
        return True

    def action_print_report(self):
        self.ensure_one()
        return self.env.ref('report_for_hr.action_report_hr_analysis').report_action(self)
