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
    location_dest_warehouse_name = fields.Char(
        string="Armazém",
        compute="_compute_location_dest_warehouse",
    )

    @api.depends("location_dest_id")
    def _compute_location_dest_warehouse(self):
        for wizard in self:
            if wizard.location_dest_id:
                warehouse = wizard.location_dest_id.warehouse_id
                wizard.location_dest_warehouse_name = warehouse.name if warehouse else "-"
            else:
                wizard.location_dest_warehouse_name = "-"

    @api.onchange("production_id")
    def _onchange_production_id(self):
        """Atualiza lista de locais internos de outros armazéns"""
        for wizard in self:
            production = wizard.production_id
            if not production or not production.location_src_id:
                wizard.domain_location_ids = self.env['stock.location'].search([('usage', '=', 'internal')])
                continue

            current_loc = production.location_src_id
            # encontra armazém do local de origem
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

            # força atualizar o domínio do campo
            return {'domain': {'location_dest_id': [('id', 'in', locs.ids)]}}

    def action_confirm(self):
        """Fase 1: Matriz → Filial"""
        if 'PS/Almoxarifado' in self.location_dest_id.complete_name:
            raise UserError("Selecione uma filial, não a matriz.")

        # 1. Cria envio da matriz (assigned)
        sending = self._create_sending_transfer()

        # 2. Cria recebimento da filial baseado no envio (assigned)
        receiving = self._create_branch_receipt(sending)

        # Vincula pickings à OP da matriz
        self.production_id.write({
            'branch_location_id': self.location_dest_id.id,
            'sending_transfer_id': sending.id,
            'branch_receipt_id': receiving.id,
            'origin_production_id': self.production_id.id,
            'state': 'progress',
        })

        return {"type": "ir.actions.act_window_close"}

    def _create_sending_transfer(self):
        """Cria envio interno da matriz para filial"""
        picking_type = self.env['stock.picking.type'].search([
            ('code','=','internal'),
            ('warehouse_id.name','=','Polispan')
        ], limit=1)
        if not picking_type:
            picking_type = self.env['stock.picking.type'].search([
                ('code','=','internal'),
                ('company_id','=',self.env.company.id)
            ], limit=1)
        if not picking_type:
            raise UserError("Tipo de operação interna não encontrado.")

        move_lines = []
        for move in self.production_id.move_finished_ids:
            if move.product_id.type != 'service':
                qty = move.product_uom_qty
                move_lines.append((0, 0, {
                    "name": f"Envio {move.product_id.display_name}",
                    "product_id": move.product_id.id,
                    "product_uom_qty": qty,
                    "product_uom": move.product_uom.id,
                    "location_id": self.production_id.location_dest_id.id,
                    "location_dest_id": self.location_dest_id.id,
                    "reserved_availability": qty,
                }))

        picking = self.env['stock.picking'].create({
            "picking_type_id": picking_type.id,
            "location_id": self.production_id.location_dest_id.id,
            "location_dest_id": self.location_dest_id.id,
            "origin": self.production_id.name,
            "move_ids_without_package": move_lines,
        })

        # Coloca em assigned
        picking.action_confirm()
        try:
            picking.action_assign()
            picking.state = "assigned"
        except Exception as e:
            _logger.warning("Não foi possível reservar automaticamente: %s", e)

        return picking

    def _create_branch_receipt(self, sending):
        """Cria o recebimento da filial sem duplicar movimentos"""
        warehouse = self.location_dest_id.warehouse_id
        picking_type = self.env['stock.picking.type'].search([
            ('warehouse_id', '=', warehouse.id),
            ('code', '=', 'incoming')
        ], limit=1)
        if not picking_type:
            raise UserError(f"Tipo de operação de recebimento não encontrado para {warehouse.name}")

        # Copiar o picking de envio para criar recebimento
        receiving = sending.copy({
            'picking_type_id': picking_type.id,
            'location_id': sending.location_dest_id.id,
            'location_dest_id': self.location_dest_id.id,
            'partner_id': self.company_id.partner_id.id,

        })

        # Define a ligação com a OP de origem (matriz)
        receiving.origin_production_id = self.production_id.id

        receiving.action_confirm()
        try:
            receiving.action_assign()
            receiving.state = 'assigned'
        except Exception as e:
            _logger.warning("Não foi possível reservar automaticamente: %s", e)

        return receiving

    # ---------------------------
    # Eventos automáticos
    # ---------------------------

    @api.model
    def on_receipt_done(self, picking):
        """Cria OP da filial automaticamente após confirmação do recebimento"""
        if picking.picking_type_code != 'internal' or not picking.origin_production_id:
            return

        total_qty = sum(move.quantity_done for move in picking.move_ids_without_package)
        if total_qty <= 0:
            return

        # Buscar local de produção da filial
        filial_production_loc = self.env['stock.location'].search([
            ('usage', '=', 'production'),
            ('complete_name', 'ilike', picking.location_dest_id.location_id.name)
        ], limit=1)

        picking_type_branch = self.env['stock.picking.type'].search([
            ('warehouse_id', '=', location_src_id.id),
            ('code', '=', 'manufacturing')
        ], limit=1)

        if not filial_production_loc:
            raise UserError(f"Não existe local de Produção configurado para {picking.location_dest_id.location_id.name}")

        mo_vals = {
            "product_id": picking.origin_production_id.product_id.id,
            "product_qty": total_qty,
            "product_uom_id": picking.origin_production_id.product_uom_id.id,
            "location_src_id": picking.location_id.id,
            "location_dest_id": filial_production_loc.id,
            "picking_type_id": picking_type_branch.id,
            "branch_receipt_id": picking.id,
            "origin": picking.origin_production_id,
            'source_procurement_group_id': picking.origin_production_id.procurement_group_id.id,


        }
        mo = self.env['mrp.production'].create(mo_vals)
        picking.branch_mo_id = mo.id

    @api.model
    def on_mo_done(self, mo):
        """Cria retorno + recebimento final ao concluir OP da filial"""
        if not mo.branch_receipt_id:
            return

        sending_type = self.env['stock.picking.type'].search([
            ('code','=','internal'),
            ('warehouse_id','=',mo.location_dest_id.warehouse_id.id)
        ], limit=1)
        if not sending_type:
            return

        move_lines = []
        for move in mo.move_finished_ids:
            move_lines.append((0,0,{
                "name": f"Retorno {move.product_id.display_name}",
                "product_id": move.product_id.id,
                "product_uom_qty": move.product_uom_qty,
                "product_uom": move.product_uom.id,
                "location_id": mo.location_dest_id.id,
                "location_dest_id": mo.origin_location_id.id,
                "reserved_availability": move.product_uom_qty,
            }))

        picking = self.env['stock.picking'].create({
            "picking_type_id": sending_type.id,
            "location_id": mo.location_dest_id.id,
            "location_dest_id": mo.origin_location_id.id,
            "origin": mo.name,
            "move_ids_without_package": move_lines,
        })


        picking.action_confirm()
        try:
            picking.action_assign()
        except Exception as e:
            _logger.warning("Não foi possível reservar retorno automaticamente: %s", e)

        mo.branch_return_id = picking.id
