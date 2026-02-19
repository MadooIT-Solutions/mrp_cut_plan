from odoo import models, fields, api, _
from odoo.exceptions import UserError
import logging

_logger = logging.getLogger(__name__)


class StockPicking(models.Model):
    _inherit = "stock.picking"

    custom_block_validate = fields.Boolean(string="Bloquear Validação")
    show_validate = fields.Boolean(string="Exibir Botão de Validação", default=True)

    branch_mo_id = fields.Many2many(
        "mrp.production",
        "stock_picking_branch_mo_rel",
        "picking_id",
        "production_id",
        string="Ordens de Produção da Filial"
    )

    branch_backorder_id = fields.Many2one("stock.picking", string="Backorder Vinculado")

    customer = fields.Many2one('res.partner', string='Partner', compute="_compute_customer")

    production_status = fields.Selection(
        [
            ('not_started', 'Não iniciado'),
            ('started_partial', 'Iniciado parcialmente'),
            ('started', 'Iniciado'),
            ('partial', 'Parcialmente pronto'),
            ('ready', 'Pronto'),
        ],
        string='Status da Produção',
        compute='_compute_production_status',
        default='not_started',
        store=True,
    )

    def _compute_production_status(self):
        MrpProduction = self.env['mrp.production']

        for picking in self:
            picking.production_status = 'not_started'

            sale_lines = picking.move_ids_without_package.mapped('sale_line_id')
            if not sale_lines:
                continue

            productions = MrpProduction.search([
                ('cut_plan_id.sale_line_id', 'in', sale_lines.ids),
                ('parent_production_id', '=', False),
                ('state', '!=', 'cancel'),
            ])

            if not productions:
                continue

            confirmed = productions.filtered(
                lambda p: p.state in ('confirmed', 'progress', 'done')
            )

            done = productions.filtered(lambda p: p.state == 'done')

            # 1️⃣ Nada confirmado
            if not confirmed:
                picking.production_status = 'not_started'

            # 2️⃣ Confirmado parcialmente
            elif len(confirmed) < len(productions):
                picking.production_status = 'started_partial'

            # 3️⃣ Tudo confirmado, nada concluído
            elif not done:
                picking.production_status = 'started'

            # 4️⃣ Concluído parcialmente
            elif len(done) < len(productions):
                picking.production_status = 'partial'

            # 5️⃣ Tudo concluído
            else:
                picking.production_status = 'ready'

    def _compute_customer(self):
        """Computa o nome do cliente a partir do partner_id"""
        for picking in self:
            sale_order = picking._get_related_sale_order()
            picking.customer = sale_order.partner_id if sale_order else picking.partner_id

    def _get_related_sale_order(self):
        """Obtém o pedido de venda relacionado ao picking"""
        self.ensure_one()

        # 1. Primeiro tenta buscar pelo sale_id (mais rápido)
        if self.sale_id:
            return self.sale_id

        # 2. Tenta buscar pela origem
        if self.origin:
            origin_clean = self.origin.split(' - ')[0] if ' - ' in self.origin else self.origin
            sale_order = self.env['sale.order'].search([
                ('name', '=', origin_clean)
            ], limit=1)
            if sale_order:
                return sale_order

        # 3. Tenta buscar pelos movimentos
        if self.move_ids:
            moves_with_sale = self.move_ids.filtered(lambda m: m.sale_line_id)
            if moves_with_sale:
                return moves_with_sale[0].sale_line_id.order_id

        # 4. Tenta buscar pelo grupo de procurement
        if self.group_id:
            sale_order = self.env['sale.order'].search([
                ('procurement_group_id', '=', self.group_id.id)
            ], limit=1)
            if sale_order:
                return sale_order

        return False

    def write(self, vals):
        """🔥 APENAS REMOVE SALE_ID DE DEVOLUÇÕES"""
        res = super().write(vals)

        for picking in self:
            # Remove sale_id de devoluções automáticas
            if (
                    picking.picking_type_id.code == 'incoming'
                    and picking.sale_id
                    and picking.origin
                    and picking.origin.startswith('Return')
            ):
                picking.sale_id = False

        return res

    def _create_returns(self):
        res = super()._create_returns()
        for picking in self:
            picking.sale_id = False
        return res

    def action_assign(self):

        # ✅ Libera reserva quando vier da OP pai
        if self.env.context.get('from_mrp_production') or self.env.context.get('skip_op_check'):
            return super().action_assign()

        for picking in self:

            sale_order = picking._get_related_sale_order()
            if not sale_order:
                continue

            for move in picking.move_ids:
                if not move.product_id or not move.sale_line_id:
                    continue

                sale_line = move.sale_line_id

                # --------------------------------------------------
                # 1️⃣ Busca OPs PAI pela LINHA DE VENDA (correto)
                # --------------------------------------------------
                parent_mos = self.env['mrp.production'].search([
                    ('cut_plan_id.sale_line_id', '=', sale_line.id),
                    ('parent_production_id', '=', False),
                    ('state', 'not in', ('cancel',)),
                ])

                if not parent_mos:
                    continue

                done_mos = parent_mos.filtered(lambda m: m.state == 'done')
                pending_mos = parent_mos.filtered(lambda m: m.state != 'done')

                # --------------------------------------------------
                # 2️⃣ Se OP concluída → atualiza entrega
                # --------------------------------------------------
                if done_mos:
                    qty = move.product_uom_qty

                    # Atualiza quantidade feita
                    if move.move_line_ids:
                        move.move_line_ids.write({
                            'qty_done': qty
                        })
                    else:
                        move._set_quantity_done(qty)

                    # Atualiza forecast
                    move.write({
                        'forecast_availability': qty
                    })

                # --------------------------------------------------
                # 3️⃣ Se existir OP NÃO concluída → bloqueia
                # --------------------------------------------------
                if pending_mos:
                    parent_mo = pending_mos[0]

                    description = (
                            move.description_picking
                            or sale_line.name
                            or move.product_id.display_name
                    )

                    raise UserError(_(
                        "❌ Produto ainda não disponível para entrega.\n\n"
                        "Descrição: %(description)s\n"
                        "Produto: %(product)s\n"
                        "OP Pai: %(mo)s\n"
                        "Status da OP: %(state)s\n\n"
                        "A entrega só pode ser reservada após a conclusão da OP Pai."
                    ) % {
                                        'description': description,
                                        'product': move.product_id.display_name,
                                        'mo': parent_mo.name,
                                        'state': parent_mo.state,
                                    })

        return super().action_assign()


