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

    # Campo production_status em StockPicking que sincroniza com os moves
    # Estados: not_started, started_partial, started, partial, ready, cancelled
    production_status = fields.Selection([
        ('not_started', 'Não Iniciado'),
        ('started_partial', 'Iniciado Parcialmente'),
        ('started', 'Iniciado'),
        ('partial', 'Parcialmente Produzido'),
        ('ready', 'Pronto para Entrega'),
        ('cancelled', 'Cancelado')
    ], string='Status de Produção', compute='_compute_production_status', store=True)

    def read(self, fields=None, load='_classic_read'):
        res = super().read(fields=fields, load=load)
        if 'production_status' in (fields or []):
            self.invalidate_cache(['production_status'])
            self._compute_production_status()
        return res

    @api.depends('move_ids.is_produced_status', 'origin', 'state')
    def _compute_production_status(self):
        """
        Calcula o status de produção do picking agregando o 'is_produced_status' de seus movimentos.
        Prioriza o status de cancelamento da OP relacionada.
        """

        for picking in self:
            picking.production_status = 'not_started'  # Default value

            # 1. Verificar se há uma OP relacionada e se ela está cancelada
            related_mo = False
            if picking.origin:
                related_mo = self.env['mrp.production'].search([('name', '=', picking.origin)], limit=1)

            if related_mo and related_mo.state == 'cancel':
                picking.production_status = 'cancelled'
                _logger.debug(f"Picking {picking.name}: Status 'cancelled' devido à OP {related_mo.name} cancelada.")
                continue

            # 2. Se não houver movimentos, o status é 'Não Iniciado'
            if not picking.move_ids:
                picking.production_status = 'not_started'
                _logger.debug(f"Picking {picking.name}: Status 'not_started' (sem movimentos).")
                continue

            # 3. Agregação dos status dos movimentos
            all_move_statuses = [move.is_produced_status for move in picking.move_ids if move.is_produced_status]

            if not all_move_statuses:
                picking.production_status = 'not_started'
                _logger.debug(f"Picking {picking.name}: Status 'not_started' (movimentos sem status).")
                continue

            total_moves = len(all_move_statuses)
            no_count = all_move_statuses.count('no')
            confirmed_count = all_move_statuses.count('confirmed')
            started_count = all_move_statuses.count('started')
            yes_count = all_move_statuses.count('yes')

            _logger.debug(f"Picking {picking.name} - Agregação de status: "
                          f"Total={total_moves}, No={no_count}, Confirmed={confirmed_count}, "
                          f"Started={started_count}, Yes={yes_count}")

            if yes_count == total_moves:
                picking.production_status = 'ready'
            elif no_count == total_moves:
                picking.production_status = 'not_started'
            elif yes_count > 0 and yes_count < total_moves:
                picking.production_status = 'partial'
            elif started_count == total_moves:
                picking.production_status = 'started'
            elif confirmed_count == total_moves:
                picking.production_status = 'started_partial'  # Todos confirmados, mas nenhum iniciado/feito
            elif started_count > 0 or confirmed_count > 0 or yes_count > 0:
                picking.production_status = 'started_partial'  # Qualquer mix de progresso
            else:
                picking.production_status = 'not_started'  # Fallback

            _logger.info(f"Picking {picking.name}: Status de Produção computado como '{picking.production_status}'.")

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
            moves_with_sale = self.move_ids.filtered(lambda m: m.sale_line_id)  # Usar 'sale_line' em vez de 'sale_line_id'
            if moves_with_sale:
                return moves_with_sale[0].sale_line_id.order_id  # Usar 'sale_line'

        # 4. Tenta buscar pelo grupo de procurement
        if self.group_id:
            sale_order = self.env['sale.order'].search([
                ('procurement_group_id', '=', self.group_id.id)
            ], limit=1)
            if sale_order:
                return sale_order

        return False

    def write(self, vals):
        """Hook para remover sale_id de devoluções automáticas"""
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
            # Garante que o sale_id seja removido para devoluções
            picking.sale_id = False
        return res

    def action_assign(self):
        res = super().action_assign()
        self._compute_production_status()  # Force
        return res


