# -*- coding: utf-8 -*-

from odoo import api, models, _
from odoo.tools import float_round

class ReportBomStructure(models.AbstractModel):
    _inherit = 'report.mrp.report_bom_structure'

    def _get_bom_lines(self, bom, bom_quantity, product, line_id, level):
        components = []
        total = 0
        for line in bom.bom_line_ids:
            
            # Verificação segura para blue_multiplier (caso o campo não exista)
            if not hasattr(line, 'blue_multiplier') or not line.blue_multiplier:
                line_quantity = (bom_quantity / (bom.product_qty or 1.0)) * line.product_qty
            else:
                line_quantity = line.product_qty

            if line._skip_bom_line(product):
                continue
            company = bom.company_id or self.env.company
            # Método atualizado para cálculo de preço
            price = line.product_id.uom_id._compute_price(
                line.product_id.with_company(company).standard_price, 
                line.product_uom_id
            ) * line_quantity
            
            if line.child_bom_id:
                factor = line.product_uom_id._compute_quantity(line_quantity, line.child_bom_id.product_uom_id)
                sub_total = self._get_price(line.child_bom_id, factor, line.product_id)
                byproduct_cost_share = sum(line.child_bom_id.byproduct_ids.mapped('cost_share'))
                if byproduct_cost_share:
                    sub_total *= float_round(1 - byproduct_cost_share / 100, precision_rounding=0.0001)
            else:
                sub_total = price
                
            sub_total = company.currency_id.round(sub_total)
            components.append({
                'prod_id': line.product_id.id,
                'prod_name': line.product_id.display_name,
                'code': line.child_bom_id and line.child_bom_id.display_name or '',
                'prod_qty': line_quantity,
                'prod_uom': line.product_uom_id.name,
                'prod_cost': company.currency_id.round(price),
                'parent_id': bom.id,
                'line_id': line.id,
                'level': level or 0,
                'total': sub_total,
                'child_bom': line.child_bom_id.id,
                'phantom_bom': line.child_bom_id and line.child_bom_id.type == 'phantom' or False,
                'attachments': self.env['mrp.document'].search([
                    '|',
                    '&', ('res_model', '=', 'product.product'), ('res_id', '=', line.product_id.id),
                    '&', ('res_model', '=', 'product.template'), ('res_id', '=', line.product_id.product_tmpl_id.id)
                ]),
            })
            total += sub_total
        return components, total