from odoo import models, fields, api
from odoo.exceptions import UserError
import logging

_logger = logging.getLogger(__name__)
_logger.warning("🔥 STOCK_PICKING.PY CARREGADO — este é o arquivo em uso REAL")


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

    def button_validate(self):
        """
        Button validate único e robusto:
        - chama super() (preserva comportamento de outros módulos como l10n_br_stock_account)
        - cria RECEBIMENTO na filial após ENVIO (outgoing) ser validado (done)
        - cria OP filial APENAS após RECEBIMENTO (incoming) estar done e ter sending_transfer done
        - respeita contexto bypass_branch_creation para evitar criação prematura durante wizard writes
        """
        # 🎯 DEBUG INICIAL
        _logger.warning(f"🎯 INICIANDO BUTTON_VALIDATE:")
        for picking in self:
            _logger.warning(f"   • Picking: {picking.name}")
            _logger.warning(f"   • Type: {picking.picking_type_code}")
            _logger.warning(f"   • State: {picking.state}")
            _logger.warning(f"   • Origin: {picking.origin}")
            _logger.warning(f"   • Origin Production ID: {picking.origin_production_id}")
            _logger.warning(
                f"   • Origin Production Name: {picking.origin_production_id.name if picking.origin_production_id else 'None'}")
            _logger.warning(f"   • Branch Receipt IDs: {picking.branch_receipt_id.ids}")
            _logger.warning(f"   • Custom Block: {picking.custom_block_validate}")

        # 1) Bloqueio: impedir validação se houver envio pendente (para incoming)
        for picking in self:
            if (picking.picking_type_code == 'incoming'
                    and picking.sending_transfer_id
                    and picking.custom_block_validate):
                pending_sendings = picking.sending_transfer_id.filtered(lambda p: p.state != 'done')
                if pending_sendings:
                    raise UserError(
                        "Não é possível validar este recebimento enquanto o envio matriz → filial não estiver concluído."
                    )

        # 2) Preserva comportamento de outros módulos (l10n_br_stock_account etc.)
        result = super(StockPicking, self).button_validate()

        # 3) Pós-validação - aplicar lógica de criação de recebimento / OP filial
        for picking in self:
            # Debug global para saber que o método realmente executou
            _logger.warning(
                f"🧨 DEBUG BUTTON_VALIDATE APÓS SUPER → {picking.name} | "
                f"type={picking.picking_type_code} | state={picking.state} | "
                f"custom_block={picking.custom_block_validate} | origin={picking.origin} | "
                f"origin_mo={picking.origin_production_id and picking.origin_production_id.name} | "
                f"sending_ids={picking.sending_transfer_id.ids} | branch_receipts={picking.branch_receipt_id.ids}"
            )

            # ---------------------------------------------------------
            # 🎯 CONDIÇÃO 0: Se é BACKORDER de envio validado -> LIBERAR recebimento correspondente na filial
            # ---------------------------------------------------------
            if (
                    picking.picking_type_code == 'outgoing'
                    and picking.state == 'done'
                    and picking.origin_production_id
                    and 'Backorder' in (picking.origin or '')
            ):
                _logger.warning(f"🎯 CONDIÇÃO 0 ATENDIDA - BACKORDER DE ENVIO VALIDADO: {picking.name}")
                try:
                    # Encontra o recebimento vinculado a este backorder
                    related_receipt = picking.branch_receipt_id.filtered(
                        lambda r: r.state in ['assigned', 'confirmed'] and 'Backorder' in (r.origin or '')
                    )

                    if related_receipt:
                        for receipt in related_receipt:
                            _logger.warning(f"   • Liberando recebimento: {receipt.name}")
                            _logger.warning(
                                f"   • Estado atual: bloqueado={receipt.custom_block_validate}, mostrar_validação={receipt.show_validate}")

                            # 🎯 LIBERA o recebimento do backorder
                            receipt.write({
                                'custom_block_validate': False,  # 🎯 LIBERA a validação
                                'show_validate': True,  # 🎯 Mostra botão de validar
                            })

                            _logger.warning(f"   ✅ Recebimento liberado: {receipt.name}")
                            _logger.warning(
                                f"   • Novo estado: bloqueado={receipt.custom_block_validate}, mostrar_validação={receipt.show_validate}")

                            # Opcional: Postar mensagem no recebimento
                            receipt.message_post(
                                body=f"✅ Recebimento liberado: Backorder da matriz {picking.name} foi validado."
                            )
                    else:
                        _logger.warning(f"   ⚠️ Nenhum recebimento encontrado para liberar")
                        _logger.warning(f"   • Branch receipts vinculados: {picking.branch_receipt_id.mapped('name')}")

                except Exception as e:
                    _logger.error(f"❌ Erro ao liberar recebimento para backorder {picking.name}: {str(e)}")
                    import traceback
                    _logger.error(traceback.format_exc())

            # ---------------------------------------------------------
            # 1️⃣ CONDIÇÃO 1: Se é um ENVIO NORMAL (outgoing) que acabou de ficar done -> criar RECEBIMENTO na filial
            # ---------------------------------------------------------
            elif (
                    picking.picking_type_code == 'outgoing'
                    and picking.state == 'done'
                    and picking.origin_production_id
                    and not picking.branch_receipt_id
                    and 'Backorder' not in (picking.origin or '')  # 🎯 Não é backorder
            ):
                _logger.warning(f"🎯 CONDIÇÃO 1 ATENDIDA - CRIANDO RECEBIMENTO NORMAL PARA: {picking.name}")
                try:
                    # 🎯 VERIFICA SE É BACKORDER
                    is_backorder = picking.backorder_id and 'Backorder' in (picking.origin or '')

                    origin_mo = picking.origin_production_id
                    _logger.warning(f"   • Origin MO: {origin_mo.name}")
                    _logger.warning(
                        f"   • Branch Location: {origin_mo.branch_location_id.display_name if origin_mo.branch_location_id else 'None'}")

                    warehouse = origin_mo.branch_location_id and origin_mo.branch_location_id.warehouse_id
                    if not warehouse:
                        _logger.warning(f"⚠️ Envio {picking.name} não tem warehouse filial configurado.")
                        continue

                    _logger.warning(f"   • Warehouse: {warehouse.name}")

                    picking_type = self.env['stock.picking.type'].search([
                        ('warehouse_id', '=', warehouse.id),
                        ('code', '=', 'incoming')
                    ], limit=1)

                    if not picking_type:
                        _logger.error(f"❌ Tipo de operação de recebimento não encontrado para {warehouse.name}")
                        continue

                    # Quantidade realmente enviada (quantity_done nos moves)
                    qty_sent = sum(
                        move.quantity_done for move in picking.move_ids_without_package
                        if move.product_id == origin_mo.product_id
                    )

                    _logger.warning(f"   • Qty Sent: {qty_sent}")

                    if qty_sent <= 0:
                        _logger.warning(
                            f"⏸️ Envio {picking.name} sem quantidades processadas, ignorando recebimento automático.")
                        continue

                    # Define a origem correta
                    if is_backorder:
                        origin_text = f"{picking.origin} - Backorder Recebimento Filial"
                    else:
                        origin_text = f"{picking.origin} - Recebimento Filial"

                    # Criar recebimento com bypass para evitar triggers no create/write
                    receiving_vals = {
                        "picking_type_id": picking_type.id,
                        "location_id": picking.location_dest_id.id,
                        "location_dest_id": origin_mo.branch_location_id.id,
                        "origin": origin_text,
                        "move_ids_without_package": [(0, 0, {
                            "name": f"Recebimento {origin_mo.product_id.display_name}",
                            "product_id": origin_mo.product_id.id,
                            "product_uom_qty": qty_sent,
                            "product_uom": origin_mo.product_uom_id.id,
                            "location_id": picking.location_dest_id.id,
                            "location_dest_id": origin_mo.branch_location_id.id,
                        })],
                        "custom_block_validate": False,  # 🎯 NÃO BLOQUEADO (recebimento normal)
                        "show_validate": True,  # 🎯 Mostrar botão de validar
                        "origin_production_id": origin_mo.id,
                        "sending_transfer_id": [(4, picking.id)],
                    }

                    _logger.warning(f"   • Receiving Vals: {receiving_vals}")

                    # 🎯 CORREÇÃO: Usar with_context em vez de merge
                    receiving = self.env['stock.picking'].with_context(
                        bypass_branch_creation=True
                    ).create(receiving_vals)
                    _logger.warning(f"   ✅ Recebimento criado: {receiving.name}")

                    receiving.with_context(bypass_branch_creation=True).action_confirm()
                    try:
                        receiving.with_context(bypass_branch_creation=True).state = 'assigned'
                        _logger.warning(f"   • Estado após assign: {receiving.state}")
                    except Exception:
                        receiving.with_context(bypass_branch_creation=True).write({'state': 'assigned'})
                        _logger.warning(f"   • Estado após assign (fallback): {receiving.state}")

                    # Vincula registros
                    picking.write({'branch_receipt_id': [(4, receiving.id)]})
                    origin_mo.write({'branch_receipt_id': [(4, receiving.id)]})

                    _logger.warning(
                        f"✅ {'BACKORDER ' if is_backorder else ''}RECEBIMENTO criado: {receiving.name} ({qty_sent})")

                except Exception as e:
                    _logger.error(
                        f"❌ Erro ao criar recebimento para {'backorder ' if is_backorder else ''}envio {picking.name}: {str(e)}")
                    import traceback
                    _logger.error(traceback.format_exc())

            # ---------------------------------------------------------
            # 2️⃣ CONDIÇÃO 2: Se é um RECEBIMENTO (incoming) validado -> criar OP filial
            #    Inclui tanto recebimentos normais quanto de backorder
            # ---------------------------------------------------------
            elif (
                    picking.picking_type_code == 'incoming'
                    and picking.state == 'done'
                    and picking.origin_production_id
                    and not picking.branch_mo_id
                    and not picking.final_receipt_id
                    and 'Recebimento Final' not in (picking.origin or '')
            ):
                _logger.warning(f"🎯 CONDIÇÃO 2 ATENDIDA - CRIANDO OP FILIAL PARA: {picking.name}")
                try:
                    # DEBUG CRÍTICO DETALHADO
                    _logger.warning(f"🔍 VERIFICANDO CONDIÇÕES PARA OP FILIAL:")
                    _logger.warning(f"   • Picking: {picking.name}")
                    _logger.warning(f"   • Estado: {picking.state}")
                    _logger.warning(f"   • Tipo: {picking.picking_type_code}")
                    _logger.warning(f"   • Origin: {picking.origin}")
                    _logger.warning(f"   • Origin Production: {picking.origin_production_id.name}")
                    _logger.warning(f"   • Branch MO IDs: {picking.branch_mo_id.ids}")
                    _logger.warning(f"   • Final Receipt IDs: {picking.final_receipt_id.ids}")
                    _logger.warning(
                        f"   • Recebimento Final na origem? {'Recebimento Final' in (picking.origin or '')}")
                    _logger.warning(f"   • bypass_branch_creation: {self.env.context.get('bypass_branch_creation')}")

                    # Se create/write foi feito com bypass, respeitar e não criar aqui
                    if self.env.context.get('bypass_branch_creation'):
                        _logger.warning(
                            f"⛔ OP DA FILIAL NÃO SERÁ CRIADA (bypass_branch_creation=True) → {picking.name}")
                        continue

                    # Exige que exista envio vinculado e que esteja done
                    _logger.warning(f"   • Sending Transfer IDs: {picking.sending_transfer_id.ids}")
                    _logger.warning(f"   • Sending Transfer Estados: {picking.sending_transfer_id.mapped('state')}")

                    if not picking.sending_transfer_id:
                        _logger.warning(f"⏸️ Recebimento {picking.name} ignorado — nenhum envio vinculado.")
                        continue

                    if any(s.state != 'done' for s in picking.sending_transfer_id):
                        _logger.warning(
                            f"⏸️ Recebimento {picking.name} ignorado — envio não concluído: {picking.sending_transfer_id.mapped('name')}")
                        continue

                    origin_mo = picking.origin_production_id

                    # Verifica quantidade recebida
                    qty_received = sum(
                        move.quantity_done for move in picking.move_ids_without_package
                        if move.product_id == origin_mo.product_id
                    )

                    _logger.warning(f"   • Qty Received: {qty_received}")

                    if qty_received <= 0:
                        _logger.warning(f"⏸️ Recebimento {picking.name} sem qty recebida para produto da OP.")
                        continue

                    _logger.warning(f"🎯 CHAMANDO _create_mo_from_receipt para OP {origin_mo.name}")

                    # Chama o método da OP matriz para criar OP filial.
                    branch_mo = origin_mo._create_mo_from_receipt(qty=qty_received, receipt_picking=picking)

                    if branch_mo:
                        picking.write({'branch_mo_id': [(4, branch_mo.id)]})
                        _logger.warning(f"✅ OP filial criada: {branch_mo.name} ({qty_received})")
                        origin_mo._compute_message_state()
                    else:
                        _logger.warning(f"❌ _create_mo_from_receipt retornou False para {picking.name}")

                except Exception as e:
                    _logger.error(f"❌ Erro ao criar OP filial para recebimento {picking.name}: {str(e)}")
                    import traceback
                    _logger.error(traceback.format_exc())

        return result

    def _action_done(self):
        """Override para processar backorders automaticamente após validação"""
        result = super(StockPicking, self)._action_done()

        # Processa backorders criados automaticamente
        for picking in self:
            if picking.backorder_ids:
                _logger.warning(f"🔄 PROCESSANDO BACKORDERS para {picking.name}")
                for backorder in picking.backorder_ids:
                    _logger.warning(f"   • Backorder: {backorder.name} | state: {backorder.state}")

                    # 🎯 CORREÇÃO: Aceita tanto 'assigned' quanto 'confirmed'
                    if (backorder.picking_type_code == 'outgoing'
                            and backorder.origin_production_id
                            and backorder.state in ['assigned', 'confirmed']):  # ⬅️ ACEITA AMBOS OS ESTADOS
                        try:
                            _logger.warning(f"🎯 PROCESSANDO BACKORDER DE ENVIO: {backorder.name}")
                            self._process_backorder_receipt(backorder)
                        except Exception as e:
                            _logger.error(f"❌ Erro ao processar backorder {backorder.name}: {str(e)}")

        return result

    def _process_backorder_receipt(self, backorder_picking):
        """Cria recebimento na filial para backorders de envio - BLOQUEADO até backorder da matriz ser validado"""
        _logger.warning(f"🔄 CRIANDO RECEBIMENTO PARA BACKORDER: {backorder_picking.name}")

        origin_mo = backorder_picking.origin_production_id
        if not origin_mo or not origin_mo.branch_location_id:
            _logger.warning(f"⚠️ Backorder {backorder_picking.name} sem OP origem ou filial configurada")
            return

        warehouse = origin_mo.branch_location_id.warehouse_id
        if not warehouse:
            _logger.warning(f"⚠️ Backorder {backorder_picking.name} não tem warehouse filial configurado.")
            return

        picking_type = self.env['stock.picking.type'].search([
            ('warehouse_id', '=', warehouse.id),
            ('code', '=', 'incoming')
        ], limit=1)

        if not picking_type:
            _logger.error(f"❌ Tipo de operação de recebimento não encontrado para {warehouse.name}")
            return

        # Quantidade do backorder
        qty_backorder = sum(
            move.product_uom_qty for move in backorder_picking.move_ids_without_package
            if move.product_id == origin_mo.product_id
        )

        if qty_backorder <= 0:
            _logger.warning(f"⏸️ Backorder {backorder_picking.name} sem quantidades para produto da OP.")
            return

        # Verifica se já existe recebimento vinculado a este backorder
        existing_receipt = backorder_picking.branch_receipt_id.filtered(
            lambda r: r.state not in ['done', 'cancel']
        )

        if existing_receipt:
            _logger.warning(f"⚠️ Já existe recebimento {existing_receipt.name} para backorder {backorder_picking.name}")
            return

        # Cria recebimento para o backorder - BLOQUEADO inicialmente
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
            })],
            "custom_block_validate": True,  # 🎯 BLOQUEADO até backorder da matriz ser validado
            "show_validate": False,  # 🎯 Não mostrar botão de validar
            "origin_production_id": origin_mo.id,
            "sending_transfer_id": [(4, backorder_picking.id)],
        }

        # Cria com bypass para evitar triggers
        receiving = self.env['stock.picking'].with_context(
            bypass_branch_creation=True
        ).create(receiving_vals)

        receiving.with_context(bypass_branch_creation=True).action_confirm()
        try:
            receiving.with_context(bypass_branch_creation=True).state = 'assigned'
        except Exception:
            receiving.with_context(bypass_branch_creation=True).write({'state': 'assigned'})

        # Vincula registros
        backorder_picking.write({'branch_receipt_id': [(4, receiving.id)]})
        origin_mo.write({'branch_receipt_id': [(4, receiving.id)]})

        _logger.warning(f"✅ RECEBIMENTO DE BACKORDER CRIADO (BLOQUEADO): {receiving.name} (qty: {qty_backorder})")

        return receiving

    def _create_backorder(self):
        backorders = super(StockPicking, self)._create_backorder()

        _logger.warning(f"🧩 BACKORDER CRIADO:")
        for backorder in backorders:
            _logger.warning(f"   • {backorder.name} | type: {backorder.picking_type_code} | origin: {backorder.origin}")
            _logger.warning(
                f"   • origin_production_id: {backorder.origin_production_id and backorder.origin_production_id.name}")
            _logger.warning(f"   • backorder_id: {backorder.backorder_id and backorder.backorder_id.name}")

            # 🎯 DEBUG DETALHADO
            if backorder.backorder_id:
                _logger.warning(
                    f"   • backorder_id.origin_production_id: {backorder.backorder_id.origin_production_id}")
                _logger.warning(
                    f"   • backorder_id.origin_production_id.id: {backorder.backorder_id.origin_production_id.id if backorder.backorder_id.origin_production_id else 'None'}")

            # 🎯 CORREÇÃO CRÍTICA: Herda origin_production_id do picking original
            if backorder.backorder_id and backorder.backorder_id.origin_production_id:
                backorder.write({
                    'origin_production_id': backorder.backorder_id.origin_production_id.id,
                    'custom_block_validate': backorder.backorder_id.custom_block_validate,
                    'show_validate': backorder.backorder_id.show_validate,
                })
                _logger.warning(f"   ✅ HERDADO origin_production_id: {backorder.origin_production_id.name}")
            else:
                _logger.warning(f"   ❌ NÃO FOI POSSÍVEL HERDAR origin_production_id")
                _logger.warning(f"      • backorder_id existe? {bool(backorder.backorder_id)}")
                if backorder.backorder_id:
                    _logger.warning(
                        f"      • backorder_id.origin_production_id: {backorder.backorder_id.origin_production_id}")
                    _logger.warning(
                        f"      • backorder_id.origin_production_id.id: {backorder.backorder_id.origin_production_id.id if backorder.backorder_id.origin_production_id else 'None'}")

        if backorders:
            backorders._process_backorder_after_creation()
        return backorders

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
                # NÃO usar sudo() aqui — isso limpa contexto e ignora nossos guards em _create_mo_from_receipt
                branch_mo = origin_mo._create_mo_from_receipt(qty_received, picking)
                if branch_mo:
                    picking.write({'branch_mo_id': [(4, branch_mo.id)]})
                    _logger.info(f"✅ OP filial criada após recebimento: {branch_mo.name} - {qty_received}")
                else:
                    _logger.warning(
                        f"⏸️ _create_mo_from_receipt retornou False — OP filial NÃO criada para {picking.name}")

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

    def create(self, vals):
        rec = super(StockPicking, self).create(vals)
        _logger.warning(f"📦 DEBUG CREATE PICKING: {rec.name} | state={rec.state} | origin={rec.origin}")
        return rec

    def _process_backorder_after_creation(self):
        for backorder in self:
            _logger.info(
                f"🧩 Processando backorder {backorder.name} | tipo={backorder.picking_type_code} | state={backorder.state}")

            # 🎯 CORREÇÃO: Tenta reservar o backorder se estiver em confirmed
            if backorder.state == 'confirmed' and not backorder.custom_block_validate:
                try:
                    _logger.warning(f"🔄 TENTANDO RESERVAR BACKORDER: {backorder.name}")
                    backorder.action_assign()
                    _logger.warning(f"   • Estado após action_assign: {backorder.state}")
                except Exception as e:
                    _logger.error(f"❌ Erro ao reservar backorder: {str(e)}")

            # Ignora backorders enquanto bloqueado ou não finalizado
            if backorder.custom_block_validate or backorder.state not in ['done', 'assigned',
                                                                          'confirmed']:  # ⬅️ INCLUI confirmed
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
                    and backorder.state in ['done', 'assigned', 'confirmed']  # ⬅️ INCLUI confirmed
            ):
                origin_mo = backorder.origin_production_id
                if origin_mo and origin_mo.branch_location_id:
                    try:
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
                                transfer_picking.write({'branch_receipt_id': [(4, backorder.id)]})
                                _logger.info(
                                    f"✅ Transferência de backorder criada: {transfer_picking.name} ({qty_backorder})")
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

    def action_assign(self):
        res = super(StockPicking, self).action_assign()

        for picking in self:
            # Não criar OP aqui — criação só deve ocorrer após RECEBIMENTO validado (button_validate)
            _logger.debug(
                f"action_assign: {picking.name} | state={picking.state} | block={picking.custom_block_validate} | sending={bool(picking.sending_transfer_id)}"
            )

        return res