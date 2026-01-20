from odoo import models, fields, api
from odoo.exceptions import UserError
import logging

_logger = logging.getLogger(__name__)


class StockPicking(models.Model):
    _inherit = "stock.picking"

    custom_block_validate = fields.Boolean(string="Bloquear Validação")
    show_validate = fields.Boolean(string="Exibir Botão de Validação", default=True)

    sending_transfer_id = fields.Many2many(
        "stock.picking",
        "stock_picking_sending_rel",
        "picking_receipt_id",
        "picking_sending_id",
        string="Transferência de Envio"
    )

    branch_receipt_id = fields.Many2many(
        "stock.picking",
        "stock_picking_branch_receipt_rel",
        "picking_sending_id",
        "picking_receipt_id",
        string="Recebimento na Filial"
    )

    branch_return_id = fields.Many2many(
        "stock.picking",
        "stock_picking_branch_return_rel",
        "production_id",
        "return_picking_id",
        string="Retorno da Filial"
    )

    final_receipt_id = fields.Many2many(
        "stock.picking",
        "stock_picking_final_receipt_rel",
        "production_id",
        "final_receipt_picking_id",
        string="Recebimento Final"
    )

    origin_production_id = fields.Many2one("mrp.production", string="Ordem de Produção de Origem")

    branch_mo_id = fields.Many2many(
        "mrp.production",
        "stock_picking_branch_mo_rel",
        "picking_id",
        "production_id",
        string="Ordens de Produção da Filial"
    )

    branch_backorder_id = fields.Many2one("stock.picking", string="Backorder Vinculado")

    customer = fields.Many2one('res.partner', string='Partner', compute="_compute_customer")
    sale_order = fields.Many2one('sale.order', string='Sale Order', compute="_compute_sale_order", store=True)

    def _compute_customer(self):
        """Computa o nome do cliente a partir do partner_id"""
        for picking in self:
            sale_order = picking._get_related_sale_order()
            picking.customer = sale_order.partner_id if sale_order else picking.partner_id

    def debug_picking_sale_info(self):
        """Debug específico para pickings de entrega"""
        for picking in self:
            print(f"=== DEBUG PICKING: {picking.name} ===")
            print(f"Origin: {picking.origin}")
            print(f"Picking Type: {picking.picking_type_code}")
            print(f"Partner: {picking.partner_id.name}")
            print(f"Sale Order (campo): {picking.sale_order.name if picking.sale_order else 'None'}")

            # Buscar pedidos possíveis
            if picking.origin:
                origin_clean = picking.origin.split(' - ')[0]
                possible_orders = env['sale.order'].search([('name', '=', origin_clean)])
                print(f"Pedidos encontrados por origin '{origin_clean}': {len(possible_orders)}")
                for order in possible_orders:
                    print(f"  • {order.name} - {order.partner_id.name}")

            print("Movimentos:")
            for move in picking.move_ids_without_package:
                print(f"  • {move.product_id.display_name} -> '{move.name}'")

    # def _compute_sale_order(self):
    #     """Computa o pedido de venda a partir da origem ou da OP de produção"""
    #     for picking in self:
    #         sale_order = False
    #
    #         # 1. Busca pelo origin_production_id
    #         if picking.origin_production_id and picking.origin_production_id.sale_order_id:
    #             sale_order = picking.origin_production_id.sale_order_id
    #
    #         # 2. Busca pelo nome do pedido no origin
    #         elif picking.origin:
    #             origin_clean = picking.origin.split(' - ')[0]
    #             sale_order = self.env['sale.order'].search([
    #                 ('name', '=', origin_clean)
    #             ], limit=1)
    #
    #         # 3. Busca pelo partner_id se for um picking de cliente
    #         elif picking.partner_id and picking.picking_type_code == 'outgoing':
    #             sale_order = self.env['sale.order'].search([
    #                 ('partner_id', '=', picking.partner_id.id),
    #                 ('state', 'in', ['sale', 'done'])
    #             ], order='date_order desc', limit=1)
    #
    #         picking.sale_order = sale_order

    def _get_related_sale_order(self):
        """Obtém o pedido de venda relacionado ao picking"""
        # 1. Tenta buscar pela OP de produção
        if self.origin_production_id and self.origin_production_id.sale_order_id:
            return self.origin_production_id.sale_order_id

        # 2. Se não encontrou, tenta buscar pelo nome na origem
        elif self.origin:
            origin_clean = self.origin.split(' - ')[0]
            return self.env['sale.order'].search([
                ('name', '=', origin_clean)
            ], limit=1)

        return False

    def _link_sale_order_lines_to_moves(self):
        """Estabelece o relacionamento entre sale.order.line e stock.move"""
        for picking in self:
            _logger.warning(f"🔗 VINCULANDO LINHAS PEDIDO: {picking.name}")

            sale_order = False

            # MÉTODO 1: Busca através do campo sale_order
            if picking.sale_order:
                sale_order = picking.sale_order
                _logger.warning(f"   📦 Pedido encontrado via sale_order: {sale_order.name}")

            # MÉTODO 2: Busca através do origin_production_id
            elif picking.origin_production_id and picking.origin_production_id.sale_order_id:
                sale_order = picking.origin_production_id.sale_order_id
                _logger.warning(f"   📦 Pedido encontrado via OP: {sale_order.name}")

            # MÉTODO 3: Busca através do origin (nome do pedido)
            elif picking.origin:
                origin_clean = picking.origin.split(' - ')[0]
                _logger.warning(f"   🔍 Buscando por origin: {origin_clean}")

                sale_order = self.env['sale.order'].search([
                    ('name', '=', origin_clean)
                ], limit=1)

                if sale_order:
                    _logger.warning(f"   📦 Pedido encontrado via origin: {sale_order.name}")

            if sale_order:
                _logger.warning(f"   📋 Linhas do pedido {sale_order.name}:")
                for line in sale_order.order_line:
                    _logger.warning(f"      • {line.product_id.display_name} -> '{line.name}'")

                for move in picking.move_ids_without_package:
                    _logger.warning(f"   🔍 Buscando linha para movimento: {move.product_id.display_name}")

                    # Busca a linha do pedido para este produto específico
                    order_line = sale_order.order_line.filtered(
                        lambda l: l.product_id.id == move.product_id.id
                    )

                    if order_line:
                        move.sale_order_line_id = order_line[0]
                        _logger.warning(f"   ✅ VINCULADO: {move.product_id.display_name} -> '{order_line[0].name}'")
                    else:
                        _logger.warning(f"   ❌ NENHUMA LINHA ENCONTRADA para: {move.product_id.display_name}")
            else:
                _logger.warning(f"   ⚠️ NENHUM PEDIDO ENCONTRADO para este picking")





    def _get_sale_order_description(self, production):
        """Obtém a descrição EXATA do pedido de venda, se disponível"""
        # Tenta encontrar a descrição do pedido de venda vinculado
        if production.sale_id:
            # Busca a linha do pedido de venda para este produto
            order_line = production.sale_id.order_line.filtered(
                lambda l: l.product_id == production.product_id
            )
            if order_line:
                # Retorna a descrição EXATA da linha do pedido
                return order_line[0].name

        # Fallback: usa a descrição padrão do produto
        return production.product_id.get_product_multiline_description_sale()


    def button_validate(self):
        """Button validate com forçamento de descrição"""

        # Bloqueio: impedir validação se houver envio pendente
        for picking in self:
            if (picking.picking_type_code == 'incoming'
                    and picking.sending_transfer_id
                    and picking.custom_block_validate):
                pending_sendings = picking.sending_transfer_id.filtered(lambda p: p.state != 'done')
                if pending_sendings:
                    raise UserError(
                        "Não é possível validar este recebimento enquanto o envio filial → matriz não estiver concluído."
                    )

        # Preserva comportamento de outros módulos
        result = super(StockPicking, self).button_validate()
        # Mantem o sale_id
        for picking in self:
            if picking.origin_production_id and picking.origin_production_id.sale_id:
                picking.write({
                    'sale_id': picking.origin_production_id.sale_id.id,
                })
        # RECEBIMENTO FILIAL!!!!
        for picking in self:
            if (picking.picking_type_code == 'outgoing'
                    and picking.state == 'done'
                    and picking.origin_production_id
                    and not picking.branch_receipt_id
                    and 'Backorder' not in (picking.origin or '')):
                try:
                    origin_mo = picking.origin_production_id
                    warehouse = origin_mo.branch_location_id and origin_mo.branch_location_id.warehouse_id
                    sale_order = origin_mo.sale_id.id
                    if not warehouse:
                        continue

                    picking_type = self.env['stock.picking.type'].search([
                        ('warehouse_id', '=', warehouse.id),
                        ('code', '=', 'incoming')
                    ], limit=1)

                    if not picking_type:
                        continue

                    qty_sent = sum(
                        move.quantity_done for move in picking.move_ids_without_package
                        if move.product_id == origin_mo.product_id
                    )

                    if qty_sent <= 0:
                        continue
                    product_description = self._get_sale_order_description(origin_mo)

                    # PREPARA VALORES - VERSÃO CORRIGIDA
                    receiving_vals = {
                        "picking_type_id": picking_type.id,
                        "location_id": picking.location_dest_id.id,
                        "location_dest_id": origin_mo.branch_location_id.id,
                        "origin": f"{picking.origin} - Recebimento Filial",
                        "move_ids_without_package": [(0, 0, {
                            "name": origin_mo.product_id.get_product_multiline_description_sale(),
                            "product_id": origin_mo.product_id.id,
                            "product_uom_qty": qty_sent,
                            "product_uom": origin_mo.product_uom_id.id,
                            "location_id": picking.location_dest_id.id,
                            "location_dest_id": origin_mo.branch_location_id.id,
                            "description_picking": product_description,
                        })],
                        "custom_block_validate": False,
                        "show_validate": True,
                        "origin_production_id": origin_mo.id,
                        "sending_transfer_id": [(4, picking.id)],
                        "sale_id": sale_order,
                        "partner_id": picking.partner_id.id if picking.partner_id else False,

                    }



                    receiving = self.env['stock.picking'].with_context(
                        bypass_branch_creation=True
                    ).create(receiving_vals)

                    receiving.with_context(bypass_branch_creation=True).action_confirm()
                    try:
                        receiving.with_context(bypass_branch_creation=True).state = 'assigned'
                    except Exception:
                        receiving.with_context(bypass_branch_creation=True).write({'state': 'assigned'})

                    picking.write({'branch_receipt_id': [(4, receiving.id)]})
                    origin_mo.write({'branch_receipt_id': [(4, receiving.id)]})

                    _logger.warning(f"✅ RECEBIMENTO criado: {receiving.name} ({qty_sent})")

                except Exception as e:
                    _logger.error(f"❌ Erro ao criar recebimento para envio {picking.name}: {str(e)}")
                    import traceback
                    _logger.error(traceback.format_exc())

            # CONDIÇÃO 2: RECEBIMENTO validado -> criar OP filial
            elif (
                    picking.picking_type_code == 'incoming'
                    and picking.state == 'done'
                    and picking.origin_production_id
                    and not picking.branch_mo_id
                    and not picking.final_receipt_id
                    and 'Recebimento Final' not in (picking.origin or '')
            ):
                _logger.warning(f"🎯 CRIANDO OP FILIAL PARA: {picking.name}")
                try:
                    if self.env.context.get('bypass_branch_creation'):
                        _logger.warning(f"⛔ OP DA FILIAL NÃO SERÁ CRIADA (bypass_branch_creation=True)")
                        continue

                    if not picking.sending_transfer_id:
                        _logger.warning(f"⏸️ Recebimento {picking.name} ignorado — nenhum envio vinculado.")
                        continue

                    if any(s.state != 'done' for s in picking.sending_transfer_id):
                        _logger.warning(f"⏸️ Recebimento {picking.name} ignorado — envio não concluído.")
                        continue

                    origin_mo = picking.origin_production_id
                    sale_order = origin_mo.sale_id.id

                    # Verifica quantidade recebida
                    qty_received = sum(
                        move.quantity_done for move in picking.move_ids_without_package
                        if move.product_id == origin_mo.product_id
                    )

                    if qty_received <= 0:
                        _logger.warning(f"⏸️ Recebimento {picking.name} sem qty recebida para produto da OP.")
                        continue

                    _logger.warning(f"🎯 CHAMANDO _create_mo_from_receipt para OP {origin_mo.name}")

                    # Chama o método da OP matriz para criar OP filial
                    branch_mo = origin_mo._create_mo_from_receipt(qty=qty_received, receipt_picking=picking)

                    if branch_mo:
                        picking.write({'branch_mo_id': [(4, branch_mo.id)],'sale_id': sale_order,
                        'partner_id': picking.partner_id.id if picking.partner_id else False})

                        _logger.warning(f"✅ OP filial criada: {branch_mo.name} ({qty_received})")
                        origin_mo._compute_message_state()
                    else:
                        _logger.warning(f"❌ _create_mo_from_receipt retornou False")

                except Exception as e:
                    _logger.error(f"❌ Erro ao criar OP filial para recebimento {picking.name}: {str(e)}")
                    import traceback
                    _logger.error(traceback.format_exc())

        return result

    def _action_done(self):
        """Override para processar backorders automaticamente após validação"""
        result = super(StockPicking, self)._action_done()

        for picking in self:
            if picking.backorder_ids:
                for backorder in picking.backorder_ids:
                    if (backorder.picking_type_code == 'outgoing'
                            and backorder.origin_production_id
                            and backorder.state in ['assigned', 'confirmed']):
                        try:
                            self._process_backorder_receipt(backorder)
                        except Exception as e:
                            _logger.error(f"Erro ao processar backorder {backorder.name}: {str(e)}")

        return result

    def _process_backorder_receipt(self, backorder_picking):
        """Cria recebimento na filial para backorders de envio"""
        origin_mo = backorder_picking.origin_production_id
        if not origin_mo or not origin_mo.branch_location_id:
            return

        warehouse = origin_mo.branch_location_id.warehouse_id
        if not warehouse:
            return

        picking_type = self.env['stock.picking.type'].search([
            ('warehouse_id', '=', warehouse.id),
            ('code', '=', 'incoming')
        ], limit=1)

        if not picking_type:
            return

        qty_backorder = sum(
            move.product_uom_qty for move in backorder_picking.move_ids_without_package
            if move.product_id == origin_mo.product_id
        )

        if qty_backorder <= 0:
            return

        existing_receipt = backorder_picking.branch_receipt_id.filtered(
            lambda r: r.state not in ['done', 'cancel']
        )

        if existing_receipt:
            return

        product_description = self._get_sale_order_description(origin_mo)

        receiving_vals = {
            "picking_type_id": picking_type.id,
            "location_id": backorder_picking.location_dest_id.id,
            "location_dest_id": origin_mo.branch_location_id.id,
            "origin": f"{backorder_picking.origin} - Backorder Recebimento Filial",
            "move_ids_without_package": [(0, 0, {
                "name": f"Recebimento Backorder {origin_mo.product_id.display_name}",
                "product_id": origin_mo.product_id.id,
                "product_uom_qty": qty_backorder,
                "product_uom": origin_mo.product_uom_id.id,
                "location_id": backorder_picking.location_dest_id.id,
                "location_dest_id": origin_mo.branch_location_id.id,
                "description_picking": product_description,
            })],
            "custom_block_validate": True,
            "show_validate": False,
            "origin_production_id": origin_mo.id,
            "sending_transfer_id": [(4, backorder_picking.id)],
            # ✅ CORREÇÃO: Usar sale_id do backorder_picking
            "sale_id": backorder_picking.sale_id.id if backorder_picking.sale_id else False,
            # ✅ CORREÇÃO: Usar partner_id do backorder_picking
            "partner_id": backorder_picking.partner_id.id if backorder_picking.partner_id else False
        }

        receiving = self.env['stock.picking'].with_context(
            bypass_branch_creation=True
        ).create(receiving_vals)

        receiving.with_context(bypass_branch_creation=True).action_confirm()
        try:
            receiving.with_context(bypass_branch_creation=True).state = 'assigned'
        except Exception:
            receiving.with_context(bypass_branch_creation=True).write({'state': 'assigned'})

        backorder_picking.write({'branch_receipt_id': [(4, receiving.id)]})
        origin_mo.write({'branch_receipt_id': [(4, receiving.id)]})

        return receiving


    @api.model
    def create(self, vals):
        """Override do create para estabelecer relacionamentos"""
        picking = super(StockPicking, self).create(vals)

        # Estabelece relacionamentos e aplica descrições
        picking._link_sale_order_lines_to_moves()


        return picking

    def write(self, vals):
        """Override do write para manter relacionamentos atualizados"""
        result = super(StockPicking, self).write(vals)

        # Se está alterando campos relevantes, atualiza relacionamentos
        if any(field in vals for field in ['origin_production_id', 'origin', 'move_ids_without_package']):
            self._link_sale_order_lines_to_moves()


        return result

    def action_assign(self):
        """Ação de assign com aplicação de descrições"""

        return super(StockPicking, self).action_assign()


