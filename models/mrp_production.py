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

    # ------------------------------------------------------------
    # MÉTODOS COMPUTE
    # ------------------------------------------------------------
    @api.depends('state', 'branch_location_id', 'final_receipt_id')
    def _compute_is_waiting_return(self):
        for record in self:
            record.is_waiting_return = (
                    record.state == 'progress' and bool(record.branch_location_id) and not bool(record.final_receipt_id)
            )

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
        """Override para controle do fluxo"""
        for record in self:
            # Verificar se quantidade total recebida é suficiente
            if record.branch_location_id and record.final_receipt_id:
                if record.total_qty_received >= record.product_qty:
                    # Quantidade suficiente recebida, pode concluir
                    record._release_delivery_order()
                    return super(BlueMrpProduction, record).button_mark_done()
                else:
                    raise UserError(
                        f"Quantidade recebida ({record.total_qty_received}) é menor que a quantidade planejada ({record.product_qty}). "
                        f"Aguarde o recebimento total ou ajuste a quantidade da OP."
                    )

            # Se existe envio/recebimento/produção/retorno/recebimento final, checar estados com any/all
            if record.branch_location_id and not record.final_receipt_id and record.branch_receipt_id and any(
                    r.state != "done" for r in record.branch_receipt_id):
                raise UserError("Em trânsito para a filial. O recebimento na filial precisa ser confirmado antes.")

            if record.branch_location_id and not record.final_receipt_id and record.branch_receipt_id and any(
                    r.state == "done" for r in record.branch_receipt_id) and (
                    not record.branch_production_id or all(m.state != "done" for m in record.branch_production_id)):
                # Se recebeu na filial e nenhuma OP filial está concluída
                raise UserError("Aguardando a fabricação na filial.")

            if record.branch_location_id and record.branch_production_id and any(
                    m.state == "done" for m in record.branch_production_id) and not record.final_receipt_id:
                raise UserError("Fabricação na filial concluída, aguardando retorno.")

            if record.final_receipt_id and any(fr.state != 'done' for fr in record.final_receipt_id):
                raise UserError("O recebimento final precisa ser confirmado antes de concluir a OP matriz.")

            # Se for OP filial, manter comportamento normal mas criar retorno automático ao finalizar
            if record.origin_production_id:
                res = super(BlueMrpProduction, record).button_mark_done()
                # se for OP filial, após super, cria o fluxo de retorno automaticamente
                record._create_return_flow_automatically()
                return res

            return super(BlueMrpProduction, record).button_mark_done()

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
        mo.write({'branch_production_id': [(4,mo.id)]})

        self.origin_production_id.branch_production_id = mo.id

        # Vincular a OP ao picking
        picking.write({'branch_mo_id': mo.id, 'branch_production_id': [(4, mo.id)]})

        _logger.info(f"✅ OP filial criada: {mo.name} para quantidade {qty} com BoM {bom.display_name}")

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

            except Exception as e:
                _logger.error(f"❌ Erro ao criar retorno automático: {str(e)}")
                raise UserError(f"Erro ao criar retorno automático: {str(e)}")

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

    # Recebimento Final #####
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