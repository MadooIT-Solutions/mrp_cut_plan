from odoo import fields, models, api

class BlueMrpBom(models.Model):
    _inherit = "mrp.bom"

    blue_template = fields.Boolean(
        string="Template?"
    )


            