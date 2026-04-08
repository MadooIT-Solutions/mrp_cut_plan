from odoo import fields, models, api

class BlueProductTemplate(models.Model):
    _inherit = "product.template"

    blue_area_calc = fields.Selection(
        selection=[
            ("n", "None"),
            ("llh", "LLH Calculation"),
            ("m", "Mold Calculation"),
            ("massa", "Cement Calculation"),
        ],
        string="Calculation Type",
        default='n',
    )
    cement = fields.Float(
        string="Cement",
    )
    boolean_coefficient_or_screen = fields.Selection(
        selection=[
            ("n", "None"),
            ("tl", "Produto é Tela"),
            ("coe", "Multiplica Pelo Coeficiente")
        ],
        string="Coeficiente ou Tela",
        default="n"
    )

    # Adicionar campo para identificar produtos MTO
    blue_mto_route = fields.Boolean(
        string="Use MTO Route",
        help="If checked, uses Make To Order strategy without creating production orders"
    )

    @api.onchange('blue_area_calc')
    def _onchange_blue_area_calc(self):
        if self.blue_area_calc == 'massa':
            self.boolean_coefficient_or_screen = 'n'