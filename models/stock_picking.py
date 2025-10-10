from odoo import models, fields, api
from odoo.exceptions import UserError
import logging

_logger = logging.getLogger(__name__)

class StockPicking(models.Model):
    _inherit = "stock.picking"

    custom_block_validate = fields.Boolean(string="Bloquear Validação")
    sending_transfer_id = fields.Many2one("stock.picking", string="Transferência de Envio")
    branch_receipt_id = fields.Many2one("stock.picking", string="Recebimento na Filial")
    origin_production_id = fields.Many2one("mrp.production", string="OP de Origem")
    return_transfer_id = fields.Many2one("stock.picking", string="Transferência de Retorno")
    final_receipt_id = fields.Many2one("stock.picking", string="Recebimento Final")
    branch_mo_id = fields.Many2one("mrp.production", string="OP Filial Gerada")

    def button_validate(self):
        res = super().button_validate()
        for picking in self:
            # Só agir em recebimento da filial criado pelo wizard
            if picking.origin_production_id and picking.state == 'done' and not picking.branch_mo_id:
                total_qty = sum(move.quantity_done for move in picking.move_ids_without_package)
                if total_qty <= 0:
                    continue

                picking_type = self.env['stock.picking.type'].search([
                ('warehouse_id', '=', picking.location_id.warehouse_id.id),
                ('code', '=', 'mrp_operation')
            ], limit=1)

                location_dest = self.env['stock.location'].search([
                    ('usage', '=', 'production'),
                    ('warehouse_id', '=', picking.location_dest_id.warehouse_id.id)
                ], limit=1)

                # Evitar criar OP duplicada
                if not self.env['mrp.production'].search([('origin_production_id', '=', picking.origin_production_id.id),
                                                          ('location_src_id', '=', picking.location_id.id),
                                                          ('location_dest_id', '=', location_dest.id)], limit=1):
                    mo_vals = {
                        "product_id": picking.origin_production_id.product_id.id,
                        "product_qty": total_qty,
                        "product_uom_id": picking.origin_production_id.product_id.uom_id.id,
                        "location_src_id": picking.location_id.id,
                        "location_dest_id": location_dest.id,
                        "picking_type_id":  picking_type.id,
                        "origin_production_id": picking.origin_production_id.id,

                    }
                    mo = self.env['mrp.production'].create(mo_vals)
                    picking.branch_mo_id = mo.id
                    picking.message_post(body=f"OP da filial criada automaticamente: {mo.name}")

                    po_origin = self.env['mrp.production'].browse(picking.origin_production_id.id)
                    po_origin.write({'branch_production_id':mo.id})

        return res

    @api.depends('move_ids')
    def _compute_show_validate(self):
        """Override para controlar visibilidade do botão Validar"""
        super()._compute_show_validate()
        for picking in self:
            if picking.custom_block_validate:
                picking.show_validate = False

