# mrp_production.py (corrigido)
from collections import defaultdict
from odoo import fields, models, api, _, Command
from odoo.exceptions import UserError
from odoo.tools import float_round, float_is_zero
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
        related='cut_plan_id.blue_I'

    )

    blue_II = fields.Float(
        string="L ",
        digits='Product Unit of Measure',
        related='cut_plan_id.blue_II'

    )

    blue_h = fields.Float(
        string="H",
        digits='Product Unit of Measure',
        related='cut_plan_id.blue_h'

    )

    blue_I_uom = fields.Many2one(
        comodel_name="uom.uom",
        string="Uom ",
        related='cut_plan_id.blue_I_uom'

    )

    blue_II_uom = fields.Many2one(
        comodel_name="uom.uom",
        string="Uom  ",
        related='cut_plan_id.blue_II_uom'

    )

    blue_h_uom = fields.Many2one(
        comodel_name="uom.uom",
        string="Uom   ",
        related='cut_plan_id.blue_h_uom'

    )

    blue_m2 = fields.Float(string="M²", related='cut_plan_id.blue_m2')
    blue_m3 = fields.Float(string="M³", related='cut_plan_id.blue_m3')

    sale_order_id = fields.Many2one(
        comodel_name="sale.order",
        string="Pedido",
        tracking=True
    )

    blue_advance = fields.Float(
        string="Advance",
        digits='Product Unit of Measure',
        related='cut_plan_id.blue_advance'

    )

    blue_advance_uom = fields.Many2one(
        comodel_name="uom.uom",
        string="Udm",
        related='cut_plan_id.blue_advance_uom'

    )

    related_type = fields.Selection(
        selection=[
            ("n", "None"),
            ("llh", "LLH Calculation"),
            ("m", "Mold Calculation")
        ],
        string="Related Type",
        store=True
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

    # NOVO: Campo para mostrar SÓ os movimentos consumidos na(s) FILIAL(IS) - opção F2
    component_moves_branch_ids = fields.Many2many(
        comodel_name='stock.move',
        string='Movimentos Consumidos na Filial',
        compute='_compute_component_moves_branch',
        store=False,
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

    def _compute_count_po(self):
        for record in self:
            record.count_po = 1 if record.cut_plan_id else 0

    @api.depends('company_id', 'bom_id', 'product_id', 'product_qty', 'product_uom_id', 'location_src_id')
    def _compute_move_raw_ids(self):
        """Override para preservar quantidades manuais"""
        # Para cada produção, processa individualmente
        for production in self:
            if production.state != 'draft' or self.env.context.get('skip_compute_move_raw_ids'):
                continue

            # ⚠️ BLOQUEIO: Não recalcula componentes para OPs com filial EXCETO na criação inicial
            if (production.origin_production_id or production.branch_location_id) and production.move_raw_ids:
                _logger.warning(f"🚫 _compute_move_raw_ids BLOQUEADO para OP com filial: {production.name}")
                continue

            # Armazena quantidades manuais antes de qualquer processamento
            manual_moves_data = []
            for move in production.move_raw_ids:
                if not float_is_zero(move.quantity_done, precision_rounding=move.product_uom.rounding):
                    manual_moves_data.append({
                        'product_id': move.product_id.id,
                        'quantity_done': move.quantity_done,
                        'bom_line_id': move.bom_line_id.id if move.bom_line_id else False
                    })

            # Executa a lógica padrão do Odoo
            if not production.bom_id and not production._origin.product_id:
                # Mantém movimentos manuais
                pass
            elif any(move.bom_line_id.bom_id != production.bom_id or move.bom_line_id._skip_bom_line(
                    production.product_id)
                     for move in production.move_raw_ids if move.bom_line_id):
                production.move_raw_ids = [Command.clear()]

            if production.bom_id and production.product_id and production.product_qty > 0:
                # Mantém entradas manuais
                list_move_raw = [Command.link(move.id) for move in
                                 production.move_raw_ids.filtered(lambda m: not m.bom_line_id)]
                moves_raw_values = production._get_moves_raw_values()
                move_raw_dict = {move.bom_line_id.id: move for move in
                                 production.move_raw_ids.filtered(lambda m: m.bom_line_id)}

                for move_raw_values in moves_raw_values:
                    if move_raw_values['bom_line_id'] in move_raw_dict:
                        list_move_raw += [
                            Command.update(move_raw_dict[move_raw_values['bom_line_id']].id, move_raw_values)]
                    else:
                        list_move_raw += [Command.create(move_raw_values)]
                production.move_raw_ids = list_move_raw
            else:
                production.move_raw_ids = [Command.delete(move.id) for move in
                                           production.move_raw_ids.filtered(lambda m: m.bom_line_id)]

            # Restaura quantidades manuais
            for manual_data in manual_moves_data:
                # Encontra o movimento correspondente
                corresponding_move = production.move_raw_ids.filtered(
                    lambda m: m.product_id.id == manual_data['product_id'] and
                              (m.bom_line_id.id if m.bom_line_id else False) == manual_data['bom_line_id']
                )
                if corresponding_move:
                    corresponding_move.quantity_done = manual_data['quantity_done']

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
                # OP FILIAL - mostra quantidades normais
                record.display_product_qty = record.product_qty
                record.display_qty_producing = record.qty_producing
            elif record.branch_location_id:
                # OP MATRIZ COM FILIAL - mostra quantidade recebida como produzida
                record.display_product_qty = record.product_qty
                record.display_qty_producing = record.total_qty_received
            else:
                # OP NORMAL - mostra quantidades padrão
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
                # OP filial - consumo é zero na matriz
                record.matrix_consumed_qty = 0.0
            elif record.branch_location_id:
                # ⚠️ OP matriz com filial - calcula consumo REAL (não mais zero)
                total_consumed = 0.0
                for move in record.move_raw_ids:
                    if move.state in ['done', 'assigned'] and move.quantity_done > 0:
                        total_consumed += move.quantity_done
                record.matrix_consumed_qty = total_consumed
                _logger.info(f"📊 Consumo matriz com filial {record.name}: {total_consumed}")
            else:
                # OP normal sem filial - calcula consumo normal
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

    @api.depends('related_type', 'branch_location_id')
    def _compute_hide_check_availability(self):
        for record in self:
            record.hide_check_availability = (record.related_type == 'm' or bool(record.branch_location_id))

    # -------------------------
    # Component moves computes
    # -------------------------
    @api.depends('move_raw_ids.quantity_done', 'branch_production_id.move_raw_ids.quantity_done')
    def _compute_component_moves(self):
        """
        Consolida movimentos consumidos — matriz + filiais.
        Agora inclui consumo REAL tanto na matriz quanto nas filiais.
        """
        StockMove = self.env['stock.move']
        for production in self:
            moves = StockMove.browse()

            # 1) movimentos da matriz com consumo REAL (quantity_done > 0)
            mat_moves = production.move_raw_ids.filtered(lambda m: m.quantity_done > 0)
            moves |= mat_moves

            # 2) movimentos das OPs da filial com consumo REAL (quantity_done > 0)
            if production.branch_production_id:
                for branch_mo in production.branch_production_id:
                    bm = branch_mo.move_raw_ids.filtered(lambda m: m.quantity_done > 0)
                    # para cada movimento da filial, garantir que a location exibida reflete a filial
                    for m in bm:
                        try:
                            # Só altera location_id se o movimento ainda não estiver 'done' (evita inconsistências contábeis)
                            if m.state != 'done' and m.location_id != branch_mo.location_src_id:
                                m.write({'location_id': branch_mo.location_src_id.id})
                        except Exception as err:
                            _logger.debug(f"Não foi possível ajustar location_id do move {m.id}: {err}")
                    moves |= bm

            production.component_moves_ids = moves

    @api.depends('branch_production_id', 'branch_production_id.move_raw_ids')
    def _compute_component_moves_branch(self):
        """Somente movimentos consumidos nas filiais (para exibir em seção separada F2)"""
        StockMove = self.env['stock.move']
        for production in self:
            branch_moves = StockMove.browse()
            if production.branch_production_id:
                for branch_mo in production.branch_production_id:
                    bm = branch_mo.move_raw_ids.filtered(lambda m: m.quantity_done > 0)
                    # opcional: garantir que location exibida seja a location_src_id da filial
                    # (não escrevemos em DB — apenas retornamos os movimentos)
                    branch_moves |= bm
            production.component_moves_branch_ids = branch_moves

    # -------------------------
    # Validações / ações importantes
    # -------------------------
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

            # # ⚠️ VERIFICA SE HÁ COMPONENTES JÁ CONSUMIDOS
            # consumed_components = record.move_raw_ids.filtered(
            #     lambda m: m.quantity_done > 0
            # )
            # if consumed_components:
            #     component_names = ", ".join(consumed_components.mapped('product_id.display_name'))
            #     raise UserError(
            #         f"Não é possível enviar para filial com componentes já consumidos:\n\n"
            #         f"• {component_names}\n\n"
            #         f"Zere as quantidades consumidas antes do envio."
            #     )
            #
            # # ⚠️ VERIFICA SE A OP ESTÁ NO ESTADO CORRETO
            # if record.state != 'confirmed':
            #     raise UserError(
            #         f"A OP deve estar no estado 'Confirmado' para envio à filial. Estado atual: {record.state}"
            #     )

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

    def _pre_button_mark_done(self):
        """Override para manter quantidades manuais no popup"""
        # Armazenar quantidades manuais antes do popup
        manual_consumptions = {}
        for production in self:
            for move in production.move_raw_ids:
                if not float_is_zero(move.quantity_done, precision_rounding=move.product_uom.rounding):
                    manual_consumptions[move.id] = move.quantity_done

        # Chamar método original
        result = super(BlueMrpProduction, self)._pre_button_mark_done()

        # Restaurar quantidades manuais após popup
        for move_id, qty_done in manual_consumptions.items():
            move = self.env['stock.move'].browse(move_id)
            if move.exists() and float_is_zero(move.quantity_done, precision_rounding=move.product_uom.rounding):
                move.quantity_done = qty_done

        return result

    def button_mark_done(self):
        for record in self:
            record._force_preserve_consumption()

            # ⚠️ BLOQUEIO CRÍTICO: OP MATRIZ não pode ser concluída sem receber todos os produtos da filial
            if record.branch_location_id and not record.origin_production_id:
                # Verifica se quantidade recebida é menor que a quantidade planejada
                if record.total_qty_received < record.product_qty:
                    raise UserError(
                        f"❌ Não é possível concluir a OP matriz!\n\n"
                        f"Quantidade recebida da filial: {record.total_qty_received}\n"
                        f"Quantidade planejada: {record.product_qty}\n\n"
                        f"Aguarde o recebimento completo de todas as unidades da filial antes de concluir a OP matriz."
                    )

                # Verifica se há processos pendentes no fluxo filial
                pending_processes = record._check_matrix_receipt_blockers()
                if pending_processes:
                    blocker_message = "\n".join([f"• {b}" for b in pending_processes])
                    raise UserError(
                        f"❌ Não é possível concluir a OP matriz!\n\n"
                        f"Ainda existem processos pendentes no fluxo filial:\n\n"
                        f"{blocker_message}\n\n"
                        f"Finalize todas as operações antes de validar a OP matriz."
                    )

            if record.origin_production_id and record.sending_transfer_id and record.branch_receipt_id:
                # ⚠️ OP FILIAL - comportamento normal
                _logger.info(f"🔄 Concluindo OP filial {record.name}")

                # ⚠️ GARANTE QUE O PRODUTO FINALIZADO TEM A QUANTIDADE CORRETA
                if record.move_finished_ids:
                    for move in record.move_finished_ids:
                        if move.product_id == record.product_id:
                            move.write({
                                'product_uom_qty': record.product_qty,
                                'quantity_done': record.qty_producing
                            })

                # ⚠️ VALIDAÇÃO: Verifica se a quantidade produzida é consistente
                if record.qty_producing <= 0:
                    raise UserError("Não é possível concluir a OP filial com quantidade produzida zero.")

                res = super(BlueMrpProduction, record).button_mark_done()

                try:
                    record._create_return_flow_automatically()
                except Exception as e:
                    _logger.error(f"❌ Erro no fluxo de retorno, mas OP foi concluída: {str(e)}")

                return res

            if record.branch_location_id:
                # ⚠️ OP MATRIZ COM FILIAL
                _logger.info(f"🔧 OP Matriz {record.name} - Concluindo após validações")

                # ⚠️ APENAS GARANTE QUE O PRODUTO FINALIZADO TEM A QUANTIDADE CORRETA
                qty_to_record = min(record.total_qty_received, record.product_qty)
                record.qty_producing = qty_to_record

                for move in record.move_finished_ids:
                    if move.product_id == record.product_id:
                        move.write({
                            'quantity_done': qty_to_record
                        })

                record._release_delivery_order()
                return super(BlueMrpProduction, record).button_mark_done()

            # ⚠️ OP NORMAL (SEM FILIAL) - COMPORTAMENTO PADRÃO
            _logger.info(f"📦 Concluindo OP normal {record.name}")
            return super(BlueMrpProduction, record).button_mark_done()

    def _clean_matrix_components(self):
        """Limpa completamente os componentes de consumo na OP matriz"""
        self.ensure_one()

        if self.branch_location_id and not self.origin_production_id:
            _logger.info(f"🧹 Limpando componentes da OP matriz {self.name}")

            # Para cada movimento de componente, zera as quantidades
            for move in self.move_raw_ids:
                if move.state in ['draft', 'confirmed', 'assigned']:
                    move.write({
                        'product_uom_qty': 0.0,
                        'quantity_done': 0.0
                    })
                    _logger.info(f"   ✅ Componente zerado: {move.product_id.display_name}")

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

        # ✅ DESCRIÇÃO IGUAL AO PEDIDO DE VENDA
        product_description = self._get_sale_order_description(self.origin_production_id)

        move_lines = [(0, 0, {
            "name": product_description,  # ✅ DESCRIÇÃO IDÊNTICA AO PEDIDO DE VENDA
            "product_id": self.product_id.id,
            "product_uom_qty": backorder_qty,
            "product_uom": self.product_uom_id.id,
            "location_id": self.location_src_id.id,
            "location_dest_id": self.branch_location_id.id,
            "description_picking": product_description,  # ✅ DESCRIÇÃO ADICIONAL
        })]

        picking = self.env['stock.picking'].create({
            "picking_type_id": picking_type.id,
            "location_id": self.location_src_id.id,
            "location_dest_id": self.branch_location_id.id,
            "origin": f"{self.name} - Backorder",
            "move_ids_without_package": move_lines,
            "custom_block_validate": False,
            "sale_id": self.origin_production_id.sale_id.id,
            "partner_id": self.origin_production_id.partner_id.id,
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

        # ✅ DESCRIÇÃO IGUAL AO PEDIDO DE VENDA
        product_description = self._get_sale_order_description(self.origin_production_id)

        receiving = self.env['stock.picking'].create({
            "picking_type_id": picking_type.id,
            "location_id": sending_picking.location_id.id,
            "location_dest_id": self.branch_location_id.id,
            "origin": f"{self.name} - Backorder Recebimento",
            "move_ids_without_package": [(0, 0, {
                "name": product_description,  # ✅ DESCRIÇÃO IDÊNTICA AO PEDIDO DE VENDA
                "product_id": self.product_id.id,
                "product_uom_qty": qty,
                "product_uom": self.product_uom_id.id,
                "location_id": sending_picking.location_id.id,
                "location_dest_id": self.branch_location_id.id,
                "description_picking": product_description,  # ✅ DESCRIÇÃO ADICIONAL
            })],
            "show_validate": False,
            "custom_block_validate": True,
            "sending_transfer_id": [(4, sending_picking.id)],
            "sale_id": self.origin_production_id.sale_id.id,
            "partner_id": self.origin_production_id.partner_id.id,
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


        original_qty = self.product_qty


        _logger.info(f"📊 Cálculo de quantidades: Matriz={original_qty}, Filial={qty}")

        # Valores para criar a OP filial
        mo_vals = {
            "product_id": self.product_id.id,
            "product_qty": qty,
            "product_uom_id": self.product_uom_id.id,
            "bom_id": bom.id,
            'cut_plan_id': self.origin_production_id.cut_plan_id.id,
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

        # ⚠️ FORÇA a criação dos movimentos de componentes (chama compute uma vez)
        _logger.warning(f"🔧 FORÇANDO criação de movimentos para OP filial {mo.name}")

        # Chama o compute para criar movimentos iniciais
        mo._compute_move_raw_ids()

        # ⚠️ COPIA AS QUANTIDADES EXATAS DA MATRIZ PARA A FILIAL
        self._force_preserve_matrix_quantities(mo)

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
        self._validate_branch_mo_quantities_exact(mo, original_qty, qty)

        # Notifica a OP matriz
        self.message_post(
            body=f"⚙️ OP filial criada: "
                 f"<a href='/web#id={mo.id}&model=mrp.production'>{mo.name}</a> "
                 f"para {qty} unidades"
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
        product_description = self._get_sale_order_description(self.origin_production_id)
        for move in self.move_finished_ids:
            if move.product_id.type != 'service' and move.product_qty > 0:
                # ✅ DESCRIÇÃO IGUAL AO PEDIDO DE VENDA para cada produto


                move_lines.append((0, 0, {
                    "name": product_description,  # ✅ DESCRIÇÃO IDÊNTICA AO PEDIDO DE VENDA
                    "product_id": move.product_id.id,
                    "product_uom_qty": move.product_qty,
                    "product_uom": move.product_uom.id,
                    "location_id": self.location_src_id.id,  # Localização da filial
                    "location_dest_id": self.origin_production_id.location_dest_id.id,  # Localização da matriz
                    "description_picking": product_description,  # ✅ DESCRIÇÃO ADICIONAL
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
            "sale_id": self.origin_production_id.sale_id.id,
            "partner_id": self.origin_production_id.partner_id.id,
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
            # ✅ DESCRIÇÃO IGUAL AO PEDIDO DE VENDA para cada produto
            product_description = self._get_sale_order_description(self.origin_production_id)

            move_lines.append((0, 0, {
                "name": product_description,  # ✅ DESCRIÇÃO IDÊNTICA AO PEDIDO DE VENDA
                "product_id": move.product_id.id,
                "product_uom_qty": move.product_uom_qty,
                "product_uom": move.product_uom.id,
                "location_id": return_picking.location_id.id,
                "location_dest_id": return_picking.location_dest_id.id,
                "description_picking": product_description,  # ✅ DESCRIÇÃO ADICIONAL
            }))

        picking = self.env["stock.picking"].create({
            "picking_type_id": picking_type.id,
            "location_id": return_picking.location_id.id,
            "location_dest_id": return_picking.location_dest_id.id,
            "origin": f"{self.name} - Recebimento Final",  # ⚠️ Usa origem da OP filial
            "move_ids_without_package": move_lines,
            "custom_block_validate": True,  # ⚠️ Bloqueado até envio ser concluído
            "show_validate": False,
            "sale_id": self.origin_production_id.sale_id.id,
            "partner_id": self.origin_production_id.partner_id.id,
            # ⚠️ NÃO vincula origin_production_id aqui - isso evita criação de nova OP
        })

        picking.action_confirm()
        picking.action_assign()

        # Vincula o recebimento final ao envio de retorno
        picking.write({
            'sending_transfer_id': [(4, return_picking.id)],
            'state': 'assigned'
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
        """
              Override ULTRA RESTRITIVO - BLOQUEIA QUALQUER alteração em OPs com filial
              PRESERVA quantidades existentes
              """
        # ⚠️ SE BYPASS ESTÁ ATIVO, NÃO FAZ NADA
        if self.env.context.get('bypass_update_moves'):
            _logger.warning(f"⛔ BYPASS ativo - _update_moves ignorado")
            return

        for production in self:
            _logger.warning(f"🚫 _update_moves chamado para: {production.name}")
            _logger.warning(f"   • Estado: {production.state}")

            # ⚠️ BLOQUEIO TOTAL para OPs com fluxo filial
            if production.origin_production_id or production.branch_location_id:
                _logger.warning(f"   🚫 BLOQUEIO ATIVADO - _update_moves IGNORADO")
                # ⚠️ NÃO CHAMA O SUPER() - BLOQUEIO COMPLETO
                return

            # ⚠️ Para OPs normais, comportamento padrão COM PROTEÇÃO
            _logger.warning(f"   🔄 OP NORMAL - Comportamento padrão")

            # Backup antes de qualquer alteração
            backup_data = {}
            for move in production.move_raw_ids:
                backup_data[move.id] = {
                    'quantity_done': move.quantity_done,
                    'product_uom_qty': move.product_uom_qty
                }

            try:
                # Chama o comportamento original
                super(BlueMrpProduction, production)._update_moves()
            except Exception as e:
                _logger.error(f"❌ Erro no _update_moves: {str(e)}")

            # ⚠️ RESTAURA quantity_done E product_uom_qty
            for move in production.move_raw_ids:
                if move.id in backup_data:
                    original_done = backup_data[move.id]['quantity_done']
                    original_uom_qty = backup_data[move.id]['product_uom_qty']

                    # Restaura quantity_done se foi alterado
                    if abs(move.quantity_done - original_done) > 0.001:
                        _logger.warning(f"   🔄 Restaurando quantity_done: {move.product_id.display_name}")
                        move.quantity_done = original_done

                    # Restaura product_uom_qty se foi alterado
                    if abs(move.product_uom_qty - original_uom_qty) > 0.001:
                        _logger.warning(f"   🔄 Restaurando product_uom_qty: {move.product_id.display_name}")
                        move.product_uom_qty = original_uom_qty

    def _force_preserve_matrix_quantities(self, branch_mo):
        """Força a preservação das quantidades exatas da matriz na OP filial"""
        _logger.warning(f"🔧 FORÇANDO preservação de quantidades da matriz para OP filial {branch_mo.name}")

        # Copia as quantidades EXATAS dos componentes da matriz para a filial
        for matrix_move in self.move_raw_ids:
            branch_move = branch_mo.move_raw_ids.filtered(
                lambda m: m.product_id == matrix_move.product_id
            )
            if branch_move:
                # ⚠️ COPIA APENAS product_uom_qty, PRESERVA quantity_done existente
                original_qty = matrix_move.product_uom_qty
                current_done = branch_move.quantity_done  # Preserva o valor atual

                branch_move.write({
                    'product_uom_qty': original_qty,
                    'quantity_done': current_done  # ⚠️ MANTÉM O VALOR ORIGINAL
                })
                _logger.warning(
                    f"   ✅ {matrix_move.product_id.display_name}: Planejado={original_qty}, Consumido={current_done}")

        # Garante que o produto acabado tenha a quantidade correta
        for branch_move in branch_mo.move_finished_ids:
            if branch_move.product_id == branch_mo.product_id:
                branch_move.write({'product_uom_qty': branch_mo.product_qty})

    @api.onchange('product_qty')
    def _onchange_product_qty(self):
        """
        Override CORRIGIDO - Bloqueia apenas OPs com fluxo filial
        Permite criação manual de OPs normais
        """
        for record in self:
            _logger.warning(f"🔍 ONCHANGE PRODUCT_QTY: {record.name}")
            _logger.warning(f"   • Nova quantidade: {record.product_qty}")
            _logger.warning(f"   • ID: {record.id}")
            _logger.warning(f"   • Estado: {record.state}")

            # ⚠️ BLOQUEIO APENAS para OPs com fluxo filial específico
            # Verifica se é uma OP de filial (tem origem definida)
            if record.origin_production_id:
                _logger.warning(f"   🚫 BLOQUEIO - OP DE FILIAL detectada")

                # Atualiza apenas produto finalizado
                if record.move_finished_ids:
                    for move in record.move_finished_ids:
                        if move.product_id == record.product_id:
                            old_qty = move.product_uom_qty
                            if abs(old_qty - record.product_qty) > 0.001:
                                move.product_uom_qty = record.product_qty
                                _logger.warning(f"   ✅ Produto final atualizado: {old_qty} → {record.product_qty}")
                return

            # ⚠️ PARA OPs NORMAIS (inclusive novas) - COMPORTAMENTO PADRÃO
            _logger.warning(f"   ✅ OP NORMAL - Aplicando comportamento padrão")

            # Para OPs NOVAS (ainda não salvas) - comportamento normal
            if not record.id or record.state in ['draft', 'confirmed']:
                _logger.warning(f"   📝 OP NOVA/RASCUNHO - Comportamento padrão")
                try:
                    super(BlueMrpProduction, record)._onchange_product_qty()
                    _logger.warning(f"   ✅ Super() executado com sucesso")
                except Exception as e:
                    _logger.error(f"❌ Erro no onchange padrão: {str(e)}")
                    # Em caso de erro, tenta o fallback
                    self._safe_onchange_fallback(record)
            else:
                # Para OPs EXISTENTES - proteção com backup
                _logger.warning(f"   🔄 OP EXISTENTE - Proteção com backup")
                backup_data = self._create_complete_moves_backup()

                try:
                    super(BlueMrpProduction, record)._onchange_product_qty()
                    _logger.warning(f"   ✅ Super() executado com backup")
                except Exception as e:
                    _logger.error(f"❌ Erro no onchange: {str(e)}")
                    self._restore_complete_moves_backup(backup_data)


        # Método fallback seguro
    def _safe_onchange_fallback(self, record):
        """Fallback seguro para quando o onchange padrão falha"""
        try:
            # Atualização manual básica dos movimentos
            if record.move_finished_ids:
                for move in record.move_finished_ids:
                    if move.product_id == record.product_id:
                        move.product_uom_qty = record.product_qty

            # Para componentes, usa BOM se disponível
            if record.bom_id and record.product_qty > 0:
                record._onchange_bom_id()

        except Exception as e:
            _logger.error(f"❌ Fallback também falhou: {str(e)}")

    def action_use_planned_quantities(self):
        """Preenche quantity_done com product_uom_qty quando está zerado"""
        for production in self:
            for move in production.move_raw_ids:
                if float_is_zero(move.quantity_done, precision_rounding=move.product_uom.rounding):
                    move.quantity_done = move.product_uom_qty  # ✅ Usar product_uom_qty em vez de planned_uom_qty
        return True

    def action_safe_update_quantities(self):
        """
        Ação manual para atualizar quantidades de forma segura
        (Para ser usada quando realmente necessário)
        """
        for record in self:
            _logger.warning(f"🔄 Atualização segura de quantidades para: {record.name}")

            # Backup dos consumos
            consumption_backup = {}
            for move in record.move_raw_ids:
                consumption_backup[move.id] = move.quantity_done

            # Atualiza usando o método original com contexto de proteção
            try:
                super(BlueMrpProduction, record.with_context(
                    safe_quantity_update=True
                ))._onchange_product_qty()
            except Exception as e:
                _logger.error(f"❌ Erro na atualização segura: {str(e)}")

            # Restaura consumos
            record._restore_consumption_values(consumption_backup)

            record.message_post(
                body="✅ Quantidades atualizadas com preservação de consumo manual"
            )

    def _restore_consumption_immediate(self, consumption_backup):
        """
        Restauração IMEDIATA e AGESSIVA dos valores de consumption
        """
        for record in self:
            _logger.warning(f"🛡️ RESTAURAÇÃO IMEDIATA de consumos para: {record.name}")

            restored_count = 0
            for move in record.move_raw_ids:
                if move.id in consumption_backup:
                    original_done = consumption_backup[move.id]
                    current_done = move.quantity_done

                    # ⚠️ RESTAURA SEMPRE, independente do estado
                    if abs(current_done - original_done) > 0.001:
                        # Escrita FORÇADA sem triggers
                        self.env.cr.execute("""
                            UPDATE stock_move 
                            SET quantity_done = %s 
                            WHERE id = %s
                        """, (original_done, move.id))

                        # Atualiza o cache local
                        move.quantity_done = original_done

                        restored_count += 1
                        _logger.warning(
                            f"   🔄 RESTAURADO: {move.product_id.display_name} {current_done} → {original_done}")

            _logger.warning(f"🛡️ TOTAL RESTAURADO: {restored_count} componentes")

            # ⚠️ FORÇA o refresh do cache
            record.invalidate_cache(['move_raw_ids'])

    def action_update_planned_qty_only(self):
        """Ação manual para atualizar apenas quantidades planejadas sem afetar consumo"""
        for record in self:
            if record.origin_production_id:
                _logger.info(f"🔄 Atualizando apenas quantidades planejadas para OP filial {record.name}")
                record.with_context(bypass_update_moves=True)._update_filial_moves_preserve_consumption()

                record.message_post(
                    body="✅ Quantidades planejadas atualizadas (consumo real preservado)"
                )

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

    def _check_consumed_materials(self):
        """Permite consumo seletivo tanto na matriz quanto na filial"""
        for production in self:
            # ⚠️ REMOVIDO: Não bloqueia mais consumo na matriz com filial
            # Agora ambas (matriz e filial) permitem consumo seletivo
            _logger.info(
                f"🔍 Verificando consumo para OP {production.name} - Tipo: {'FILIAL' if production.origin_production_id else 'MATRIZ'}")

        return super(BlueMrpProduction, self)._check_consumed_materials()

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
        # allowed_states = ['confirmed']
        # if self.state not in allowed_states:
        #     errors.append(f"OP deve estar 'Confirmada'. Estado atual: {self.state}")

        # 2. Verifica componentes consumidos
        # consumed_moves = self.move_raw_ids.filtered(lambda m: m.quantity_done > 0)
        # if consumed_moves:
        #     component_list = "\n".join([f"• {m.product_id.display_name}: {m.quantity_done}" for m in consumed_moves])
        #     errors.append(f"Componentes já consumidos:\n{component_list}")

        # 3. Verifica se já existe produção na filial
        if self.branch_production_id:
            errors.append(f"Já existem OPs filiais vinculadas: {', '.join(self.branch_production_id.mapped('name'))}")

        # 4. Verifica quantidades dos componentes
        # for move in self.move_raw_ids:
        #     if move.product_uom_qty <= 0:
        #         errors.append(f"Componente {move.product_id.display_name} com quantidade zero ou negativa")

        if errors:
            error_message = "Não é possível enviar para filial:\n\n" + "\n".join(errors)
            raise UserError(error_message)

        return True

    def _update_branch_mo_moves_original(self, branch_mo):
        """Atualiza movimentos da OP filial MANTENDO quantidades originais da matriz"""
        _logger.info(f"🔧 Atualizando movimentos OP filial {branch_mo.name} com quantidades ORIGINAIS")

        # ⚠️ COPIA AS QUANTIDADES EXATAS DA MATRIZ PARA A FILIAL
        for origin_move in self.move_raw_ids:
            # Encontra o movimento correspondente na filial
            branch_move = branch_mo.move_raw_ids.filtered(
                lambda m: m.product_id == origin_move.product_id
            )

            if branch_move:
                # ⚠️ MANTÉM A QUANTIDADE ORIGINAL DA MATRIZ - NÃO MULTIPLICA
                branch_move.write({'product_uom_qty': origin_move.product_uom_qty})

                _logger.info(f"📦 Componente {origin_move.product_id.display_name}: "
                             f"Matriz={origin_move.product_uom_qty}, "
                             f"Filial={origin_move.product_uom_qty} (MESMA QUANTIDADE)")

        # ⚠️ ATUALIZA MOVIMENTOS DE PRODUTO ACABADO
        for origin_move in self.move_finished_ids:
            if origin_move.product_id == self.product_id:
                branch_move = branch_mo.move_finished_ids.filtered(
                    lambda m: m.product_id == branch_mo.product_id
                )
                if branch_move:
                    branch_move.write({'product_uom_qty': branch_mo.product_qty})

    def _validate_branch_mo_quantities_exact(self, branch_mo, original_qty, received_qty):
        """Valida se as quantidades da OP filial são IGUAIS às da matriz"""
        self.ensure_one()

        _logger.info(f"🔍 Validando quantidades: OP Matriz {self.name} -> OP Filial {branch_mo.name}")
        _logger.info(f"📊 Original: {original_qty}, Recebido: {received_qty}")

        discrepancies = []

        # Verifica quantidade do produto principal
        if branch_mo.product_qty != received_qty:
            discrepancies.append(f"Quantidade produto: Esperado={received_qty}, Atual={branch_mo.product_qty}")
            branch_mo.write({'product_qty': received_qty})

        # ⚠️ VERIFICA SE OS COMPONENTES TEM MESMAS QUANTIDADES DA MATRIZ
        for branch_move in branch_mo.move_raw_ids:
            # Encontra o movimento correspondente na matriz
            origin_move = self.move_raw_ids.filtered(
                lambda m: m.product_id == branch_move.product_id
            )

            if origin_move:
                origin_move = origin_move[0]
                # ⚠️ ESPERA A MESMA QUANTIDADE DA MATRIZ
                expected_qty = origin_move.product_uom_qty

                # Tolerância de 0.001 para diferenças de arredondamento
                if abs(branch_move.product_uom_qty - expected_qty) > 0.001:
                    discrepancies.append(
                        f"Componente {branch_move.product_id.display_name}: "
                        f"Esperado={expected_qty:.3f} (Igual matriz), "
                        f"Atual={branch_move.product_uom_qty:.3f}"
                    )
                    # ⚠️ CORRIGE PARA SER EXATAMENTE IGUAL À MATRIZ
                    branch_move.write({'product_uom_qty': expected_qty})
                    _logger.info(
                        f"🔧 Corrigido {branch_move.product_id.display_name}: {branch_move.product_uom_qty:.3f} -> {expected_qty:.3f}")

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
        """Ação MANUAL para recálculo de consumo (quando necessário)"""
        for record in self:
            _logger.warning(f"🔄 RECÁLCULO MANUAL de consumo para: {record.name}")

            # Backup das quantidades atuais
            current_quantities = {}
            for move in record.move_raw_ids:
                current_quantities[move.id] = {
                    'product_uom_qty': move.product_uom_qty,
                    'quantity_done': move.quantity_done
                }

            # Força recálculo chamando o método original COM contexto
            try:
                super(BlueMrpProduction, record.with_context(
                    force_recalculation=True
                ))._compute_move_raw_ids()

                # Restaura quantity_done dos movimentos que já tinham consumo
                for move in record.move_raw_ids:
                    if move.id in current_quantities:
                        original_uom_qty = current_quantities[move.id]['product_uom_qty']
                        original_done = current_quantities[move.id]['quantity_done']
                        # Restaura product_uom_qty (inclusive se era zero)
                        move.product_uom_qty = original_uom_qty

                        # Restaura quantity_done (inclusive se era zero)
                        move.quantity_done = original_done

                        _logger.warning(
                            f"   🔄 Restaurado: {move.product_id.display_name} = {original_uom_qty} (done: {original_done})")

                record.message_post(body="✅ Consumo recalculado manualmente (todas as quantidades preservadas)")

            except Exception as e:
                _logger.error(f"❌ Erro no recálculo manual: {str(e)}")
                record.message_post(body=f"❌ Erro no recálculo manual: {str(e)}")

        return True

    @api.model
    def _scheduled_fix_branch_quantities(self):
        """Tarefa agendada para corrigir quantidades de OPs filiais"""
        _logger.warning("🔧 Executando correção agendada de quantidades...")

        # Encontra todas as OPs matriz com filial
        matrix_mos = self.search([
            ('branch_location_id', '!=', False),
            ('origin_production_id', '=', False)
        ])

        for matrix_mo in matrix_mos:
            _logger.warning(f"🔧 Verificando OP matriz: {matrix_mo.name}")

            # Para cada OP filial vinculada, corrige as quantidades
            for branch_mo in matrix_mo.branch_production_id:
                _logger.warning(f"🔧 Corrigindo OP filial: {branch_mo.name}")

                # Copia as quantidades exatas da matriz para a filial
                for matrix_move in matrix_mo.move_raw_ids:
                    branch_move = branch_mo.move_raw_ids.filtered(
                        lambda m: m.product_id == matrix_move.product_id
                    )
                    if branch_move:
                        original_qty = matrix_move.product_uom_qty
                        current_qty = branch_move.product_uom_qty

                        if abs(original_qty - current_qty) > 0.001:
                            branch_move.write({'product_uom_qty': original_qty})
                            _logger.warning(
                                f"   ✅ Corrigido: {matrix_move.product_id.display_name} {current_qty} → {original_qty}")

    def _set_qty_producing(self):
        """Custom implementation to preserve manual quantities"""
        # Primeiro chama a implementação original para moves sem quantidade manual
        manual_moves = self.env['stock.move']
        for production in self:
            manual_moves |= production.move_raw_ids.filtered(
                lambda m: not float_is_zero(m.quantity_done, precision_rounding=m.product_uom.rounding)
            )

        # Aplica a lógica original apenas para moves sem quantidade manual
        auto_productions = self.filtered(lambda p: any(
            float_is_zero(m.quantity_done, precision_rounding=m.product_uom.rounding)
            for m in p.move_raw_ids
        ))

        if auto_productions:
            super(BlueMrpProduction, auto_productions)._set_qty_producing()

    @api.model
    def create(self, vals):
        """Override do create para forçar criação inicial de movimentos"""
        record = super(BlueMrpProduction, self).create(vals)

        # ⚠️ FORÇA criação inicial de movimentos APENAS para novas OPs
        if record.bom_id and not record.move_raw_ids:
            _logger.warning(f"🔧 Criando movimentos iniciais para nova OP: {record.name}")
            record.with_context(allow_initial_compute=True)._compute_move_raw_ids()

        return record

    def write(self, vals):
        """Override do write para evitar recálculo automático de componentes"""
        # Se está alterando a quantidade do produto, EVITAR recálculo de componentes
        if 'product_qty' in vals and not self.env.context.get('force_update_moves'):
            _logger.warning(f"🚫 Alteração de product_qty BLOQUEADA para recálculo automático")

            # Escreve APENAS o product_qty sem disparar recálculos
            for production in self:
                # Atualiza apenas o campo product_qty
                super(BlueMrpProduction, production).write({'product_qty': vals['product_qty']})

                # Atualiza movimento do produto finalizado se necessário
                if production.move_finished_ids:
                    for move in production.move_finished_ids:
                        if move.product_id == production.product_id:
                            move.product_uom_qty = vals['product_qty']
                            _logger.warning(f"   ✅ Produto final atualizado: {move.product_uom_qty}")

            return True

        # Para outros campos, comportamento normal
        return super(BlueMrpProduction, self).write(vals)

    def _force_preserve_consumption(self):
        """Força a preservação do consumo em todos os movimentos - método de emergência"""
        for production in self:
            _logger.warning(f"🚨 FORÇANDO preservação de consumo para OP: {production.name}")

            for move in production.move_raw_ids:
                if move.quantity_done > 0 and move.state not in ['done', 'cancel']:
                    original_done = move.quantity_done
                    # Garante que quantity_done não seja alterado
                    move.with_context(bypass_consumption_check=True).write({
                        'quantity_done': original_done
                    })
                    _logger.warning(
                        f"   🔒 Consumo travado: {move.product_id.display_name} = {original_done}"
                    )

    def _force_preserve_consumption_immediate(self):
        """
        Preservação IMEDIATA e URGENTE dos consumos
        Usado durante onchanges para travar os valores
        """
        for record in self:
            _logger.warning(f"🔒 TRAVANDO consumos para: {record.name}")

            for move in record.move_raw_ids:
                if move.quantity_done > 0:
                    current_done = move.quantity_done

                    # ⚠️ ESCREVE DIRETAMENTE NO BANCO para evitar triggers
                    self.env.cr.execute("""
                        UPDATE stock_move 
                        SET quantity_done = %s 
                        WHERE id = %s AND quantity_done != %s
                    """, (current_done, move.id, current_done))

                    _logger.warning(f"   🔒 TRAVADO: {move.product_id.display_name} = {current_done}")

            # ⚠️ FORÇA o refresh
            record.invalidate_cache(['move_raw_ids'])

    def _create_complete_moves_backup(self):
        """
        Cria backup COMPLETO de todos os movimentos
        """
        backup_data = {}
        for record in self:
            backup_data[record.id] = {
                'raw_moves': [],
                'finished_moves': []
            }

            # Backup movimentos de componentes
            for move in record.move_raw_ids:
                backup_data[record.id]['raw_moves'].append({
                    'id': move.id,
                    'product_id': move.product_id.id,
                    'product_uom_qty': move.product_uom_qty,
                    'quantity_done': move.quantity_done,
                    'product_uom': move.product_uom.id,
                    'name': move.name,
                    'state': move.state,
                    'bom_line_id': move.bom_line_id.id if move.bom_line_id else False
                })
                _logger.warning(f"   💾 BACKUP COMPONENTE: {move.product_id.display_name} - Done: {move.quantity_done}")

            # Backup movimentos finalizados
            for move in record.move_finished_ids:
                backup_data[record.id]['finished_moves'].append({
                    'id': move.id,
                    'product_id': move.product_id.id,
                    'product_uom_qty': move.product_uom_qty,
                    'quantity_done': move.quantity_done,
                    'product_uom': move.product_uom.id,
                    'name': move.name,
                    'state': move.state
                })

        return backup_data

    def _restore_complete_moves_backup(self, backup_data):
        """
        Restauração COMPLETA dos movimentos do backup
        """
        for record in self:
            if record.id not in backup_data:
                continue

            _logger.warning(f"🔄 RESTAURAÇÃO COMPLETA para: {record.name}")

            data = backup_data[record.id]
            restored_count = 0

            # ⚠️ RESTAURA movimentos de componentes
            for move_backup in data['raw_moves']:
                move = record.move_raw_ids.filtered(lambda m: m.id == move_backup['id'])
                if move:
                    # Verifica se algo foi alterado
                    needs_restore = (
                            abs(move.product_uom_qty - move_backup['product_uom_qty']) > 0.001 or
                            abs(move.quantity_done - move_backup['quantity_done']) > 0.001
                    )

                    if needs_restore:
                        # ⚠️ ESCRITA DIRETA NO BANCO para evitar triggers
                        self.env.cr.execute("""
                            UPDATE stock_move 
                            SET product_uom_qty = %s, 
                                quantity_done = %s,
                                product_uom = %s
                            WHERE id = %s
                        """, (
                            move_backup['product_uom_qty'],
                            move_backup['quantity_done'],
                            move_backup['product_uom'],
                            move.id
                        ))

                        # Atualiza cache
                        move.product_uom_qty = move_backup['product_uom_qty']
                        move.quantity_done = move_backup['quantity_done']
                        move.product_uom = move_backup['product_uom']

                        restored_count += 1
                        _logger.warning(f"   🔄 RESTAURADO: {move.product_id.display_name}")
                        _logger.warning(f"      Qty: {move.product_uom_qty} → {move_backup['product_uom_qty']}")
                        _logger.warning(f"      Done: {move.quantity_done} → {move_backup['quantity_done']}")

            # ⚠️ RESTAURA movimentos finalizados (apenas quantidade planejada)
            for move_backup in data['finished_moves']:
                move = record.move_finished_ids.filtered(lambda m: m.id == move_backup['id'])
                if move and move.product_id == record.product_id:
                    if abs(move.product_uom_qty - record.product_qty) > 0.001:
                        move.product_uom_qty = record.product_qty
                        _logger.warning(f"   ✅ Produto final: {move.product_uom_qty}")

            _logger.warning(f"🔄 TOTAL RESTAURADO: {restored_count} componentes")

            # ⚠️ FORÇA INVALIDAÇÃO DO CACHE
            record.invalidate_cache()

    def action_verify_and_fix_consumption(self):
        """
        Ação para verificar e corrigir consumos manualmente
        """
        for record in self:
            _logger.warning(f"🔍 VERIFICANDO CONSUMOS: {record.name}")

            problems = []

            # Verifica componentes
            for move in record.move_raw_ids:
                bom_line = record.bom_id.bom_line_ids.filtered(
                    lambda l: l.product_id == move.product_id
                )

                if bom_line:
                    expected_qty = bom_line.product_qty * record.product_qty / record.bom_id.product_qty

                    if abs(move.product_uom_qty - expected_qty) > 0.001:
                        problems.append(
                            f"• {move.product_id.display_name}: "
                            f"Esperado={expected_qty:.3f}, Atual={move.product_uom_qty:.3f}"
                        )

            if problems:
                message = "Problemas encontrados:\n\n" + "\n".join(problems)
                _logger.warning(f"❌ PROBLEMAS: {message}")

                # Pergunta se quer corrigir
                return {
                    'name': 'Corrigir Consumos',
                    'type': 'ir.actions.act_window',
                    'res_model': 'mrp.production.fix.consumption.wizard',
                    'view_mode': 'form',
                    'target': 'new',
                    'context': {
                        'default_production_id': record.id,
                        'default_problems': "\n".join(problems)
                    }
                }
            else:
                record.message_post(body="✅ Consumos verificados - Todos corretos")
                raise UserError("✅ Todos os consumos estão corretos!")

    def _cal_price(self, consumed_moves):
        """Override para lidar com validação distribuída entre matriz e filiais"""
        # Filtrar apenas moves válidos para cálculo de custo
        valid_moves = consumed_moves.filtered(
            lambda m: m.state == 'done' and m.product_qty != 0
        )

        # Para cada produção, processar individualmente
        for production in self:
            # Encontrar o movimento do produto final correto
            finished_moves = production.move_finished_ids.filtered(
                lambda m: m.product_id == production.product_id and
                          m.state == 'done'
            )

            if not finished_moves:
                continue

            # Se houver múltiplos moves, usar o principal
            if len(finished_moves) > 1:
                # Ordenar por ID e pegar o mais recente ou usar lógica específica
                main_finished_move = finished_moves.sorted(key=lambda m: m.id, reverse=True)[0]
            else:
                main_finished_move = finished_moves

            try:
                # Chamar a implementação original com o move correto
                super(BlueMrpProduction, production)._cal_price(valid_moves)
            except ValueError as e:
                # Fallback: calcular custo manualmente se houver erro
                if "Expected singleton" in str(e):
                    production._fallback_cal_price(valid_moves, main_finished_move)

        return True

    def _fallback_cal_price(self, consumed_moves, finished_move):
        """Fallback para cálculo de custo quando há múltiplos moves"""
        # Implementação simplificada de cálculo de custo
        total_cost = 0.0
        for move in consumed_moves:
            if move.raw_material_production_id == self:
                # Calcular custo baseado no preço padrão
                total_cost += move.product_qty * move.product_id.standard_price

        # Atribuir custo ao produto final
        if finished_move and finished_move.quantity_done > 0:
            unit_cost = total_cost / finished_move.quantity_done
            finished_move.price_unit = unit_cost

            # Atualizar custo padrão do produto se configurado
            if self.env.company.auto_update_standard_cost:
                finished_move.product_id.standard_price = unit_cost