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
            selectedJob: null,
            departments: [],
            jobs: [],
            // Data
            todayStats: {},
            recentCheckins: [],
            lastUpdate: new Date().toLocaleTimeString(),
            // View mode
            activeTab: 'overview',
            employeeList: [],
            employeeFilter: 'all',
            // Monthly summary
            monthlySummary: { employees: [], month: new Date().getMonth() + 1, year: new Date().getFullYear(), month_name: '' },
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
                [this.state.selectedDepartment, this.state.selectedJob]
            );

            this.state.todayStats = data.today_stats;
            this.state.recentCheckins = data.recent_checkins;
            this.state.monthlySummary = data.monthly_summary;
            this.state.departments = data.departments;
            this.state.jobs = data.jobs;
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
        this.state.refreshing = false;
    }

    async onDepartmentChange(ev) {
        const value = ev.target.value;
        this.state.selectedDepartment = value ? parseInt(value) : null;
        await this.refreshData();
    }

    async onJobChange(ev) {
        const value = ev.target.value;
        this.state.selectedJob = value ? parseInt(value) : null;
        await this.refreshData();
    }

    async clearFilters() {
        this.state.selectedDepartment = null;
        this.state.selectedJob = null;
        await this.refreshData();
    }

    setActiveTab(tab) {
        this.state.activeTab = tab;
        if (tab === 'employees') {
            this.loadEmployeeList();
        } else if (tab === 'monthly') {
            this.loadMonthlySummary();
        }
    }

    async loadEmployeeList() {
        try {
            const data = await this.orm.call(
                "attendance.dashboard",
                "get_employee_list",
                [this.state.employeeFilter, this.state.selectedDepartment, this.state.selectedJob]
            );
            this.state.employeeList = data;
        } catch (error) {
            console.error("Xodimlar ro'yxatini yuklashda xato:", error);
        }
    }

    async onEmployeeFilterChange(filter) {
        this.state.employeeFilter = filter;
        await this.loadEmployeeList();
    }

    async loadMonthlySummary() {
        try {
            const data = await this.orm.call(
                "attendance.dashboard",
                "get_monthly_work_summary",
                [this.state.selectedDepartment, this.state.selectedJob, this.state.selectedMonth, this.state.selectedYear]
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

    getProgressColor(rate) {
        if (rate >= 90) return '#10b981';
        if (rate >= 70) return '#f59e0b';
        return '#ef4444';
    }

    exportToExcel() {
        let url = '/attendance_dashboard/export_monthly_excel?';
        const params = [];

        if (this.state.selectedDepartment) {
            params.push(`department_id=${this.state.selectedDepartment}`);
        }
        if (this.state.selectedJob) {
            params.push(`job_id=${this.state.selectedJob}`);
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

    getStatusClass(emp) {
        if (!emp.check_in) return 'absent';
        if (emp.is_late) return 'late';
        return 'on-time';
    }

    getStatusText(emp) {
        if (!emp.check_in) return '❌ Kelmagan';
        if (emp.is_working) return '🟢 Ishda';
        if (emp.is_late) return '⚠️ Kechikdi';
        return '✅ O\'z vaqtida';
    }
}

registry.category("actions").add("attendance_dashboard", AttendanceDashboard);
