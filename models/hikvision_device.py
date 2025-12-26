# -*- coding: utf-8 -*-
"""
Hikvision Face ID Device Model

Bu model barcha Hikvision mixin'larini birlashtiradi va
asosiy fields'larni o'z ichiga oladi.
"""

import logging
from urllib.parse import urlparse
import json

from odoo import models, fields

_logger = logging.getLogger(__name__)


class HikvisionDevice(models.Model):
    """Hikvision Face ID qurilmasini boshqarish modeli"""
    
    _name = 'hikvision.device'
    _description = 'Hikvision Face ID Device'
    _inherit = [
        'hikvision.api.mixin',
        'hikvision.sync.mixin',
        'hikvision.attendance.mixin',
        'hikvision.cron.mixin',
        'hikvision.leave.sync.mixin',
    ]

    # =====================================================
    # FIELDS
    # =====================================================
    name = fields.Char(string='Device Name', required=True)
    ip_address = fields.Char(string='IP Address', required=True)
    port = fields.Integer(string='Port', default=80, required=True)
    username = fields.Char(string='Username', required=True)
    password = fields.Char(string='Password', required=True)
    device_id = fields.Char(string='Device ID')
    state = fields.Selection([
        ('draft', 'Draft'),
        ('confirmed', 'Confirmed'),
        ('error', 'Error')
    ], string='Status', default='draft')
    last_fetch_time = fields.Datetime(string='Last Fetch Time')

    # =====================================================
    # HELPER METHODS
    # =====================================================
    
    def _notify(self, title, message, notif_type='success', sticky=False):
        """Foydalanuvchiga xabar ko'rsatish."""
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': title,
                'message': message,
                'type': notif_type,
                'sticky': sticky,
            }
        }

    # =====================================================
    # DEVICE ACTIONS
    # =====================================================
    
    def action_test_connection(self):
        """Qurilma bilan ulanishni test qilish"""
        self.ensure_one()
        try:
            self._make_request('GET', 'System/deviceInfo')
            self.state = 'confirmed'
            return self._notify('Muvaffaqiyatli', 'Qurilmaga ulanish muvaffaqiyatli!')
        except Exception as e:
            self.state = 'error'
            return self._notify('Ulanish xatosi', str(e), 'danger', sticky=True)

    # =====================================================
    # WEBHOOK CONFIGURATION
    # =====================================================
    
    def action_configure_webhook(self):
        """Hikvision qurilmasida HTTP Host konfiguratsiya qilish."""
        self.ensure_one()
        
        base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url')
        webhook_url = f"{base_url}/hikvision/webhook"
        
        parsed = urlparse(base_url)
        host_ip = parsed.hostname
        host_port = parsed.port or (443 if parsed.scheme == 'https' else 80)
        
        http_host_config = {
            "HttpHostNotification": {
                "id": "1",
                "url": "/hikvision/webhook",
                "protocolType": "HTTP",
                "parameterFormatType": "JSON",
                "addressingFormatType": "ipaddress",
                "ipAddress": host_ip,
                "portNo": host_port,
                "httpAuthenticationMethod": "none"
            }
        }
        
        try:
            self._make_request('PUT', 'Event/notification/httpHosts/1?format=json', 
                             data=json.dumps(http_host_config))
            return self._notify('Webhook sozlandi', f'Qurilma hodisalarni {webhook_url} ga yuboradi.')
        except Exception as e:
            return self._notify('Xato', f'Webhook sozlashda xato: {str(e)}', 'danger', sticky=True)
