from odoo import fields, models

class ProductionSaleOrder(models.Model):
    _name = "mrp_cut_plan.production_sale_order"

    sale_order_id = fields.Many2one(
        comodel_name='sale.order',
        string='Sale Order'
    )
    production_order_id = fields.Many2one(
        comodel_name='mrp.production',
        string='Production Order'
    )
    produced_quantity = fields.Float(
        string='Produced Quantity'
    )
