# -*- coding: utf-8 -*-
{
    'name': 'HR Reports',
    'version': '19.0.1.0.0',
    'category': 'Human Resources',
    'summary': 'Advanced HR Reports for Employees, Attendance and Time Off',
    'description': """
HR Reports Module
=================
This module provides comprehensive reports for Human Resources management:

* Employee Reports
* Attendance Reports  
* Time Off / Leave Reports
* Combined HR Analytics
    """,
    'author': 'Custom Development',
    'website': '',
    'license': 'LGPL-3',
    'depends': [
        'hr',
        'hr_attendance',
        'hr_holidays',
    ],
    'data': [
        'security/ir.model.access.csv',
        'views/hr_report_settings_views.xml',
        'views/hr_report_views.xml',
        'views/hr_attendance_wizard_views.xml',
        'views/hr_monthly_report_views.xml',
        'views/menu_views.xml',
        'reports/hr_report_templates.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'report_for_hr/static/src/css/hr_report.css',
            'report_for_hr/static/src/js/hr_report_form.js',
        ],
    },
    'installable': True,
    'application': True,
    'auto_install': False,
}
