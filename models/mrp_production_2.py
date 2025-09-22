from odoo import api, fields, models, _


class MrpProduction(models.Model):
    _inherit = 'mrp.production'

    sales_order = fields.Many2one(
        comodel_name="sale.order",
        string="Pedido de venda",
        compute="_compute_sale_order_mrp",
        store=True
    )

    @api.depends("origin")
    def _compute_sale_order_mrp(self):
        for record in self:
            if record.origin:
                mrp = self.env['mrp_cut_plan.mrp_cut_plan'].search([('name', '=', record.origin)], limit=1)
                if mrp:
                    record.sales_order = mrp.sale_order_id.id
                else:
                    record.sales_order = False
            else:
                record.sales_order = False

