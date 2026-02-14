from odoo import models, fields, api


class ProductCategory(models.Model):
    _inherit = 'product.category'

    complete_name_store = fields.Char(
        string='Caminho Completo',
        compute='_compute_complete_name_store',
        store=True,
        recursive=True,
    )

    @api.depends('name', 'parent_id.complete_name_store')
    def _compute_complete_name_store(self):
        for category in self:
            if category.parent_id:
                category.complete_name_store = f"{category.parent_id.complete_name_store} / {category.name}"
            else:
                category.complete_name_store = category.name