from odoo import models, fields, api, _
from odoo.exceptions import UserError


class TemplatePriceConfig(models.Model):
    _name = 'mrp_cut_plan.template_price_config'
    _description = 'Template Price Config'
    _inherit = 'mail.thread'
    _rec_name = 'product_id'

    blue_wall = fields.Float(
        string="Standard Wall"
    )

    blue_wall_uom = fields.Many2one(
        comodel_name="uom.uom",
        string="Udm"
    )

    blue_eps_product_id = fields.Many2one(
        comodel_name="product.product",
        string="EPS Product"
    )

    blue_eps_cost = fields.Float(
        related="blue_eps_product_id.standard_price",
        string="EPS Cost"
    )

    blue_tela_product_id = fields.Many2one(
        comodel_name="product.product",
        string="Canvas/Mortar Product"
    )

    blue_tela_cost = fields.Float(
        related="blue_tela_product_id.standard_price",
        string="Screen Cost"
    )

    blue_tela_multi = fields.Float(
        string="Labor Cost",
        default=1
    )

    blue_tela_multi2 = fields.Float(
        string="Cost of Mortar m2",
        default=1
    )

    blue_curve_cost = fields.Float(
        string="Additional Cost Curve"
    )

    blue_margin_percent = fields.Float(
        string="Marge Percentage"
    )

    product_id = fields.Many2one(
        comodel_name="product.product",
        string="Produto"
    )

    _sql_constraints = [
        ('product_id', 'unique (product_id)', 'Já existe um template configurado para esse produto')
    ]

    mortar_coefficient = fields.Float(
        string="Coeficiente Argamassa"
    )