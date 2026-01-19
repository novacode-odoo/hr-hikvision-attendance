/** @odoo-module **/

import { FormController } from "@web/views/form/form_controller";
import { patch } from "@web/core/utils/patch";

// Hide action menu (gear) and cloud icons for hr.daily.report model
patch(FormController.prototype, {
    setup() {
        super.setup();
        // Check if this is hr.daily.report model
        if (this.props.resModel === 'hr.daily.report') {
            // Add class to identify this form
            this.env.config.disableActionMenu = true;
        }
    },

    get actionMenuItems() {
        // Hide action menu for hr.daily.report
        if (this.props.resModel === 'hr.daily.report') {
            return {};
        }
        return super.actionMenuItems;
    }
});
