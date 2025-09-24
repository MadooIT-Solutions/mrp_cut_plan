from collections import defaultdict
from odoo import fields, models, api, _
from odoo.tools import float_round
from odoo.tools.misc import groupby as tools_groupby


class BlueMrpProduction(models.Model):
    _inherit = "mrp.production"

    cut_plan_id = fields.Many2one(
        comodel_name="mrp_cut_plan.mrp_cut_plan",
        string="Cut Plan",
        tracking=True
    )
    count_po = fields.Integer(
        string="Documents Count",
        compute="_compute_count_po",
        tracking=True
    )

    partner_id = fields.Many2one(
        string="Cliente",
        comodel_name="res.partner"
    )

    # REMOVER OS CAMPOS RELATED QUE NÃO EXISTEM NO MODELO BASE
    # Em vez de usar related, vamos acessar através do cut_plan_id
    blue_I = fields.Float(
        string="L",
        digits='Product Unit of Measure',
        tracking=True,
        compute="_compute_cut_plan_fields",
        store=False  # Não armazenar no banco, calcular sob demanda
    )

    blue_II = fields.Float(
        string="L ",
        digits='Product Unit of Measure',
        tracking=True,
        compute="_compute_cut_plan_fields",
        store=False
    )

    blue_h = fields.Float(
        string="H",
        digits='Product Unit of Measure',
        tracking=True,
        compute="_compute_cut_plan_fields",
        store=False
    )

    blue_I_uom = fields.Many2one(
        comodel_name="uom.uom",
        string="Uom ",
        tracking=True,
        compute="_compute_cut_plan_fields",
        store=False
    )

    blue_II_uom = fields.Many2one(
        comodel_name="uom.uom",
        string="Uom  ",
        tracking=True,
        compute="_compute_cut_plan_fields",
        store=False
    )

    blue_h_uom = fields.Many2one(
        comodel_name="uom.uom",
        string="Uom   ",
        tracking=True,
        compute="_compute_cut_plan_fields",
        store=False
    )

    sale_order_id = fields.Many2one(
        comodel_name="sale.order",
        string="Pedido",
    )

    blue_advance = fields.Float(
        string="Advance",
        digits='Product Unit of Measure',
        compute="_compute_cut_plan_fields",
        store=False
    )

    blue_advance_uom = fields.Many2one(
        comodel_name="uom.uom",
        string="Udm",
        compute="_compute_cut_plan_fields",
        store=False
    )

    # CORRIGIDO: Adicionar selection para o campo related_type
    related_type = fields.Selection(
        selection=[
            ("n", "None"),
            ("llh", "LLH Calculation"),
            ("m", "Mold Calculation")
        ],
        string="Related Type",
        compute="_compute_cut_plan_fields",
        store=False
    )

    cotation_partner_id = fields.Many2one(
        comodel_name="res.partner",
        related="sale_order_id.partner_id",
        string="Cliente"
    )


    def _compute_count_po(self):
        for record in self:
            if record.cut_plan_id:
                record.count_po = 1
            else:
                record.count_po = 0

    def open_linked_po(self):
        domain = [('id', '=', self.cut_plan_id.id)] if self.cut_plan_id else [('id', '=', 0)]
        return {
            'name': _('Plano de Corte'),
            'domain': domain,
            'type': 'ir.actions.act_window',
            'res_model': 'mrp_cut_plan.mrp_cut_plan',
            'view_id': False,
            'view_mode': 'tree,form',
        }

    @api.depends('cut_plan_id')
    def _compute_cut_plan_fields(self):
        """Calcular todos os campos relacionados ao cut_plan sob demanda"""
        for record in self:
            if record.cut_plan_id:
                # Acessar os campos através do cut_plan_id
                record.blue_I = record.cut_plan_id.blue_I
                record.blue_II = record.cut_plan_id.blue_II
                record.blue_h = record.cut_plan_id.blue_h
                record.blue_I_uom = record.cut_plan_id.blue_I_uom
                record.blue_II_uom = record.cut_plan_id.blue_II_uom
                record.blue_h_uom = record.cut_plan_id.blue_h_uom
                record.blue_advance = record.cut_plan_id.blue_advance
                record.blue_advance_uom = record.cut_plan_id.blue_advance_uom
                record.related_type = record.cut_plan_id.related_type
            else:
                # Definir valores padrão quando não houver cut_plan
                record.blue_I = 0.0
                record.blue_II = 0.0
                record.blue_h = 0.0
                record.blue_I_uom = False
                record.blue_II_uom = False
                record.blue_h_uom = False
                record.blue_advance = 0.0
                record.blue_advance_uom = False
                record.related_type = False

    @api.onchange('move_raw_ids')
    def _onchange_move_raw_ids(self):
        for record in self:
            if record.cut_plan_id:
                for move in record.move_raw_ids:
                    move.product_uom_qty = record.cut_plan_id.blue_m3

    @api.onchange('product_qty')
    def _onchange_product_qty(self):
        if self.bom_id and self.move_raw_ids:
            multiplier_bom_ids = self.bom_id.bom_line_ids.filtered_domain([('blue_multiplier', '=', True)])
            if multiplier_bom_ids:
                for line in self.move_raw_ids:
                    bom_id = multiplier_bom_ids.filtered_domain([('product_id', '=', line.product_id.id)])
                    line.product_uom_qty = bom_id.product_qty

    def _post_inventory(self, cancel_backorder=False):
        moves_to_do, moves_not_to_do = set(), set()
        for move in self.move_raw_ids:
            if move.state == 'done':
                moves_not_to_do.add(move.id)
            elif move.state != 'cancel':
                moves_to_do.add(move.id)
                if move.product_qty == 0.0 and move.quantity_done > 0:
                    move.product_uom_qty = move.quantity_done
        self.env['stock.move'].browse(moves_to_do)._action_done(cancel_backorder=cancel_backorder)
        moves_to_do = self.move_raw_ids.filtered(lambda x: x.state == 'done') - self.env['stock.move'].browse(
            moves_not_to_do)
        moves_to_do_by_order = defaultdict(lambda: self.env['stock.move'], [
            (key, self.env['stock.move'].concat(*values))
            for key, values in tools_groupby(moves_to_do, key=lambda m: m.raw_material_production_id.id)
        ])
        for order in self:
            finish_moves = order.move_finished_ids.filtered(
                lambda m: m.product_id == order.product_id and m.state not in ('done', 'cancel'))
            if finish_moves and not finish_moves.quantity_done:
                finish_moves._set_quantity_done(float_round(order.qty_producing - order.qty_produced,
                                                            precision_rounding=order.product_uom_id.rounding,
                                                            rounding_method='HALF-UP'))
                finish_moves.move_line_ids.lot_id = order.lot_producing_id
            for workorder in order.workorder_ids:
                if workorder.state not in ('done', 'cancel'):
                    workorder.duration_expected = workorder._get_duration_expected()
                if workorder.duration == 0.0:
                    workorder.duration = workorder.duration_expected * order.qty_produced / order.product_qty
            order._cal_price(moves_to_do_by_order[order.id])
        moves_to_finish = self.move_finished_ids.filtered(lambda x: x.state not in ('done', 'cancel'))
        moves_to_finish = moves_to_finish._action_done(cancel_backorder=cancel_backorder)
        self.action_assign()
        for order in self:
            consume_move_lines = moves_to_do_by_order[order.id].mapped('move_line_ids')
            order.move_finished_ids.move_line_ids.consume_line_ids = [(6, 0, consume_move_lines.ids)]
        return True

