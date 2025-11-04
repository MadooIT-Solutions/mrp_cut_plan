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
        "stock_picking_sending_rel_cutplan",
        "cutplan_picking_id",
        "cutplan_sending_id",
        string="Transferência de Envio"
    )
    branch_receipt_id = fields.Many2many(
        "stock.picking",
        "stock_picking_receipt_rel_cutplan",
        "cutplan_picking_id",
        "cutplan_receipt_id",
        string="Recebimento na Filial"
    )
    branch_return_id = fields.Many2many(
        "stock.picking",
        "stock_picking_return_rel_cutplan",
        "cutplan_picking_id",
        "cutplan_return_id",
        string="Retorno da Filial"
    )
    final_receipt_id = fields.Many2many(
        "stock.picking",
        "stock_picking_final_receipt_rel_cutplan",
        "cutplan_picking_id",
        "cutplan_final_receipt_id",
        string="Recebimento Final"
    )

    origin_production_id = fields.Many2one("mrp.production", string="Ordem de Produção de Origem")
    branch_mo_id = fields.Many2one("mrp.production", string="Ordem de Produção da Filial")
    branch_backorder_id = fields.Many2one("stock.picking", string="Backorder Vinculado")

    # -------------------------------------------------------------------------
    # Validação de picking - CORREÇÃO DO BLOQUEIO
    # -------------------------------------------------------------------------

    def button_validate(self):
        for picking in self:
            _logger.info(
                f"🔍 Validando picking {picking.name} - Tipo: {picking.picking_type_code} - Estado: {picking.state}")

            # BLOQUEIO 1: não permitir validar recebimento na filial se envio da matriz não concluído
            if (picking.picking_type_code == 'internal' and
                    picking.custom_block_validate and
                    picking.sending_transfer_id):

                pending_sendings = picking.sending_transfer_id.filtered(lambda p: p.state != 'done')
                if pending_sendings:
                    pending_names = ", ".join(pending_sendings.mapped('name'))
                    raise UserError(
                        f"Não é possível validar este recebimento na filial enquanto o envio matriz → filial não estiver concluído.\n"
                        f"Transferências pendentes: {pending_names}"
                    )

            # BLOQUEIO 2: não permitir validar recebimento na matriz se envio da filial não concluído
            if (picking.picking_type_code == 'incoming' and
                    picking.custom_block_validate and
                    picking.sending_transfer_id):

                # Verificar se há envios da filial pendentes
                pending_sendings = picking.sending_transfer_id.filtered(lambda p: p.state != 'done')
                if pending_sendings:
                    pending_names = ", ".join(pending_sendings.mapped('name'))
                    raise UserError(
                        f"Não é possível validar o recebimento na matriz enquanto o envio da filial não estiver concluído.\n"
                        f"Envios pendentes: {pending_names}\n\n"
                        f"Conclua primeiro o envio na filial antes de receber na matriz."
                    )

            # BLOQUEIO 3: não permitir validar recebimento na matriz se processos da filial não concluídos
            if (picking.picking_type_code == 'incoming' and
                    picking.origin_production_id):

                origin_mo = picking.origin_production_id
                _logger.info(f"🔍 Verificando recebimento matriz para OP {origin_mo.name}")

                # Se é OP matriz (não tem origin_production_id)
                if not origin_mo.origin_production_id and origin_mo.branch_location_id:
                    _logger.info(f"🔍 OP {origin_mo.name} é matriz com filial - verificando bloqueios")

                    blockers = []

                    # 1. Verificar se há retornos da filial pendentes
                    if origin_mo.return_transfer_id:
                        pending_returns = origin_mo.return_transfer_id.filtered(
                            lambda r: r.state != 'done'
                        )
                        for ret in pending_returns:
                            blockers.append(f"Envio pendente da filial: {ret.name} ({ret.state})")

                    # 2. Verificar se todas as produções da filial estão concluídas
                    if origin_mo.branch_production_id:
                        pending_productions = origin_mo.branch_production_id.filtered(
                            lambda p: p.state != 'done'
                        )
                        for prod in pending_productions:
                            blockers.append(f"Produção pendente na filial: {prod.name} ({prod.state})")

                    # 3. Verificar se todos os recebimentos na filial estão concluídos
                    if origin_mo.branch_receipt_id:
                        pending_receipts = origin_mo.branch_receipt_id.filtered(
                            lambda r: r.state != 'done'
                        )
                        for rec in pending_receipts:
                            blockers.append(f"Recebimento pendente na filial: {rec.name} ({rec.state})")

                    # Se há bloqueadores, impedir a validação
                    if blockers:
                        blocker_message = "\n".join([f"• {b}" for b in blockers])
                        raise UserError(
                            f"Não é possível validar o recebimento na matriz enquanto existirem processos pendentes na filial:\n\n"
                            f"{blocker_message}\n\n"
                            f"Conclua primeiro todos os processos na filial antes de receber na matriz."
                        )

        res = super(StockPicking, self).button_validate()

        # Processar após validação
        for picking in self:
            # LIBERAR RECEBIMENTO NA MATRIZ APÓS CONCLUSÃO DO ENVIO DA FILIAL
            if (picking.picking_type_code == 'internal' and
                    picking.state == 'done' and
                    picking.branch_receipt_id):

                # Para cada recebimento na matriz vinculado a este envio
                for receipt in picking.branch_receipt_id:
                    if receipt.state not in ['done', 'cancel']:
                        receipt.write({
                            'custom_block_validate': False,  # Libera o recebimento
                            'show_validate': True,  # Mostra botão de validar
                        })
                        receipt.message_post(
                            body=f"✅ Recebimento liberado: envio {picking.name} da filial concluído."
                        )
                        _logger.info(
                            f"✅ Recebimento na matriz {receipt.name} liberado após conclusão do envio {picking.name}")

            # ATUALIZAR CONSUMO APÓS VALIDAÇÃO
            if picking.state == 'done' and picking.origin_production_id:
                # Forçar recálculo do consumo
                picking.origin_production_id._compute_matrix_consumed_qty()
                picking.origin_production_id._compute_branch_consumed_qty()

                # Se for picking de componentes na filial, atualizar consumo da filial
                if (picking.picking_type_code == 'internal' and
                        picking.origin_production_id.origin_production_id):
                    picking.origin_production_id.origin_production_id._compute_branch_consumed_qty()

            # SINCRONIZAR QUANTIDADES APÓS VALIDAÇÃO
            if (picking.state == 'done' and
                    picking.picking_type_code == 'incoming' and
                    picking.origin_production_id):

                origin_mo = picking.origin_production_id

                # Se é recebimento final na matriz, atualizar quantidade da OP matriz
                if not origin_mo.origin_production_id:  # É OP matriz
                    # Recalcular quantidade recebida
                    origin_mo._compute_total_qty_received()

                    # Atualizar quantidade produzindo
                    origin_mo.qty_producing = origin_mo.total_qty_received

                    # Atualizar moves finished
                    for move in origin_mo.move_finished_ids:
                        if move.product_id == origin_mo.product_id:
                            move.write({
                                'quantity_done': origin_mo.total_qty_received
                            })

                    _logger.info(
                        f"✅ Quantidades sincronizadas para OP matriz {origin_mo.name}: {origin_mo.total_qty_received}")

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
                    # Se já existe OP, atualizar quantidade ou criar nova
                    if picking.branch_mo_id:
                        # Atualizar quantidade da OP existente
                        old_qty = picking.branch_mo_id.product_qty
                        picking.branch_mo_id.write({'product_qty': qty_received})
                        picking.branch_mo_id._update_moves()
                        _logger.info(
                            f"🔄 OP filial atualizada: {picking.branch_mo_id.name} - {old_qty} → {qty_received}")
                    else:
                        # Criar nova OP
                        branch_mo = origin_mo.sudo()._create_mo_from_receipt(qty_received, picking)
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
                _logger.info(f"✅ OP filial criada para recebimento completo: {branch_mo.name} - {qty_received}")

        except Exception as e:
            _logger.error(f"❌ Erro ao processar recebimento na filial: {str(e)}")
            # Não levantar exceção para não bloquear a validação do picking

    # -------------------------------------------------------------------------
    # Override _action_done para bloqueio extra
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
    # processar backorders após criação
    # -------------------------------------------------------------------------
    def _process_backorder_after_creation(self):
        """Processa backorders após sua criação """
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

                        # Quando o backorder for recebido na filial, criar OP automaticamente
                        # Monitorar quando este backorder for validado

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
    # Override _create_backorder para versão compatível com Odoo 16
    # -------------------------------------------------------------------------
    def _create_backorder(self):
        """Cria backorder e processa fluxo personalizado"""
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
                        _logger.info(f"✅ OP filial criada ao liberar backorder: {branch_mo.name} - {qty}")

                except Exception as e:
                    _logger.error(f"❌ Erro ao criar OP ao liberar backorder: {str(e)}")

        return res

    # NOVO MÉTODO para verificar status da filial
    def action_check_branch_status(self):
        """Verifica o status da filial para este picking"""
        for picking in self:
            if not picking.origin_production_id:
                raise UserError("Este picking não está vinculado a uma OP.")

            origin_mo = picking.origin_production_id

            if not origin_mo.branch_location_id:
                raise UserError("A OP de origem não possui filial configurada.")

            # Usar o método de verificação da OP
            return origin_mo.action_check_flow_status()



    # ADICIONE ESTE MÉTODO NO stock_picking.py
    def _check_receipt_dependencies(self):
        """Verifica dependências para recebimento na matriz"""
        self.ensure_one()

        if self.picking_type_code != 'incoming':
            return []

        dependencies = []

        # Verificar envios da filial pendentes
        if self.sending_transfer_id:
            pending_sendings = self.sending_transfer_id.filtered(lambda p: p.state != 'done')
            for sending in pending_sendings:
                dependencies.append(f"Envio pendente da filial: {sending.name} ({sending.state})")

        # Verificar se este recebimento está bloqueado
        if self.custom_block_validate:
            dependencies.append("Recebimento bloqueado - aguardando conclusão de processos anteriores")

        return dependencies

    # ATUALIZE o método action_debug_picking_status
    def action_debug_picking_status(self):
        """Debug do status do picking"""
        for picking in self:
            _logger.info(f"🔍 DEBUG PICKING {picking.name}:")
            _logger.info(f"  - Tipo: {picking.picking_type_code}")
            _logger.info(f"  - Estado: {picking.state}")
            _logger.info(f"  - Bloqueado: {picking.custom_block_validate}")
            _logger.info(f"  - Mostrar Validar: {picking.show_validate}")

            # Dependências
            dependencies = picking._check_receipt_dependencies()
            _logger.info(f"  - Dependências: {len(dependencies)}")
            for dep in dependencies:
                _logger.info(f"    - {dep}")

            if picking.origin_production_id:
                origin_mo = picking.origin_production_id
                _logger.info(f"  - OP Origem: {origin_mo.name}")
                _logger.info(f"  - Tipo OP: {'MATRIZ' if not origin_mo.origin_production_id else 'FILIAL'}")
                _logger.info(
                    f"  - Filial OP: {origin_mo.branch_location_id.display_name if origin_mo.branch_location_id else 'Nenhuma'}")

        dependencies_list = self._check_receipt_dependencies()
        dependencies_message = "\n".join(
            [f"• {d}" for d in dependencies_list]) if dependencies_list else "Nenhuma dependência"

        raise UserError(
            f"Status do Picking {self.name}:\n\n"
            f"Tipo: {self.picking_type_code}\n"
            f"Estado: {self.state}\n"
            f"Bloqueado: {'SIM' if self.custom_block_validate else 'NÃO'}\n"
            f"Mostrar Validar: {'SIM' if self.show_validate else 'NÃO'}\n"
            f"OP Origem: {self.origin_production_id.name if self.origin_production_id else 'Nenhuma'}\n"
            f"Dependências:\n{dependencies_message}"
        )