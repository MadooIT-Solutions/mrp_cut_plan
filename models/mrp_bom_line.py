from odoo import fields, models

class BlueMrpBomLine(models.Model):
    _inherit = "mrp.bom.line"

    blue_multiplier = fields.Boolean(string="No Multiply", default=False, help="Se marcado, usa quantidade fixa da lista de materiais")
    mandatory = fields.Boolean(string="Mandatory", default=False, help="Componente obrigatório deve ter consumo informado")
    calc = fields.Boolean(string="Calculated", default=False, help="Componente com quantidade calculada a partir de medidas")