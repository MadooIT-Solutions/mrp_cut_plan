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
        compute="_compute_cut_plan_fields"
    )

    cotation_partner_id = fields.Many2one(
        comodel_name="res.partner",
        related="sale_order_id.partner_id",
        string="Cliente"
    )

    # Campos para controle do fluxo
    branch_location_id = fields.Many2one("stock.location", string="Armazém de Processamento", readonly=True)
    sending_transfer_id = fields.Many2one("stock.picking", string="Transferência de Envio", readonly=True)
    branch_receipt_id = fields.Many2one("stock.picking", string="Recebimento na Filial", readonly=True)
    branch_production_id = fields.Many2one("mrp.production", string="OP da Filial", readonly=True)
    return_transfer_id = fields.Many2one("stock.picking", string="Retorno da Filial", readonly=True)
    final_receipt_id = fields.Many2one("stock.picking", string="Recebimento Final", readonly=True)

    message_state = fields.Char(string="Status", compute="_compute_message_state", store=True)

    origin_production_id = fields.Many2one("mrp.production", string="OP de Origem", readonly=True)

    # ------------------------------------------------------------
    # MÉTODOS
    # ------------------------------------------------------------

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
            # log para depuração
            _logger.debug(f"_compute_message_state rodando para OP {record.name} (id={record.id})")

            if (
                record.branch_location_id
                and not record.final_receipt_id
                and record.branch_receipt_id
                and record.branch_receipt_id.state == "assigned"
                and record.sending_transfer_id
                and record.sending_transfer_id.state == "assigned"
            ):
                msg = "Aguardando envio para filial."

            elif (
                record.branch_location_id
                and not record.final_receipt_id
                and record.branch_receipt_id
                and record.branch_receipt_id.state == "assigned"
                and record.sending_transfer_id
                and record.sending_transfer_id.state == "done"
            ):
                msg = "Em trânsito para a filial."

            elif (
                record.branch_location_id
                and not record.final_receipt_id
                and record.branch_receipt_id
                and record.branch_receipt_id.state == "done"
                and record.branch_production_id
                and record.branch_production_id.state == "draft"
            ):
                msg = "Recebido na filial. Aguardando início da produção."

            elif (
                record.branch_location_id
                and not record.final_receipt_id
                and not record.return_transfer_id
                and record.branch_receipt_id
                and record.branch_receipt_id.state == "done"
                and record.branch_production_id
                and record.branch_production_id.state == "confirmed"
            ):
                msg = "Aguardando a fabricação na filial."

            elif (
                record.final_receipt_id
                and record.state == "done"
                and record.return_transfer_id
                and record.return_transfer_id.state == "assigned"
            ):
                msg = "Fabricação na filial concluída, aguardando envio."
                filial = True

            elif (
                record.branch_location_id
                and record.return_transfer_id
                and record.return_transfer_id.state == "done"
                and record.final_receipt_id
                and record.final_receipt_id.state != "done"
            ):
                msg = "Em trânsito para a matriz."
                filial = True

            elif (
                record.branch_location_id
                and record.final_receipt_id
                and record.final_receipt_id.state == "done"
            ):
                msg = "Recebido na matriz."

            elif (
                record.branch_location_id
                and record.final_receipt_id
                and record.final_receipt_id.state == "done"
                and record.state == "done"
            ):
                msg = "Produção Concluída. Aguardando envio para o cliente."
            if msg:
                record.message_state = msg
                if filial:
                    record.origin_production_id.message_state = msg

    def button_mark_done(self):
        """Override para controle do fluxo"""
        for record in self:
            if record.origin_production_id:
                res = super(BlueMrpProduction, record).button_mark_done()
                # se for OP filial, após super, cria o fluxo de retorno automaticamente
                record._create_return_flow_automatically()
                return res

            if record.branch_location_id and not record.final_receipt_id and record.branch_receipt_id and record.branch_receipt_id.state != "done":
                raise UserError("Em trânsito para a filial.")

            if record.branch_location_id and not record.final_receipt_id and record.branch_receipt_id and record.branch_receipt_id.state == "done":
                raise UserError("Aguardando a fabricação na filial.")

            if record.branch_location_id and record.branch_production_id and record.branch_production_id.state == "done" and not record.final_receipt_id:
                raise UserError("Fabricação na filial concluída, aguardando retorno.")

            if not record.branch_location_id:
                return {
                    'name': 'Selecionar Armazém para Processamento',
                    'type': 'ir.actions.act_window',
                    'res_model': 'mrp.production.transfer.wizard',
                    'view_mode': 'form',
                    'target': 'new',
                    'context': {'default_production_id': record.id}
                }

            if record.final_receipt_id and record.final_receipt_id.state != 'done':
                raise UserError("O recebimento final precisa ser confirmado antes de concluir a OP matriz.")

            return super(BlueMrpProduction, record).button_mark_done()

    # ------------------------------------------------------------
    # MÉTODOS AUXILIARES
    # ------------------------------------------------------------

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

                record.write({
                    'return_transfer_id': return_picking.id,
                    'final_receipt_id': final_receipt.id,
                })

                # também atualiza a OP de origem (matriz)
                record.origin_production_id.write({
                    'return_transfer_id': return_picking.id,
                    'final_receipt_id': final_receipt.id,
                })

                # Forçar recálculo e persistência do campo armazenado message_state
                # (evita dependências indiretas que o ORM pode não detectar)
                record._compute_message_state()
                record.origin_production_id._compute_message_state()
                record.write({'message_state': record.message_state})
                record.origin_production_id.write({'message_state': record.origin_production_id.message_state})

                _logger.info(f"✅ Retorno automático criado: {return_picking.name}")
                _logger.info(f"✅ Recebimento final criado: {final_receipt.name}")

            except Exception as e:
                _logger.error(f"❌ Erro ao criar retorno automático: {str(e)}")
                raise UserError(f"Erro ao criar retorno automático: {str(e)}")

    def _create_return_transfer(self):
        self.ensure_one()
        """Cria transferência de retorno da filial para matriz"""
        move_lines = []
        for move in self.move_finished_ids:
            if move.product_id.type != 'service' and move.product_qty > 0:
                move_lines.append((0, 0, {
                    "name": f"Retorno {move.product_id.display_name}",
                    "product_id": move.product_id.id,
                    "product_uom_qty": move.product_qty,
                    "product_uom": move.product_uom.id,
                    "location_id": self.location_dest_id.id,
                    "location_dest_id": self.location_dest_id.id,
                }))

        if not move_lines:
            raise UserError("❌ Nenhum movimento válido encontrado para criar retorno.")

        picking = self.env["stock.picking"].create({
            "location_id": self.location_dest_id.id,
            "location_dest_id": self.location_dest_id.id,
            "origin": f"{self.name} - Retorno para Matriz",
            "move_ids_without_package": move_lines,
            "picking_type_id": self.env['stock.picking.type'].search([
                ('warehouse_id', '=', self.location_dest_id.warehouse_id.id),
                ('code', '=', 'internal')
            ], limit=1).id,
        })

        picking.action_confirm()
        picking.action_assign()
        return picking

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
            "location_id": move.location_id.id,
            "location_dest_id": move.location_dest_id.id,
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
