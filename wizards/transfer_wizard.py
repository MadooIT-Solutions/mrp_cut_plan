from odoo import models, fields, api
from odoo.exceptions import UserError
import logging

_logger = logging.getLogger(__name__)

class MrpProductionTransferWizard(models.TransientModel):
    _name = "mrp.production.transfer.wizard"
    _description = "Fluxo Matriz → Filial → Matriz"

    production_id = fields.Many2one("mrp.production", required=True, readonly=True)
    location_dest_id = fields.Many2one("stock.location", string="Filial", domain=lambda self: [('id', 'in', self.domain_location_ids.ids)], required=True)
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
        if 'PS/Almoxarifado' in self.location_dest_id.complete_name:
            raise UserError("Selecione uma filial, não a matriz.")

        # Cria envio da matriz
        sending = self._create_sending_transfer()

        # Cria recebimento da filial
        receiving = self._create_branch_receipt(sending)

        # Vincula pickings à OP da matriz
        self.production_id.write({
            'branch_location_id': self.location_dest_id.id,
            'sending_transfer_id': [(4, sending.id)],
            'branch_receipt_id': [(4, receiving.id)],
            'origin_production_id': self.production_id.id,
            'state': 'progress',
        })

        # Relação envio -> recebimento
        sending.write({'branch_receipt_id': [(4, receiving.id)]})
        receiving.write({'sending_transfer_id': [(4, sending.id)], 'origin_production_id': self.production_id.id})

        return {"type": "ir.actions.act_window_close"}

    def _create_sending_transfer(self):
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

        picking = self.env['stock.picking'].create({
            "picking_type_id": picking_type.id,
            "location_id": self.production_id.location_dest_id.id,
            "location_dest_id": self.location_dest_id.id,
            "origin": self.production_id.name,
            "move_ids_without_package": move_lines,
            "custom_block_validate": True,
        })

        picking.action_confirm()
        picking.state = "assigned"
        try:
            picking.action_assign()
        except Exception as e:
            _logger.warning("Não foi possível reservar automaticamente: %s", e)
            picking.write({'state': 'assigned'})

        return picking

    def _create_branch_receipt(self, sending):
        warehouse = self.location_dest_id.warehouse_id
        picking_type = self.env['stock.picking.type'].search([
            ('warehouse_id', '=', warehouse.id),
            ('code', '=', 'internal')
        ], limit=1)
        if not picking_type:
            raise UserError(f"Tipo de operação de recebimento não encontrado para {warehouse.name}")

        receiving = sending.copy({
            'picking_type_id': picking_type.id,
            'location_id': sending.location_id.id,
            'location_dest_id': self.location_dest_id.id,
            'partner_id': sending.company_id.partner_id.id,
        })

        receiving.origin_production_id = self.production_id.id
        receiving.action_confirm()
        try:
            receiving.action_assign()
            receiving.state = 'assigned'
        except Exception as e:
            _logger.warning("Não foi possível reservar automaticamente: %s", e)

        receiving.write({
            'show_validate': False,
            'custom_block_validate': True,
            'sending_transfer_id': [(4, sending.id)],
        })

        sending.write({
            'branch_receipt_id': [(4, receiving.id)],
            'custom_block_validate': True,
        })

        return receiving
