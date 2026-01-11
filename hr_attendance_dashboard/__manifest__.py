{
    "name": "Davomat Dashboard",
    "version": "1.0",
    "category": "Human Resources",
    "summary": "Davomatni real vaqtda chiroyli grafiklar bilan ko'rsatish",
    "description": """
        Davomat Dashboard
        =================
        
        Ushbu modul quyidagi imkoniyatlarni beradi:
        
        * Kunlik davomat statistikasi (Donut Chart)
        * Haftalik trend (Line Chart)
        * Bo'limlar bo'yicha davomat (Bar Chart)
        * Real-time xodimlar soni
        * Kech qolish statistikasi
        
        Barcha grafiklar chiroyli va interaktiv ko'rinishda.
    """,
    "author": "Hikmatillo",
    "depends": ["hr_attendance", "hr"],
    "external_dependencies": {
        "python": ["xlsxwriter"],
    },
    "assets": {
        "web.assets_backend": [
            "hr_attendance_dashboard/static/src/css/attendance_dashboard.css",
            "hr_attendance_dashboard/static/src/js/attendance_dashboard.js",
            "hr_attendance_dashboard/static/src/xml/attendance_dashboard.xml",
        ],
    },
    "data": [
        "security/ir.model.access.csv",
        "views/dashboard_views.xml",
        "views/dashboard_menu.xml",
    ],
    "images": ["static/description/icon.png"],
    "installable": True,
    "application": True,
    "auto_install": False,
    "license": "LGPL-3",
}
