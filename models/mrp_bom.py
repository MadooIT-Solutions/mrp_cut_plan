from odoo import fields, models, api

class BlueMrpBom(models.Model):
    _inherit = "mrp.bom"

    blue_template = fields.Boolean(
        string="Template?"
    )

    @api.onchange('blue_template')
    def _onchange_blue_template(self):
        for record in self:
            self.blue_template = record.blue_template
            record.active = False if record.blue_template else True
            