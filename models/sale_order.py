from odoo import api, models, fields, _
from odoo.exceptions import UserError
import logging

_logger = logging.getLogger(__name__)


class SaleOrder(models.Model):
    _inherit = "sale.order"

    count_po = fields.Integer(
        string="Documents Count",
        compute="_compute_count_po",
        tracking=True
    )

    # 🔥 NOVO CAMPO: Contador de OPs
    mrp_production_count = fields.Integer(
        string="Ordens de Produção",
        compute="_compute_mrp_production_count",
        tracking=True
    )

    # 🔥 NOVO CAMPO: Relação com OPs
    mrp_production_ids = fields.One2many(
        'mrp.production',
        'sale_id',
        string='Ordens de Produção'
    )

    @api.depends('count_po')
    def _compute_count_po(self):
        for record in self:
            qty = self.env['mrp_cut_plan.mrp_cut_plan'].search([('blue_origin', '=', self.name)])
            record.count_po = len(qty)

    @api.depends('mrp_production_ids')
    def _compute_mrp_production_count(self):
        for record in self:
            record.mrp_production_count = len(record.mrp_production_ids)

    def open_linked_po(self):
        domain = [('blue_origin', '=', self.name)]
        return {
            'name': _('Planos de Corte'),
            'domain': domain,
            'type': 'ir.actions.act_window',
            'res_model': 'mrp_cut_plan.mrp_cut_plan',
            'view_id': False,
            'view_mode': 'tree,form',
        }

    # 🔥 NOVA AÇÃO: Abrir OPs vinculadas
    def action_open_linked_productions(self):
        self.ensure_one()
        return {
            'name': _('Ordens de Produção'),
            'type': 'ir.actions.act_window',
            'res_model': 'mrp.production',
            'view_mode': 'tree,form',
            'domain': [('sale_id', '=', self.id)],
            'context': {'create': False},
        }


    def open_linked_po(self):
        domain = [('blue_origin', '=', self.name)]
        return {
            'name': _('Cut Plan'),
            'domain': domain,
            'type': 'ir.actions.act_window',
            'res_model': 'mrp_cut_plan.mrp_cut_plan',
            'view_id': False,
            'view_mode': 'tree,form',
        }

    # Antes de criar OPs, verifique se os planos têm tudo necessário
    valid_plans = self.env['mrp_cut_plan.mrp_cut_plan']
    for plan in plans_without_mo:
        if not plan.product_id:
            _logger.error(f"Plano {plan.id} sem produto!")
            continue
        if not plan.blue_qty or plan.blue_qty <= 0:
            _logger.error(f"Plano {plan.id} com quantidade inválida: {plan.blue_qty}")
            continue
        if not plan.blue_bom_template_id:
            _logger.error(f"Plano {plan.id} sem lista de materiais!")
            continue

        _logger.info(f"Plano {plan.id} válido para criar OP")
        valid_plans |= plan

    if valid_plans:
        # Cria OPs apenas para os planos válidos
        valid_plans.with_context(
            active_ids=valid_plans.ids,
            active_model='mrp_cut_plan.mrp_cut_plan'
        ).button_create_po_multi()

    def _create_cut_plan_flow(self, lines):
        CutPlan = self.env['mrp_cut_plan.mrp_cut_plan']

        for line in lines:

            if line.product_id.blue_area_calc in ['llh', 'm']:
                bom_ids = self.env['mrp.bom'].search([
                    ('product_tmpl_id', '=', line.product_id.product_tmpl_id.id)
                ])

            # 🔥 cria o plano de corte
            cut_plan = CutPlan.create({
                    'blue_origin': line.order_id.name,
                    'product_id': line.product_id.id,
                    'blue_qty': line.product_uom_qty,
                    'blue_bom_template_id': bom_ids[:1].id if bom_ids else False,
                    'blue_I': line.blue_I,
                    'blue_II': line.blue_II,
                    'blue_h': line.blue_h,
                    'blue_I_uom': line.blue_I_uom.id if line.blue_I_uom else False,
                    'blue_II_uom': line.blue_II_uom.id if line.blue_II_uom else False,
                    'blue_h_uom': line.blue_h_uom.id if line.blue_h_uom else False,
                    'blue_advance': line.blue_advance,
                    'blue_wall': line.blue_wall,
                    'blue_wall_uom': line.blue_wall_uom.id if line.blue_wall_uom else False,
                    'blue_advance_uom': line.blue_advance_uom.id if line.blue_advance_uom else False,
                    'binany_field': line.binany_field,
                    'partner_id': self.partner_id.id,
                    'sale_id': self.id
            })

            # 🔥 confirma o plano
            cut_plan.action_confirm()

    def _create_cut_plans_from_line(self, line):
        CutPlan = self.env['mrp_cut_plan.mrp_cut_plan']

        if CutPlan.search([
            ('sale_id', '=', self.id),
            ('sale_line_id', '=', line.id)
        ], limit=1):
            return

        bom = self.env['mrp.bom'].search([
            ('product_tmpl_id', '=', line.product_id.product_tmpl_id.id)
        ], limit=1)

        if not bom:
            return

        CutPlan.create({
            'sale_id': self.id,
            'sale_line_id': line.id,
            'partner_id': self.partner_id.id,
            'product_id': line.product_id.id,
            'blue_qty': line.product_uom_qty,
            'blue_bom_template_id': bom.id,
            'blue_origin': self.name,

            # medidas
            'blue_I': line.blue_I,
            'blue_II': line.blue_II,
            'blue_h': line.blue_h,
            'blue_I_uom': line.blue_I_uom.id,
            'blue_II_uom': line.blue_II_uom.id,
            'blue_h_uom': line.blue_h_uom.id,
            'blue_advance': line.blue_advance,
            'blue_wall': line.blue_wall,
            'blue_wall_uom': line.blue_wall_uom.id,
            'blue_advance_uom': line.blue_advance_uom.id,
        })


    def _create_cut_plans(self):
        self.ensure_one()
        CutPlan = self.env['mrp_cut_plan.mrp_cut_plan']
        plans = self.env['mrp_cut_plan.mrp_cut_plan']

        for line in self.order_line.filtered(
                lambda l: l.product_id.type == 'product' and l.product_id.bom_ids
        ):
            bom_ids = self.env['mrp.bom'].search([
                ('product_tmpl_id', '=', line.product_id.product_tmpl_id.id)
                # ('active', '=', False)
            ])

            if not bom_ids:
                raise UserError(
                    _('Produto %s não possui BOM definida.') %
                    line.product_id.display_name
                )

            plan = CutPlan.create({
                'blue_origin': line.order_id.name,
                'product_id': line.product_id.id,
                'blue_qty': line.product_uom_qty,
                'blue_bom_template_id': bom_ids[:1].id if bom_ids else False,
                'blue_I': line.blue_I,
                'blue_II': line.blue_II,
                'blue_h': line.blue_h,
                'blue_I_uom': line.blue_I_uom.id if line.blue_I_uom else False,
                'blue_II_uom': line.blue_II_uom.id if line.blue_II_uom else False,
                'blue_h_uom': line.blue_h_uom.id if line.blue_h_uom else False,
                'blue_advance': line.blue_advance,
                'blue_wall': line.blue_wall,
                'blue_wall_uom': line.blue_wall_uom.id if line.blue_wall_uom else False,
                'blue_advance_uom': line.blue_advance_uom.id if line.blue_advance_uom else False,
                'binany_field': line.binany_field,
                'partner_id': self.partner_id.id,
                'sale_id': self.id
            })

            plans |= plan

        return plans

    def _create_invoices(self, grouped=False, final=False, date=None):
        moves = super()._create_invoices(grouped=grouped, final=final, date=date)

        for move in moves:
            for invoice_line in move.invoice_line_ids:
                if invoice_line.price_total < 0 and 'Pagamento de entrada' in invoice_line.name:
                    move.write({'payment_state': 'partial'})

        return moves