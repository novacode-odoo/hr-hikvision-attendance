from odoo import models, fields

class HikvisionLog(models.Model):
    _name = 'hikvision.log'
    _description = 'Hikvision Attendance Log'
    _order = 'timestamp desc'

    device_id = fields.Many2one('hikvision.device', string='Device', required=True)
    employee_id = fields.Many2one('hr.employee', string='Employee')
    timestamp = fields.Datetime(string='Timestamp', required=True)
    attendance_type = fields.Selection([
        ('check_in', 'Check In'),
        ('check_out', 'Check Out')
    ], string='Attendance Type')
    image = fields.Binary(string='Captured Image')
