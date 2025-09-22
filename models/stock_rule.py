from odoo import models

class StockRule(models.Model):
    _inherit = "stock.rule"

    def _run_manufacture(self, procurements):
        # Chama o comportamento padrão do MTO
        productions = super()._run_manufacture(procurements)

        if not productions:
            return productions

        for procurement in procurements:
            if isinstance(procurement, tuple):
                procurement = procurement[0]

            # Busca a MO criada para este procurement
            production = self.env['mrp.production'].search([
                ('origin', '=', procurement.origin),
                ('product_id', '=', procurement.product_id.id),
                ('state', 'in', ['draft', 'confirmed'])
            ], limit=1, order='id desc')

            if not production:
                continue

            product = production.product_id

            # Busca a BoM template (blue_template=True)
            bom_template = self.env['mrp.bom'].search([
                ('product_tmpl_id', '=', product.product_tmpl_id.id),
                ('blue_template', '=', True)
            ], order='id desc', limit=1)

            if bom_template:
                # Arquiva a BoM template após a criação da MO
                bom_template.write({'active': False})

        return productions
