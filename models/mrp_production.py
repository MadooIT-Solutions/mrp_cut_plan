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
        compute="_compute_cut_plan_fields"
    )

    cotation_partner_id = fields.Many2one(
        comodel_name="res.partner",
        related="sale_order_id.partner_id",
        string="Cliente"
    )

    # Campos para controle do fluxo
    branch_location_id = fields.Many2one(
        "stock.location",
        string="Armazém de Processamento",
        readonly=True
    )
    sending_transfer_id = fields.Many2one(
        "stock.picking",
        string="Transferência de Envio",
        readonly=True
    )
    branch_receipt_id = fields.Many2one(
        "stock.picking",
        string="Recebimento na Filial",
        readonly=True
    )
    branch_production_id = fields.Many2one(
        "mrp.production",
        string="OP da Filial",
        readonly=True
    )
    return_transfer_id = fields.Many2one(
        "stock.picking",
        string="Retorno da Filial",
        readonly=True
    )
    final_receipt_id = fields.Many2one(
        "stock.picking",
        string="Recebimento Final",
        readonly=True
    )
    is_waiting_return = fields.Boolean(
        string="Aguardando Retorno",
        compute="_compute_is_waiting_return"
    )

    origin_production_id = fields.Many2one(
        "mrp.production",
        string="OP de Origem",
        readonly=True
    )

    def _compute_count_po(self):
        for record in self:
            record.count_po = 1 if record.cut_plan_id else 0

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

    @api.depends('state', 'branch_location_id', 'final_receipt_id')
    def _compute_is_waiting_return(self):
        for record in self:
            record.is_waiting_return = (
                    record.state == 'progress' and
                    record.branch_location_id and
                    not record.final_receipt_id
            )

    def button_mark_done(self):
        """Override para controle do fluxo"""
        # Se for OP filial (tem origem), ao concluir cria retorno automático
        if self.origin_production_id:
            res = super().button_mark_done()
            self._create_return_flow_automatically()
            return res

        # Caso seja OP matriz
        if self.branch_location_id and not self.final_receipt_id:
            raise UserError(
                "Esta ordem de produção está aguardando retorno do processamento na filial. "
                "Conclua o recebimento final antes de marcar como done."
            )

        if not self.branch_location_id:
            return {
                'name': 'Selecionar Armazém para Processamento',
                'type': 'ir.actions.act_window',
                'res_model': 'mrp.production.transfer.wizard',
                'view_mode': 'form',
                'target': 'new',
                'context': {'default_production_id': self.id}
            }

        if self.final_receipt_id and self.final_receipt_id.state != 'done':
            raise UserError(
                "O recebimento final precisa ser confirmado antes de concluir a OP matriz."
            )

        return super().button_mark_done()

    def action_create_return_flow(self):
        """Mantido apenas para compatibilidade - agora é automático"""
        self.ensure_one()
        if self.return_transfer_id:
            return {
                'name': _('Transferência de Retorno'),
                'type': 'ir.actions.act_window',
                'res_model': 'stock.picking',
                'view_mode': 'form',
                'res_id': self.return_transfer_id.id,
                'target': 'current',
            }
        else:
            raise UserError(
                "O fluxo de retorno é criado automaticamente quando a OP da filial é concluída."
            )

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
        try:
            # 1. Criar transferência de retorno (Filial → Matriz) - state = assigned
            return_picking = self._create_return_transfer()

            # 2. Criar recebimento final na matriz - state = assigned mas bloqueado
            final_receipt = self._create_final_receipt(return_picking)

            # Vincular
            return_picking.final_receipt_id = final_receipt.id
            final_receipt.return_transfer_id = return_picking.id

            # Atualizar OP filial
            self.write({
                'return_transfer_id': return_picking.id,
                'final_receipt_id': final_receipt.id,
            })

            # Atualizar OP matriz
            self.origin_production_id.write({
                'return_transfer_id': return_picking.id,
                'final_receipt_id': final_receipt.id,
            })

            _logger.info(f"✅ Retorno automático criado: {return_picking.name}")
            _logger.info(f"✅ Recebimento final criado: {final_receipt.name}")

            # Mensagem na OP filial
            self.message_post(
                body=f"""
                <b>✅ Retorno automático criado!</b><br/>
                • <a href='/web#id={return_picking.id}&model=stock.picking'>Envio para Matriz</a> - PRONTO para processar<br/>
                • <a href='/web#id={final_receipt.id}&model=stock.picking'>Recebimento Final</a> - AGUARDANDO envio
                """
            )

            # Mensagem na OP matriz
            self.origin_production_id.message_post(
                body=f"""
                <b>✅ Retorno automático criado da filial!</b><br/>
                • <a href='/web#id={return_picking.id}&model=stock.picking'>Envio da Filial</a> - PRONTO para processar<br/>
                • <a href='/web#id={final_receipt.id}&model=stock.picking'>Recebimento Final</a> - AGUARDANDO envio
                <br/><br/>
                <b>📋 Próximos passos:</b><br/>
                1. Processe e confirme o envio da filial<br/>
                2. Após confirmação, o recebimento final ficará disponível<br/>
                3. Confirme o recebimento final<br/>
                4. A OP será concluída automaticamente
                """
            )

        except Exception as e:
            _logger.error(f"❌ Erro ao criar retorno automático: {str(e)}")
            raise UserError(f"Erro ao criar retorno automático: {str(e)}")

    def action_create_branch_production(self):
        """Fase 2: Cria ordem de produção na filial - só pode criar após recebimento confirmado"""
        self.ensure_one()

        _logger.info(f"=== INICIANDO FASE 2 - Criando OP na filial ===")
        _logger.info(f"OP Matriz: {self.name}")
        _logger.info(f"Branch Receipt: {self.branch_receipt_id.name if self.branch_receipt_id else 'None'}")

        if not self.branch_receipt_id:
            raise UserError("❌ Recebimento na filial não encontrado.")

        if self.branch_receipt_id.state != 'done':
            raise UserError("⏳ O recebimento na filial precisa ser confirmado primeiro.")

        if self.branch_production_id:
            raise UserError("❌ Ordem de produção na filial já foi criada.")

        # === Buscar local de produção da filial ===
        branch_warehouse = self.branch_location_id.warehouse_id
        if not branch_warehouse:
            raise UserError("❌ Nenhum armazém vinculado à filial selecionada.")

        branch_prod_location = self.env['stock.location'].search([
            ('usage', '=', 'production'),
            ('location_id', '=', self.branch_location_id.location_id.id),
        ], limit=1)

        if not branch_prod_location:
            raise UserError(
                f"❌ Nenhum local de produção encontrado para {branch_warehouse.name} "
                f"(verifique se há 'CP/Produção' ou 'SG/Produção')"
            )

        # === Buscar tipo de operação de produção da filial ===
        picking_type_branch = self.env['stock.picking.type'].search([
            ('warehouse_id', '=', branch_warehouse.id),
            ('code', '=', 'mrp_operation')
        ], limit=1)

        # if not picking_type_branch:
        #     # fallback comum em instalações CE: tipo "Manufacturing"
        #     picking_type_branch = self.env['stock.picking.type'].search([
        #         ('warehouse_id', '=', branch_warehouse.id),
        #         ('code', '=', 'manufacturing')
        #     ], limit=1)

        if not picking_type_branch:
            raise UserError(
                f"❌ Nenhum tipo de operação de produção encontrado para o armazém {branch_warehouse.name}."
            )

        # === Copiar OP com contexto da filial ===
        branch_production = self.copy({
            'name': f"{self.name} - {branch_warehouse.name}",
            'company_id': branch_warehouse.company_id.id,
            'picking_type_id': picking_type_branch.id,  # 👈 aqui está a correção principal
            'location_src_id': self.branch_location_id.id,  # estoque da filial
            'location_dest_id': branch_prod_location.id,  # produção da filial
            'branch_location_id': False,
            'sending_transfer_id': False,
            'branch_receipt_id': False,
            'branch_production_id': False,
            'return_transfer_id': False,
            'final_receipt_id': False,
            'origin_production_id': self.id,
        })

        # Confirmar OP
        branch_production.action_confirm()
        # self.branch_production_id = branch_production.id

        # 👇 CORREÇÃO CRÍTICA: VINCULAR A OP FILIAL À OP MATRIZ
        self.write({
            'branch_production_id': branch_production.id
        })

        _logger.info(f"✅ OP Filial criada: {branch_production.name}")
        _logger.info(f"✅ OP Matriz {self.name} vinculada à OP Filial {branch_production.name}")

        self.message_post(body=f"""
            <b>✅ Fase 2: OP criada na filial {branch_warehouse.name}!</b><br/>
            • <a href='/web#id={branch_production.id}&model=mrp.production'>OP {branch_production.name}</a><br/>
            <b>📋 Próximo passo:</b> Processe e conclua a OP na filial.
        """)

        return {
            'name': _('Ordem de Produção - Filial'),
            'type': 'ir.actions.act_window',
            'res_model': 'mrp.production',
            'view_mode': 'form',
            'res_id': branch_production.id,
            'target': 'current',
        }

    def action_create_return_flow(self):
        """Método mantido para compatibilidade - agora é automático"""
        self.ensure_one()

        if self.return_transfer_id:
            # Se já existe, redirecionar para a transferência de retorno
            return {
                'name': _('Transferência de Retorno'),
                'type': 'ir.actions.act_window',
                'res_model': 'stock.picking',
                'view_mode': 'form',
                'res_id': self.return_transfer_id.id,
                'target': 'current',
            }
        else:
            # Se não existe, informar que será criada automaticamente
            raise UserError(
                "O fluxo de retorno será criado automaticamente quando a OP da filial for concluída. "
                "Verifique se a OP na filial já foi concluída."
            )

    def _create_return_transfer(self):
        """Cria transferência de retorno da filial para matriz - State ASSIGNED"""

        _logger.info(f"=== CRIANDO TRANSFERÊNCIA DE RETORNO ===")
        _logger.info(f"OP Matriz: {self.name}")
        _logger.info(f"Branch Production ID: {self.branch_production_id.id if self.branch_production_id else 'None'}")

        # Verificar se temos a OP filial vinculada
        if not self.branch_production_id:
            _logger.error(f"❌ OP filial não encontrada para OP matriz {self.name}")
            # Tentar buscar a OP filial através do origin_production_id
            branch_production = self.env['mrp.production'].search([
                ('origin_production_id', '=', self.id)
            ], limit=1)

            if branch_production:
                _logger.info(f"✅ OP filial encontrada via busca: {branch_production.name}")
                self.write({
                    'branch_production_id': branch_production.id
                })
            else:
                raise UserError(
                    "❌ OP da filial não encontrada para criar retorno. Verifique se a OP foi criada corretamente na filial.")

        # Buscar o warehouse da filial
        branch_warehouse = self.branch_location_id.warehouse_id
        if not branch_warehouse:
            # Fallback: buscar warehouse através da localização da OP filial
            branch_warehouse = self.branch_production_id.location_src_id.warehouse_id

        if not branch_warehouse:
            raise UserError("❌ Armazém da filial não encontrado.")

        picking_type = self.env["stock.picking.type"].search([
            ("code", "=", "internal"),
            ("warehouse_id", "=", branch_warehouse.id)
        ], limit=1)

        if not picking_type:
            raise UserError(f"❌ Tipo de operação interna não encontrado para {branch_warehouse.name}")

        move_lines = []
        for move in self.branch_production_id.move_finished_ids:
            if move.product_id.type != 'service' and move.product_qty > 0:
                move_lines.append((0, 0, {
                    "name": f"Retorno {move.product_id.display_name} - {self.branch_production_id.name}",
                    "product_id": move.product_id.id,
                    "product_uom_qty": move.product_qty,
                    "product_uom": move.product_uom.id,
                    "location_id": self.branch_production_id.location_dest_id.id,
                    "location_dest_id": self.location_dest_id.id,
                }))

        if not move_lines:
            # Tentar usar os movimentos de produtos acabados se os finished não existirem
            for move in self.branch_production_id.move_finished_ids:
                if move.product_id.type != 'service' and move.quantity_done > 0:
                    move_lines.append((0, 0, {
                        "name": f"Retorno {move.product_id.display_name} - {self.branch_production_id.name}",
                        "product_id": move.product_id.id,
                        "product_uom_qty": move.quantity_done,
                        "product_uom": move.product_uom.id,
                        "location_id": self.branch_production_id.location_dest_id.id,
                        "location_dest_id": self.location_dest_id.id,
                    }))

        if not move_lines:
            raise UserError("❌ Nenhum movimento válido encontrado para criar retorno.")

        picking = self.env["stock.picking"].create({
            "picking_type_id": picking_type.id,
            "location_id": self.branch_production_id.location_dest_id.id,
            "location_dest_id": self.location_dest_id.id,
            "origin": f"{self.branch_production_id.name} - Retorno para Matriz",
            "move_ids_without_package": move_lines,
            "note": f"Retorno do processamento na filial. OP origem: {self.name}",
        })

        picking.action_confirm()
        picking.action_assign()

        _logger.info(f"✅ Transferência de retorno criada: {picking.name}")

        return picking


    def _create_final_receipt(self, return_picking):
        """Cria recebimento final na matriz - State ASSIGNED mas bloqueado"""
        picking_type = self.env["stock.picking.type"].search([
            ("code", "=", "incoming"),
            ("warehouse_id.name", "=", "Polispan")
        ], limit=1)

        if not picking_type:
            picking_type = self.env["stock.picking.type"].search([
                ("code", "=", "internal"),
                ("warehouse_id.name", "=", "Polispan")
            ], limit=1)

        if not picking_type:
            raise UserError("❌ Tipo de operação de recebimento não encontrado para Polispan")

        move_lines = []
        for move in return_picking.move_ids_without_package:
            move_lines.append((0, 0, {
                "name": f"Recebimento Final {move.product_id.display_name} - {self.name}",
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
            "origin": f"{self.name} - Recebimento Final",
            "move_ids_without_package": move_lines,
            "note": f"Recebimento final do processamento na filial. Aguardando confirmação do retorno.",
        })

        picking.action_confirm()
        picking.action_assign()

        # Bloquear a validação até que o retorno seja confirmado
        picking.write({
            'show_validate': False,
            'custom_block_validate': True,
        })

        _logger.info(f"✅ Recebimento final criado: {picking.name}")

        return picking

    def action_finalize_production(self):
        """Finaliza a OP quando o recebimento final é confirmado"""
        self.ensure_one()

        _logger.info(f"=== FINALIZANDO OP MATRIZ ===")
        _logger.info(f"OP: {self.name}")
        _logger.info(f"Recebimento Final: {self.final_receipt_id.name if self.final_receipt_id else 'None'}")
        _logger.info(f"Recebimento Final State: {self.final_receipt_id.state if self.final_receipt_id else 'None'}")

        if not self.final_receipt_id:
            raise UserError("❌ Recebimento final não encontrado.")

        if self.final_receipt_id.state != 'done':
            raise UserError("⏳ O recebimento final precisa ser confirmado primeiro.")

        # Marcar como done
        result = super().button_mark_done()

        message = f"""
        <b>✅ OP Concluída com Sucesso!</b><br/>
        • Processamento na filial finalizado<br/>
        • Retorno confirmado<br/>
        • Produção concluída
        """
        self.message_post(body=message)

        return result

    def _compute_cut_plan_fields(self):
        """Calcular campos relacionados ao cut_plan"""
        for record in self:
            if record.cut_plan_id:
                cut_plan = record.cut_plan_id
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
                # Reset para valores padrão
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

    def _post_inventory(self, cancel_backorder=False):
        """Override do método _post_inventory se necessário"""
        result = super()._post_inventory(cancel_backorder=cancel_backorder)
        return result

    def action_cancel_branch_flow(self):
        """Cancela o fluxo de filial se algo der errado"""
        if self.state == 'done':
            raise UserError("Não é possível cancelar fluxo de uma OP concluída.")

        transfers_to_cancel = self.env['stock.picking']
        if self.sending_transfer_id:
            transfers_to_cancel |= self.sending_transfer_id
        if self.branch_receipt_id:
            transfers_to_cancel |= self.branch_receipt_id
        if self.return_transfer_id:
            transfers_to_cancel |= self.return_transfer_id
        if self.final_receipt_id:
            transfers_to_cancel |= self.final_receipt_id

        transfers_to_cancel.action_cancel()

        self.write({
            'branch_location_id': False,
            'sending_transfer_id': False,
            'branch_receipt_id': False,
            'branch_production_id': False,
            'return_transfer_id': False,
            'final_receipt_id': False,
        })

        self.message_post(body="Fluxo de filial cancelado manualmente.")

    def _get_picking_type_for_warehouse(self, warehouse, operation_type='internal'):
        """Busca o tipo de operação para um warehouse específico"""
        picking_type = self.env["stock.picking.type"].search([
            ("warehouse_id", "=", warehouse.id),
            ("code", "=", operation_type)
        ], limit=1)

        # Fallback: se não encontrar o tipo específico
        if not picking_type and operation_type == 'incoming':
            picking_type = self.env["stock.picking.type"].search([
                ("code", "=", "internal"),
                ("warehouse_id", "=", warehouse.id)
            ], limit=1)

        return picking_type