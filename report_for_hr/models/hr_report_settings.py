# -*- coding: utf-8 -*-

from odoo import models, fields, api


class HrReportSettings(models.Model):
    _name = 'hr.report.settings'
    _description = 'HR Hisobot Sozlamalari'
    _rec_name = 'id'

    # Grace period settings for HR Reports
    late_grace_minutes = fields.Integer(
        string="Kech kelishga ruxsat (minut)",
        default=0,
        help="Agar xodim shu minut ichida kech kelsa, kechikish hisobga olinmaydi"
    )
    early_leave_grace_minutes = fields.Integer(
        string="Erta ketishga ruxsat (minut)",
        default=0,
        help="Agar xodim shu minut ichida erta ketsa, erta ketish hisobga olinmaydi"
    )
    company_id = fields.Many2one(
        'res.company',
        string='Kompaniya',
        default=lambda self: self.env.company,
        required=True
    )

    @api.model
    def get_settings(self):
        """Get or create settings for current company"""
        settings = self.search([('company_id', '=', self.env.company.id)], limit=1)
        if not settings:
            settings = self.create({
                'company_id': self.env.company.id,
                'late_grace_minutes': 0,
                'early_leave_grace_minutes': 0,
            })
        return settings

    @api.model
    def get_grace_minutes(self):
        """Return grace period settings as dict"""
        settings = self.get_settings()
        return {
            'late': settings.late_grace_minutes,
            'early': settings.early_leave_grace_minutes,
        }