class StockMove(models.Model):
    _inherit = 'stock.move'

    sale_order_line_id = fields.Many2one(
        'sale.order.line',
        string='Linha do Pedido de Venda',
        help='Relacionamento direto com a linha do pedido de venda'
    )

    sale_line_description = fields.Char(
        string='Descrição do Pedido',
        store=True
    )

    planned_uom_qty = fields.Float(
        string='Planned Quantity',
        compute='_compute_planned_uom_qty',
        store=True
    )

    calc = fields.Boolean(
        string='Calcular por Área',
        help='Indica que o consumo será calculado automaticamente (blue_m3)'
    )

    is_produced_status = fields.Selection(
        [
            ('no', 'Não'),
            ('started', 'Iniciado'),
            ('yes', 'Sim'),
        ],
        string='Produzido',
        compute='_compute_is_produced_status',
        store=True,
        readonly=True,
        default='no'
    )

    @api.depends('sale_line_id', 'product_id')
    def _compute_is_produced_status(self):
        for move in self:
            move.is_produced_status = 'yes' if move.is_produced_status else 'no'

    def _action_done(self, cancel_backorder=False):
        """Override para garantir atualização do consumo na OP pai"""
        _logger.info("=" * 60)
        _logger.info(f"📦 StockMove._action_done")
        _logger.info(f"   Movimentos: {self.ids}")

        res = super()._action_done(cancel_backorder)

        for move in self:
            production = move.raw_material_production_id or move.production_id
            if production and production.parent_production_id:
                _logger.info(f"   🔄 Movimento da OP filha {production.name} concluído")
                try:
                    # 🔥 CORREÇÃO: usar o método correto
                    production._update_parent_consumption_from_child()
                    _logger.info(f"      ✅ Consumo atualizado na OP pai {production.parent_production_id.name}")
                except Exception as e:
                    _logger.error(f"      ❌ Erro ao atualizar consumo: {str(e)}")

        _logger.info("=" * 60)
        return res

    @api.depends('product_uom_qty')
    def _compute_planned_uom_qty(self):
        for move in self:
            move.planned_uom_qty = move.product_uom_qty

    def write(self, vals):
        allowed_contexts = [
            'from_child_production',
            'from_cut_plan_creation',
            'force_allow_write',
            'from_production_creation',
            'skip_consumption_check',
            'from_delivery_update'
        ]

        if any(self.env.context.get(ctx) for ctx in allowed_contexts):
            return super().write(vals)

        for move in self:
            production = move.raw_material_production_id or move.production_id
            if production and production.state == 'draft':
                return super().write(vals)

        quantity_fields = {'quantity_done', 'product_uom_qty'}
        if not quantity_fields.intersection(vals):
            return super().write(vals)

        for move in self:
            production = move.raw_material_production_id or move.production_id
            if not production:
                continue

            if not move.calc:
                continue

            if production.parent_production_id:
                continue

            if move.state in ('done', 'cancel'):
                continue

            has_child = self.env['mrp.production'].search_count([
                ('parent_production_id', '=', production.id),
                ('product_id', '=', move.product_id.id),
                ('state', 'not in', ('cancel',)),
            ]) > 0

            if has_child:
                child_ops = self.env['mrp.production'].search([
                    ('parent_production_id', '=', production.id),
                    ('product_id', '=', move.product_id.id),
                    ('state', 'not in', ('cancel',)),
                ])

                child_names = ", ".join([op.name for op in child_ops[:3]])
                if len(child_ops) > 3:
                    child_names += f" e mais {len(child_ops) - 3}"

                raise UserError(
                    _(
                        "❌ Edição manual de consumo bloqueada.\n\n"
                        "Produto: %(product_name)s\n"
                        "Este componente tem consumo calculado automaticamente (calc=True).\n"
                        "Existe OP filha relacionada.\n\n"
                        "OPs filhas: %(child_ops)s\n\n"
                        "O consumo é atualizado automaticamente ao concluir a OP filha."
                    ) % {
                        'product_name': move.product_id.display_name,
                        'child_ops': child_names or 'Nenhuma encontrada'
                    }
                )

        return super().write(vals)


