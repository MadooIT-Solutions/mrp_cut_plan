from odoo import models, fields, api
from odoo.exceptions import UserError
import logging

_logger = logging.getLogger(__name__)


class MrpProductionTransferWizard(models.TransientModel):
    _name = "mrp.production.transfer.wizard"
    _description = "Fluxo Matriz → Filial → Matriz"

    production_id = fields.Many2one("mrp.production", required=True, readonly=True)
    location_dest_id = fields.Many2one(
        "stock.location",
        string="Filial",
        domain=lambda self: [('id', 'in', self.domain_location_ids.ids)],
        required=True
    )
    domain_location_ids = fields.Many2many("stock.location")
    location_dest_warehouse_name = fields.Char(string="Armazém", compute="_compute_location_dest_warehouse")

    @api.depends("location_dest_id")
    def _compute_location_dest_warehouse(self):
        for wizard in self:
            wizard.location_dest_warehouse_name = wizard.location_dest_id.warehouse_id.name if wizard.location_dest_id and wizard.location_dest_id.warehouse_id else "-"

    @api.onchange("production_id")
    def _onchange_production_id(self):
        for wizard in self:
            production = wizard.production_id
            if not production or not production.location_src_id:
                wizard.domain_location_ids = self.env['stock.location'].search([('usage', '=', 'internal')])
                continue

            current_loc = production.location_src_id
            warehouses = self.env['stock.warehouse'].search([])
            current_warehouse = False
            for wh in warehouses:
                all_locs = wh.view_location_id | wh.view_location_id.child_ids
                if current_loc.id in all_locs.ids:
                    current_warehouse = wh
                    break

            locs = self.env['stock.location'].search([('usage', '=', 'internal')])
            if current_warehouse:
                excluded_locs = current_warehouse.view_location_id | current_warehouse.view_location_id.child_ids
                locs = locs - excluded_locs
            locs = locs - current_loc
            wizard.domain_location_ids = locs
            return {'domain': {'location_dest_id': [('id', 'in', locs.ids)]}}

    def action_confirm(self):
        if 'PS/Almoxarifado' in (self.location_dest_id.complete_name or ""):
            raise UserError("Selecione uma filial, não a matriz.")

        # ⚙️ Valida condições da OP
        self.production_id._validate_before_branch_transfer()

        # ⚙️ Cria apenas o envio (sem recebimento)
        sending = self._create_sending_transfer()

        _logger.warning(f"🧩 Antes do write() na produção {self.production_id.name}")
        # usa sudo + context bypass para evitar triggers que criem OP durante o write
        self.production_id.sudo().with_context(bypass_branch_creation=True).write({
            'branch_location_id': self.location_dest_id.id,
            'sending_transfer_id': [(4, sending.id)],
        })
        _logger.warning(f"🧩 Depois do write() na produção {self.production_id.name}")

        self.production_id.message_post(
            body=f"📦 Envio criado para filial {self.location_dest_id.display_name}. "
                 f"Aguardando validação para gerar recebimento e OP filial."
        )

        _logger.info(f"✅ Wizard: criado envio {sending.name} (aguardando validação para gerar recebimento)")
        return {"type": "ir.actions.act_window_close"}

    def _create_sending_transfer(self):
        picking_type = self.env['stock.picking.type'].search([
            ('code', '=', 'outgoing'),
            ('warehouse_id.name', '=', 'Polispan')
        ], limit=1)
        if not picking_type:
            picking_type = self.env['stock.picking.type'].search([
                ('code', '=', 'outgoing'),
                ('company_id', '=', self.env.company.id)
            ], limit=1)
        if not picking_type:
            raise UserError("Tipo de operação interna não encontrado.")

        # ⚠️ ENVIA APENAS O PRODUTO FINALIZADO, NÃO OS COMPONENTES
        move_lines = []
        for move in self.production_id.move_finished_ids:
            if move.product_id.type != 'service':
                move_lines.append((0, 0, {
                    "name": f"Envio {move.product_id.display_name}",
                    "product_id": move.product_id.id,
                    "product_uom_qty": move.product_uom_qty,
                    "product_uom": move.product_uom.id,
                    "location_id": self.production_id.location_src_id.id,
                    "location_dest_id": self.location_dest_id.id,
                }))

        # ⚠️ NÃO INCLUI COMPONENTES NA TRANSFERÊNCIA
        _logger.info(f"📦 Enviando apenas produto finalizado: {self.production_id.product_id.display_name}")

        sending_vals = {
            "picking_type_id": picking_type.id,
            "location_id": self.production_id.location_src_id.id if self.production_id.location_src_id else self.production_id.location_dest_id.id,
            "location_dest_id": self.location_dest_id.id,
            "origin": self.production_id.name,
            "move_ids_without_package": move_lines,
            "custom_block_validate": True,
            # 🎯 CRÍTICO: Define origin_production_id no picking
            "origin_production_id": self.production_id.id,
        }

        sending = self.env['stock.picking'].create(sending_vals)

        sending.action_confirm()
        try:
            sending.state = 'assigned'
        except Exception as e:
            _logger.warning("Não foi possível reservar automaticamente o envio: %s", e)
            sending.write({'state': 'assigned'})

        _logger.warning(f"✅ Envio criado: {sending.name} - Origin Production ID: {sending.origin_production_id.name}")
        return sending

    def _create_branch_receipt(self, sending):
        # Determina o picking_type da filial
        warehouse = self.location_dest_id.warehouse_id
        picking_type = self.env['stock.picking.type'].search([
            ('warehouse_id', '=', warehouse.id),
            ('code', '=', 'incoming')
        ], limit=1)
        if not picking_type:
            raise UserError(f"Tipo de operação de recebimento não encontrado para {warehouse.name}")

        # Cria o recebimento explicitamente (sem origin_production_id para não disparar criação automática de OP)
        receiving = sending.copy({
            'picking_type_id': picking_type.id,
            'location_id': sending.location_id.id if sending.location_id else sending.location_dest_id.id,
            'location_dest_id': self.location_dest_id.id,
            'partner_id': sending.company_id.partner_id.id if sending.company_id and sending.company_id.partner_id else False,
            'show_validate': False,
            'custom_block_validate': True,  # bloqueia até envio ser concluído
            })
        # receiving = self.env['stock.picking'].create(receiving_vals)
        receiving.action_confirm()
        # Agora vincula manualmente a produção de origem (evita triggers automáticos durante create/copy)
        receiving.write({
            'origin_production_id': self.production_id.id,
            'sending_transfer_id': [(4, sending.id)],
            'show_validate': False,
            'custom_block_validate': True,
        })

        # Vincula o recebimento ao envio
        sending.write({
            'branch_receipt_id': [(4, receiving.id)],
            'custom_block_validate': True,
        })

        # Confirma e tenta reservar o recebimento (fica em assigned)

        try:
            # receiving.action_assign()
            receiving.state = 'assigned'
        except Exception as e:
            _logger.warning("Não foi possível reservar automaticamente o recebimento: %s", e)
            receiving.write({'state': 'assigned'})

        _logger.info(f"✅ Recebimento criado (bloqueado) para envio {sending.name}: {receiving.name}")
        return receiving

    def action_reset_consumption(self):
        """Reseta quantidades consumidas para permitir envio à filial"""
        for record in self:
            if record.state == 'progress' and record.branch_location_id:
                # Zera quantidades consumidas dos componentes
                for move in record.move_raw_ids:
                    if move.quantity_done > 0:
                        old_qty = move.quantity_done
                        move.write({'quantity_done': 0})
                        _logger.info(f"🔄 Zerado consumo {move.product_id.display_name}: {old_qty} -> 0")

                record.message_post(
                    body="🔄 Consumo de componentes zerado para envio à filial"
                )


class ConsumptionRecalcWizard(models.TransientModel):
    _name = "consumption.recalc.wizard"
    _description = "Recalcular Consumos"

    production_id = fields.Many2one("mrp.production", required=True)

    def action_recalculate_consumption(self):
        self.production_id._compute_matrix_consumed_qty()
        self.production_id._compute_branch_consumed_qty()
        self.production_id._compute_total_components_consumed()

        return {
            'type': 'ir.actions.act_window',
            'res_model': 'mrp.production',
            'res_id': self.production_id.id,
            'view_mode': 'form',
            'target': 'current',
        }
