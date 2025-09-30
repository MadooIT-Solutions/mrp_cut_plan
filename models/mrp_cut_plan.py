from odoo import models, fields, api, _
from odoo.exceptions import UserError
import json


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

    def button_create_po(self):
        # Verificar se é estratégia MTO
        # if self.blue_mto_strategy:
        #     return self._process_mto_strategy()

        self.state = 'prod_order'

        # Criar a ordem de produção
        production_order = self.env['mrp.production'].create({
            'cut_plan_id': self.id,
            'product_id': self.product_id.id,
            'product_uom_id': self.product_id.uom_id.id,
            'bom_id': self.blue_bom_template_id.id,
            'product_qty': self.blue_qty,
            'partner_id': self.partner_id.id,
            'origin': self.name,
            'sale_id': self.sale_order_id.id,
            'sale_order_id':self.sale_order_id.id
        })

        # Criar movimentos manualmente a partir da BOM
        # move_raw_ids = []
        # bom = self.blue_bom_template_id
        #
        # for line in bom.bom_line_ids:
        #     move_raw_ids.append((0, 0, {
        #         'name': production_order.name,
        #         'product_id': line.product_id.id,
        #         'product_uom_qty': line.product_qty * self.blue_qty,
        #         'product_uom': line.product_uom_id.id,
        #         'location_id': production_order.location_src_id.id,
        #         'location_dest_id': production_order.product_id.property_stock_production.id,
        #         'raw_material_production_id': production_order.id,
        #         'company_id': production_order.company_id.id,
        #     }))
        #
        # production_order.write({'move_raw_ids': move_raw_ids})

        self._update_production_order_quantities(production_order)
        # self._update_count_sale_mrp()

        return {
            'type': 'ir.actions.act_window',
            'res_model': 'mrp.production',
            'view_mode': 'form',
            'res_id': production_order.id,
            'target': 'current',
            'flags': {'reload': True}
        }

    def _update_count_sale_mrp(self):
        pedido = self.sale_order_id.id

        mrp_production_ids = self.env['mrp.production'].search([('sale_id','=',pedido)])
        sale = self.env['sale.order'].browse(pedido)
        sale.mrp_production_count = len(mrp_production_ids)
        sale.mrp_production_ids = mrp_production_ids


    def _update_production_order_quantities(self, production_order):
        """Atualizar quantidades dos componentes na ordem de produção"""
        if not self.blue_bom_template_id:
            return

        for bom_line in self.blue_bom_template_id.bom_line_ids:
            # Encontrar o movimento correspondente ao componente
            move = production_order.move_raw_ids.filtered(
                lambda m: m.product_id == bom_line.product_id
            )

            if move:
                # Calcular a quantidade baseada no tipo de cálculo
                if bom_line.product_id.blue_area_calc in ['llh', 'm']:
                    if bom_line.blue_multiplier:
                        quantity = bom_line.product_qty
                    else:
                        quantity = self.blue_m3
                else:
                    if bom_line.blue_multiplier:
                        quantity = bom_line.product_qty
                    else:
                        quantity = (self.blue_qty / self.blue_bom_template_id.product_qty) * bom_line.product_qty

                # Ajustes específicos para cálculo tipo 'm'
                if self.related_type == 'm':
                    if bom_line.product_id.boolean_coefficient_or_screen == 'tl':
                        quantity = self.blue_m2
                    elif bom_line.product_id.boolean_coefficient_or_screen == 'coe':
                        template_price_config_id = self.env['mrp_cut_plan.template_price_config'].search([
                            ('product_id', '=', self.product_id.id)
                        ], limit=1)
                        if template_price_config_id:
                            quantity = self.blue_m2 * template_price_config_id.mortar_coefficient
                        else:
                            quantity = self.blue_m2 * 0

                # Atualizar a quantidade do movimento
                move.write({'product_uom_qty': quantity})

    def _process_mto_strategy(self):
        """Process MTO strategy - update stock moves without creating production orders"""
        try:
            # Atualizar o estado para produção sem criar ordem de produção
            self.state = 'draft'

            # Criar movimentos de estoque diretamente
            stock_moves = self._create_mto_stock_moves()

            # Atualizar quantidades baseadas no BOM
            self._update_mto_quantities(stock_moves)

            # Confirmar os movimentos
            stock_moves._action_confirm()

            # Adicionar mensagem de log
            self.message_post(body=_('MTO strategy applied: Stock moves created without production order'))

            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('MTO Strategy Applied'),
                    'message': _('Quantities updated using MTO strategy without creating production orders.'),
                    'type': 'success',
                    'sticky': False,
                }
            }

        except Exception as e:
            raise UserError(_('Error processing MTO strategy: %s') % str(e))

    def _create_mto_stock_moves(self):
        """Create stock moves for MTO strategy"""
        moves = self.env['stock.move']

        if not self.blue_bom_template_id:
            raise UserError(_('No BOM template defined for MTO strategy'))

        # Localizações padrão
        stock_location = self.env.ref('stock.stock_location_stock')
        production_location = self.env['stock.location'].search([
            ('usage', '=', 'production')
        ], limit=1)

        if not production_location:
            raise UserError("Nenhum local de produção configurado!")
        # production_location = self.env.ref('stock.stock_location_production')
        customer_location = self.env.ref('stock.stock_location_customers')

        # Criar movimento para o produto final (venda -> cliente)
        finished_move_vals = {
            'name': self.name,
            'product_id': self.product_id.id,
            'product_uom': self.product_id.uom_id.id,
            'product_uom_qty': self.blue_qty,
            'location_id': stock_location.id,
            'location_dest_id': customer_location.id,
            'state': 'draft',
            'origin': self.name,
            'company_id': self.env.company.id,
        }
        moves |= self.env['stock.move'].create(finished_move_vals)

        # Criar movimentos para componentes do BOM (estoque -> produção)
        for bom_line in self.blue_bom_template_id.bom_line_ids:
            component_qty = self._calculate_component_quantity(bom_line)

            move_vals = {
                'name': f"{self.name} - {bom_line.product_id.name}",
                'product_id': bom_line.product_id.id,
                'product_uom': bom_line.product_uom_id.id,
                'product_uom_qty': component_qty,
                'location_id': stock_location.id,
                'location_dest_id': production_location.id,
                'state': 'draft',
                'origin': self.name,
                'company_id': self.env.company.id,
            }
            moves |= self.env['stock.move'].create(move_vals)

        return moves

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

    def _update_mto_quantities(self, moves):
        """Update quantities for MTO strategy"""
        for move in moves:
            if move.product_id == self.product_id:
                # Produto final
                move.product_uom_qty = self.blue_qty
            else:
                # Componentes - encontrar a linha do BOM correspondente
                bom_line = self.blue_bom_template_id.bom_line_ids.filtered(
                    lambda l: l.product_id == move.product_id
                )
                if bom_line:
                    move.product_uom_qty = self._calculate_component_quantity(bom_line[0])

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
        @api.onchange('move_raw_ids')
        def _onchange_move_raw_ids(self):
            """
            Onchange para matérias-primas - Odoo 16
            """
            if self.move_raw_ids:
                # Recalcula quantidades disponíveis
                self._action_compute()
                # Atualiza a disponibilidade
                self.move_raw_ids._action_assign()

    # Para produtos acabados
    @api.onchange('move_finished_ids')
    def _onchange_move_finished_ids(self):
        """
        Onchange para produtos acabados - Odoo 16
        """
        if self.move_finished_ids:
            # Recalcula quantidades e atualiza estado
            self._action_compute()
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