class StockMove(models.Model):
    _inherit = 'stock.move'

    sale_order_line_id = fields.Many2one(
        'sale.order.line',
        string='Linha do Pedido de Venda',
        help='Relacionamento direto com a linha do pedido de venda'
    )

    sale_line_description = fields.Char(
        string='Descrição do Pedido',
        compute='_compute_sale_line_description',
        store=True
    )

    planned_uom_qty = fields.Float(
        string='Planned Quantity',
        compute='_compute_planned_uom_qty',
        store=True
    )

    @api.depends('product_uom_qty')
    def _compute_planned_uom_qty(self):
        for move in self:
            move.planned_uom_qty = move.product_uom_qty

    @api.depends('picking_id.sale_id', 'picking_id.origin', 'product_id')
    def _compute_sale_line_description(self):
        """Computa a descrição buscando diretamente no pedido de venda do picking - VERSÃO AGUESSIVA"""
        for move in self:
            _logger.info(f"🔍 COMPUTANDO DESCRIÇÃO PARA MOVIMENTO: {move.id}")
            _logger.info(f"   • Produto: {move.product_id.display_name}")
            _logger.info(f"   • Picking: {move.picking_id.name if move.picking_id else 'None'}")

            sale_line_description = move.product_id.display_name  # Fallback

            # Busca em MÚLTIPLAS fontes
            sale_order = False

            # 1. Busca através do sale_order do picking
            if move.picking_id and move.picking_id.sale_order:
                sale_order = move.picking_id.sale_order
                _logger.info(f"   📦 Pedido encontrado via sale_order: {sale_order.name}")

            # 2. Busca através do origin do picking (nome do pedido)
            elif move.picking_id and move.picking_id.origin:
                origin_clean = move.picking_id.origin.split(' - ')[0]
                _logger.info(f"   🔍 Buscando por origin: {origin_clean}")

                sale_order = self.env['sale.order'].search([
                    ('name', '=', origin_clean)
                ], limit=1)

                if sale_order:
                    _logger.info(f"   📦 Pedido encontrado via origin: {sale_order.name}")

            # 3. Busca através do group_id (procurement group)
            elif move.group_id:
                sale_order = self.env['sale.order'].search([
                    ('procurement_group_id', '=', move.group_id.id)
                ], limit=1)

                if sale_order:
                    _logger.info(f"   📦 Pedido encontrado via procurement group: {sale_order.name}")

            # Se encontrou o pedido, busca a descrição exata
            if sale_order:
                order_line = sale_order.order_line.filtered(
                    lambda l: l.product_id.id == move.product_id.id
                )

                if order_line:
                    sale_line_description = order_line[0].name
                    _logger.info(f"   ✅ DESCRIÇÃO ENCONTRADA: '{order_line[0].name}'")

                    # ⚠️ ATUALIZAÇÃO AGUESSIVA: Força a atualização do campo name
                    if move.name != order_line[0].name:
                        move.name = order_line[0].name
                        _logger.info(f"   🔄 Campo 'name' atualizado para: '{order_line[0].name}'")

                    # Atualiza o relacionamento
                    move.sale_order_line_id = order_line[0]
                else:
                    _logger.warning(f"   ❌ PRODUTO NÃO ENCONTRADO NO PEDIDO: {move.product_id.display_name}")

            move.sale_line_description = sale_line_description

    def action_force_update_description(self):
        """Ação manual para forçar atualização da descrição"""
        for move in self:
            # Recomputa a descrição
            move._compute_sale_line_description()

            # Força a escrita se necessário
            if move.sale_order_line_id and move.name != move.sale_order_line_id.name:
                move.name = move.sale_order_line_id.name

        return True

    @api.model
    def create(self, vals):
        """Override do create para vincular linha do pedido automaticamente"""
        move = super(StockMove, self).create(vals)

        # Se o movimento tem um picking, tenta vincular
        if move.picking_id:
            move.picking_id._link_sale_order_lines_to_moves()

        return move

    def write(self, vals):
        """Override do write para manter relacionamentos"""
        result = super(StockMove, self).write(vals)

        # Se está mudando o picking, tenta vincular
        if 'picking_id' in vals:
            for move in self:
                if move.picking_id:
                    move.picking_id._link_sale_order_lines_to_moves()

        return result

class StockMoveLine(models.Model):
    _inherit = 'stock.move.line'

    sale_line_description = fields.Char(
        string='Descrição do Pedido',
        compute='_compute_sale_line_description',
        store=True
    )

    @api.depends('move_id.sale_order_line_id', 'move_id.sale_order_line_id.name')
    def _compute_sale_line_description(self):
        """Computa a descrição baseada no movimento pai"""
        for move_line in self:
            if move_line.move_id.sale_order_line_id:
                move_line.sale_line_description = move_line.move_id.sale_order_line_id.name
            else:
                move_line.sale_line_description = move_line.product_id.display_name