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

    # -------------------------------------------------------------------------
    # Validação de picking
    # -------------------------------------------------------------------------
    def button_validate(self):
        for picking in self:
            # Bloqueio 1: não permitir validar recebimento na filial se envio da matriz não concluído
            if (picking.picking_type_code == 'incoming' and
                    picking.sending_transfer_id and
                    picking.custom_block_validate):
                pending_sendings = picking.sending_transfer_id.filtered(lambda p: p.state != 'done')
                if pending_sendings:
                    raise UserError(
                        "Não é possível validar este recebimento enquanto o envio matriz → filial não estiver concluído."
                    )

        # Executa validação padrão do Odoo
        res = super(StockPicking, self).button_validate()

        # PROCESSAMENTO APÓS VALIDAÇÃO
        for picking in self:
            _logger.info(f"🔍 Pós-validação: {picking.name} | Tipo={picking.picking_type_code} | State={picking.state}")

            # 1️⃣ Após validação de envio (matriz → filial): libera recebimento na filial
            if (picking.picking_type_code == 'outgoing' and
                    picking.state == 'done' and
                    picking.branch_receipt_id):

                for receipt in picking.branch_receipt_id:
                    receipt.write({
                        'custom_block_validate': False,
                        'show_validate': True
                    })
                    receipt.message_post(
                        body=f"✅ Recebimento liberado: envio {picking.name} concluído."
                    )
                    _logger.info(f"✅ Recebimento {receipt.name} liberado após envio {picking.name}")

            # 2️⃣ Após validação de recebimento na FILIAL: criar OP filial
            # ⚠️ ADICIONAR VERIFICAÇÃO PARA EVITAR RECEBIMENTOS FINAIS
            if (picking.picking_type_code == 'incoming' and
                    picking.state == 'done' and
                    picking.origin_production_id and
                    not picking.branch_mo_id and
                    not picking.final_receipt_id and  # ⚠️ EVITA RECEBIMENTOS FINAIS
                    'Recebimento Final' not in picking.origin):  # ⚠️ VERIFICA A ORIGEM

                _logger.info(f"✅ Recebimento na filial confirmado ({picking.name}), criando OP filial...")

                try:
                    # Busca a OP matriz através do origin_production_id
                    origin_mo = picking.origin_production_id
                    if not origin_mo:
                        _logger.warning(f"⚠️ Recebimento {picking.name} sem OP matriz vinculada")
                        continue

                    # Calcula quantidade recebida
                    qty_received = sum(
                        move.quantity_done for move in picking.move_ids_without_package
                        if move.product_id == origin_mo.product_id
                    )

                    if qty_received > 0:
                        # Cria OP filial usando o método da OP matriz
                        branch_mo = origin_mo._create_mo_from_receipt(
                            qty=qty_received,
                            receipt_picking=picking
                        )

                        if branch_mo:
                            # Vincula a OP filial ao recebimento
                            picking.write({
                                'branch_mo_id': [(4, branch_mo.id)]
                            })
                            _logger.info(f"✅ OP filial criada: {branch_mo.name} para {qty_received} unidades")

                            # Atualiza estado da OP matriz
                            origin_mo._compute_message_state()
                except Exception as e:
                    _logger.error(f"❌ Erro ao criar OP filial para {picking.name}: {str(e)}")

            # 3️⃣ Após validação de OP FILIAL: criar envio de retorno
            if (picking.picking_type_code == 'mrp_operation' and
                    picking.state == 'done' and
                    picking.origin_production_id):

                branch_mo = picking
                origin_mo = branch_mo.origin_production_id

                _logger.info(f"✅ OP filial concluída ({branch_mo.name}), criando retorno...")

                try:
                    # Verifica se já existe retorno criado
                    if not branch_mo.return_transfer_id:
                        return_picking = branch_mo._create_return_transfer()
                        final_receipt = branch_mo._create_final_receipt(return_picking)

                        # Vincula os pickings
                        branch_mo.write({
                            'return_transfer_id': [(4, return_picking.id)],
                            'final_receipt_id': [(4, final_receipt.id)]
                        })

                        origin_mo.write({
                            'return_transfer_id': [(4, return_picking.id)],
                            'final_receipt_id': [(4, final_receipt.id)]
                        })

                        _logger.info(f"✅ Retorno criado: {return_picking.name}")

                except Exception as e:
                    _logger.error(f"❌ Erro ao criar retorno da filial: {str(e)}")

            # 4️⃣ Após validação de envio da FILIAL: libera recebimento na matriz
            if (picking.picking_type_code == 'outgoing' and
                    picking.state == 'done' and
                    picking.final_receipt_id):

                for final_receipt in picking.final_receipt_id:
                    final_receipt.write({
                        'custom_block_validate': False,
                        'show_validate': True
                    })
                    _logger.info(f"✅ Recebimento final {final_receipt.name} liberado")

            # 5️⃣ Atualiza quantidade total recebida após recebimento final na matriz
            # ⚠️ MODIFICADO: Só atualiza se for um recebimento final válido
            if (picking.picking_type_code == 'incoming' and
                    picking.state == 'done' and
                    picking.origin_production_id and
                    'Recebimento Final' in (picking.origin or '')):
                picking.origin_production_id._compute_total_qty_received()
                _logger.info(f"📦 Quantidade recebida atualizada para OP matriz {picking.origin_production_id.name}")

        return res

    def _process_partial_branch_receipt(self, picking):
        """Processa recebimento na filial - cria/atualiza OP somente se recebimento validado"""
        try:
            # ⚠️ VERIFICA SE É UM RECEBIMENTO FINAL
            if 'Recebimento Final' in (picking.origin or ''):
                _logger.info(f"⏸️ Ignorando processamento: é um recebimento final {picking.name}")
                return

            origin_mo = picking.origin_production_id
            if not origin_mo or not origin_mo.branch_location_id:
                _logger.info("Ignorando processamento parcial: sem origin_mo ou sem branch_location_id.")
                return

            # Garante que o recebimento foi validado e não está bloqueado
            if picking.custom_block_validate or picking.state != 'done':
                _logger.info(f"⏳ Recebimento {picking.name} ainda bloqueado ou não finalizado. Ignorando.")
                return

            # Quantidade recebida do produto da OP
            qty_received = sum(
                move.quantity_done for move in picking.move_ids_without_package
                if move.product_id == origin_mo.product_id and move.quantity_done > 0
            )

            _logger.info(
                f"📦 Recebimento detectado ({picking.name}): {qty_received} x {origin_mo.product_id.display_name}")

            if qty_received <= 0:
                return

            # Verificar se já existe OP filial vinculada (não criar duplicada)
            existing_mos = picking.branch_mo_id.filtered(lambda mo: mo.state not in ['done', 'cancel'])
            if existing_mos:
                mo_to_update = existing_mos[0]
                old_qty = mo_to_update.product_qty
                mo_to_update.write({'product_qty': qty_received})
                mo_to_update._update_moves()
                _logger.info(f"🔄 OP filial atualizada: {mo_to_update.name} ({old_qty} → {qty_received})")
            else:
                branch_mo = origin_mo.sudo()._create_mo_from_receipt(qty_received, picking)
                picking.write({'branch_mo_id': [(4, branch_mo.id)]})
                _logger.info(f"✅ OP filial criada após recebimento: {branch_mo.name} - {qty_received}")

            # Caso haja backorder, cria transferência da matriz para filial
            backorder = self.search([('backorder_id', '=', picking.id), ('state', 'not in', ['done', 'cancel'])],
                                    limit=1)
            qty_backorder = 0.0
            if backorder:
                qty_backorder = sum(move.product_uom_qty for move in backorder.move_ids_without_package if
                                    move.product_id == origin_mo.product_id)

            if qty_backorder > 0:
                existing_transfer = self.search([
                    ('origin', 'ilike', f"{origin_mo.name} - Backorder"),
                    ('state', 'not in', ['done', 'cancel']),
                    ('location_dest_id', '=', origin_mo.branch_location_id.id)
                ], limit=1)
                if not existing_transfer:
                    transfer_picking = origin_mo.sudo()._create_backorder_transfer(qty_backorder)
                    if backorder:
                        backorder.write({
                            'sending_transfer_id': [(4, transfer_picking.id)],
                            'custom_block_validate': True,
                            'show_validate': False,
                        })
                    transfer_picking.write({'branch_receipt_id': [(4, backorder.id)] if backorder else []})
                    _logger.info(f"✅ Transferência de backorder criada: {transfer_picking.name} ({qty_backorder})")

        except Exception as e:
            _logger.error(f"❌ Erro ao processar recebimento na filial: {str(e)}")

    # -------------------------------------------------------------------------
    # _action_done: bloqueio extra
    # -------------------------------------------------------------------------
    def _action_done(self):
        for picking in self:
            if picking.picking_type_code == 'internal' and picking.sending_transfer_id:
                pending = picking.sending_transfer_id.filtered(lambda p: p.state != 'done')
                if pending:
                    raise UserError(
                        "Não é possível validar esta backorder na filial enquanto a backorder correspondente da matriz não for concluída."
                    )
        return super(StockPicking, self)._action_done()

    # -------------------------------------------------------------------------
    # Processar backorders após criação (ajustado para não criar OP prematuramente)
    # -------------------------------------------------------------------------
    def _process_backorder_after_creation(self):
        for backorder in self:
            _logger.info(f"🧩 Processando backorder {backorder.name} | tipo={backorder.picking_type_code} | state={backorder.state}")

            # Ignora backorders enquanto bloqueado ou não finalizado
            if backorder.custom_block_validate or backorder.state not in ['done', 'assigned']:
                _logger.info(f"⏸️ Ignorando backorder {backorder.name}: bloqueado ou state={backorder.state}")
                continue

            original_picking = backorder.backorder_id
            if original_picking and getattr(original_picking, 'custom_block_validate', False):
                backorder.custom_block_validate = True

            # Se for backorder de recebimento na filial, apenas cria transferência se necessário.
            if (
                backorder.picking_type_code == 'internal'
                and backorder.origin_production_id
                and backorder.location_dest_id.usage == 'internal'
                and backorder.sending_transfer_id
                and not backorder.custom_block_validate
                and backorder.state == 'done'
            ):
                origin_mo = backorder.origin_production_id
                if origin_mo and origin_mo.branch_location_id:
                    try:
                        qty_backorder = sum(move.product_uom_qty for move in backorder.move_ids_without_package if move.product_id == origin_mo.product_id)
                        if qty_backorder > 0:
                            existing_transfer = self.search([
                                ('origin', 'ilike', f"{origin_mo.name} - Backorder"),
                                ('state', 'not in', ['done', 'cancel']),
                                ('location_dest_id', '=', origin_mo.branch_location_id.id)
                            ], limit=1)
                            if not existing_transfer:
                                transfer_picking = origin_mo.sudo()._create_backorder_transfer(qty_backorder)
                                backorder.write({
                                    'sending_transfer_id': [(4, transfer_picking.id)],
                                    'custom_block_validate': True,
                                    'show_validate': False,
                                })
                                transfer_picking.write({'branch_receipt_id': [(4, backorder.id)]})
                                _logger.info(f"✅ Transferência de backorder criada: {transfer_picking.name} ({qty_backorder})")
                            else:
                                _logger.info(f"⚠️ Transferência de backorder já existe: {existing_transfer.name}")
                    except Exception as e:
                        _logger.error(f"❌ Erro ao criar transferência de backorder: {str(e)}")

            # Se for backorder da matriz -> herda bloqueios mas não cria OP
            elif backorder.picking_type_code == 'internal' and backorder.branch_receipt_id:
                pending = backorder.branch_receipt_id.filtered(lambda p: p.state not in ['done', 'cancel'])
                if pending:
                    backorder.custom_block_validate = True
                    backorder.message_post(body="❌ Backorder da filial bloqueada: aguarde a conclusão da matriz.")

            if backorder.custom_block_validate:
                try:
                    backorder.action_confirm()
                    backorder.action_assign()
                except Exception:
                    backorder.write({'state': 'assigned'})

    # -------------------------------------------------------------------------
    # Override _create_backorder para processamento automático
    # -------------------------------------------------------------------------
    def _create_backorder(self):
        backorders = super(StockPicking, self)._create_backorder()
        if backorders:
            backorders._process_backorder_after_creation()
        return backorders

    def action_assign(self):
        res = super(StockPicking, self).action_assign()

        for picking in self:
            # Não criar OP aqui — criação só deve ocorrer após RECEBIMENTO validado (button_validate)
            _logger.debug(
                f"action_assign: {picking.name} | state={picking.state} | block={picking.custom_block_validate} | sending={bool(picking.sending_transfer_id)}"
            )

        return res
