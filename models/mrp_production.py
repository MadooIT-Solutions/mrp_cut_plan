# mrp_production.py (corrigido)
from collections import defaultdict
from odoo import fields, models, api, _
from odoo.exceptions import UserError
from odoo.tools import float_round
from odoo.tools.misc import groupby as tools_groupby
import logging

_logger = logging.getLogger(__name__)


class BlueMrpProduction(models.Model):
    _inherit = "mrp.production"

    cut_plan_id = fields.Many2one(
        comodel_name="mrp_cut_plan.mrp_cut_plan",
        string="Cut Plan",
        tracking=True
    )

    count_po = fields.Integer(
        string="Documents Count",
        compute="_compute_count_po"
    )

    partner_id = fields.Many2one(
        string="Cliente",
        comodel_name="res.partner"
    )

    # Campos compute
    blue_I = fields.Float(
        string="L",
        digits='Product Unit of Measure',
        compute="_compute_cut_plan_fields"
    )

    blue_II = fields.Float(
        string="L ",
        digits='Product Unit of Measure',
        compute="_compute_cut_plan_fields"
    )

    blue_h = fields.Float(
        string="H",
        digits='Product Unit of Measure',
        compute="_compute_cut_plan_fields"
    )

    blue_I_uom = fields.Many2one(
        comodel_name="uom.uom",
        string="Uom ",
        compute="_compute_cut_plan_fields"
    )

    blue_II_uom = fields.Many2one(
        comodel_name="uom.uom",
        string="Uom  ",
        compute="_compute_cut_plan_fields"
    )

    blue_h_uom = fields.Many2one(
        comodel_name="uom.uom",
        string="Uom   ",
        compute="_compute_cut_plan_fields"
    )

    sale_order_id = fields.Many2one(
        comodel_name="sale.order",
        string="Pedido",
        tracking=True
    )

    blue_advance = fields.Float(
        string="Advance",
        digits='Product Unit of Measure',
        compute="_compute_cut_plan_fields"
    )

    blue_advance_uom = fields.Many2one(
        comodel_name="uom.uom",
        string="Udm",
        compute="_compute_cut_plan_fields"
    )

    related_type = fields.Selection(
        selection=[
            ("n", "None"),
            ("llh", "LLH Calculation"),
            ("m", "Mold Calculation")
        ],
        string="Related Type",
        compute="_compute_cut_plan_fields", store=True
    )

    cotation_partner_id = fields.Many2one(
        comodel_name="res.partner",
        related="sale_order_id.partner_id",
        string="Cliente"
    )

    # Campos para controle do fluxo
    branch_location_id = fields.Many2one("stock.location", string="Armazém de Processamento", readonly=True)
    sending_transfer_id = fields.Many2many(
        "stock.picking",
        "mrp_sending_transfer_rel",
        "production_id",
        "picking_id",
        string="Transferências de Envio",
        readonly=True,
    )

    branch_receipt_id = fields.Many2many(
        "stock.picking",
        "mrp_branch_receipt_rel",
        "production_id",
        "picking_id",
        string="Recebimentos na Filial",
        readonly=True,
    )

    branch_production_id = fields.Many2many(
        "mrp.production",
        "mrp_branch_production_rel",
        "production_id",
        "branch_id",
        string="OPs da Filial",
        readonly=True,
    )

    return_transfer_id = fields.Many2many(
        "stock.picking",
        "mrp_return_transfer_rel",
        "production_id",
        "picking_id",
        string="Retornos da Filial",
        readonly=True,
    )

    final_receipt_id = fields.Many2many(
        "stock.picking",
        "mrp_final_receipt_rel",
        "production_id",
        "picking_id",
        string="Recebimentos Finais",
        readonly=True,
    )

    is_waiting_return = fields.Boolean(string="Aguardando Retorno", compute="_compute_is_waiting_return")

    message_state = fields.Char(string="Status", compute="_compute_message_state", store=True)

    origin_production_id = fields.Many2one("mrp.production", string="OP de Origem", readonly=True)

    # Campos para controle de quantidades
    total_qty_produced = fields.Float(
        string="Quantidade Total Produzida",
        compute="_compute_total_qty_produced",
        store=True
    )

    total_qty_received = fields.Float(
        string="Quantidade Total Recebida",
        compute="_compute_total_qty_received",
        store=True
    )

    # NOVOS CAMPOS PARA CONTROLE DE CONSUMO
    matrix_consumed_qty = fields.Float(
        string="Quantidade Consumida na Matriz",
        compute="_compute_matrix_consumed_qty",
        store=True
    )

    branch_consumed_qty = fields.Float(
        string="Quantidade Consumida na Filial",
        compute="_compute_branch_consumed_qty",
        store=True
    )

    total_components_consumed = fields.Float(
        string="Total Componentes Consumidos",
        compute="_compute_total_components_consumed"
    )

    # Campos para controle visual das quantidades
    display_product_qty = fields.Float(
        string="Quantidade a Produzir",
        compute="_compute_display_quantities"
    )

    display_qty_producing = fields.Float(
        string="Quantidade Produzindo",
        compute="_compute_display_quantities"
    )

    is_branch_flow = fields.Boolean(
        string="É Fluxo Filial",
        compute="_compute_is_branch_flow"
    )

    hide_check_availability = fields.Boolean(
        string="Ocultar Verificar Disponibilidade",
        compute='_compute_hide_check_availability',
        store=False
    )



    @api.depends('related_type', 'branch_location_id')
    def _compute_hide_check_availability(self):
        for record in self:
            # Ocultar quando for molde OU tiver filial definida
            record.hide_check_availability = (
                    record.related_type == 'm' or
                    record.branch_location_id
            )

    # ------------------------------------------------------------
    # MÉTODOS COMPUTE (mantidos)
    # ------------------------------------------------------------
    @api.depends('state', 'branch_location_id', 'final_receipt_id')
    def _compute_is_waiting_return(self):
        for record in self:
            record.is_waiting_return = (
                    record.state == 'progress' and bool(record.branch_location_id) and not bool(record.final_receipt_id)
            )

    @api.depends('branch_location_id', 'origin_production_id')
    def _compute_is_branch_flow(self):
        for record in self:
            record.is_branch_flow = bool(record.branch_location_id or record.origin_production_id)

    @api.depends('product_qty', 'qty_producing', 'branch_location_id', 'origin_production_id', 'total_qty_received')
    def _compute_display_quantities(self):
        for record in self:
            if record.origin_production_id:
                record.display_product_qty = record.product_qty
                record.display_qty_producing = record.qty_producing
            elif record.branch_location_id:
                record.display_product_qty = record.product_qty
                record.display_qty_producing = record.total_qty_received
            else:
                record.display_product_qty = record.product_qty
                record.display_qty_producing = record.qty_producing

    @api.depends('branch_production_id', 'branch_production_id.qty_producing')
    def _compute_total_qty_produced(self):
        for record in self:
            if record.branch_production_id:
                record.total_qty_produced = sum(record.branch_production_id.mapped('qty_produced'))
            else:
                record.total_qty_produced = record.qty_produced

    @api.depends('final_receipt_id', 'final_receipt_id.move_ids_without_package.quantity_done')
    def _compute_total_qty_received(self):
        for record in self:
            if record.final_receipt_id:
                total_received = 0.0
                for picking in record.final_receipt_id:
                    if picking.state == 'done':
                        for move in picking.move_ids_without_package:
                            if move.product_id == record.product_id:
                                total_received += move.quantity_done
                record.total_qty_received = total_received
            else:
                record.total_qty_received = 0.0

    @api.depends('move_raw_ids.quantity_done', 'state')
    def _compute_matrix_consumed_qty(self):
        for record in self:
            if record.origin_production_id:
                record.matrix_consumed_qty = 0.0
            else:
                total_consumed = 0.0
                for move in record.move_raw_ids:
                    if move.state in ['done', 'assigned'] and move.quantity_done > 0:
                        total_consumed += move.quantity_done
                record.matrix_consumed_qty = total_consumed

    @api.depends('branch_production_id', 'branch_production_id.move_raw_ids.quantity_done')
    def _compute_branch_consumed_qty(self):
        for record in self:
            total_branch_consumed = 0.0
            if record.branch_production_id:
                for branch_mo in record.branch_production_id:
                    for move in branch_mo.move_raw_ids:
                        if move.state in ['done', 'assigned'] and move.quantity_done > 0:
                            total_branch_consumed += move.quantity_done
            record.branch_consumed_qty = total_branch_consumed

    @api.depends('matrix_consumed_qty', 'branch_consumed_qty')
    def _compute_total_components_consumed(self):
        for record in self:
            record.total_components_consumed = record.matrix_consumed_qty + record.branch_consumed_qty

    def open_linked_po(self):
        if not self.cut_plan_id:
            raise UserError("Nenhum Plano de Corte vinculado.")

        return {
            'name': _('Plano de Corte'),
            'type': 'ir.actions.act_window',
            'res_model': 'mrp_cut_plan.mrp_cut_plan',
            'res_id': self.cut_plan_id.id,
            'view_mode': 'form',
        }

    def _compute_count_po(self):
        for record in self:
            record.count_po = 1 if record.cut_plan_id else 0

    @api.depends(
        "branch_location_id",
        "branch_receipt_id.state",
        "sending_transfer_id.state",
        "branch_production_id.state",
        "return_transfer_id.state",
        "final_receipt_id.state",
        "state",
    )
    def _compute_message_state(self):
        for record in self:
            msg = ''
            filial_flag = False

            if not record.branch_location_id:
                record.message_state = ''
                continue

            pending_backorders = any(picking.state != 'done' for picking in record.sending_transfer_id)
            pending_receipts = any(picking.state != 'done' for picking in record.branch_receipt_id)
            if pending_backorders or pending_receipts:
                msg = "Aguardando confirmação de backorder/recebimento na filial."

            elif record.branch_production_id:
                production_states = record.branch_production_id.mapped('state')
                if all(s != 'done' for s in production_states):
                    msg = "Aguardando fabricação na filial (OPs pendentes)."

                if any(p.state not in ['done', 'cancel'] for p in
                       record.sending_transfer_id.filtered(lambda p: 'Backorder' in (p.origin or ''))):
                    msg = "Aguardando processamento de backorder na matriz/filial."

                elif any(s == 'done' for s in production_states) and not record.return_transfer_id:
                    msg = "Fabricação na filial concluída, aguardando retorno."
                    filial_flag = True

            elif record.return_transfer_id and any(r.state != 'done' for r in record.return_transfer_id):
                msg = "Em trânsito para a matriz."
                filial_flag = True

            elif record.final_receipt_id and any(f.state != 'done' for f in record.final_receipt_id):
                msg = "Recebimento final em andamento."

            elif record.final_receipt_id and all(f.state == 'done' for f in record.final_receipt_id):
                if record.state == 'done':
                    msg = "Produção concluída. Aguardando envio para o cliente."
                else:
                    msg = "Recebido na matriz."

            record.message_state = msg
            if filial_flag and record.origin_production_id:
                record.origin_production_id.message_state = msg

    def button_send_to_branch(self):
        for record in self:
            if record.related_type != 'm':
                raise UserError("Este botão só pode ser usado para Mold Calculation.")

            # ⚠️ VERIFICA SE HÁ COMPONENTES JÁ CONSUMIDOS
            consumed_components = record.move_raw_ids.filtered(
                lambda m: m.quantity_done > 0
            )
            if consumed_components:
                component_names = ", ".join(consumed_components.mapped('product_id.display_name'))
                raise UserError(
                    f"Não é possível enviar para filial com componentes já consumidos:\n\n"
                    f"• {component_names}\n\n"
                    f"Zere as quantidades consumidas antes do envio."
                )

            # ⚠️ VERIFICA SE A OP ESTÁ NO ESTADO CORRETO
            if record.state != 'confirmed':
                raise UserError(
                    f"A OP deve estar no estado 'Confirmado' para envio à filial. Estado atual: {record.state}"
                )

            if not record.branch_location_id:
                return {
                    'name': 'Selecionar Armazém para Processamento',
                    'type': 'ir.actions.act_window',
                    'res_model': 'mrp.production.transfer.wizard',
                    'view_mode': 'form',
                    'target': 'new',
                    'context': {'default_production_id': record.id}
                }

            raise UserError("A OP já está em processamento ou não pode ser enviada.")

    def button_mark_done(self):
        for record in self:
            if record.origin_production_id:
                # ⚠️ OP FILIAL - VALIDAÇÕES ESPECÍFICAS
                _logger.info(f"🔄 Concluindo OP filial {record.name}")

                # Verifica se todos os componentes foram consumidos
                for move in record.move_raw_ids:
                    if move.product_uom_qty > 0 and move.quantity_done <= 0:
                        raise UserError(
                            f"Componente {move.product_id.display_name} não consumido. "
                            f"Planejado: {move.product_uom_qty}, Consumido: {move.quantity_done}"
                        )

                # ⚠️ GARANTE QUE A QUANTIDADE PRODUZIDA É A MESMA DA OP
                if record.move_finished_ids:
                    for move in record.move_finished_ids:
                        if move.product_id == record.product_id:
                            move.write({
                                'product_uom_qty': record.product_qty,
                                'quantity_done': record.product_qty
                            })

                res = super(BlueMrpProduction, record).button_mark_done()

                try:
                    record._create_return_flow_automatically()
                except Exception as e:
                    _logger.error(f"❌ Erro no fluxo de retorno, mas OP foi concluída: {str(e)}")

                return res

            if record.branch_location_id:
                # ⚠️ OP MATRIZ COM FILIAL - NÃO ALTERA QUANTIDADES
                if not record._can_receive_at_matrix():
                    blockers = record._check_matrix_receipt_blockers()
                    blocker_message = "\n".join([f"• {b}" for b in blockers])
                    raise UserError(
                        f"Não é possível concluir a OP matriz enquanto existirem processos pendentes na filial:\n\n"
                        f"{blocker_message}"
                    )

                if record.total_qty_received < record.product_qty:
                    raise UserError(
                        f"Quantidade recebida ({record.total_qty_received}) é menor que a quantidade planejada ({record.product_qty}). "
                        f"Aguarde o recebimento total das filiais."
                    )

                # ⚠️ NÃO ALTERA AS QUANTIDADES DOS MOVIMENTOS - MANTÉM AS ORIGINAIS
                # Apenas ajusta a quantidade produzida para o total recebido
                record.qty_producing = record.total_qty_received

                # Para o movimento finalizado, ajusta apenas a quantidade feita, não a planejada
                for move in record.move_finished_ids:
                    if move.product_id == record.product_id:
                        move.write({
                            'quantity_done': record.total_qty_received
                        })

                record._release_delivery_order()
                return super(BlueMrpProduction, record).button_mark_done()

            return super(BlueMrpProduction, record).button_mark_done()

    def _can_receive_at_matrix(self):
        self.ensure_one()

        if not self.branch_location_id:
            return True

        if self.branch_production_id:
            pending_productions = self.branch_production_id.filtered(lambda p: p.state != 'done')
            if pending_productions:
                pending_names = ", ".join(pending_productions.mapped('name'))
                _logger.warning(f"⏳ Produções pendentes na filial: {pending_names}")
                return False

        if self.return_transfer_id:
            pending_returns = self.return_transfer_id.filtered(lambda r: r.state != 'done')
            if pending_returns:
                pending_names = ", ".join(pending_returns.mapped('name'))
                _logger.warning(f"⏳ Retornos pendentes da filial: {pending_names}")
                return False

        if self.branch_receipt_id:
            pending_receipts = self.branch_receipt_id.filtered(lambda r: r.state != 'done')
            if pending_receipts:
                pending_names = ", ".join(pending_receipts.mapped('name'))
                _logger.warning(f"⏳ Recebimentos pendentes na filial: {pending_names}")
                return False

        return True

    def _calculate_total_required_consumption(self):
        self.ensure_one()
        total_required = 0.0
        if self.bom_id:
            for line in self.bom_id.bom_line_ids:
                line_qty = line.product_qty * self.product_qty / self.bom_id.product_qty
                total_required += line_qty
        return total_required

    def _create_backorder_transfer(self, backorder_qty):
        self.ensure_one()
        if not self.branch_location_id:
            raise UserError("Não existe filial definida para criar transferência de backorder.")

        picking_type = self.env['stock.picking.type'].search([
            ('code', '=', 'internal'),
            ('warehouse_id.name', '=', 'Polispan')
        ], limit=1)
        if not picking_type:
            picking_type = self.env['stock.picking.type'].search([
                ('code', '=', 'internal'),
                ('company_id', '=', self.env.company.id)
            ], limit=1)
        if not picking_type:
            raise UserError("Tipo de operação interna não encontrado.")

        move_lines = [(0, 0, {
            "name": f"Backorder {self.product_id.display_name}",
            "product_id": self.product_id.id,
            "product_uom_qty": backorder_qty,
            "product_uom": self.product_uom_id.id,
            "location_id": self.location_src_id.id,
            "location_dest_id": self.branch_location_id.id,
        })]

        picking = self.env['stock.picking'].create({
            "picking_type_id": picking_type.id,
            "location_id": self.location_src_id.id,
            "location_dest_id": self.branch_location_id.id,
            "origin": f"{self.name} - Backorder",
            "move_ids_without_package": move_lines,
            "custom_block_validate": False,
        })

        picking.action_confirm()
        try:
            picking.action_assign()
        except Exception as e:
            _logger.warning("Não foi possível reservar automaticamente: %s", e)
            picking.write({'state': 'assigned'})

        _logger.info(f"✅ Transferência de backorder criada: {picking.name} para quantidade {backorder_qty}")

        return picking

    def _create_branch_receipt_for_backorder(self, sending_picking, qty):
        warehouse = self.branch_location_id.warehouse_id
        picking_type = self.env['stock.picking.type'].search([
            ('warehouse_id', '=', warehouse.id),
            ('code', '=', 'internal')
        ], limit=1)
        if not picking_type:
            raise UserError(f"Tipo de operação de recebimento não encontrado para {warehouse.name}")

        receiving = self.env['stock.picking'].create({
            "picking_type_id": picking_type.id,
            "location_id": sending_picking.location_id.id,
            "location_dest_id": self.branch_location_id.id,
            "origin": f"{self.name} - Backorder Recebimento",
            "move_ids_without_package": [(0, 0, {
                "name": f"Recebimento Backorder {self.product_id.display_name}",
                "product_id": self.product_id.id,
                "product_uom_qty": qty,
                "product_uom": self.product_uom_id.id,
                "location_id": sending_picking.location_id.id,
                "location_dest_id": self.branch_location_id.id,
            })],
            "show_validate": False,
            "custom_block_validate": True,
            "sending_transfer_id": [(4, sending_picking.id)],
        })

        receiving.action_confirm()
        try:
            receiving.action_assign()
            receiving.state = 'assigned'
        except Exception as e:
            _logger.warning("Não foi possível reservar automaticamente: %s", e)

        return receiving

    def _create_mo_from_receipt(self, qty, receipt_picking=None):
        """Cria a OP da filial APÓS o recebimento na filial ser validado"""
        self.ensure_one()

        # 0) Bypass por contexto — usado pelo wizard ao escrever a OP matriz para não disparar criação
        if self.env.context.get('bypass_branch_creation'):
            _logger.warning(f"⛔ Bypass ativo - criação de OP filial ignorada (context) para OP matriz {self.name}")
            return False

        # 1) receipt_picking obrigatório e existente
        if not receipt_picking:
            receipt_picking = self.branch_receipt_id and self.branch_receipt_id[:1]
        if not receipt_picking or not receipt_picking.exists():
            _logger.warning(f"⏸️ _create_mo_from_receipt: nenhum receipt_picking válido para {self.name}")
            return False

        # 2) somente se o picking estiver concluído
        if receipt_picking.state != 'done':
            _logger.warning(
                f"⏸️ Recebimento {receipt_picking.name} não está concluído (state={receipt_picking.state}). "
                f"Aguardando conclusão para criar OP filial."
            )
            return False

        # 3) garantir que o picking realmente pertence a esta OP matriz (proteção contra chamadas indevidas)
        if receipt_picking.origin_production_id and receipt_picking.origin_production_id.id != self.id:
            _logger.warning(
                f"⏸️ Recebimento {receipt_picking.name} não pertence a OP matriz {self.name} (origin_production_id={getattr(receipt_picking.origin_production_id, 'name', False)})"
            )
            return False

        # 4) garantir que exista envio vinculado e que esteja concluído (protege contra recebimentos criados isoladamente)
        if not receipt_picking.sending_transfer_id or any(
                s.state != 'done' for s in receipt_picking.sending_transfer_id):
            _logger.warning(
                f"⏸️ Recebimento {receipt_picking.name} ignorado — envio vinculado ausente ou não concluído: {receipt_picking.sending_transfer_id.mapped('name')}"
            )
            return False

        # 5) garantir que o produto recebido é o produto da OP e qtd positiva
        qty_received = sum(
            m.quantity_done for m in receipt_picking.move_ids_without_package if m.product_id == self.product_id
        )
        if qty_received <= 0:
            _logger.warning(
                f"⏸️ Recebimento {receipt_picking.name} sem qty do produto da OP ({self.product_id.display_name}).")
            return False

        # (a partir daqui o código original segue utilizando 'qty' ou 'qty_received' conforme desejar)

        # ⚙️ Verifica se já existe OP vinculada a este recebimento
        if receipt_picking.branch_mo_id:
            existing_mo = receipt_picking.branch_mo_id[0]
            _logger.info(f"⚠️ Já existe OP {existing_mo.name} vinculada ao recebimento {receipt_picking.name}")

            # Atualiza quantidade se necessário
            if existing_mo.product_qty != qty:
                existing_mo.write({'product_qty': qty})
                existing_mo._update_moves()
                _logger.info(f"🔄 Quantidade da OP filial atualizada: {qty}")

            return existing_mo

        warehouse = receipt_picking.location_dest_id.warehouse_id

        # Localização de produção na filial
        production_loc = self.env['stock.location'].search([
            ('usage', '=', 'production'),
            ('warehouse_id', '=', warehouse.id)
        ], limit=1) or receipt_picking.location_dest_id

        # Tipo de operação de fabricação na filial
        picking_type = self.env['stock.picking.type'].search([
            ('warehouse_id', '=', warehouse.id),
            ('code', '=', 'mrp_operation')
        ], limit=1)

        if not picking_type:
            raise UserError(f"Tipo de operação de fabricação não encontrado para o armazém {warehouse.name}")

        # Lista de materiais - USA A MESMA BOM DA MATRIZ
        bom = self.bom_id
        if not bom:
            raise UserError(f"Nenhuma lista de materiais encontrada para {self.product_id.display_name}")

        # ⚠️ CALCULA O RATIO EXATO BASEADO NA QUANTIDADE ORIGINAL DA MATRIZ
        original_qty = self.product_qty
        ratio = qty / original_qty if original_qty > 0 else 1

        _logger.info(f"📊 Cálculo de quantidades: Matriz={original_qty}, Filial={qty}, Ratio={ratio}")

        # Valores para criar a OP filial
        mo_vals = {
            "product_id": self.product_id.id,
            "product_qty": qty,
            "product_uom_id": self.product_uom_id.id,
            "bom_id": bom.id,
            "location_src_id": receipt_picking.location_dest_id.id,
            "location_dest_id": production_loc.id,
            "picking_type_id": picking_type.id,
            "origin": f"{self.name} - Matriz",
            "origin_production_id": self.id,
            "branch_location_id": warehouse.lot_stock_id.id,
            "state": "draft",
            "sending_transfer_id": [(6, 0, self.sending_transfer_id.ids)],
            "branch_receipt_id": [(6, 0, [receipt_picking.id])],
        }

        # Cria a OP filial
        mo = self.env['mrp.production'].create(mo_vals)

        # ⚠️ ATUALIZA OS MOVIMENTOS COM QUANTIDADES EXATAS PROPORCIONAIS ÀS DA MATRIZ
        self._update_branch_mo_moves_exact(mo, ratio)

        # Vincula a OP filial a si mesma
        mo.write({
            'branch_production_id': [(4, mo.id)]
        })

        # Vincula a OP filial ao recebimento
        receipt_picking.write({
            'branch_mo_id': [(4, mo.id)]
        })

        # Vincula a OP filial à OP matriz
        self.write({
            'branch_production_id': [(4, mo.id)]
        })

        _logger.info(f"✅ OP filial criada: {mo.name} (qty={qty})")

        # Valida as quantidades
        self._validate_branch_mo_quantities_exact(mo, original_qty, qty, ratio)

        # Notifica a OP matriz
        self.message_post(
            body=f"⚙️ OP filial criada: "
                 f"<a href='/web#id={mo.id}&model=mrp.production'>{mo.name}</a> "
                 f"para {qty} unidades (Ratio: {ratio:.3f})."
        )

        return mo

    def _create_return_transfer(self):
        self.ensure_one()

        # ⚠️ VERIFICA SE É UMA OP FILIAL (tem origin_production_id)
        if not self.origin_production_id:
            raise UserError("Esta OP não é uma filial. Não é possível criar retorno.")

        # ⚠️ VERIFICA SE EXISTEM MOVIMENTOS DE PRODUTO FINALIZADO
        if not self.move_finished_ids:
            raise UserError("Não existem produtos finalizados para criar o retorno.")

        move_lines = []
        for move in self.move_finished_ids:
            if move.product_id.type != 'service' and move.product_qty > 0:
                move_lines.append((0, 0, {
                    "name": f"Retorno {move.product_id.display_name}",
                    "product_id": move.product_id.id,
                    "product_uom_qty": move.product_qty,
                    "product_uom": move.product_uom.id,
                    "location_id": self.location_src_id.id,  # Localização da filial
                    "location_dest_id": self.origin_production_id.location_dest_id.id,  # Localização da matriz
                }))

        # Encontra o tipo de operação para retorno
        picking_type = self.env['stock.picking.type'].search([
            ('warehouse_id', '=', self.location_dest_id.warehouse_id.id),
            ('code', '=', 'outgoing')  # ⚠️ MUDEI para 'outgoing' pois é saída da filial
        ], limit=1)

        if not picking_type:
            # Fallback: busca qualquer tipo de operação interna
            picking_type = self.env['stock.picking.type'].search([
                ('code', '=', 'outgoing'),
                ('company_id', '=', self.env.company.id)
            ], limit=1)

        if not picking_type:
            raise UserError("Tipo de operação de retorno não encontrado.")

        picking = self.env['stock.picking'].create({
            "location_id": self.location_src_id.id,  # Da filial
            "location_dest_id": self.origin_production_id.location_dest_id.id,  # Para matriz
            "origin": f"{self.name} - Retorno para Matriz",
            "move_ids_without_package": move_lines,
            "picking_type_id": picking_type.id,
            "custom_block_validate": False,  # ⚠️ Não bloqueia inicialmente
            "show_validate": True,
        })

        picking.action_confirm()
        picking.action_assign()

        _logger.info(f"✅ Transferência de retorno criada: {picking.name}")
        _logger.info(f"✅ De: {picking.location_id.name} → Para: {picking.location_dest_id.name}")

        return picking

    def _create_return_flow_automatically(self):
        """Cria fluxo de retorno automaticamente quando OP filial é concluída"""
        for record in self:
            # ⚠️ VERIFICA SE É UMA OP FILIAL
            if not record.origin_production_id:
                _logger.info(f"⚠️ OP {record.name} não é uma filial. Ignorando criação de retorno.")
                continue

            if record.return_transfer_id:
                _logger.warning(f"⚠️ OP {record.name} já possui retorno criado.")
                continue

            try:
                _logger.info(f"🔄 Criando fluxo de retorno para OP filial {record.name}")

                # Cria transferência de retorno
                return_picking = record._create_return_transfer()

                # Cria recebimento final na matriz
                final_receipt = record._create_final_receipt(return_picking)

                # ⚠️ CONFIGURA ORIGEM CORRETAMENTE PARA EVITAR CONFUSÃO
                final_receipt.write({
                    'custom_block_validate': True,
                    'show_validate': False,
                    'origin': f"{record.name} - Recebimento Final",  # ⚠️ ORIGEM CLARA
                })

                # ⚠️ VINCULA OS PICKINGS À OP FILIAL
                record.write({
                    'return_transfer_id': [(4, return_picking.id)],
                    'final_receipt_id': [(4, final_receipt.id)],
                })

                # ⚠️ VINCULA OS PICKINGS À OP MATRIZ TAMBÉM
                if record.origin_production_id:
                    record.origin_production_id.write({
                        'return_transfer_id': [(4, return_picking.id)],
                        'final_receipt_id': [(4, final_receipt.id)],
                    })

                # Atualiza estados
                record._compute_message_state()
                if record.origin_production_id:
                    record.origin_production_id._compute_message_state()

                _logger.info(f"✅ Retorno automático criado: {return_picking.name}")
                _logger.info(f"✅ Recebimento final criado: {final_receipt.name}")
                _logger.info(f"🔒 Recebimento na matriz BLOQUEADO até conclusão do envio da filial")

            except Exception as e:
                _logger.error(f"❌ Erro ao criar retorno automático para {record.name}: {str(e)}")
                # ⚠️ NÃO levanta UserError aqui para não bloquear a conclusão da OP
                record.message_post(
                    body=f"❌ Erro ao criar retorno automático: {str(e)}"
                )

    def _create_final_receipt(self, return_picking):
        self.ensure_one()

        # ⚠️ VERIFICA SE É UMA OP FILIAL
        if not self.origin_production_id:
            raise UserError("Esta OP não é uma filial. Não é possível criar recebimento final.")

        picking_type = self.env["stock.picking.type"].search([
            ("code", "=", "incoming"),
            ("warehouse_id", "=", self.origin_production_id.location_dest_id.warehouse_id.id)
        ], limit=1)

        if not picking_type:
            raise UserError("❌ Tipo de operação de recebimento não encontrado para a matriz")

        move_lines = []
        for move in return_picking.move_ids_without_package:
            move_lines.append((0, 0, {
                "name": f"Recebimento Final {move.product_id.display_name}",
                "product_id": move.product_id.id,
                "product_uom_qty": move.product_uom_qty,
                "product_uom": move.product_uom.id,
                "location_id": return_picking.location_id.id,
                "location_dest_id": return_picking.location_dest_id.id,
            }))

        picking = self.env["stock.picking"].create({
            "picking_type_id": picking_type.id,
            "location_id": return_picking.location_id.id,
            "location_dest_id": return_picking.location_dest_id.id,
            "origin": f"{self.name} - Recebimento Final",  # ⚠️ Usa origem da OP filial
            "move_ids_without_package": move_lines,
            "custom_block_validate": True,  # ⚠️ Bloqueado até envio ser concluído
            "show_validate": False,
            # ⚠️ NÃO vincula origin_production_id aqui - isso evita criação de nova OP
        })

        picking.action_confirm()
        picking.action_assign()

        # Vincula o recebimento final ao envio de retorno
        picking.write({
            'sending_transfer_id': [(4, return_picking.id)]
        })

        _logger.info(f"✅ Recebimento final criado: {picking.name}")

        return picking

    def _release_delivery_order(self):
        try:
            delivery_orders = self.env['stock.picking'].search([
                ('origin', 'ilike', self.name),
                ('picking_type_id.code', '=', 'outgoing'),
                ('state', 'in', ['assigned', 'confirmed'])
            ])

            for delivery in delivery_orders:
                if delivery.state in ['assigned', 'confirmed']:
                    delivery.message_post(
                        body=f"✅ Produção concluída. Ordem de entrega liberada para processamento."
                    )
                    _logger.info(f"✅ Ordem de entrega liberada: {delivery.name}")

            if delivery_orders:
                self.message_post(
                    body=f"<b>📦 Ordens de entrega liberadas:</b><br/>" +
                         "".join([f"• <a href='/web#id={do.id}&model=stock.picking'>{do.name}</a><br/>" for do in
                                  delivery_orders])
                )

        except Exception as e:
            _logger.error(f"❌ Erro ao liberar ordens de entrega: {str(e)}")

    @api.depends('cut_plan_id')
    def _compute_cut_plan_fields(self):
        for record in self:
            cut_plan = record.cut_plan_id
            if cut_plan:
                record.blue_I = cut_plan.blue_I
                record.blue_II = cut_plan.blue_II
                record.blue_h = cut_plan.blue_h
                record.blue_I_uom = cut_plan.blue_I_uom
                record.blue_II_uom = cut_plan.blue_II_uom
                record.blue_h_uom = cut_plan.blue_h_uom
                record.blue_advance = cut_plan.blue_advance
                record.blue_advance_uom = cut_plan.blue_advance_uom
                record.related_type = cut_plan.related_type
            else:
                record.update({
                    'blue_I': 0.0,
                    'blue_II': 0.0,
                    'blue_h': 0.0,
                    'blue_I_uom': False,
                    'blue_II_uom': False,
                    'blue_h_uom': False,
                    'blue_advance': 0.0,
                    'blue_advance_uom': False,
                    'related_type': False,
                })

    def _update_moves(self):
        for production in self:
            # ⚠️ SE FOR OP MATRIZ SENDO ENVIADA PARA FILIAL, PRESERVA AS QUANTIDADES ORIGINAIS
            if production.branch_location_id and not production.origin_production_id:
                _logger.info(
                    f"🛑 OP Matriz {production.name} com filial - preservando quantidades originais dos componentes")
                # NÃO FAZ NADA - preserva as quantidades existentes
                continue

            # ⚠️ PARA OP FILIAL: USA A QUANTIDADE DA PRÓPRIA OP, NÃO DA MATRIZ
            if production.origin_production_id:
                # OP filial - usa sua própria quantidade
                product_qty = production.product_qty
                bom = production.bom_id
                bom_product_qty = bom.product_qty or 1

                for move in production.move_raw_ids:
                    bom_line = bom.bom_line_ids.filtered(
                        lambda line: line.product_id == move.product_id
                    )
                    if bom_line:
                        # Calcula baseado na quantidade da OP filial
                        new_qty = bom_line.product_qty * product_qty / bom_product_qty
                        move.write({'product_uom_qty': new_qty})
                        _logger.info(f"📦 OP Filial {production.name}: {move.product_id.display_name} = {new_qty}")

                for move in production.move_finished_ids:
                    if move.product_id == production.product_id:
                        move.write({'product_uom_qty': product_qty})
            else:
                # OP matriz SEM filial - comportamento original
                for move in production.move_raw_ids:
                    bom_line = production.bom_id.bom_line_ids.filtered(
                        lambda line: line.product_id == move.product_id
                    )
                    if bom_line:
                        new_qty = bom_line.product_qty * production.product_qty / production.bom_id.product_qty
                        move.write({'product_uom_qty': new_qty})
                for move in production.move_finished_ids:
                    if move.product_id == production.product_id:
                        move.write({'product_uom_qty': production.product_qty})

    def action_check_flow_status(self):
        for record in self:
            messages = []
            if not record.branch_location_id:
                raise UserError("Esta OP não possui fluxo para filial configurado.")

            if record.sending_transfer_id:
                pending_sendings = record.sending_transfer_id.filtered(lambda s: s.state != 'done')
                if pending_sendings:
                    messages.append(f"❌ Envios pendentes para filial: {len(pending_sendings)}")
                else:
                    messages.append("✅ Todos os envios para filial concluídos")

            if record.branch_receipt_id:
                pending_receipts = record.branch_receipt_id.filtered(lambda r: r.state != 'done')
                if pending_receipts:
                    messages.append(f"❌ Recebimentos pendentes na filial: {len(pending_receipts)}")
                else:
                    messages.append("✅ Todos os recebimentos na filial concluídos")

            if record.branch_production_id:
                pending_productions = record.branch_production_id.filtered(lambda p: p.state != 'done')
                if pending_productions:
                    messages.append(f"❌ Produções pendentes na filial: {len(pending_productions)}")
                    for prod in pending_productions:
                        messages.append(f"   - {prod.name}: {prod.state}")
                else:
                    messages.append("✅ Todas as produções na filial concluídas")

            if record.return_transfer_id:
                pending_returns = record.return_transfer_id.filtered(lambda r: r.state != 'done')
                if pending_returns:
                    messages.append(f"❌ Retornos pendentes da filial: {len(pending_returns)}")
                    for ret in pending_returns:
                        messages.append(f"   - {ret.name}: {ret.state}")
                else:
                    messages.append("✅ Todos os retornos da filial concluídos")

            if record.final_receipt_id:
                pending_final = record.final_receipt_id.filtered(lambda f: f.state != 'done')
                if pending_final:
                    messages.append(f"❌ Recebimentos finais pendentes: {len(pending_final)}")
                else:
                    messages.append("✅ Todos os recebimentos finais concluídos")

            message = "Status do Fluxo Matriz-Filial:\n\n" + "\n".join(messages)
            raise UserError(message)

    def _can_receive_at_matrix(self):
        self.ensure_one()
        _logger.info(f"🔍 Verificando se pode receber na matriz para OP {self.name}")

        if not self.branch_location_id:
            _logger.info(f"✅ OP {self.name} não tem filial - pode receber")
            return True

        if self.branch_production_id:
            pending_productions = self.branch_production_id.filtered(lambda p: p.state != 'done')
            if pending_productions:
                pending_names = ", ".join(pending_productions.mapped('name'))
                _logger.warning(f"⏳ Produções pendentes na filial: {pending_names}")
                return False
            else:
                _logger.info(f"✅ Todas as produções na filial concluídas para OP {self.name}")

        if self.return_transfer_id:
            pending_returns = self.return_transfer_id.filtered(lambda r: r.state != 'done')
            if pending_returns:
                pending_names = ", ".join(pending_returns.mapped('name'))
                _logger.warning(f"⏳ Retornos pendentes da filial: {pending_names}")
                return False
            else:
                _logger.info(f"✅ Todos os retornos da filial concluídos para OP {self.name}")
        else:
            _logger.info(f"ℹ️ OP {self.name} não tem retornos da filial configurados")

        if self.branch_receipt_id:
            pending_receipts = self.branch_receipt_id.filtered(lambda r: r.state != 'done')
            if pending_receipts:
                pending_names = ", ".join(pending_receipts.mapped('name'))
                _logger.warning(f"⏳ Recebimentos pendentes na filial: {pending_names}")
                return False
            else:
                _logger.info(f"✅ Todos os recebimentos na filial concluídos para OP {self.name}")

        _logger.info(f"✅ OP {self.name} pode receber na matriz - todos os processos da filial concluídos")
        return True

    def _check_matrix_receipt_blockers(self):
        self.ensure_one()
        blockers = []

        if not self.branch_location_id:
            return blockers

        if self.branch_production_id:
            pending_productions = self.branch_production_id.filtered(lambda p: p.state != 'done')
            for prod in pending_productions:
                blockers.append(f"Produção pendente na filial: {prod.name} ({prod.state})")

        if self.return_transfer_id:
            pending_returns = self.return_transfer_id.filtered(lambda r: r.state != 'done')
            for ret in pending_returns:
                blockers.append(f"Envio pendente da filial: {ret.name} ({ret.state})")

        if self.branch_receipt_id:
            pending_receipts = self.branch_receipt_id.filtered(lambda r: r.state != 'done')
            for rec in pending_receipts:
                blockers.append(f"Recebimento pendente na filial: {rec.name} ({rec.state})")

        return blockers

    def _validate_branch_mo_quantities(self, branch_mo, original_qty, received_qty):
        """Valida se as quantidades da OP filial estão corretas"""
        self.ensure_one()

        if branch_mo.product_qty != received_qty:
            _logger.warning(f"⚠️ Quantidade OP filial incorreta: {branch_mo.product_qty} vs {received_qty}")
            branch_mo.write({'product_qty': received_qty})
            branch_mo._update_moves()

        # Verifica se a BOM é a mesma
        if branch_mo.bom_id != self.bom_id:
            _logger.warning(
                f"⚠️ BOM diferente: OP matriz={self.bom_id.display_name}, OP filial={branch_mo.bom_id.display_name}")

        # Log das quantidades dos componentes
        for move in branch_mo.move_raw_ids:
            bom_line = branch_mo.bom_id.bom_line_ids.filtered(
                lambda line: line.product_id == move.product_id
            )
            if bom_line:
                expected_qty = bom_line.product_qty * received_qty / branch_mo.bom_id.product_qty
                _logger.info(
                    f"📊 Componente {move.product_id.display_name}: Esperado={expected_qty}, Atual={move.product_uom_qty}")

                if abs(move.product_uom_qty - expected_qty) > 0.001:
                    _logger.warning(f"🔧 Ajustando quantidade do componente {move.product_id.display_name}")
                    move.write({'product_uom_qty': expected_qty})

    def _validate_before_branch_transfer(self):
        """Valida se a OP está em condições de ser enviada para filial"""
        self.ensure_one()

        errors = []

        # 1. Verifica estado - VERSÃO FLEXÍVEL
        allowed_states = ['confirmed']
        if self.state not in allowed_states:
            errors.append(f"OP deve estar 'Confirmada'. Estado atual: {self.state}")

        # 2. Verifica componentes consumidos
        consumed_moves = self.move_raw_ids.filtered(lambda m: m.quantity_done > 0)
        if consumed_moves:
            component_list = "\n".join([f"• {m.product_id.display_name}: {m.quantity_done}" for m in consumed_moves])
            errors.append(f"Componentes já consumidos:\n{component_list}")

        # 3. Verifica se já existe produção na filial
        if self.branch_production_id:
            errors.append(f"Já existem OPs filiais vinculadas: {', '.join(self.branch_production_id.mapped('name'))}")

        # 4. Verifica quantidades dos componentes
        for move in self.move_raw_ids:
            if move.product_uom_qty <= 0:
                errors.append(f"Componente {move.product_id.display_name} com quantidade zero ou negativa")

        if errors:
            error_message = "Não é possível enviar para filial:\n\n" + "\n".join(errors)
            raise UserError(error_message)

        return True

    def _update_branch_mo_moves_exact(self, branch_mo, ratio):
        """Atualiza movimentos da OP filial com quantidades exatas proporcionais às da matriz"""
        _logger.info(f"🔧 Atualizando movimentos OP filial {branch_mo.name} com ratio {ratio}")

        # ⚠️ REPLICA OS MOVIMENTOS DE MATÉRIA-PRIMA DA MATRIZ EXATAMENTE (PROPORCIONALMENTE)
        for origin_move in self.move_raw_ids:
            # Encontra o movimento correspondente na filial
            branch_move = branch_mo.move_raw_ids.filtered(
                lambda m: m.product_id == origin_move.product_id
            )

            if branch_move:
                # ⚠️ CALCULA QUANTIDADE EXATA PROPORCIONAL À MATRIZ
                exact_qty = origin_move.product_uom_qty * ratio
                branch_move.write({'product_uom_qty': exact_qty})

                _logger.info(f"📦 Componente {origin_move.product_id.display_name}: "
                             f"Matriz={origin_move.product_uom_qty}, "
                             f"Filial={exact_qty} (ratio={ratio})")

        # ⚠️ REPLICA OS MOVIMENTOS DE PRODUTO ACABADO
        for origin_move in self.move_finished_ids:
            if origin_move.product_id == self.product_id:
                branch_move = branch_mo.move_finished_ids.filtered(
                    lambda m: m.product_id == branch_mo.product_id
                )
                if branch_move:
                    branch_move.write({'product_uom_qty': branch_mo.product_qty})

    def _validate_branch_mo_quantities_exact(self, branch_mo, original_qty, received_qty, ratio):
        """Valida se as quantidades da OP filial estão exatamente proporcionais às da matriz"""
        self.ensure_one()

        _logger.info(f"🔍 Validando quantidades exatas: OP Matriz {self.name} -> OP Filial {branch_mo.name}")
        _logger.info(f"📊 Original: {original_qty}, Recebido: {received_qty}, Ratio: {ratio}")

        discrepancies = []

        # Verifica quantidade do produto principal
        if branch_mo.product_qty != received_qty:
            discrepancies.append(f"Quantidade produto: Esperado={received_qty}, Atual={branch_mo.product_qty}")
            branch_mo.write({'product_qty': received_qty})

        # Verifica componentes com quantidades exatas da matriz
        for branch_move in branch_mo.move_raw_ids:
            # Encontra o movimento correspondente na matriz
            origin_move = self.move_raw_ids.filtered(
                lambda m: m.product_id == branch_move.product_id
            )

            if origin_move:
                origin_move = origin_move[0]  # Pega o primeiro movimento correspondente
                expected_qty = origin_move.product_uom_qty * ratio

                # Tolerância de 0.001 para diferenças de arredondamento
                if abs(branch_move.product_uom_qty - expected_qty) > 0.001:
                    discrepancies.append(
                        f"Componente {branch_move.product_id.display_name}: "
                        f"Esperado={expected_qty:.3f} (Matriz: {origin_move.product_uom_qty} × {ratio}), "
                        f"Atual={branch_move.product_uom_qty:.3f}"
                    )
                    # ⚠️ CORRIGE A QUANTIDADE PARA SER EXATAMENTE PROPORCIONAL
                    branch_move.write({'product_uom_qty': expected_qty})
                    _logger.info(
                        f"🔧 Corrigido {branch_move.product_id.display_name}: {branch_move.product_uom_qty:.3f} -> {expected_qty:.3f}")

            else:
                _logger.warning(f"⚠️ Componente {branch_move.product_id.display_name} não encontrado na OP matriz")

        # Log do resultado
        if discrepancies:
            _logger.warning(f"⚠️ Discrepâncias corrigidas na OP {branch_mo.name}:")
            for disc in discrepancies:
                _logger.warning(f"   • {disc}")

            branch_mo.message_post(
                body=f"⚠️ Quantidades ajustadas para compatibilidade com OP matriz:<br/>" +
                     "<br/>".join([f"• {disc}" for disc in discrepancies])
            )
        else:
            _logger.info(f"✅ Quantidades da OP filial {branch_mo.name} validadas com sucesso")

    def action_recalculate_consumption(self):
        """Recalcula consumos baseado na BOM atual"""
        for record in self:
            _logger.warning(f"🔄 Recalculando consumo para OP: {record.name}")

            # Remove movimentos existentes
            record.move_raw_ids.filtered(lambda m: m.state in ['draft', 'confirmed']).unlink()

            # Força recálculo baseado na BOM
            record._onchange_bom_id()
            record._onchange_move_raw()

            _logger.warning(f"✅ Consumo recalculado para: {record.name}")

        return True