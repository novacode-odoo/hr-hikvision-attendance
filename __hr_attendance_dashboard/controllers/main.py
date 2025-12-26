# -*- coding: utf-8 -*-

from odoo import http
from odoo.http import request, content_disposition
import io
import json

try:
    import xlsxwriter
except ImportError:
    xlsxwriter = None


class AttendanceDashboardExport(http.Controller):

    @http.route('/attendance_dashboard/export_monthly_excel', type='http', auth='user', methods=['GET'])
    def export_monthly_excel(self, department_id=None, job_id=None, month=None, year=None, **kwargs):
        """Oylik ish hisobotini Excel faylga export qilish"""
        
        if xlsxwriter is None:
            return request.make_response(
                json.dumps({'error': 'xlsxwriter kutubxonasi o\'rnatilmagan'}),
                headers=[('Content-Type', 'application/json')]
            )
        
        # Parametrlarni olish
        department_id = int(department_id) if department_id else None
        job_id = int(job_id) if job_id else None
        month = int(month) if month else None
        year = int(year) if year else None
        
        # Ma'lumotlarni olish
        dashboard = request.env['attendance.dashboard']
        data = dashboard.get_monthly_work_summary(department_id, job_id, month, year)
        
        # Excel fayl yaratish
        output = io.BytesIO()
        workbook = xlsxwriter.Workbook(output, {'in_memory': True})
        worksheet = workbook.add_worksheet('Oylik Hisobot')
        
        # Stillar
        header_format = workbook.add_format({
            'bold': True,
            'align': 'center',
            'valign': 'vcenter',
            'bg_color': '#6366f1',
            'font_color': 'white',
            'border': 1,
            'font_size': 11,
        })
        
        cell_format = workbook.add_format({
            'align': 'left',
            'valign': 'vcenter',
            'border': 1,
            'font_size': 10,
        })
        
        center_format = workbook.add_format({
            'align': 'center',
            'valign': 'vcenter',
            'border': 1,
            'font_size': 10,
        })
        
        success_format = workbook.add_format({
            'align': 'center',
            'valign': 'vcenter',
            'border': 1,
            'font_size': 10,
            'bg_color': '#d1fae5',
            'font_color': '#059669',
        })
        
        warning_format = workbook.add_format({
            'align': 'center',
            'valign': 'vcenter',
            'border': 1,
            'font_size': 10,
            'bg_color': '#fef3c7',
            'font_color': '#d97706',
        })
        
        danger_format = workbook.add_format({
            'align': 'center',
            'valign': 'vcenter',
            'border': 1,
            'font_size': 10,
            'bg_color': '#fee2e2',
            'font_color': '#dc2626',
        })
        
        purple_format = workbook.add_format({
            'align': 'center',
            'valign': 'vcenter',
            'border': 1,
            'font_size': 10,
            'bg_color': '#ede9fe',
            'font_color': '#7c3aed',
        })
        
        # Sarlavha
        title_format = workbook.add_format({
            'bold': True,
            'font_size': 14,
            'align': 'center',
        })
        worksheet.merge_range('A1:K1', f"Oylik Ish Hisoboti - {data['month_name']} {data['year']}", title_format)
        
        # Ustun kengliklari
        worksheet.set_column('A:A', 5)   # #
        worksheet.set_column('B:B', 30)  # Xodim
        worksheet.set_column('C:C', 20)  # Bo'lim
        worksheet.set_column('D:D', 20)  # Lavozim
        worksheet.set_column('E:E', 12)  # Kerak kun
        worksheet.set_column('F:F', 12)  # Ishladi kun
        worksheet.set_column('G:G', 12)  # Kerak soat
        worksheet.set_column('H:H', 12)  # Ishladi soat
        worksheet.set_column('I:I', 12)  # Ta'til soat
        worksheet.set_column('J:J', 10)  # Foiz
        worksheet.set_column('K:K', 25)  # Dam kunlari
        
        # Sarlavhalar
        headers = ['#', 'Xodim', "Bo'lim", 'Lavozim', 'Kerak kun', 'Ishladi kun', 'Kerak soat', 'Ishladi soat', "Ta'til soat", 'Foiz %', 'Dam kunlari']
        for col, header in enumerate(headers):
            worksheet.write(2, col, header, header_format)
        
        # Ma'lumotlar
        row = 3
        for idx, emp in enumerate(data['employees'], 1):
            worksheet.write(row, 0, idx, center_format)
            worksheet.write(row, 1, emp['name'], cell_format)
            worksheet.write(row, 2, emp['department'], cell_format)
            worksheet.write(row, 3, emp['job'], cell_format)
            worksheet.write(row, 4, emp['expected_days'], center_format)
            worksheet.write(row, 5, emp['worked_days'], success_format)
            worksheet.write(row, 6, emp.get('expected_hours', 0), center_format)
            worksheet.write(row, 7, emp.get('worked_hours', 0), success_format)
            worksheet.write(row, 8, emp.get('leave_hours', 0), purple_format if emp.get('leave_hours', 0) > 0 else center_format)
            
            # Foiz uchun rang
            rate = emp['rate']
            if rate >= 90:
                rate_format = success_format
            elif rate >= 70:
                rate_format = warning_format
            else:
                rate_format = danger_format
            worksheet.write(row, 9, f"{rate}%", rate_format)
            
            # Dam kunlari
            rest_days_str = ', '.join(emp['rest_days']) if emp['rest_days'] else '-'
            worksheet.write(row, 10, rest_days_str, cell_format)
            
            row += 1
        
        workbook.close()
        
        # Response
        output.seek(0)
        filename = f"Oylik_Hisobot_{data['month_name']}_{data['year']}.xlsx"
        
        return request.make_response(
            output.read(),
            headers=[
                ('Content-Type', 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'),
                ('Content-Disposition', content_disposition(filename)),
            ]
        )

