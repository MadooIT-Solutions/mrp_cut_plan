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

    def _compute_customer(self):
        """Computa o nome do cliente a partir do partner_id"""
        for picking in self:
            sale_order = picking._get_related_sale_order()
            picking.customer = sale_order.partner_id if sale_order else picking.partner_id




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
        # compute='_compute_sale_line_description',
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