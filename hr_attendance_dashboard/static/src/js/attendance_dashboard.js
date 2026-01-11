/** @odoo-module **/

import { Component, useState, onWillStart, onMounted } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

export class AttendanceDashboard extends Component {
    static template = "hr_attendance_dashboard.Dashboard";
    static props = { "*": true };

    setup() {
        this.orm = useService("orm");
        this.state = useState({
            loading: true,
            refreshing: false,
            // Filters
            selectedDepartment: null,
            departments: [],
            // Data
            todayStats: {},
            absentEmployees: [],
            onLeaveEmployees: [],
            showLeaveList: false,
            lastUpdate: new Date().toLocaleTimeString(),
            // View mode
            activeTab: 'overview',
            // Monthly summary
            monthlySummary: { employees: [], days_in_month: 31, month: new Date().getMonth() + 1, year: new Date().getFullYear(), month_name: '' },
            selectedMonth: new Date().getMonth() + 1,
            selectedYear: new Date().getFullYear(),
        });

        onWillStart(async () => {
            await this.loadDashboardData();
        });

        onMounted(() => {
            this.refreshInterval = setInterval(() => this.refreshData(), 60000);
        });
    }

    async loadDashboardData() {
        try {
            const data = await this.orm.call(
                "attendance.dashboard",
                "get_all_dashboard_data",
                [this.state.selectedDepartment]
            );

            this.state.todayStats = data.today_stats;
            this.state.absentEmployees = data.absent_employees;
            this.state.onLeaveEmployees = data.on_leave_employees || [];
            this.state.departments = data.departments;
            this.state.lastUpdate = new Date().toLocaleTimeString();
            this.state.loading = false;
        } catch (error) {
            console.error("Dashboard ma'lumotlarini yuklashda xato:", error);
            this.state.loading = false;
        }
    }

    async refreshData() {
        this.state.refreshing = true;
        await this.loadDashboardData();
        if (this.state.activeTab === 'monthly') {
            await this.loadMonthlySummary();
        }
        this.state.refreshing = false;
    }

    async onDepartmentChange(ev) {
        const value = ev.target.value;
        this.state.selectedDepartment = value ? parseInt(value) : null;
        await this.refreshData();
    }

    async clearFilters() {
        this.state.selectedDepartment = null;
        await this.refreshData();
    }

    setActiveTab(tab) {
        this.state.activeTab = tab;
        this.state.showLeaveList = false;
        if (tab === 'monthly') {
            this.loadMonthlySummary();
        }
    }

    toggleLeaveList() {
        this.state.showLeaveList = !this.state.showLeaveList;
    }

    async loadMonthlySummary() {
        try {
            const data = await this.orm.call(
                "attendance.dashboard",
                "get_monthly_work_summary",
                [this.state.selectedDepartment, this.state.selectedMonth, this.state.selectedYear]
            );
            this.state.monthlySummary = data;
        } catch (error) {
            console.error("Oylik ma'lumotlarni yuklashda xato:", error);
        }
    }

    async onMonthChange(ev) {
        this.state.selectedMonth = parseInt(ev.target.value);
        await this.loadMonthlySummary();
    }

    async onYearChange(ev) {
        this.state.selectedYear = parseInt(ev.target.value);
        await this.loadMonthlySummary();
    }

    getMonthOptions() {
        return [
            { value: 1, label: 'Yanvar' },
            { value: 2, label: 'Fevral' },
            { value: 3, label: 'Mart' },
            { value: 4, label: 'Aprel' },
            { value: 5, label: 'May' },
            { value: 6, label: 'Iyun' },
            { value: 7, label: 'Iyul' },
            { value: 8, label: 'Avgust' },
            { value: 9, label: 'Sentabr' },
            { value: 10, label: 'Oktabr' },
            { value: 11, label: 'Noyabr' },
            { value: 12, label: 'Dekabr' },
        ];
    }

    getYearOptions() {
        const currentYear = new Date().getFullYear();
        return [currentYear - 1, currentYear, currentYear + 1];
    }

    getDaysArray() {
        const days = [];
        for (let i = 1; i <= this.state.monthlySummary.days_in_month; i++) {
            days.push(i);
        }
        return days;
    }

    exportToExcel() {
        let url = '/attendance_dashboard/export_monthly_excel?';
        const params = [];

        if (this.state.selectedDepartment) {
            params.push(`department_id=${this.state.selectedDepartment}`);
        }
        if (this.state.selectedMonth) {
            params.push(`month=${this.state.selectedMonth}`);
        }
        if (this.state.selectedYear) {
            params.push(`year=${this.state.selectedYear}`);
        }

        url += params.join('&');
        window.open(url, '_blank');
    }

    getInitials(name) {
        if (!name) return '?';
        const parts = name.split(' ');
        if (parts.length >= 2) {
            return (parts[0][0] + parts[1][0]).toUpperCase();
        }
        return name.substring(0, 2).toUpperCase();
    }
}

registry.category("actions").add("attendance_dashboard", AttendanceDashboard);
