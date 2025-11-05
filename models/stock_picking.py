from odoo import models, fields, api
from odoo.exceptions import UserError
import logging

_logger = logging.getLogger(__name__)


class StockPicking(models.Model):
    _inherit = "stock.picking"

    custom_block_validate = fields.Boolean(string="Bloquear Validação")
    show_validate = fields.Boolean(string="Exibir Botão de Validação", default=True)

    # ✅ CORRIGIDO: Relações Many2many com nomes de colunas válidos
    sending_transfer_id = fields.Many2many(
        "stock.picking",
        "stock_picking_sending_rel",
        "picking_receipt_id",  # Este picking (recebimento)
        "picking_sending_id",  # Picking de envio relacionado
        string="Transferência de Envio"
    )

    branch_receipt_id = fields.Many2many(
        "stock.picking",
        "stock_picking_branch_receipt_rel",
        "picking_sending_id",  # Este picking (envio)
        "picking_receipt_id",  # Picking de recebimento na filial
        string="Recebimento na Filial"
    )

    # ✅ CORRIGIDO: Para múltiplos retornos da filial
    branch_return_id = fields.Many2many(
        "stock.picking",
        "stock_picking_branch_return_rel",
        "production_id",  # OP relacionada
        "return_picking_id",  # Picking de retorno
        string="Retorno da Filial"
    )

    # ✅ CORRIGIDO: Para múltiplos recebimentos finais
    final_receipt_id = fields.Many2many(
        "stock.picking",
        "stock_picking_final_receipt_rel",
        "production_id",  # OP relacionada
        "final_receipt_picking_id",  # Picking de recebimento final
        string="Recebimento Final"
    )

    origin_production_id = fields.Many2one("mrp.production", string="Ordem de Produção de Origem")

    # ✅ CORRIGIDO: Many2many para múltiplas OPs filiais
    branch_mo_id = fields.Many2many(
        "mrp.production",
        "stock_picking_branch_mo_rel",
        "picking_id",  # Este picking
        "production_id",  # OP filial relacionada
        string="Ordens de Produção da Filial"
    )

    branch_backorder_id = fields.Many2one("stock.picking", string="Backorder Vinculado")
    is_branch_flow = fields.Boolean(
        string="É Fluxo Filial",
        compute='_compute_is_branch_flow',
        store=False
    )

    is_mold_product = fields.Boolean(
        string="É Produto Molde",
        compute='_compute_is_mold_product',
        store=False
    )

    # -------------------------------------------------------------------------
    # Validação de picking - MANTIDO
    # -------------------------------------------------------------------------
    def button_validate(self):
        for picking in self:
            # Bloqueio: não permitir validar filial se envio da matriz não concluído
            if picking.custom_block_validate and picking.sending_transfer_id:
                pending = picking.sending_transfer_id.filtered(lambda p: p.state != 'done')
                if pending:
                    raise UserError(
                        "Não é possível validar este recebimento enquanto o envio matriz → filial não estiver concluído."
                    )

            # Bloqueio: não permitir validar recebimento na matriz se envio da filial ainda não foi concluído
            if (picking.picking_type_code == 'incoming' and picking.origin_production_id
                    and picking.origin_production_id.return_transfer_id):
                pending_returns = picking.origin_production_id.return_transfer_id.filtered(lambda r: r.state != 'done')
                if pending_returns:
                    raise UserError(
                        "Não é possível validar o recebimento na matriz enquanto o envio da filial ainda não estiver concluído."
                    )

        res = super(StockPicking, self).button_validate()

        # Processar após validação
        for picking in self:
            # Após validação da matriz, libera filial
            if picking.picking_type_code == 'internal' and picking.state == 'done':
                for receipt in picking.branch_receipt_id:
                    receipt.write({'custom_block_validate': False, 'show_validate': True})
                    receipt.message_post(
                        body=f"✅ Recebimento liberado: envio {picking.name} concluído."
                    )

            # Após validação do recebimento final, verificar se pode concluir OP matriz
            if picking.picking_type_code == 'incoming' and picking.state == 'done':
                origin_mo = picking.origin_production_id
                if origin_mo and origin_mo.branch_location_id:
                    # Verificar se quantidade total recebida é suficiente
                    if origin_mo.total_qty_received >= origin_mo.product_qty:
                        origin_mo.message_post(
                            body=f"✅ Quantidade total recebida ({origin_mo.total_qty_received}) atingiu a quantidade planejada ({origin_mo.product_qty}). "
                                 f"OP pode ser concluída."
                        )

            # Se é um recebimento na filial que foi parcialmente validado (criou backorder)
            if (picking.picking_type_code == 'internal' and picking.state == 'done' and
                    picking.origin_production_id and picking.location_dest_id.usage == 'internal'):
                self._process_partial_branch_receipt(picking)

            # Atualiza quantidade total recebida na OP matriz após recebimento final
            if picking.picking_type_code == 'incoming' and picking.state == 'done' and picking.origin_production_id:
                picking.origin_production_id._compute_total_qty_received()

        return res

    def _process_partial_branch_receipt(self, picking):
        """Processa recebimento parcial na filial - cria transferência e OP para quantidade recebida"""
        try:
            origin_mo = picking.origin_production_id
            if not origin_mo or not origin_mo.branch_location_id:
                return

            # Calcular quantidade recebida (feita) - usar o produto da OP
            qty_received = 0
            for move in picking.move_ids_without_package:
                if move.product_id == origin_mo.product_id and move.quantity_done > 0:
                    qty_received += move.quantity_done

            _logger.info(
                f"📦 Recebimento detectado: {qty_received} recebido do produto {origin_mo.product_id.display_name}")

            # Encontrar o backorder criado para este picking
            backorder = self.search([
                ('backorder_id', '=', picking.id),
                ('state', 'not in', ['done', 'cancel'])
            ], limit=1)

            if backorder:
                # Calcular quantidade faltante (no backorder)
                qty_backorder = 0
                for move in backorder.move_ids_without_package:
                    if move.product_id == origin_mo.product_id:
                        qty_backorder += move.product_uom_qty

                _logger.info(f"📦 Recebimento parcial: {qty_received} recebido, {qty_backorder} em backorder")

                # 1. SEMPRE criar OP na filial para quantidade RECEBIDA (mesmo que já exista)
                if qty_received > 0:
                    # ✅ ATUALIZADO: Agora verifica se já existe alguma OP vinculada
                    existing_mos = picking.branch_mo_id.filtered(lambda mo: mo.state not in ['done', 'cancel'])
                    if existing_mos:
                        # Atualizar quantidade da OP existente (pega a primeira não concluída)
                        mo_to_update = existing_mos[0]
                        old_qty = mo_to_update.product_qty
                        mo_to_update.write({'product_qty': qty_received})
                        mo_to_update._update_moves()
                        _logger.info(
                            f"🔄 OP filial atualizada: {mo_to_update.name} - {old_qty} → {qty_received}")
                    else:
                        # Criar nova OP
                        branch_mo = origin_mo.sudo()._create_mo_from_receipt(qty_received, picking)
                        # ✅ ATUALIZADO: Adiciona à relação Many2many
                        picking.write({'branch_mo_id': [(4, branch_mo.id)]})
                        _logger.info(f"✅ OP filial criada para quantidade recebida: {branch_mo.name} - {qty_received}")

                # 2. Criar transferência da matriz para quantidade FALTANTE (backorder)
                if qty_backorder > 0:
                    # Verificar se já existe transferência para este backorder
                    existing_transfer = self.search([
                        ('origin', 'ilike', f"{origin_mo.name} - Backorder"),
                        ('state', 'not in', ['done', 'cancel']),
                        ('location_dest_id', '=', origin_mo.branch_location_id.id)
                    ], limit=1)

                    if not existing_transfer:
                        transfer_picking = origin_mo.sudo()._create_backorder_transfer(qty_backorder)
                        # Vincular o backorder à transferência criada
                        backorder.write({
                            'sending_transfer_id': [(4, transfer_picking.id)],
                            'custom_block_validate': True,
                            'show_validate': False,
                        })
                        transfer_picking.write({
                            'branch_receipt_id': [(4, backorder.id)]
                        })
                        _logger.info(f"✅ Transferência de backorder criada: {transfer_picking.name} - {qty_backorder}")
                    else:
                        _logger.info(f"⚠️ Transferência de backorder já existe: {existing_transfer.name}")

            # Caso não tenha backorder mas tenha quantidade recebida (recebimento completo)
            elif qty_received > 0 and not picking.branch_mo_id:
                # Criar OP para quantidade recebida completa
                branch_mo = origin_mo.sudo()._create_mo_from_receipt(qty_received, picking)
                # ✅ ATUALIZADO: Adiciona à relação Many2many
                picking.write({'branch_mo_id': [(4, branch_mo.id)]})
                _logger.info(f"✅ OP filial criada para recebimento completo: {branch_mo.name} - {qty_received}")

        except Exception as e:
            _logger.error(f"❌ Erro ao processar recebimento na filial: {str(e)}")
            # Não levantar exceção para não bloquear a validação do picking

    # -------------------------------------------------------------------------
    # ✅ MANTIDO: _action_done para bloqueio extra
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
    # ✅ MANTIDO: processar backorders após criação
    # -------------------------------------------------------------------------
    def _process_backorder_after_creation(self):
        """Processa backorders após sua criação - ESSENCIAL para múltiplas OPs"""
        for backorder in self:
            # Herda flag de bloqueio do original
            original_picking = backorder.backorder_id
            if original_picking and getattr(original_picking, 'custom_block_validate', False):
                backorder.custom_block_validate = True

            # Se backorder é um recebimento na filial
            if (backorder.picking_type_code == 'internal' and
                    backorder.origin_production_id and
                    backorder.location_dest_id.usage == 'internal'):

                origin_mo = backorder.origin_production_id
                if origin_mo and origin_mo.branch_location_id:
                    try:
                        # Calcular quantidade faltante no backorder
                        qty_backorder = sum(move.product_uom_qty for move in backorder.move_ids_without_package
                                            if move.product_id == origin_mo.product_id)

                        # Verificar se já existe transferência para este backorder
                        existing_transfer = self.search([
                            ('origin', 'ilike', f"{origin_mo.name} - Backorder"),
                            ('state', 'not in', ['done', 'cancel']),
                            ('location_dest_id', '=', origin_mo.branch_location_id.id)
                        ], limit=1)

                        if not existing_transfer and qty_backorder > 0:
                            # Criar transferência da matriz para filial com quantidade faltante
                            transfer_picking = origin_mo.sudo()._create_backorder_transfer(qty_backorder)

                            # Vincular o backorder à transferência criada
                            backorder.write({
                                'sending_transfer_id': [(4, transfer_picking.id)],
                                'custom_block_validate': True,
                                'show_validate': False,
                            })
                            transfer_picking.write({
                                'branch_receipt_id': [(4, backorder.id)]
                            })

                            _logger.info(
                                f"✅ Transferência de backorder criada: {transfer_picking.name} para quantidade {qty_backorder}")

                    except Exception as e:
                        _logger.error(f"❌ Erro ao criar transferência de backorder: {str(e)}")

            # Se for backorder da matriz, bloqueia filial até conclusão
            if backorder.picking_type_code == 'internal' and backorder.branch_receipt_id:
                pending = backorder.branch_receipt_id.filtered(lambda p: p.state not in ['done', 'cancel'])
                if pending:
                    backorder.custom_block_validate = True
                    backorder.message_post(
                        body="❌ Backorder da filial bloqueada: aguarde a conclusão da matriz."
                    )

            # Forçar status "Para Processar" se bloqueado
            if backorder.custom_block_validate:
                try:
                    backorder.action_confirm()
                    backorder.action_assign()
                except Exception:
                    backorder.write({'state': 'assigned'})

    # -------------------------------------------------------------------------
    # ✅ MANTIDO: Override _create_backorder para processamento automático
    # -------------------------------------------------------------------------
    def _create_backorder(self):
        """Cria backorder e processa fluxo personalizado - ESSENCIAL para múltiplas OPs"""
        backorders = super(StockPicking, self)._create_backorder()

        # Processar backorders criados
        if backorders:
            backorders._process_backorder_after_creation()

        return backorders

    def action_assign(self):
        """Override para criar OP quando backorder for atribuído/liberado"""
        res = super(StockPicking, self).action_assign()

        for picking in self:
            # Se é um backorder de recebimento na filial que foi liberado
            if (picking.picking_type_code == 'internal' and
                    picking.origin_production_id and
                    picking.location_dest_id.usage == 'internal' and
                    picking.state == 'assigned' and
                    not picking.branch_mo_id):

                try:
                    origin_mo = picking.origin_production_id
                    qty = sum(move.product_uom_qty for move in picking.move_ids_without_package
                              if move.product_id == origin_mo.product_id)

                    if qty > 0:
                        branch_mo = origin_mo.sudo()._create_mo_from_receipt(qty, picking)
                        # ✅ ATUALIZADO: Adiciona à relação Many2many
                        picking.write({'branch_mo_id': [(4, branch_mo.id)]})
                        _logger.info(f"✅ OP filial criada ao liberar backorder: {branch_mo.name} - {qty}")

                except Exception as e:
                    _logger.error(f"❌ Erro ao criar OP ao liberar backorder: {str(e)}")

        return res