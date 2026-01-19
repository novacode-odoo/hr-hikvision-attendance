# -*- coding: utf-8 -*-

from odoo import models, fields, api
from datetime import datetime, timedelta


class HrReportWizard(models.TransientModel):
    _name = 'hr.report.wizard'
    _description = 'HR Report Wizard'

    date_from = fields.Date(
        string='Date From',
        required=True,
        default=lambda self: fields.Date.today().replace(day=1)
    )
    date_to = fields.Date(
        string='Date To',
        required=True,
        default=fields.Date.today
    )
    
    employee_ids = fields.Many2many(
        'hr.employee',
        string='Employees',
        help='Select employees for the report. Leave empty for all employees.'
    )
    department_id = fields.Many2one(
        'hr.department',
        string='Department',
        help='Filter by department'
    )
    
    report_type = fields.Selection([
        ('attendance', 'Attendance Report'),
        ('timeoff', 'Time Off Report'),
        ('combined', 'Combined Report'),
    ], string='Report Type', default='combined', required=True)

    def action_generate_report(self):
        """Generate report from wizard"""
        self.ensure_one()
        
        report = self.env['hr.report.analysis'].create({
            'name': f'HR Report {self.date_from} - {self.date_to}',
            'date_from': self.date_from,
            'date_to': self.date_to,
            'employee_ids': [(6, 0, self.employee_ids.ids)],
            'department_id': self.department_id.id,
            'report_type': self.report_type,
        })
        
        report.action_generate_report()
        
        return {
            'type': 'ir.actions.act_window',
            'name': 'Generated Report',
            'res_model': 'hr.report.analysis',
            'res_id': report.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def action_print_direct(self):
        """Print report directly without saving"""
        self.ensure_one()
        
        # Get employees based on filters
        domain = []
        if self.department_id:
            domain.append(('department_id', '=', self.department_id.id))
        
        if self.employee_ids:
            employees = self.employee_ids
        else:
            employees = self.env['hr.employee'].search(domain)
        
        data = {
            'date_from': self.date_from,
            'date_to': self.date_to,
            'employee_ids': employees.ids,
            'report_type': self.report_type,
        }
        
        return self.env.ref('report_for_hr.action_report_hr_wizard').report_action(self, data=data)
