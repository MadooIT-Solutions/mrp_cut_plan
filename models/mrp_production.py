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

    # ------------------------------------------------------------
    # MÉTODOS COMPUTE
    # ------------------------------------------------------------
    @api.depends('state', 'branch_location_id', 'final_receipt_id')
    def _compute_is_waiting_return(self):
        for record in self:
            record.is_waiting_return = (
                    record.state == 'progress' and bool(record.branch_location_id) and not bool(record.final_receipt_id)
            )

    @api.depends('branch_location_id', 'origin_production_id')
    def _compute_is_branch_flow(self):
        """Define se esta OP faz parte de um fluxo matriz-filial"""
        for record in self:
            record.is_branch_flow = bool(record.branch_location_id or record.origin_production_id)

    @api.depends('product_qty', 'qty_producing', 'branch_location_id', 'origin_production_id', 'total_qty_received')
    def _compute_display_quantities(self):
        """Calcula as quantidades para exibição correta na interface"""
        for record in self:
            if record.origin_production_id:
                # OP FILIAL: Mostra quantidade normal
                record.display_product_qty = record.product_qty
                record.display_qty_producing = record.qty_producing
            elif record.branch_location_id:
                # OP MATRIZ COM FILIAL: Mostra quantidade recebida como produzindo
                record.display_product_qty = record.product_qty
                record.display_qty_producing = record.total_qty_received
            else:
                # OP NORMAL: Comportamento padrão
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

    # NOVOS MÉTODOS COMPUTE PARA CONSUMO
    @api.depends('move_raw_ids.quantity_done', 'state')
    def _compute_matrix_consumed_qty(self):
        """Calcula consumo apenas na matriz (OP principal)"""
        for record in self:
            if record.origin_production_id:
                # Se é OP filial, não tem consumo na matriz
                record.matrix_consumed_qty = 0.0
            else:
                # OP matriz - soma apenas moves confirmados/done
                total_consumed = 0.0
                for move in record.move_raw_ids:
                    if move.state in ['done', 'assigned'] and move.quantity_done > 0:
                        total_consumed += move.quantity_done
                record.matrix_consumed_qty = total_consumed

    @api.depends('branch_production_id', 'branch_production_id.move_raw_ids.quantity_done')
    def _compute_branch_consumed_qty(self):
        """Calcula consumo total nas filiais"""
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

            # 1️⃣ Backorders ou recebimentos pendentes
            pending_backorders = any(picking.state != 'done' for picking in record.sending_transfer_id)
            pending_receipts = any(picking.state != 'done' for picking in record.branch_receipt_id)
            if pending_backorders or pending_receipts:
                msg = "Aguardando confirmação de backorder/recebimento na filial."

            # 2️⃣ OPs da filial (múltiplas OPs)
            elif record.branch_production_id:
                production_states = record.branch_production_id.mapped('state')
                if all(s != 'done' for s in production_states):
                    msg = "Aguardando fabricação na filial (OPs pendentes)."

                # Antes do elif de OPs filiais
                if any(p.state not in ['done', 'cancel'] for p in
                       record.sending_transfer_id.filtered(lambda p: 'Backorder' in (p.origin or ''))):
                    msg = "Aguardando processamento de backorder na matriz/filial."


                elif any(s == 'done' for s in production_states) and not record.return_transfer_id:
                    msg = "Fabricação na filial concluída, aguardando retorno."
                    filial_flag = True


            # 3️⃣ Em trânsito de retorno
            elif record.return_transfer_id and any(r.state != 'done' for r in record.return_transfer_id):
                msg = "Em trânsito para a matriz."
                filial_flag = True

            # 4️⃣ Recebimento final
            elif record.final_receipt_id and any(f.state != 'done' for f in record.final_receipt_id):
                msg = "Recebimento final em andamento."

            # 5️⃣ Recebimento final concluído
            elif record.final_receipt_id and all(f.state == 'done' for f in record.final_receipt_id):
                if record.state == 'done':
                    msg = "Produção concluída. Aguardando envio para o cliente."
                else:
                    msg = "Recebido na matriz."

            record.message_state = msg
            if filial_flag and record.origin_production_id:
                record.origin_production_id.message_state = msg

    def button_send_to_branch(self):
        """Botão que envia OP para a filial"""
        for record in self:
            if record.related_type != 'm':
                raise UserError("Este botão só pode ser usado para Mold Calculation.")

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
        """Override para controle do fluxo com consumo separado"""
        for record in self:
            # Se for OP filial - comportamento normal
            if record.origin_production_id:
                # Verificar se todos os componentes foram consumidos
                for move in record.move_raw_ids:
                    if move.product_uom_qty > 0 and move.quantity_done <= 0:
                        raise UserError(
                            f"Componente {move.product_id.display_name} não consumido. "
                            f"Planejado: {move.product_uom_qty}, Consumido: {move.quantity_done}"
                        )

                res = super(BlueMrpProduction, record).button_mark_done()
                record._create_return_flow_automatically()
                return res

            # Se for OP matriz com filial
            if record.branch_location_id:
                # 1. Verificar se pode receber na matriz
                if not record._can_receive_at_matrix():
                    blockers = record._check_matrix_receipt_blockers()
                    blocker_message = "\n".join([f"• {b}" for b in blockers])
                    raise UserError(
                        f"Não é possível concluir a OP matriz enquanto existirem processos pendentes na filial:\n\n"
                        f"{blocker_message}"
                    )

                # 2. Verificar se quantidade total recebida é suficiente
                if record.total_qty_received < record.product_qty:
                    raise UserError(
                        f"Quantidade recebida ({record.total_qty_received}) é menor que a quantidade planejada ({record.product_qty}). "
                        f"Aguarde o recebimento total das filiais."
                    )

                # 3. ATUALIZAR moves finished com quantidade recebida
                for move in record.move_finished_ids:
                    if move.product_id == record.product_id:
                        move.write({
                            'product_uom_qty': record.total_qty_received,
                            'quantity_done': record.total_qty_received
                        })

                # 4. Atualizar quantidade produzida
                record.qty_producing = record.total_qty_received

                # 5. Liberar entrega e concluir
                record._release_delivery_order()

                # 6. Chamar super com a quantidade correta
                return super(BlueMrpProduction, record).button_mark_done()

            # OP matriz sem filial - comportamento normal
            return super(BlueMrpProduction, record).button_mark_done()

    def _can_receive_at_matrix(self):
        """Verifica se pode receber na matriz (todos os envios da filial concluídos)"""
        self.ensure_one()

        # Se não tem filial, pode receber normalmente
        if not self.branch_location_id:
            return True

        # Verificar se todas as produções da filial estão concluídas
        if self.branch_production_id:
            pending_productions = self.branch_production_id.filtered(lambda p: p.state != 'done')
            if pending_productions:
                pending_names = ", ".join(pending_productions.mapped('name'))
                _logger.warning(f"⏳ Produções pendentes na filial: {pending_names}")
                return False

        # Verificar se todos os retornos da filial estão concluídos
        if self.return_transfer_id:
            pending_returns = self.return_transfer_id.filtered(lambda r: r.state != 'done')
            if pending_returns:
                pending_names = ", ".join(pending_returns.mapped('name'))
                _logger.warning(f"⏳ Retornos pendentes da filial: {pending_names}")
                return False

        # Verificar se todos os recebimentos na filial estão concluídos
        if self.branch_receipt_id:
            pending_receipts = self.branch_receipt_id.filtered(lambda r: r.state != 'done')
            if pending_receipts:
                pending_names = ", ".join(pending_receipts.mapped('name'))
                _logger.warning(f"⏳ Recebimentos pendentes na filial: {pending_names}")
                return False

        return True

    def _calculate_total_required_consumption(self):
        """Calcula o consumo total requerido baseado na BoM"""
        self.ensure_one()
        total_required = 0.0
        if self.bom_id:
            for line in self.bom_id.bom_line_ids:
                # Calcular quantidade total requerida para a produção
                line_qty = line.product_qty * self.product_qty / self.bom_id.product_qty
                total_required += line_qty
        return total_required

    def _create_backorder_transfer(self, backorder_qty):
        """Cria transferência interna da matriz para filial quando backorder é criado na filial"""
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
            "custom_block_validate": False,  # Não bloquear - permite processamento imediato
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
        """Cria recebimento na filial para backorder"""
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
        self.ensure_one()
        picking = receipt_picking or self.branch_receipt_id
        if not picking:
            raise UserError("Não existe picking de recebimento definido.")

        # Verificar se já existe uma OP para este picking
        if picking.branch_mo_id:
            _logger.info(f"⚠️ Já existe OP {picking.branch_mo_id.name} vinculada ao picking {picking.name}")
            # Se já existe, atualiza a quantidade se necessário
            if picking.branch_mo_id.product_qty != qty:
                picking.branch_mo_id.write({'product_qty': qty})
                # Atualizar moves manualmente
                picking.branch_mo_id._update_moves()
            return picking.branch_mo_id

        warehouse = picking.location_dest_id.warehouse_id

        # Encontrar local de produção na filial
        production_loc = self.env['stock.location'].search([
            ('usage', '=', 'production'),
            ('warehouse_id', '=', warehouse.id)
        ], limit=1)
        if not production_loc:
            # Se não encontrar, usar o local de destino do picking
            production_loc = picking.location_dest_id
            _logger.warning(f"Usando local de destino como produção: {production_loc.display_name}")

        picking_type = self.env['stock.picking.type'].search([
            ('warehouse_id', '=', warehouse.id),
            ('code', '=', 'mrp_operation')
        ], limit=1)
        if not picking_type:
            raise UserError(f"Tipo de operação de fabricação não encontrado para o armazém {warehouse.name}")

        # Usar a mesma lista de materiais da OP matriz
        bom = self.bom_id
        if not bom:
            bom = self.env['mrp.bom']._bom_find(product=self.product_id)
        if not bom:
            raise UserError(f"Nenhuma lista de materiais encontrada para {self.product_id.display_name}")

        # Criar a OP usando create do modelo - maneira mais simples e compatível
        mo_vals = {
            "product_id": self.product_id.id,
            "product_qty": qty,
            "product_uom_id": self.product_uom_id.id,
            "bom_id": bom.id,
            "location_src_id": picking.location_dest_id.id,  # componentes saem do estoque da filial
            "location_dest_id": production_loc.id,  # produção na filial
            "picking_type_id": picking_type.id,
            "sending_transfer_id": self.sending_transfer_id,
            "branch_receipt_id": self.branch_receipt_id,
            "origin": f"{self.name} - Matriz",
            "origin_production_id": self.id,
        }

        # Criar a OP - o Odoo vai automaticamente gerar os moves ao confirmar
        mo = self.env['mrp.production'].create(mo_vals)

        # Confirmar a OP para gerar os movimentos automaticamente
        mo.action_confirm()

        # Verificar se os moves foram criados
        if not mo.move_raw_ids:
            _logger.warning(f"⚠️ Moves de componentes não criados automaticamente para OP {mo.name}")
            # Criar moves manualmente se necessário
            mo._generate_moves()

        mo.write({'branch_production_id': [(4, mo.id)]})

        self.origin_production_id.branch_production_id = [(4, mo.id)]

        # Vincular a OP ao picking
        picking.write({'branch_mo_id': mo.id, 'branch_production_id': [(4, mo.id)]})

        _logger.info(f"✅ OP filial criada: {mo.name} para quantidade {qty} com BoM {bom.display_name}")

        # Atualizar estado e mensagens da OP matriz
        if self.origin_production_id:
            self.origin_production_id._compute_message_state()
            self.origin_production_id.message_post(
                body=f"⚙️ Nova OP criada na filial: <a href='/web#id={mo.id}&model=mrp.production'>{mo.name}</a> "
                     f"para {qty} unidades."
            )

        return mo

    def _release_delivery_order(self):
        """Libera ordem de entrega para o cliente quando OP é concluída"""
        try:
            # Buscar ordens de entrega relacionadas a esta OP
            delivery_orders = self.env['stock.picking'].search([
                ('origin', 'ilike', self.name),
                ('picking_type_id.code', '=', 'outgoing'),
                ('state', 'in', ['assigned', 'confirmed'])
            ])

            for delivery in delivery_orders:
                # Se a entrega estava esperando a produção, liberar para processamento
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



    # Retorno Filial para Matriz #######
    def _create_return_transfer(self):
        self.ensure_one()
        if not self.branch_production_id:
            raise UserError("Não existe OP filial para criar retorno.")

        move_lines = []
        for move in self.move_finished_ids:
            if move.product_id.type != 'service' and move.product_qty > 0:
                move_lines.append((0, 0, {
                    "name": f"Retorno {move.product_id.display_name}",
                    "product_id": move.product_id.id,
                    "product_uom_qty": move.product_qty,
                    "product_uom": move.product_uom.id,
                    "location_id": self.origin_production_id.branch_location_id.id,
                    "location_dest_id": self.location_dest_id.id,
                }))

        picking_type = self.env['stock.picking.type'].search([
            ('warehouse_id', '=', self.location_dest_id.warehouse_id.id),
            ('code', '=', 'internal')
        ], limit=1)
        if not picking_type:
            raise UserError("Tipo de operação de retorno interno não encontrado.")

        picking = self.env['stock.picking'].create({
            "location_id": self.origin_production_id.branch_location_id.id,
            "location_dest_id": self.location_dest_id.id,
            "origin": f"{self.name} - Retorno para Matriz",
            "move_ids_without_package": move_lines,
            "picking_type_id": picking_type.id,
        })
        picking.action_confirm()
        picking.action_assign()
        return picking



    @api.depends('cut_plan_id')
    def _compute_cut_plan_fields(self):
        """Calcular campos relacionados ao cut_plan"""
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
        """Atualiza os moves quando a quantidade da OP é alterada"""
        for production in self:
            # Para moves de componentes (raw)
            for move in production.move_raw_ids:
                # Encontrar a linha correspondente na BoM
                bom_line = production.bom_id.bom_line_ids.filtered(
                    lambda line: line.product_id == move.product_id
                )
                if bom_line:
                    new_qty = bom_line.product_qty * production.product_qty / production.bom_id.product_qty
                    move.write({'product_uom_qty': new_qty})

            # Para moves de produtos acabados (finished)
            for move in production.move_finished_ids:
                if move.product_id == production.product_id:
                    move.write({'product_uom_qty': production.product_qty})

    # NOVO MÉTODO para verificar status do fluxo
    def action_check_flow_status(self):
        """Verifica o status completo do fluxo matriz-filial"""
        for record in self:
            messages = []

            if not record.branch_location_id:
                raise UserError("Esta OP não possui fluxo para filial configurado.")

            # Verificar envios para filial
            if record.sending_transfer_id:
                pending_sendings = record.sending_transfer_id.filtered(lambda s: s.state != 'done')
                if pending_sendings:
                    messages.append(f"❌ Envios pendentes para filial: {len(pending_sendings)}")
                else:
                    messages.append("✅ Todos os envios para filial concluídos")

            # Verificar recebimentos na filial
            if record.branch_receipt_id:
                pending_receipts = record.branch_receipt_id.filtered(lambda r: r.state != 'done')
                if pending_receipts:
                    messages.append(f"❌ Recebimentos pendentes na filial: {len(pending_receipts)}")
                else:
                    messages.append("✅ Todos os recebimentos na filial concluídos")

            # Verificar produções na filial
            if record.branch_production_id:
                pending_productions = record.branch_production_id.filtered(lambda p: p.state != 'done')
                if pending_productions:
                    messages.append(f"❌ Produções pendentes na filial: {len(pending_productions)}")
                    for prod in pending_productions:
                        messages.append(f"   - {prod.name}: {prod.state}")
                else:
                    messages.append("✅ Todas as produções na filial concluídas")

            # Verificar retornos da filial
            if record.return_transfer_id:
                pending_returns = record.return_transfer_id.filtered(lambda r: r.state != 'done')
                if pending_returns:
                    messages.append(f"❌ Retornos pendentes da filial: {len(pending_returns)}")
                    for ret in pending_returns:
                        messages.append(f"   - {ret.name}: {ret.state}")
                else:
                    messages.append("✅ Todos os retornos da filial concluídos")

            # Verificar recebimentos finais
            if record.final_receipt_id:
                pending_final = record.final_receipt_id.filtered(lambda f: f.state != 'done')
                if pending_final:
                    messages.append(f"❌ Recebimentos finais pendentes: {len(pending_final)}")
                else:
                    messages.append("✅ Todos os recebimentos finais concluídos")

            message = "Status do Fluxo Matriz-Filial:\n\n" + "\n".join(messages)
            raise UserError(message)

    def _can_receive_at_matrix(self):
        """Verifica se pode receber na matriz (todos os envios da filial concluídos)"""
        self.ensure_one()

        _logger.info(f"🔍 Verificando se pode receber na matriz para OP {self.name}")

        # Se não tem filial, pode receber normalmente
        if not self.branch_location_id:
            _logger.info(f"✅ OP {self.name} não tem filial - pode receber")
            return True

        # Verificar se todas as produções da filial estão concluídas
        if self.branch_production_id:
            pending_productions = self.branch_production_id.filtered(lambda p: p.state != 'done')
            if pending_productions:
                pending_names = ", ".join(pending_productions.mapped('name'))
                _logger.warning(f"⏳ Produções pendentes na filial: {pending_names}")
                return False
            else:
                _logger.info(f"✅ Todas as produções na filial concluídas para OP {self.name}")

        # Verificar se todos os retornos da filial estão concluídos
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

        # Verificar se todos os recebimentos na filial estão concluídos
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
        """Retorna lista de bloqueios para recebimento na matriz"""
        self.ensure_one()
        blockers = []

        if not self.branch_location_id:
            return blockers

        # Verificar produções pendentes
        if self.branch_production_id:
            pending_productions = self.branch_production_id.filtered(lambda p: p.state != 'done')
            for prod in pending_productions:
                blockers.append(f"Produção pendente na filial: {prod.name} ({prod.state})")

        # Verificar retornos pendentes
        if self.return_transfer_id:
            pending_returns = self.return_transfer_id.filtered(lambda r: r.state != 'done')
            for ret in pending_returns:
                blockers.append(f"Envio pendente da filial: {ret.name} ({ret.state})")

        # Verificar recebimentos pendentes
        if self.branch_receipt_id:
            pending_receipts = self.branch_receipt_id.filtered(lambda r: r.state != 'done')
            for rec in pending_receipts:
                blockers.append(f"Recebimento pendente na filial: {rec.name} ({rec.state})")

        return blockers

    # NO MÉTODO _create_return_flow_automatically, ATUALIZE para criar dependência
    def _create_return_flow_automatically(self):
        """Cria fluxo de retorno automaticamente quando OP filial é concluída"""
        for record in self:
            if not record.origin_production_id:
                continue  # só faz sentido para OPs filiais

            # Evita duplicado
            if record.return_transfer_id or record.final_receipt_id:
                _logger.warning(f"⚠️ OP {record.name} já possui retorno criado.")
                continue

            try:
                return_picking = record._create_return_transfer()
                final_receipt = record._create_final_receipt(return_picking)

                # VINCULAR OS PICKINGS COMO DEPENDENTES
                # O recebimento na matriz depende do envio da filial
                final_receipt.write({
                    'sending_transfer_id': [(4, return_picking.id)],  # Vincula o envio da filial
                    'custom_block_validate': True,  # Bloqueia até o envio ser concluído
                    'show_validate': False,  # Oculta botão de validar
                })

                return_picking.write({
                    'branch_receipt_id': [(4, final_receipt.id)],  # Vincula o recebimento da matriz
                })

                # note: return_picking and final_receipt são pickings (recordset), pode ser vários; aqui assumimos únicos
                record.write({
                    'return_transfer_id': [(4, return_picking.id)] if return_picking else False,
                    'final_receipt_id': [(4, final_receipt.id)] if final_receipt else False,
                })

                # também atualiza a OP de origem (matriz)
                if record.origin_production_id:
                    record.origin_production_id.write({
                        'return_transfer_id': [(4, return_picking.id)] if return_picking else False,
                        'final_receipt_id': [(4, final_receipt.id)] if final_receipt else False,
                    })

                # Forçar recálculo e persistência do campo armazenado message_state
                record._compute_message_state()
                if record.origin_production_id:
                    record.origin_production_id._compute_message_state()

                record.write({'message_state': record.message_state})
                if record.origin_production_id:
                    record.origin_production_id.write({'message_state': record.origin_production_id.message_state})

                _logger.info(f"✅ Retorno automático criado: {return_picking.name}")
                _logger.info(f"✅ Recebimento final criado: {final_receipt.name}")
                _logger.info(f"🔒 Recebimento na matriz BLOQUEADO até conclusão do envio da filial")

            except Exception as e:
                _logger.error(f"❌ Erro ao criar retorno automático: {str(e)}")
                raise UserError(f"Erro ao criar retorno automático: {str(e)}")

    # ATUALIZE o método _create_final_receipt para incluir bloqueio inicial
    def _create_final_receipt(self, return_picking):
        self.ensure_one()
        """Cria recebimento final na matriz"""
        picking_type = self.env["stock.picking.type"].search([
            ("code", "=", "incoming"),
            ("warehouse_id.name", "=", "Polispan")
        ], limit=1)

        if not picking_type:
            raise UserError("❌ Tipo de operação de recebimento não encontrado para Polispan")

        move_lines = [(0, 0, {
            "name": f"Recebimento Final {move.product_id.display_name}",
            "product_id": move.product_id.id,
            "product_uom_qty": move.product_uom_qty,
            "product_uom": move.product_uom.id,
            "location_id": return_picking.location_id.id,
            "location_dest_id": return_picking.location_dest_id.id,
        }) for move in return_picking.move_ids_without_package]

        picking = self.env["stock.picking"].create({
            "picking_type_id": picking_type.id,
            "location_id": return_picking.location_id.id,
            "location_dest_id": return_picking.location_dest_id.id,
            "origin": f"{self.name} - Recebimento Final",
            "move_ids_without_package": move_lines,
            "custom_block_validate": True,  # BLOQUEADO inicialmente
            "show_validate": False,  # Oculta botão de validar
        })

        picking.action_confirm()
        picking.action_assign()

        # Vincular o recebimento ao envio da filial
        picking.write({
            'sending_transfer_id': [(4, return_picking.id)]
        })

        return picking