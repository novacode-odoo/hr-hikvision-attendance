{
    'name': 'Hikvision Face ID Attendance',
    'version': '1.0',
    'category': 'Human Resources',
    'summary': 'Integration with Hikvision Face ID devices for attendance',
    'description': """
        This module integrates Hikvision Face ID devices with Odoo HR Attendance.
        It allows managing devices and fetching attendance logs.
    """,
    'author': 'NovaCode',
    'depends': ['base', 'hr', 'hr_attendance'],
    'data': [
        'security/ir.model.access.csv',
        'data/ir_cron_data.xml',
        'views/hikvision_device_views.xml',
        'views/hikvision_log_views.xml',
        'views/hikvision_menus.xml',
    ],
    'installable': True,
    'application': True,
    'license': 'LGPL-3',
}
