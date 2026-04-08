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
        res = super().action_confirm()

        for order in self:
            cut_plans_created = self.env['mrp_cut_plan.mrp_cut_plan']

            # 🔥 CRIAR ORDEM DE ENTREGA PRIMEIRO (UMA ÚNICA VEZ PARA O PEDIDO INTEIRO)
            delivery = None

            for line in order.order_line.filtered(
                    lambda l: l.product_id.type == 'product'  # Todos os produtos do tipo produto
            ):
                # 🔥 APENAS para produtos COM cálculo especial, criamos plano de corte
                if line.product_id.blue_area_calc in ['llh', 'm']:
                    # Verifica se já existe plano de corte para esta linha
                    existing_cut_plan = self.env['mrp_cut_plan.mrp_cut_plan'].search([
                        ('sale_id', '=', order.id),
                        ('sale_line_id', '=', line.id)
                    ], limit=1)

                    if existing_cut_plan:
                        _logger.info(f"⏭️ Plano de corte já existe para linha {line.id}")
                        cut_plans_created |= existing_cut_plan
                        continue

                    # Verifica se o produto tem BOM
                    bom = self.env['mrp.bom'].search([
                        '|',
                        ('product_id', '=', line.product_id.id),
                        ('product_tmpl_id', '=', line.product_id.product_tmpl_id.id),
                        ('type', '=', 'normal'),
                        ('active', '=', True)
                    ], limit=1)

                    if bom:
                        _logger.info(
                            f"📝 Criando plano de corte para produto {line.product_id.name} (tipo cálculo: {line.product_id.blue_area_calc})")

                        cut_plan_vals = {
                            'sale_id': order.id,
                            'sale_line_id': line.id,
                            'product_id': line.product_id.id,
                            'blue_qty': line.product_uom_qty,
                            'blue_bom_template_id': bom.id,
                            'blue_origin': order.name,
                            'blue_I': line.blue_I,
                            'blue_II': line.blue_II,
                            'blue_h': line.blue_h,
                            'blue_advance': line.blue_advance,
                            'blue_I_uom': line.blue_I_uom.id if line.blue_I_uom else False,
                            'blue_II_uom': line.blue_II_uom.id if line.blue_II_uom else False,
                            'blue_h_uom': line.blue_h_uom.id if line.blue_h_uom else False,
                            'blue_advance_uom': line.blue_advance_uom.id if line.blue_advance_uom else False,
                            'partner_id': order.partner_id.id,
                        }

                        cut_plan = self.env['mrp_cut_plan.mrp_cut_plan'].create(cut_plan_vals)
                        cut_plans_created |= cut_plan
                    else:
                        _logger.warning(f"⚠️ Produto {line.product_id.name} com cálculo mas sem BOM - pulando")

                # 🔥 PRODUTOS SEM CÁLCULO (n) - CRIAR OP DIRETAMENTE
                elif line.product_id.blue_area_calc == 'n':
                    _logger.info(f"🏭 Produto sem cálculo especial - criando OP diretamente para {line.product_id.name}")

                    # Buscar BOM do produto
                    bom = self.env['mrp.bom'].search([
                        '|',
                        ('product_id', '=', line.product_id.id),
                        ('product_tmpl_id', '=', line.product_id.product_tmpl_id.id),
                        ('type', '=', 'normal'),
                        ('active', '=', True)
                    ], limit=1)

                    if bom:
                        # Criar OP diretamente sem plano de corte
                        production = order._create_production_directly(line, bom)

                        # Se ainda não criamos a ordem de entrega, criar agora
                        if not delivery:
                            delivery = order.with_context(
                                from_sale_order_confirmation=True
                            )._ensure_delivery_order()
                    else:
                        _logger.warning(f"⚠️ Produto {line.product_id.name} sem BOM - não é possível criar OP")

            # Processar planos de corte criados (para produtos com cálculo)
            if cut_plans_created:
                # 🔥 SE AINDA NÃO CRIAMOS A ENTREGA, CRIAR AGORA
                if not delivery:
                    first_plan = cut_plans_created[0]
                    delivery = first_plan._create_delivery_with_items(order)

                # Criar OPs apenas para planos que NÃO têm OP
                plans_without_mo = cut_plans_created.filtered(lambda p: not p.mo_id)
                if plans_without_mo:
                    _logger.info(f"🔍 Criando OPs para {len(plans_without_mo)} planos de corte")

                    # Passar o contexto correto com active_ids
                    plans_without_mo = plans_without_mo.with_context(
                        active_ids=plans_without_mo.ids,
                        active_model='mrp_cut_plan.mrp_cut_plan',
                        sale_line_id=line.id
                    )
                    plans_without_mo.button_create_po_multi()

                    # Vincular a entrega criada aos planos
                    for plan in plans_without_mo:
                        if plan.sale_id:
                            plan._force_link_sale_to_productions()
                else:
                    _logger.info("⏭️ Todos os planos já possuem OPs")

            # 🔥 GARANTIR QUE A ORDEM DE ENTREGA TEM TODOS OS ITENS
            if delivery:
                # Verificar se todos os itens do pedido estão na entrega
                for line in order.order_line.filtered(lambda l: l.product_id.type == 'product'):
                    if line.product_uom_qty <= 0:
                        continue

                    existing_move = delivery.move_ids.filtered(
                        lambda m: m.sale_line_id.id == line.id
                    )

                    if not existing_move:
                        _logger.info(f"📦 Adicionando item faltante à entrega: {line.product_id.name}")

                        move_vals = {
                            'name': line.name or line.product_id.display_name,
                            'product_id': line.product_id.id,
                            'product_uom_qty': line.product_uom_qty,
                            'product_uom': line.product_uom.id,
                            'location_id': delivery.location_id.id,
                            'location_dest_id': delivery.location_dest_id.id,
                            'company_id': delivery.company_id.id,
                            'sale_line': line.id,
                            'picking_id': delivery.id,
                            'description_picking': line.name,
                        }

                        self.env['stock.move'].create(move_vals)

                # Reconfirmar a entrega para atualizar
                delivery.action_confirm()
                delivery.action_assign()
                _logger.info(f"✅ Entrega finalizada com {len(delivery.move_ids)} itens")

        return res

    def _create_production_directly(self, line, bom):
        """
        Cria ordem de produção diretamente para produtos sem cálculo especial
        """
        _logger.info(f"🏭 Criando OP diretamente para {line.product_id.name}")

        # Buscar empresa matriz (Polispan)
        company_matrix = self.env['res.company'].search([('name', '=', 'Polispan')], limit=1)
        if not company_matrix:
            _logger.error("❌ Empresa matriz (Polispan) não encontrada.")
            return False

        warehouse_matrix = self.env['stock.warehouse'].search([('company_id', '=', company_matrix.id)], limit=1)
        if not warehouse_matrix:
            _logger.error("❌ Nenhum armazém encontrado para a matriz (Polispan).")
            return False

        # Encontrar o picking_type_id correto da matriz
        picking_type_matrix = self.env['stock.picking.type'].search([
            ('warehouse_id', '=', warehouse_matrix.id),
            ('code', '=', 'mrp_operation')
        ], limit=1)

        if not picking_type_matrix:
            picking_type_matrix = self.env['stock.picking.type'].search([
                ('warehouse_id', '=', warehouse_matrix.id),
            ], limit=1)

        if not picking_type_matrix:
            _logger.error("❌ Tipo de operação de fabricação não encontrado para a matriz.")
            return False

        # Preparar dados da OP
        production_data = {
            'company_id': company_matrix.id,
            'location_src_id': warehouse_matrix.lot_stock_id.id,
            'location_dest_id': warehouse_matrix.lot_stock_id.id,
            'picking_type_id': picking_type_matrix.id,
            'product_id': line.product_id.id,
            'product_uom_id': line.product_id.uom_id.id,
            'bom_id': bom.id,
            'product_qty': line.product_uom_qty,
            'partner_id': self.partner_id.id,
            'origin': self.name,
            'sale_id': self.id,
            'sale_line': line.id,
            'source_procurement_group_id': self.procurement_group_id.id if self.procurement_group_id else False,
        }

        if self.commitment_date:
            production_data['date_planned_start'] = self.commitment_date

        try:
            # Criar OP
            production_order = self.env['mrp.production'].with_company(company_matrix).with_context(
                allowed_company_ids=[company_matrix.id],
                company_id=company_matrix.id
            ).create(production_data)

            _logger.info(f"   ✅ OP criada: {production_order.name}")

            # Confirmar OP (cria movimentos)
            production_order.action_confirm()
            production_order.state = 'draft'

            # Criar OPs filhas para componentes fabricáveis
            production_order._create_child_productions_from_components()

            # Refazer reservas
            production_order.move_raw_ids._action_assign()

            # Atualizar contador de OPs no pedido
            self._update_mrp_production_count()

            # Criar ou atualizar ordem de entrega
            self._ensure_delivery_order()

            return production_order

        except Exception as e:
            _logger.error(f"❌ Erro ao criar OP diretamente: {str(e)}")
            import traceback
            _logger.error(traceback.format_exc())
            return False

    def _ensure_delivery_order(self):
        """
        Garante que existe uma ordem de entrega para o pedido com TODOS os itens
        """
        # Verificar se já existe ordem de entrega
        existing_delivery = self.env['stock.picking'].search([
            ('sale_id', '=', self.id),
            ('picking_type_id.code', '=', 'outgoing'),
            ('state', 'not in', ['cancel'])
        ], limit=1)

        if existing_delivery:
            _logger.info(f"📦 Entrega já existe: {existing_delivery.name}")

            # Verificar se todos os itens estão na entrega
            for line in self.order_line.filtered(lambda l: l.product_id.type == 'product'):
                if line.product_uom_qty <= 0:
                    continue

                existing_move = existing_delivery.move_ids.filtered(
                    lambda m: m.sale_line_id.id == line.id
                )

                if not existing_move:
                    _logger.info(f"   ➕ Adicionando item faltante: {line.product_id.name}")
                    move_vals = {
                        'name': line.name or line.product_id.display_name,
                        'product_id': line.product_id.id,
                        'product_uom_qty': line.product_uom_qty,
                        'product_uom': line.product_uom.id,
                        'location_id': existing_delivery.location_id.id,
                        'location_dest_id': existing_delivery.location_dest_id.id,
                        'company_id': existing_delivery.company_id.id,
                        'sale_line_id': line.id,
                        'picking_id': existing_delivery.id,
                        'description_picking': line.name,
                    }
                    self.env['stock.move'].create(move_vals)

            return existing_delivery

        # Criar nova ordem de entrega com TODOS os itens
        _logger.info(f"📦 Criando nova ordem de entrega para pedido {self.name}")

        picking_type = self.warehouse_id.out_type_id
        if not picking_type:
            picking_type = self.env['stock.picking.type'].search([
                ('code', '=', 'outgoing'),
                ('warehouse_id.company_id', '=', self.company_id.id)
            ], limit=1)

        if not picking_type:
            _logger.error("❌ Tipo de operação de saída não encontrado")
            return False

        # Criar a ordem de entrega com TODOS os itens
        picking_vals = {
            'partner_id': self.partner_id.id,
            'sale_id': self.id,
            'origin': self.name,
            'picking_type_id': picking_type.id,
            'location_id': picking_type.default_location_src_id.id,
            'location_dest_id': self.partner_id.property_stock_customer.id,
            'company_id': self.company_id.id,
            'group_id': self.procurement_group_id.id if self.procurement_group_id else False,
            'move_ids': []
        }

        # Adicionar movimentos para TODAS as linhas do pedido
        for line in self.order_line.filtered(lambda l: l.product_id.type == 'product'):
            if line.product_uom_qty <= 0:
                continue

            move_vals = {
                'name': line.name or line.product_id.display_name,
                'product_id': line.product_id.id,
                'product_uom_qty': line.product_uom_qty,
                'product_uom': line.product_uom.id,
                'location_id': picking_type.default_location_src_id.id,
                'location_dest_id': self.partner_id.property_stock_customer.id,
                'company_id': self.company_id.id,
                'sale_line_id': line.id,
                'description_picking': line.name,
            }
            picking_vals['move_ids'].append((0, 0, move_vals))

        try:
            # 🔥 IMPORTANTE: Adicionar contexto para ignorar verificação de OP
            picking = self.env['stock.picking'].with_context(
                from_sale_order_confirmation=True
            ).create(picking_vals)

            picking.action_confirm()
            picking.action_assign()

            _logger.info(f"✅ Ordem de entrega criada: {picking.name} com {len(picking.move_ids)} itens")
            return picking

        except Exception as e:
            _logger.error(f"❌ Erro ao criar ordem de entrega: {str(e)}")
            return False

    def _update_mrp_production_count(self):
        """
        Atualiza o contador de OPs no pedido de venda
        """
        ops = self.env['mrp.production'].search([
            ('sale_id', '=', self.id)
        ])

        all_ops = ops
        for op in ops:
            if op.child_production_ids:
                all_ops |= op.child_production_ids

        self.write({
            'mrp_production_count': len(all_ops),
            'mrp_production_ids': [(6, 0, all_ops.ids)]
        })

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
                'blue_m2': line.blue_m2,
                'blue_m3': line.blue_m3,
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