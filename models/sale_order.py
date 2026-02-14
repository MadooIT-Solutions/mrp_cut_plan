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

    def action_confirm(self):
        # PRIMEIRO: VALIDAÇÃO DE MEDIDAS
        for order in self:
            for line in order.order_line.filtered(
                    lambda l: l.product_id.blue_area_calc != 'n'
            ):
                # Validação para produtos LLH
                if line.product_id.blue_area_calc == 'llh':
                    missing = []
                    if not line.blue_I or line.blue_I <= 0:
                        missing.append('Medida I')
                    if not line.blue_II or line.blue_II <= 0:
                        missing.append('Medida II')
                    if not line.blue_h or line.blue_h <= 0:
                        missing.append('Medida H')

                    if missing:
                        raise UserError(
                            f"Produto LLH '{line.product_id.name}' na linha {line.name} "
                            f"está faltando as seguintes medidas:\n- " + "\n- ".join(missing)
                        )

                # Validação para produtos Molde
                if line.product_id.blue_area_calc == 'm':
                    missing = []
                    if not line.blue_advance or line.blue_advance <= 0:
                        missing.append('Medida Avanço')
                    if not line.blue_h or line.blue_h <= 0:
                        missing.append('Medida H')

                    if missing:
                        raise UserError(
                            f"Produto Molde '{line.product_id.name}' na linha {line.name} "
                            f"está faltando as seguintes medidas:\n- " + "\n- ".join(missing)
                        )

        # SEGUNDO: CONFIRMA O PEDIDO (só executa se passou na validação)
        res = super().action_confirm()

        # TERCEIRO: CRIA OS PLANOS DE CORTE
        for order in self:
            cut_plans_created = self.env['mrp_cut_plan.mrp_cut_plan']

            for line in order.order_line.filtered(
                    lambda l: l.product_id.blue_area_calc != 'n'
            ):
                # Verifica se já existe plano de corte para esta linha
                existing_cut_plan = self.env['mrp_cut_plan.mrp_cut_plan'].search([
                    ('sale_id', '=', order.id),
                    ('sale_line_id', '=', line.id)
                ], limit=1)

                if existing_cut_plan:
                    _logger.info(f"⏭️ Plano de corte já existe para linha {line.id}")
                    cut_plans_created |= existing_cut_plan
                    continue

                # Cria novo plano de corte
                cut_plan = self.env['mrp_cut_plan.mrp_cut_plan'].create({
                    'sale_id': order.id,
                    'sale_line_id': line.id,
                    'product_id': line.product_id.id,
                    'blue_qty': line.product_uom_qty,
                    'blue_bom_template_id': line.product_id.bom_ids[:1].id if line.product_id.bom_ids else False,
                    'blue_origin': order.name,
                    'blue_I': line.blue_I,
                    'blue_II': line.blue_II,
                    'blue_h': line.blue_h,
                    'blue_advance': line.blue_advance,
                    'blue_m2': line.blue_m2,
                    'blue_m3': line.blue_m3,
                    'blue_I_uom': line.blue_I_uom.id if line.blue_I_uom else False,
                    'blue_II_uom': line.blue_II_uom.id if line.blue_II_uom else False,
                    'blue_h_uom': line.blue_h_uom.id if line.blue_h_uom else False,
                    'blue_advance_uom': line.blue_advance_uom.id if line.blue_advance_uom else False,
                    'partner_id': order.partner_id.id,
                })
                cut_plans_created |= cut_plan

            # 🔥 CRIAR A ORDEM DE ENTREGA PRIMEIRO
            if cut_plans_created:
                # Criar ordem de entrega para o pedido
                first_plan = cut_plans_created[0]
                delivery = first_plan._create_delivery_with_items(order)

                if delivery:
                    _logger.info(f"✅ Ordem de entrega criada: {delivery.name}")

                # Criar OPs apenas para planos que NÃO têm OP
                plans_without_mo = cut_plans_created.filtered(lambda p: not p.mo_id)
                if plans_without_mo:
                    _logger.info(f"🔍 Criando OPs para {len(plans_without_mo)} planos de corte")

                    # Passar o contexto correto com active_ids
                    plans_without_mo = plans_without_mo.with_context(
                        active_ids=plans_without_mo.ids,
                        active_model='mrp_cut_plan.mrp_cut_plan'
                    )
                    plans_without_mo.button_create_po_multi()

                    # 🔥 VINCULAR A ENTREGA CRIADA AOS PLANOS
                    for plan in plans_without_mo:
                        if plan.sale_id:
                            plan._force_link_sale_to_productions()
                else:
                    _logger.info("⏭️ Todos os planos já possuem OPs")

        return res

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