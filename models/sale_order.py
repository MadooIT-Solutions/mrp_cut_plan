from odoo import api, models, fields, _
from odoo.exceptions import UserError


class SaleOrder(models.Model):
    _inherit = "sale.order"

    count_po = fields.Integer(
        string="Documents Count",
        compute="_compute_count_po",
        tracking=True
    )

    @api.depends('count_po')
    def _compute_count_po(self):
        for record in self:
            qty = self.env['mrp_cut_plan.mrp_cut_plan'].search([('blue_origin', '=', self.name)])
            record.count_po = len(qty)

    def open_linked_po(self):
        domain = [('blue_origin', '=', self.name)]
        return {
            'name': _('Production Orders'),
            'domain': domain,
            'type': 'ir.actions.act_window',
            'res_model': 'mrp_cut_plan.mrp_cut_plan',
            'view_id': False,
            'view_mode': 'tree,form',
        }

    def _adjust_stock_picking_to_waiting(self):
        for rec in self.picking_ids:
            manufactured = rec.move_line_ids.filtered(lambda r: r.product_id.detailed_type == 'consu')
            if rec.state == 'assigned' and manufactured:
                rec.do_unreserve()

    def action_confirm(self):
        CutPlan = self.env['mrp_cut_plan.mrp_cut_plan']
        MrpProduction = self.env['mrp.production']

        cut_plan_map = {}  # product_id → cut_plan

        for record in self.order_line:
            if record.product_id.blue_area_calc in ['llh', 'm']:
                bom_ids = self.env['mrp.bom'].search([
                    ('product_tmpl_id', '=', record.product_id.product_tmpl_id.id)
                    # ('active', '=', False)
                ])

                pl = CutPlan.create({
                    'blue_origin': record.order_id.name,
                    'product_id': record.product_id.id,
                    'blue_qty': record.product_uom_qty,
                    'blue_bom_template_id': bom_ids[:1].id if bom_ids else False,
                    'blue_I': record.blue_I,
                    'blue_II': record.blue_II,
                    'blue_h': record.blue_h,
                    'blue_I_uom': record.blue_I_uom.id if record.blue_I_uom else False,
                    'blue_II_uom': record.blue_II_uom.id if record.blue_II_uom else False,
                    'blue_h_uom': record.blue_h_uom.id if record.blue_h_uom else False,
                    'blue_advance': record.blue_advance,
                    'blue_wall': record.blue_wall,
                    'blue_wall_uom': record.blue_wall_uom.id if record.blue_wall_uom else False,
                    'blue_advance_uom': record.blue_advance_uom.id if record.blue_advance_uom else False,
                    'binany_field': record.binany_field,
                    'partner_id': self.partner_id.id,
                    'sale_order_id': self.id
                })

                cut_plan_map[record.product_id.id] = pl  # guarda o vínculo

                try:
                    if bom_ids:
                        pl.write({'blue_bom_template_id': bom_ids[0].id})
                except Exception:
                    raise UserError(
                        f'Por gentileza, revise e ajuste a lista de materiais conforme necessário do produto: {record.product_id.name}'
                    )

                pl.message_post(body=f'Plano de corte criado a partir da cotação: {record.order_id.name}')

        # confirma pedido de venda → gera MO padrão do Odoo
        res = super(SaleOrder, self).action_confirm()
        self._adjust_stock_picking_to_waiting()

        # agora vincula as MOs criadas ao plano de corte
        for line in self.order_line:
            if line.product_id.id in cut_plan_map:
                mo = MrpProduction.search([
                    ('origin', '=', self.name),
                    ('product_id', '=', line.product_id.id),
                ], limit=1)
                if mo:
                    mo.cut_plan_id = cut_plan_map[line.product_id.id].id

        return res

    def _create_invoices(self, grouped=False, final=False, date=None):
        moves = super()._create_invoices(grouped=grouped, final=final, date=date)

        for move in moves:
            for invoice_line in move.invoice_line_ids:
                if invoice_line.price_total < 0 and 'Pagamento de entrada' in invoice_line.name:
                    move.write({'payment_state': 'partial'})

        return moves
