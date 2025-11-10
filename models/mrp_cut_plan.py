from odoo import models, fields, api, _
from odoo.exceptions import UserError
import json
import logging

_logger = logging.getLogger(__name__)

class MrpCutPlan(models.Model):
    _name = 'mrp_cut_plan.mrp_cut_plan'
    _description = 'Cut Plan Model'
    _inherit = 'mail.thread'

    name = fields.Char(
        string="Name",
        readonly=True
    )
    product_id = fields.Many2one(  # ESTE CAMPO JÁ EXISTE NO SEU CÓDIGO ORIGINAL
        comodel_name="product.product",
        string="Product",
        required=True,
        tracking=True
    )
    product_id_number = fields.Integer(
        string="Id of Product",
        compute="_compute_product_id_number"
    )
    product_uom_id = fields.Many2one(
        related="product_id.uom_id",
        string="Uom",
        tracking=True
    )
    blue_qty = fields.Float(
        string="Quantity",
        required=True,
        tracking=True
    )

    blue_bom_template_id = fields.Many2one(
        comodel_name="mrp.bom",
        string="Material List Model",
        domain="[('product_id', '=', product_id )]",
        tracking=True
    )

    blue_origin = fields.Char(
        string="Sales order",
        tracking=True
    )
    blue_I = fields.Float(
        string="L",
        digits='Product Unit of Measure',
        tracking=True
    )
    blue_II = fields.Float(
        string="L ",
        digits='Product Unit of Measure',
        tracking=True
    )
    blue_h = fields.Float(
        string="H",
        digits='Product Unit of Measure',
        tracking=True
    )
    blue_I_uom = fields.Many2one(
        comodel_name="uom.uom",
        string="Uom ",
        tracking=True
    )
    blue_II_uom = fields.Many2one(
        comodel_name="uom.uom",
        string="Uom  ",
        tracking=True
    )
    blue_h_uom = fields.Many2one(
        comodel_name="uom.uom",
        string="Uom   ",
        tracking=True,
    )
    blue_m3 = fields.Float(
        string="Total in m³",
        readonly=True,
        compute="_compute_blue_m3",
        digits='Product Unit of Measure',
        tracking=True
    )
    blue_m2 = fields.Float(
        string="Total in m²",
        readonly=True,
        compute="_compute_blue_m2",
        digits='Product Unit of Measure',
        tracking=True
    )
    state = fields.Selection(
        selection=[
            ('draft', 'Draft'),
            ('prod_order', 'Production Order'),
            ('canceled', 'Canceled')
        ],
        default="draft",
        string="State",
        readonly=True,
        tracking=True
    )
    blue_po_count = fields.Integer(
        string="Documents Count",
        compute="_compute_blue_po_count",
        tracking=True
    )
    production_order_id = fields.One2many(
        comodel_name="mrp.production",
        inverse_name="cut_plan_id",
        string="Production Order",
        tracking=True
    )

    blue_advance = fields.Float(
        string="Advance",
        digits='Product Unit of Measure',
    )

    blue_wall = fields.Float(
        string="Wall",
        digits='Product Unit of Measure',
    )

    blue_wall_uom = fields.Many2one(
        comodel_name="uom.uom",
        string="Udm"
    )

    blue_advance_uom = fields.Many2one(
        comodel_name="uom.uom",
        string="Udm"
    )

    related_type = fields.Selection(
        related="product_id.blue_area_calc"
    )

    cotation_partner_id = fields.Many2one(
        comodel_name="res.partner",
        related="sale_order_id.partner_id",
        string="Cliente"
    )

    template_price_config_id = fields.Many2one(
        comodel_name="mrp_cut_plan.template_price_config",
        string="Template Price Config",
        compute="_compute_template_price_config_id"
    )

    binany_field = fields.Image(
        string="Imagem"
    )

    partner_id = fields.Many2one(
        string="Cliente",
        comodel_name="res.partner"
    )

    sale_order_id = fields.Many2one(
        comodel_name="sale.order",
        string="Cotação",
    )

    # NOVO CAMPO PARA ESTRATÉGIA MTO
    blue_mto_strategy = fields.Boolean(
        string="MTO Strategy",
        compute="_compute_blue_mto_strategy",
        help="If True, uses MTO strategy without creating production orders"
    )

    def open_linked_po_orders(self):
        domain = [('cut_plan_id', '=', self.id)]
        return {
            'name': _('Production Orders'),
            'domain': domain,
            'type': 'ir.actions.act_window',
            'res_model': 'mrp.production',
            'view_id': False,
            'view_mode': 'tree,form',
        }

    @api.depends('production_order_id')
    def _compute_blue_po_count(self):
        for record in self:
            record.blue_po_count = len(record.production_order_id)

    @api.depends('product_id')  # CORRIGIDO - product_id JÁ EXISTE
    def _compute_blue_mto_strategy(self):
        for record in self:
            if record.product_id:
                # Verificar se o produto tem rota MTO configurada
                mto_route = self.env.ref('stock.route_warehouse0_mto', raise_if_not_found=False)
                if mto_route and mto_route in record.product_id.route_ids:
                    record.blue_mto_strategy = True
                else:
                    record.blue_mto_strategy = False
            else:
                record.blue_mto_strategy = False

    def _update_count_sale_mrp(self):
        pedido = self.sale_order_id.id

        mrp_production_ids = self.env['mrp.production'].search([('sale_id','=',pedido)])
        sale = self.env['sale.order'].browse(pedido)
        sale.mrp_production_count = len(mrp_production_ids)
        sale.mrp_production_ids = mrp_production_ids

    def _calculate_component_quantity(self, bom_line):
        """Calculate component quantity based on BOM line and cut plan"""
        if bom_line.product_id.blue_area_calc in ['llh', 'm']:
            if bom_line.blue_multiplier:
                return bom_line.product_qty
            else:
                return self.blue_m3
        else:
            if bom_line.blue_multiplier:
                return bom_line.product_qty
            else:
                return (self.blue_qty / self.blue_bom_template_id.product_qty) * bom_line.product_qty

    # ------------------------------
    # Botão "Enviar para Filial"
    # ------------------------------
    def button_send_to_branch(self):
        """Botão que envia OP para a filial, só aparece para related_type='m'"""
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

        # ------------------------------
        # Botão "Marcar como Concluído"
        # ------------------------------
        def button_mark_done_custom(self):
            """Botão que conclui OP, só aparece quando não é Mold Calculation"""
            for record in self:
                if record.related_type == 'm':
                    raise UserError("Este botão não está disponível para Mold Calculation.")

                return super(BlueMrpProduction, record).button_mark_done()

    def button_create_po(self):
        self.ensure_one()
        self.state = 'prod_order'

        venda = self.sale_order_id.procurement_group_id if self.sale_order_id else False
        data_plan = self.sale_order_id.commitment_date if self.sale_order_id else False
        # 🔹 Forçar criação na matriz (exemplo: Polispan)
        company_matrix = self.env['res.company'].search([('name', '=', 'Polispan')], limit=1)
        warehouse_matrix = self.env['stock.warehouse'].search([('company_id', '=', company_matrix.id)], limit=1)

        if not warehouse_matrix:
            raise UserError("❌ Nenhum armazém encontrado para a matriz (Polispan).")

        # 🔹 Criação da OP
        production_data = {
            'company_id': company_matrix.id,
            'location_src_id': warehouse_matrix.lot_stock_id.id,  # Estoque origem
            'location_dest_id': warehouse_matrix.lot_stock_id.id,  # Produção destino
            'cut_plan_id': self.id,
            'product_id': self.product_id.id,
            'product_uom_id': self.product_id.uom_id.id,
            'bom_id': self.blue_bom_template_id.id,
            'product_qty': self.blue_qty,
            'partner_id': self.partner_id.id,
            'origin': self.name,
            'source_procurement_group_id': venda.id if venda else False,
            'related_type': self.product_id.blue_area_calc,
        }

        if data_plan:
            production_data['date_planned_start'] = data_plan

        production_order = self.env['mrp.production'].create(production_data)

        # 🔹 Gera os movimentos (substitui os antigos onchange)
        production_order.action_confirm()

        # 🔹 Ajusta manualmente as quantidades conforme lógica do Odoo 15
        for bom_line in self.blue_bom_template_id.bom_line_ids:
            for move in production_order.move_raw_ids:
                if move.product_id == bom_line.product_id:
                    if move.product_id.blue_area_calc in ['llh', 'm']:
                        if bom_line.blue_multiplier:
                            move.product_uom_qty = bom_line.product_qty
                        else:
                            move.product_uom_qty = self.blue_m3
                    else:
                        if bom_line.blue_multiplier:
                            move.product_uom_qty = bom_line.product_qty
                        else:
                            move.product_uom_qty = (
                                    (self.blue_qty / self.blue_bom_template_id.product_qty) * bom_line.product_qty
                            )

                    if self.related_type == 'm':
                        if move.product_id.boolean_coefficient_or_screen == 'tl':
                            move.product_uom_qty = self.blue_m2
                        elif move.product_id.boolean_coefficient_or_screen == 'coe':
                            template_price_config_id = self.env['mrp_cut_plan.template_price_config'].search([
                                ('product_id', '=', self.product_id.id)
                            ], limit=1)
                            if template_price_config_id:
                                move.product_uom_qty = self.blue_m2 * template_price_config_id.mortar_coefficient
                            else:
                                move.product_uom_qty = self.blue_m2 * 0

        # 🔹 Refaz as reservas conforme as novas quantidades
        production_order.move_raw_ids._action_assign()

        # 🔹 Atualiza contador de OPs
        self._update_count_sale_mrp()

        # 🔹 Abre a OP criada
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'mrp.production',
            'view_mode': 'form',
            'res_id': production_order.id,
            'target': 'current',
            'flags': {'reload': True},
        }

    def _force_generate_moves(self, production_order):
        """Garante que a MO terá moves raw e finished"""
        if not production_order.bom_id:
            _logger.warning("MO %s não possui BOM, pulando geração de movimentos", production_order.name)
            return

        # -----------------------------
        # 1) Cria os moves raw
        # -----------------------------
        if not production_order.move_raw_ids:
            raw_vals_list = production_order._get_moves_raw_values()
            if raw_vals_list:
                raw_moves = self.env['stock.move'].create(raw_vals_list)
                raw_moves._action_confirm()
                _logger.warning("Criados %s raw moves manualmente para MO %s", len(raw_moves), production_order.name)

        # -----------------------------
        # 2) Cria os moves finished
        # -----------------------------
        if not production_order.move_finished_ids:
            finished_vals_list = production_order._get_move_finished_values()
            if finished_vals_list:
                finished_moves = self.env['stock.move'].create(finished_vals_list)
                finished_moves._action_confirm()
                _logger.warning("Criado finished move para MO %s", production_order.name)

        # -----------------------------
        # 3) Ajusta quantidade dos moves raw conforme Cut Plan
        # -----------------------------
        bom = production_order.bom_id
        for bom_line in bom.bom_line_ids:
            product = bom_line.product_id
            if not product:
                continue

            # Calcula qty conforme regras Cut Plan
            if product.blue_area_calc in ('llh', 'm'):
                qty = bom_line.product_qty if bom_line.blue_multiplier else self.blue_m3
            else:
                bom_qty = bom.product_qty or 1.0
                qty = (
                                  self.blue_qty / bom_qty) * bom_line.product_qty if not bom_line.blue_multiplier else bom_line.product_qty

            # Ajustes extras para tipo 'm'
            if self.related_type == 'm':
                if product.boolean_coefficient_or_screen == 'tl':
                    qty = self.blue_m2
                elif product.boolean_coefficient_or_screen == 'coe':
                    config = self.env['mrp_cut_plan.template_price_config'].search(
                        [('product_id', '=', self.product_id.id)], limit=1
                    )
                    qty = (self.blue_m2 * config.mortar_coefficient) if config else 0

            if qty <= 0:
                continue

            moves = production_order.move_raw_ids.filtered(lambda m: m.product_id == product)
            for mv in moves:
                mv.product_uom_qty = qty
                if hasattr(mv, 'product_qty'):
                    try:
                        mv.product_qty = qty
                    except Exception:
                        pass

        _logger.warning("Geração de moves completa para MO %s", production_order.name)

    def button_cancel(self):
        self.state = 'canceled'

    @api.depends('product_id')
    def _compute_template_price_config_id(self):
        for record in self:
            if record.related_type == "m":
                template_price_config_id = self.env['mrp_cut_plan.template_price_config'].search(
                    [('product_id', '=', self.product_id.id)])
                self.template_price_config_id = template_price_config_id.id
            else:
                self.template_price_config_id = False

    @api.onchange('product_id')
    def _onchange_product_id(self):
        for record in self:
            if record.product_id.secondary_uom_id.category_id == self.env.ref('uom.product_uom_meter').category_id:
                record.blue_I_uom = record.product_id.secondary_uom_id
                record.blue_II_uom = record.product_id.secondary_uom_id
                record.blue_h_uom = record.product_id.secondary_uom_id
                record.blue_wall_uom = record.product_id.secondary_uom_id
                record.blue_advance_uom = record.product_id.secondary_uom_id

        if self.related_type == 'm':
            template_price_config_id = self.env['mrp_cut_plan.template_price_config'].search(
                [('product_id', '=', self.product_id.id)])
            if template_price_config_id:
                self.blue_wall = template_price_config_id.blue_wall
                self.blue_wall_uom = template_price_config_id.blue_wall_uom.id
                self.template_price_config_id = template_price_config_id.id
            else:
                self.blue_wall = 0
                self.blue_wall_uom = False

    @api.depends('blue_I', 'blue_I_uom', 'blue_h', 'blue_h_uom', 'blue_II', 'blue_II_uom', 'blue_qty', 'blue_advance',
                 'blue_advance_uom')
    def _compute_blue_m3(self):
        for record in self:

            meter_uom_id = self.env.ref('uom.product_uom_meter')
            height = record.blue_h

            if record.product_id.blue_area_calc == 'llh':
                if all(getattr(record, field) for field in [
                    'blue_I', 'blue_II', 'blue_h', 'blue_I_uom', 'blue_II_uom', 'blue_h_uom']
                       ):
                    side1 = record.blue_I
                    side2 = record.blue_II

                    if record.blue_I_uom != meter_uom_id:
                        side1 = record.blue_I_uom._compute_quantity(record.blue_I, meter_uom_id, round=False)

                    if record.blue_II_uom != meter_uom_id:
                        side2 = record.blue_II_uom._compute_quantity(record.blue_II, meter_uom_id, round=False)

                    if record.blue_h_uom != meter_uom_id:
                        height = record.blue_h_uom._compute_quantity(record.blue_h, meter_uom_id, round=False)

                    record.blue_m3 = side1 * side2 * height * record.blue_qty
                else:
                    record.blue_m3 = 0

            elif record.product_id.blue_area_calc == 'm':
                if all(getattr(record, field) for field in [
                    'blue_advance', 'blue_advance_uom', 'blue_h', 'blue_h_uom']
                       ):
                    advance = record.blue_advance

                    if record.blue_advance_uom != meter_uom_id:
                        advance = record.blue_advance_uom._compute_quantity(record.blue_advance, meter_uom_id,
                                                                            round=False)

                    if record.blue_h_uom != meter_uom_id:
                        height = record.blue_h_uom._compute_quantity(record.blue_h, meter_uom_id, round=False)

                    record.blue_m3 = advance * height
                else:
                    record.blue_m3 = 0
            else:
                record.blue_m3 = 0

    @api.depends('blue_I', 'blue_II', 'blue_I_uom', 'blue_II_uom', 'blue_qty', 'blue_advance', 'blue_wall',
                 'blue_wall_uom', 'blue_advance_uom')
    def _compute_blue_m2(self):
        for record in self:
            meter_uom_id = self.env.ref('uom.product_uom_meter')

            if record.product_id.blue_area_calc == 'llh':
                if all(getattr(record, field) for field in ['blue_I', 'blue_II', 'blue_I_uom', 'blue_II_uom']):
                    side1 = record.blue_I
                    side2 = record.blue_II

                    if record.blue_I_uom != meter_uom_id:
                        side1 = record.blue_I_uom._compute_quantity(record.blue_I, meter_uom_id, round=False)

                    if record.blue_II_uom != meter_uom_id:
                        side2 = record.blue_II_uom._compute_quantity(record.blue_II, meter_uom_id, round=False)

                    record.blue_m2 = side1 * side2 * record.blue_qty
                else:
                    record.blue_m2 = 0

            elif record.product_id.blue_area_calc == 'm':
                if all(getattr(record, field) for field in
                       ['blue_wall', 'blue_advance', 'blue_wall_uom', 'blue_advance_uom', 'blue_h', 'blue_h_uom']):

                    wall = record.blue_wall
                    advance = record.blue_advance
                    height = record.blue_h

                    if record.blue_wall_uom != meter_uom_id:
                        wall = record.blue_wall_uom._compute_quantity(record.blue_wall, meter_uom_id, round=False)

                    if record.blue_advance_uom != meter_uom_id:
                        advance = record.blue_advance_uom._compute_quantity(record.blue_advance, meter_uom_id,
                                                                            round=False)

                    if record.blue_h_uom != meter_uom_id:
                        height = record.blue_h_uom._compute_quantity(record.blue_h, meter_uom_id, round=False)

                    record.blue_m2 = wall + height + advance + advance
                else:
                    record.blue_m2 = 0
            else:
                record.blue_m2 = 0

    @api.model
    def create(self, vals):
        vals['name'] = self.env['ir.sequence'].next_by_code('mrp.cut.plan')
        return super(MrpCutPlan, self).create(vals)

    @api.depends('product_id')
    def _compute_product_id_number(self):
        for record in self:
            record.product_id_number = record.product_id.id



        # Para matérias-primas
        # @api.onchange('move_raw_ids')
        # def _onchange_move_raw_ids(self):
        #     """
        #     Onchange para matérias-primas - Odoo 16
        #     """
        #     if self.move_raw_ids:
        #         # Recalcula quantidades disponíveis
        #         self._action_compute()
        #         # Atualiza a disponibilidade
        #         self.move_raw_ids._action_assign()

    # Para produtos acabados
    # @api.onchange('move_finished_ids')
    # def _onchange_move_finished_ids(self):
    #     """
    #     Onchange para produtos acabados - Odoo 16
    #     """
    #     if self.move_finished_ids:
    #         # Recalcula quantidades e atualiza estado
    #         self._action_compute()
            # Para produtos acabados, geralmente não fazemos action_assign
            # pois são produtos que serão produzidos

    # Para ordens de trabalho
    @api.onchange('workorder_ids')
    def _onchange_workorder_ids(self):
        """
        Onchange para ordens de trabalho - Odoo 16
        """
        if self.workorder_ids:
            # Recalcula a duração esperada
            self._onchange_workorder_duration()
            # Atualiza operações
            self._create_workorder()

    def _onchange_workorder_duration(self):
        """
        Método auxiliar para calcular duração das ordens de trabalho
        """
        total_duration = sum(wo.duration_expected for wo in self.workorder_ids)
        self.duration_expected = total_duration