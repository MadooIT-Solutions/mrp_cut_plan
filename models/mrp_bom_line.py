from odoo import fields, models

class BlueMrpBomLine(models.Model):
    _inherit = "mrp.bom.line"

    blue_multiplier = fields.Boolean(
        string="No Multiply"
    )
