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

    @api.depends('move_ids_without_package.is_produced_status')
    def _compute_production_status(self):
        """
        Computa o status da produção baseado no is_produced_status das linhas de movimento
        """
        for picking in self:
            # Pega todos os moves que têm is_produced_status diferente de 'no'
            moves_with_production = picking.move_ids_without_package.filtered(
                lambda m: m.is_produced_status != 'no'
            )

            if not moves_with_production:
                picking.production_status = 'not_started'
                continue

            # Contagem de status
            total_moves = len(moves_with_production)
            confirmed_moves = len(moves_with_production.filtered(
                lambda m: m.is_produced_status == 'confirmed'
            ))
            started_moves = len(moves_with_production.filtered(
                lambda m: m.is_produced_status == 'started'
            ))
            done_moves = len(moves_with_production.filtered(
                lambda m: m.is_produced_status == 'yes'
            ))

            _logger.info(f"📋 Calculando status para picking {picking.name}")
            _logger.info(f"   Total moves: {total_moves}")
            _logger.info(f"   Confirmados: {confirmed_moves}")
            _logger.info(f"   Iniciados: {started_moves}")
            _logger.info(f"   Concluídos: {done_moves}")

            # 1️⃣ Nada confirmado (só draft)
            if confirmed_moves == 0 and started_moves == 0 and done_moves == 0:
                picking.production_status = 'not_started'

            # 2️⃣ Confirmado parcialmente (alguns confirmados, outros não)
            elif confirmed_moves > 0 and (confirmed_moves + started_moves + done_moves) < total_moves:
                picking.production_status = 'started_partial'

            # 3️⃣ Tudo confirmado, nada iniciado nem concluído
            elif confirmed_moves == total_moves:
                picking.production_status = 'started'

            # 4️⃣ Concluído parcialmente (alguns concluídos, outros em andamento/confirmados)
            elif done_moves > 0 and done_moves < total_moves:
                picking.production_status = 'partial'

            # 5️⃣ Tudo concluído
            elif done_moves == total_moves:
                picking.production_status = 'ready'

            # 6️⃣ Caso padrão (mistura de iniciados com outros status)
            else:
                picking.production_status = 'started_partial'

            _logger.info(f"   ✅ Status final: {picking.production_status}")

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
        # ✅ Libera reserva quando vier da OP pai ou durante criação do pedido
        if self.env.context.get('from_mrp_production') or self.env.context.get('skip_op_check') or self.env.context.get(
                'from_sale_order_confirmation'):
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
                # 1️⃣ Busca OPs PAI pela LINHA DE VENDA (considerando plano de corte)
                # --------------------------------------------------
                domain = [
                    ('sale_id', '=', sale_order.id),
                    ('product_id', '=', move.product_id.id),
                    ('parent_production_id', '=', False),
                    ('state', 'not in', ('cancel',)),
                ]

                # 🔥 Se a linha de venda tem plano de corte, buscar pelo cut_plan_id
                cut_plan = self.env['mrp_cut_plan.mrp_cut_plan'].search([
                    ('sale_line_id', '=', sale_line.id),
                    ('product_id', '=', move.product_id.id)
                ], limit=1)

                if cut_plan:
                    # Para produtos com plano de corte, buscar OPs específicas deste plano
                    domain.append(('cut_plan_id', '=', cut_plan.id))
                    _logger.info(
                        f"🔍 Buscando OP para produto com plano de corte: {move.product_id.name} - Plano: {cut_plan.name}")
                else:
                    # Para produtos sem plano de corte, buscar qualquer OP do produto
                    _logger.info(f"🔍 Buscando OP para produto sem plano de corte: {move.product_id.name}")

                parent_mos = self.env['mrp.production'].search(domain)

                if not parent_mos:
                    # 🔥 Se não encontrou pelo cut_plan, tenta buscar sem ele (para produtos sem plano)
                    if not cut_plan:
                        fallback_domain = [
                            ('sale_id', '=', sale_order.id),
                            ('product_id', '=', move.product_id.id),
                            ('parent_production_id', '=', False),
                            ('state', 'not in', ('cancel',)),
                        ]
                        parent_mos = self.env['mrp.production'].search(fallback_domain)
                        if parent_mos:
                            _logger.info(f"   ✅ Encontrada OP sem plano de corte: {parent_mos[0].name}")
                    continue

                # Log para debug
                for mo in parent_mos:
                    _logger.info(
                        f"   OP encontrada: {mo.name} - Estado: {mo.state} - Plano: {mo.cut_plan_id.name if mo.cut_plan_id else 'Sem plano'}")

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
                # 3️⃣ Só bloqueia se tiver OP CONFIRMADA (não em draft)
                # --------------------------------------------------
                confirmed_pending = pending_mos.filtered(lambda m: m.state in ['confirmed', 'progress'])

                if confirmed_pending:
                    parent_mo = confirmed_pending[0]

                    description = (
                            move.description_picking
                            or sale_line.name
                            or move.product_id.display_name
                    )

                    # 🔥 Incluir informação do plano de corte na mensagem de erro
                    plan_info = f" - Plano: {parent_mo.cut_plan_id.name}" if parent_mo.cut_plan_id else ""

                    raise UserError(_(
                        "❌ Produto ainda não disponível para entrega.\n\n"
                        "Descrição: %(description)s\n"
                        "Produto: %(product)s%(plan_info)s\n"
                        "OP Pai: %(mo)s\n"
                        "Status da OP: %(state)s\n\n"
                        "A entrega só pode ser reservada após a conclusão da OP Pai."
                    ) % {
                                        'description': description,
                                        'product': move.product_id.display_name,
                                        'plan_info': plan_info,
                                        'mo': parent_mo.name,
                                        'state': parent_mo.state,
                                    })
                else:
                    # 🔥 Se só tem OPs em draft, permite a reserva
                    _logger.info(
                        f"✅ Permitindo reserva para {move.product_id.name} - OPs em draft: {[mo.name for mo in pending_mos]}")

        return super().action_assign()


class StockMove(models.Model):
    _inherit = 'stock.move'

    sale_line = fields.Many2one(
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
            ('confirmed', 'Confirmado'),
            ('started', 'Iniciado'),
            ('yes', 'Sim'),
        ],
        string='Produzido',
        compute='_compute_is_produced_status',
        store=True,
        readonly=True,
        default='no'
    )

    @api.depends('sale_line')
    def _compute_is_produced_status(self):
        """Computa se o produto já foi produzido baseado na OP relacionada"""
        for move in self:
            if not move.sale_line:
                move.is_produced_status = 'no'
                continue

            producao = self.env['mrp.production'].search([
                ('sale_line', '=', move.sale_line.id)
            ], limit=1)

            if not producao:
                move.is_produced_status = 'no'
                continue

            status = producao.state
            if status == 'draft':
                move.is_produced_status = 'no'
            elif status == 'confirmed':
                move.is_produced_status = 'confirmed'
            elif status == 'progress':
                move.is_produced_status = 'started'
            elif status == 'done':
                move.is_produced_status = 'yes'
            else:
                move.is_produced_status = 'no'


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

    @api.depends('move_id.sale_line', 'move_id.sale_line.name')
    def _compute_sale_line_description(self):
        for move_line in self:
            if move_line.move_id.sale_line:
                move_line.sale_line_description = move_line.move_id.sale_line.name
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