class StockMoveLine(models.Model):
    _inherit = 'stock.move.line'

    sale_line_description = fields.Char(
        string='Descrição do Pedido',
        compute='_compute_sale_line_description',
        store=True
    )

    @api.depends('move_id.sale_order_line_id', 'move_id.sale_order_line_id.name')
    def _compute_sale_line_description(self):
        for move_line in self:
            if move_line.move_id.sale_order_line_id:
                move_line.sale_line_description = move_line.move_id.sale_order_line_id.name
            else:
                move_line.sale_line_description = move_line.product_id.display_name


class StockRule(models.Model):
    _inherit = 'stock.rule'

    def _prepare_mo_vals(
        self, product_id, product_qty, product_uom, location_id,
        name, origin, company_id, values, bom
    ):
        return super()._prepare_mo_vals(
            product_id, product_qty, product_uom, location_id,
            name, origin, company_id, values, bom
        )

    def _run_manufacture(self, procurements):
        productions = super()._run_manufacture(procurements)

        for procurement, rule in procurements:
            mo = productions.get(procurement)
            if not mo:
                continue

            sale_line = procurement.values.get('sale_line_id')
            if not sale_line:
                continue

            product = procurement.product_id
            if product.blue_area_calc == 'n':
                continue

            cut_plan = self.env['mrp_cut_plan.mrp_cut_plan'].search([
                ('sale_line_id', '=', sale_line.id),
                ('product_id', '=', product.id),
            ], limit=1)

            if not cut_plan:
                continue

            # vincula tudo
            mo.write({
                'cut_plan_id': cut_plan.id,
                'sale_line_id': sale_line.id,
                'procurement_group_id': procurement.group_id.id,
            })

            # 🔥 cria OPs filhas
            mo._create_child_productions_from_cut_plan()

        return productions

    # ---------------------------------------------------------
    # FLUXO PLANO DE CORTE
    # ---------------------------------------------------------
    def _run_cut_plan_flow(self, procurement):
        product = procurement.product_id
        sale_line = procurement.values.get('sale_line_id')

        if not sale_line:
            return

        _logger.error(
            "✂️ Criando Cut Plan | produto=%s | linha=%s",
            product.display_name,
            sale_line.id
        )

        self.env['mrp_cut_plan.mrp_cut_plan'].create({
            'sale_id': sale_line.order_id.id,
            'sale_line_id': sale_line.id,
            'product_id': product.id,
            'blue_qty': procurement.product_qty,
            'blue_bom_template_id': product.bom_ids[:1].id,
            'blue_origin': sale_line.order_id.name,
        })


