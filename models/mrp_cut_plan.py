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
        self.state = 'prod_order'
        venda = self.sale_order_id.procurement_group_id
        data_plan = self.sale_order_id.commitment_date

        # Cria a ordem de produção
        production_data = { 'cut_plan_id': self.id,
            'product_id': self.product_id.id,
            'product_uom_id': self.product_id.uom_id.id,
            'bom_id': self.blue_bom_template_id.id,
            'product_qty': self.blue_qty,
            'partner_id': self.partner_id.id,
            'origin': self.name,
            'source_procurement_group_id': venda.id,
            }
        if data_plan:
            production_data['date_planned_start'] = data_plan

        production_order = self.env['mrp.production'].create(production_data)

        # Gera automaticamente os movimentos (padrão Odoo)
        production_order.action_confirm()


        # --- DIAGNÓSTICO: info detalhada das linhas da BOM e dos movimentos gerados ---
        for line in self.blue_bom_template_id.bom_line_ids:
            prod = line.product_id
            _logger.warning(
                "BOM LINE: id=%s | name=%s | area_calc=%s | display_type=%s | uom=%s | product_type=%s | product_active=%s | bom_line_qty=%s",
                prod.id if prod else None,
                prod.display_name if prod else 'NO_PRODUCT',
                getattr(prod, 'blue_area_calc', None),
                getattr(line, 'display_type', None),
                line.product_uom_id.name if line.product_uom_id else None,
                prod.type if prod else None,
                prod.active if prod else None,
                line.product_qty
            )
        for move in production_order.move_raw_ids:
            _logger.warning(
                "MOVE GENERATED: id=%s | product=%s | qty=%s | uom=%s",
                move.id,
                move.product_id.display_name,
                move.product_uom_qty,
                move.product_uom.name if move.product_uom else None
            )
        # --- fim diagnóstico ---
        # Agora ajusta apenas as quantidades conforme suas regras
        for bom_line in self.blue_bom_template_id.bom_line_ids:
            move = production_order.move_raw_ids.filtered(lambda m: m.product_id.id == bom_line.product_id.id)
            if not move:
                continue  # produto não presente no movimento

            move = move[0]
            product = bom_line.product_id
            qty = move.product_uom_qty  # quantidade padrão como base

            # 🧮 Regras personalizadas
            if product.blue_area_calc in ('llh', 'm'):
                qty = bom_line.product_qty if bom_line.blue_multiplier else self.blue_m3
            else:
                if bom_line.blue_multiplier:
                    qty = bom_line.product_qty
                else:
                    qty = (self.blue_qty / self.blue_bom_template_id.product_qty) * bom_line.product_qty

            # ⚙️ Ajustes extras para tipo "m"
            if self.related_type == 'm':
                if product.boolean_coefficient_or_screen == 'tl':
                    qty = self.blue_m2
                elif product.boolean_coefficient_or_screen == 'coe':
                    config = self.env['mrp_cut_plan.template_price_config'].search(
                        [('product_id', '=', self.product_id.id)], limit=1
                    )
                    qty = self.blue_m2 * config.mortar_coefficient if config else 0

            # Atualiza a linha
            move.product_uom_qty = qty

        # Atualiza contador da integração com vendas
        self._update_count_sale_mrp()

        return {
            'type': 'ir.actions.act_window',
            'res_model': 'mrp.production',
            'view_mode': 'form',
            'res_id': production_order.id,
            'target': 'current',
            'flags': {'reload': True}
        }



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