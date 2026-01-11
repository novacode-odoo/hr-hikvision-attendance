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
    def export_monthly_excel(self, department_id=None, month=None, year=None, **kwargs):
        """Oylik ish hisobotini Excel faylga export qilish - har kun uchun ustun"""
        
        if xlsxwriter is None:
            return request.make_response(
                json.dumps({'error': 'xlsxwriter kutubxonasi o\'rnatilmagan'}),
                headers=[('Content-Type', 'application/json')]
            )
        
        # Parametrlarni olish
        department_id = int(department_id) if department_id else None
        month = int(month) if month else None
        year = int(year) if year else None
        
        # Ma'lumotlarni olish
        dashboard = request.env['attendance.dashboard']
        data = dashboard.get_monthly_work_summary(department_id, month, year)
        
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
            'font_size': 10,
        })
        
        cell_format = workbook.add_format({
            'align': 'left',
            'valign': 'vcenter',
            'border': 1,
            'font_size': 9,
        })
        
        center_format = workbook.add_format({
            'align': 'center',
            'valign': 'vcenter',
            'border': 1,
            'font_size': 9,
        })
        
        # Kun turi formatlari
        work_format = workbook.add_format({
            'align': 'center',
            'valign': 'vcenter',
            'border': 1,
            'font_size': 9,
            'bg_color': '#d1fae5',
            'font_color': '#059669',
            'bold': True,
        })
        
        rest_format = workbook.add_format({
            'align': 'center',
            'valign': 'vcenter',
            'border': 1,
            'font_size': 9,
            'bg_color': '#f1f5f9',
            'font_color': '#64748b',
        })
        
        leave_format = workbook.add_format({
            'align': 'center',
            'valign': 'vcenter',
            'border': 1,
            'font_size': 9,
            'bg_color': '#ede9fe',
            'font_color': '#7c3aed',
            'bold': True,
        })
        
        holiday_format = workbook.add_format({
            'align': 'center',
            'valign': 'vcenter',
            'border': 1,
            'font_size': 9,
            'bg_color': '#fef3c7',
            'font_color': '#d97706',
            'bold': True,
        })
        
        absent_format = workbook.add_format({
            'align': 'center',
            'valign': 'vcenter',
            'border': 1,
            'font_size': 9,
            'bg_color': '#fee2e2',
            'font_color': '#dc2626',
        })
        
        total_format = workbook.add_format({
            'align': 'center',
            'valign': 'vcenter',
            'border': 1,
            'font_size': 9,
            'bg_color': '#eef2ff',
            'font_color': '#6366f1',
            'bold': True,
        })
        
        # Sarlavha
        title_format = workbook.add_format({
            'bold': True,
            'font_size': 12,
            'align': 'center',
        })
        
        days_in_month = data['days_in_month']
        last_col = 2 + days_in_month  # Xodim, Bo'lim + kunlar + Jami
        worksheet.merge_range(0, 0, 0, last_col, f"Oylik Ish Hisoboti - {data['month_name']} {data['year']}", title_format)
        
        # Legend
        legend_format = workbook.add_format({'font_size': 9})
        worksheet.write(1, 0, "Izoh: Soat=Ishladi, D=Dam, T=Ta'til, U=Bayram, -=Kelmadi", legend_format)
        
        # Ustun kengliklari
        worksheet.set_column('A:A', 25)  # Xodim
        worksheet.set_column('B:B', 15)  # Bo'lim
        for col in range(2, 2 + days_in_month):
            worksheet.set_column(col, col, 5)  # Kunlar
        worksheet.set_column(2 + days_in_month, 2 + days_in_month, 8)  # Jami
        
        # Sarlavhalar
        row = 3
        worksheet.write(row, 0, 'Xodim', header_format)
        worksheet.write(row, 1, "Bo'lim", header_format)
        for day in range(1, days_in_month + 1):
            worksheet.write(row, 1 + day, str(day), header_format)
        worksheet.write(row, 2 + days_in_month, 'Jami', header_format)
        
        # Ma'lumotlar
        row = 4
        for emp in data['employees']:
            worksheet.write(row, 0, emp['name'], cell_format)
            worksheet.write(row, 1, emp['department'], cell_format)
            
            # Har bir kun
            for day_data in emp['days']:
                col = 1 + day_data['day']
                value = day_data['value']
                day_type = day_data['type']
                
                # Formatni tanlash
                if day_type == 'work':
                    fmt = work_format
                elif day_type == 'rest':
                    fmt = rest_format
                elif day_type == 'leave':
                    fmt = leave_format
                elif day_type == 'holiday':
                    fmt = holiday_format
                elif day_type == 'absent':
                    fmt = absent_format
                else:
                    fmt = center_format
                
                worksheet.write(row, col, value, fmt)
            
            # Jami
            worksheet.write(row, 2 + days_in_month, emp['total_hours'], total_format)
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