class StockMove(models.Model):
    _inherit = 'stock.move'

    sale_line_id = fields.Many2one(
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

    # Campo is_produced_status em StockMove
    # Mapeia o estado da OP para o status do movimento
    is_produced_status = fields.Selection([
        ('no', 'Não Produzido'),
        ('confirmed', 'Confirmado'),
        ('started', 'Iniciado'),
        ('yes', 'Produzido')
    ], string='Status de Produção', compute='_compute_is_produced_status', store=True)

    @api.depends(
        'sale_line_id',
        'production_id',
        'raw_material_production_id',
        'production_id.state',
        'raw_material_production_id.state',
        'production_id.parent_production_id',
        'raw_material_production_id.parent_production_id',
    )
    def _compute_is_produced_status(self):
        for move in self:
            move.is_produced_status = 'no'

            production = move.raw_material_production_id or move.production_id

            # Se não vier direto pelo move, busca pela linha de venda
            if not production and move.sale_line_id:
                productions = self.env['mrp.production'].search([
                    '|',
                    ('sale_line_id', '=', move.sale_line_id.id),
                    ('cut_plan_id.sale_line_id', '=', move.sale_line_id.id),
                ], order='id desc')

                if productions:
                    # Prioriza sempre a OP raiz
                    root_candidates = productions.filtered(lambda p: not p.parent_production_id)
                    production = root_candidates[:1] or productions[:1]

            if not production:
                continue

            # Sobe até a OP raiz
            root = production
            while root.parent_production_id:
                root = root.parent_production_id

            # Status deve seguir só a raiz
            if root.state == 'draft':
                move.is_produced_status = 'no'
            elif root.state == 'confirmed':
                move.is_produced_status = 'confirmed'
            elif root.state == 'progress':
                move.is_produced_status = 'started'
            elif root.state == 'done':
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
                    # CORREÇÃO: usar o método correto (assumindo que existe em mrp.production)
                    if hasattr(production, '_update_parent_consumption_from_child'):
                        production._update_parent_consumption_from_child()
                        _logger.info(f"      ✅ Consumo atualizado na OP pai {production.parent_production_id.name}")
                    else:
                        _logger.warning(
                            f"      ⚠️ Método _update_parent_consumption_from_child não encontrado na OP {production.name}.")
                except Exception as e:
                    _logger.error(f"      ❌ Erro ao atualizar consumo: {str(e)}")

        _logger.info("=" * 60)
        return res

    @api.depends('product_uom_qty')
    def _compute_planned_uom_qty(self):
        for move in self:
            move.planned_uom_qty = move.product_uom_qty

    def write(self, vals):
        """
        Override do método write para adicionar lógica de bloqueio de edição de consumo
        quando há OPs filhas ou quando o campo 'calc' está ativo.
        """
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
                        "🔒 Edição manual de consumo bloqueada."
                        "Produto: %(product_name)s"
                        "Este componente tem consumo calculado automaticamente (calc=True)."
                        "Existe OP filha relacionada."
                        "OPs filhas: %(child_ops)s"
                        "O consumo é atualizado automaticamente ao concluir a OP filha."
                    ) % {
                        'product_name': move.product_id.display_name,
                        'child_ops': child_names or 'Nenhuma encontrada'
                    }
                )

        return super().write(vals)

    def init(self):
        self._compute_is_produced_status


class StockMoveLine(models.Model):
    _inherit = 'stock.move.line'

    sale_line_description = fields.Char(
        string='Descrição do Pedido',
        compute='_compute_sale_line_description',
        store=True
    )

    @api.depends('move_id.sale_line_id', 'move_id.sale_line_id.name')
    def _compute_sale_line_description(self):
        """
        Computa a descrição da linha do pedido de venda para a linha de movimento de estoque.
        """
        for move_line in self:
            if move_line.move_id.sale_line_id:
                move_line.sale_line_description = move_line.move_id.sale_line_id.name
            else:
                move_line.sale_line_description = move_line.product_id.display_name


class StockRule(models.Model):
    _inherit = 'stock.rule'

    def _prepare_mo_vals(
            self, product_id, product_qty, product_uom, location_id,
            name, origin, company_id, values, bom
    ):
        """
        Prepara os valores para a criação de uma Ordem de Produção.
        """
        return super()._prepare_mo_vals(
            product_id, product_qty, product_uom, location_id,
            name, origin, company_id, values, bom
        )

    def _run_manufacture(self, procurements):
        """
        Override para vincular OPs a planos de corte e criar OPs filhas.
        """
        productions = super()._run_manufacture(procurements)
        for procurement, rule in procurements:
            mo = productions.get(procurement)
            if not mo:
                continue

            sale_line = procurement.values.get('sale_line_id')
            if not sale_line:
                continue

            product = procurement.product_id
            # Assumindo que 'blue_area_calc' é um campo em product.product
            if hasattr(product, 'blue_area_calc') and product.blue_area_calc == 'n':
                continue

            cut_plan = self.env['mrp_cut_plan.mrp_cut_plan'].search([
                ('sale_line_id', '=', sale_line_id.id),
                ('product_id', '=', product.id),
            ], limit=1)

            if not cut_plan:
                continue

            # Vincula a OP ao plano de corte, linha de venda e grupo de procurement
            mo.write({
                'cut_plan_id': cut_plan.id,
                'sale_line_id': sale_line_id.id,
                'procurement_group_id': procurement.group_id.id,
            })

            # Cria OPs filhas se o método existir na OP
            if hasattr(mo, '_create_child_productions_from_cut_plan'):
                mo._create_child_productions_from_cut_plan()
            else:
                _logger.warning(f"⚠️ Método _create_child_productions_from_cut_plan não encontrado na OP {mo.name}.")

        return productions

    def _run_cut_plan_flow(self, procurement):
        """
        Cria um plano de corte a partir de um procurement.
        """
        product = procurement.product_id
        sale_line = procurement.values.get('sale_line_id')
        if not sale_line:
            return

        _logger.info(
            "✂️ Criando Cut Plan | produto=%s | linha=%s",
            product.display_name,
            sale_line_id.id
        )

        self.env['mrp_cut_plan.mrp_cut_plan'].create({
            'sale_id': sale_line_id.order_id.id,
            'sale_line_id': sale_line_id.id,
            'product_id': product.id,
            'blue_qty': procurement.product_qty,
            'blue_bom_template_id': product.bom_ids[:1].id,
            # Assumindo que 'blue_bom_template_id' é um campo em mrp_cut_plan.mrp_cut_plan
            'blue_origin': sale_line_id.order_id.name,
        })
