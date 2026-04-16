from odoo import models, fields, api
from odoo.exceptions import UserError, ValidationError

class BlueSaleOrderLineConfig(models.TransientModel):
    _name = "sale.order.line.config"
    _description = "Order Line Area Calculation"

    order_line_id = fields.Many2one(
        comodel_name="sale.order.line",
        string="Sale Order Line",
    )
    product_id = fields.Many2one(
        comodel_name="product.product",
        related="order_line_id.product_id"
    )

    product_template_id = fields.Many2one(
        string="Product",
        comodel_name="product.template",
        readonly="True"
    )

    quantity = fields.Integer(
        string="Quantity"
    )

    pricelist_id = fields.Many2one(
        comodel_name="product.pricelist"
    )

    currency_id = fields.Many2one(related='pricelist_id.currency_id', depends=["pricelist_id"], store=True, ondelete="restrict")

    price_unit = fields.Monetary(
        string="Price",
        currency_field="currency_id",
    )

    price_total = fields.Monetary(
        string="Total",
        currency_field="currency_id",
        readonly="True",
        compute="_compute_price",
        store=True
    )

    blue_I_uom = fields.Many2one(
        comodel_name="uom.uom",
        string="Udm",
    )
    blue_II_uom = fields.Many2one(
        comodel_name="uom.uom",
        string="Udm ",
    )
    blue_h_uom = fields.Many2one(
        comodel_name="uom.uom",
        string="Udm  ",
    )
    blue_I = fields.Float(
        string="L ",
        digits='Product Unit of Measure',
    )
    blue_II = fields.Float(
        string="L",
        digits='Product Unit of Measure',
    )
    blue_h = fields.Float(
        string="H",
        digits='Product Unit of Measure',
    )
    blue_m3 = fields.Float(
        string="Total in m³",
        readonly=True,
        compute="_compute_blue_m3",
        store=True,
        digits='Product Unit of Measure',
    )
    blue_m2 = fields.Float(
        string="Total in m²",
        readonly=True,
        compute="_compute_blue_m2",
        store=True,
        digits='Product Unit of Measure',
    )

    blue_m3_unit = fields.Float(
        string="m³",
        readonly=True,
        compute="_compute_blue_m3_unit",
        store=True,
        digits='Product Unit of Measure',
    )
    blue_m2_unit = fields.Float(
        string="m²",
        readonly=True,
        compute="_compute_blue_m2_unit",
        store=True,
        digits='Product Unit of Measure',
    )

    blue_advance = fields.Float(
        string="Advance",
        digits='Product Unit of Measure',
    )

    blue_wall = fields.Float(
        string="wall",
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

    blue_tela_cost = fields.Float(
        string="Screen Cost",
        compute="_compute_blue_tela_cost",
        digits='Product Unit of Measure',
    )

    blue_eps_cost = fields.Float(
        string="EPS Cost",
        compute="_compute_blue_eps_cost",
        digits='Product Unit of Measure',
    )

    blue_curve_cost = fields.Float(
        string="Curve Cost",
        compute="_compute_blue_curve_cost",
        digits='Product Unit of Measure',
    )

    template_price_config_id = fields.Many2one( 
        comodel_name="mrp_cut_plan.template_price_config",
        string="Template Price Config"
    )

    related_type = fields.Selection(
        related="product_template_id.blue_area_calc"
    )

    price_unit_llh = fields.Float(
        string="Price Unit llh"
    )

    price_unit_m = fields.Float(
        string="Price Unit",
        compute="_compute_price_unit_m",
    )

    template_price_boolean = fields.Boolean(
        string="Verificação",
        compute="_compute_template_boolean"
    )

    @api.depends('quantity', 'price_unit_llh', 'template_price_config_id', 'blue_tela_cost', 'blue_eps_cost')
    def _compute_price_unit_m(self):
        for record in self:
            template_price_config_id = record.template_price_config_id
            if template_price_config_id:
                blue_margin_percent = template_price_config_id.blue_margin_percent
            else:
                blue_margin_percent = 0
            record.price_unit_m = ((record.blue_tela_cost * blue_margin_percent) / 100) + record.blue_tela_cost

    @api.depends('price_unit', 'price_unit_llh', 'price_unit_m', 'blue_m2', 'blue_m3', 'blue_I', 'blue_I_uom', 'blue_h', 'blue_h_uom', 'blue_II', 'blue_II_uom', 'quantity', 'blue_advance', 'blue_advance_uom')
    def _compute_price(self):
        for record in self:
            if record.related_type == 'llh':
                record.price_total = record.price_unit * record.blue_m3
            else:
                record.price_total = record.price_unit_m * record.quantity
    
    @api.depends('blue_I', 'blue_I_uom', 'blue_h', 'blue_h_uom', 'blue_II', 'blue_II_uom', 'quantity', 'blue_advance', 'blue_advance_uom')
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

                    record.blue_m3 = side1 * side2 * height * record.quantity
                else:
                    record.blue_m3 = 0

            elif record.product_id.blue_area_calc == 'm':
                if all(getattr(record, field) for field in [
                    'blue_advance', 'blue_advance_uom', 'blue_h', 'blue_h_uom']
                ):
                    advance = record.blue_advance
                    
                    if record.blue_advance_uom != meter_uom_id:
                        advance = record.blue_advance_uom._compute_quantity(record.blue_advance, meter_uom_id, round=False)
                    
                    if record.blue_h_uom != meter_uom_id:
                        height = record.blue_h_uom._compute_quantity(record.blue_h, meter_uom_id, round=False)
                    if record.quantity == 1:
                        record.blue_m3 = advance * height
                    else:
                        record.blue_m3 = advance * height * record.quantity
                else:
                    record.blue_m3 = 0
            else:
                record.blue_m3 = 0

    @api.depends('blue_I', 'blue_I_uom', 'blue_h', 'blue_h_uom', 'blue_II', 'blue_II_uom', 'quantity', 'blue_advance',
                 'blue_advance_uom')
    def _compute_blue_m3_unit(self):
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

                    record.blue_m3_unit = side1 * side2 * height
                else:
                    record.blue_m3_unit = 0

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
                    if record.quantity == 1:
                        record.blue_m3_unit = advance * height
                    else:
                        record.blue_m3_unit = advance * height
                else:
                    record.blue_m3 = 0
            else:
                record.blue_m3 = 0

    @api.depends('blue_I', 'blue_II', 'blue_I_uom', 'blue_h', 'blue_h_uom', 'blue_II_uom', 'quantity', 'blue_advance', 'blue_wall', 'blue_wall_uom', 'blue_advance_uom')
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

                    record.blue_m2 = side1 * side2 * record.quantity
                else:
                    record.blue_m2 = 0

            elif record.product_id.blue_area_calc == 'm':
                if all(getattr(record, field) for field in ['blue_wall', 'blue_advance', 'blue_wall_uom', 'blue_advance_uom', 'blue_h', 'blue_h_uom']):
                    wall = record.blue_wall
                    advance = record.blue_advance
                    height = record.blue_h

                    if record.blue_wall_uom != meter_uom_id:
                        wall = record.blue_wall_uom._compute_quantity(record.blue_wall, meter_uom_id, round=False)
                    
                    if record.blue_advance_uom != meter_uom_id:
                        advance = record.blue_advance_uom._compute_quantity(record.blue_advance, meter_uom_id, round=False)
                    
                    if record.blue_h_uom != meter_uom_id:
                        height = record.blue_h_uom._compute_quantity(record.blue_h, meter_uom_id, round=False)

                    record.blue_m2 = wall + height + advance + advance * record.quantity
                else:
                    record.blue_m2 = 0
            else:
                record.blue_m2 = 0

    @api.depends('blue_I', 'blue_II', 'blue_I_uom', 'blue_h', 'blue_h_uom', 'blue_II_uom', 'quantity', 'blue_advance',
                 'blue_wall', 'blue_wall_uom', 'blue_advance_uom')
    def _compute_blue_m2_unit(self):
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

                    record.blue_m2_unit = side1 * side2
                else:
                    record.blue_m2_unit = 0

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

                    record.blue_m2_unit = wall + height + advance + advance
                else:
                    record.blue_m2_unit = 0
            else:
                record.blue_m2_unit = 0

    @api.depends('blue_m2', 'blue_eps_cost', 'blue_m3')
    def _compute_blue_tela_cost(self):
        for record in self:
            template_price_config = record.template_price_config_id
            if template_price_config:
                record.blue_tela_cost = ((template_price_config.blue_tela_cost * record.blue_m2_unit) * template_price_config.blue_tela_multi * template_price_config.blue_tela_multi2) + record.blue_eps_cost
            else:
                record.blue_tela_cost = 0
    
    @api.depends('blue_h', 'blue_advance', 'template_price_config_id')
    def _compute_blue_curve_cost(self):
        for record in self:
            template_price_config = record.template_price_config_id
            meter_uom_id = self.env.ref('uom.product_uom_meter')
            advance = record.blue_advance
            height = record.blue_h

            if all(getattr(record, field) for field in ['blue_advance', 'blue_advance_uom', 'blue_h', 'blue_h_uom']):
                if record.blue_advance_uom != meter_uom_id:
                    advance = record.blue_advance_uom._compute_quantity(record.blue_advance, meter_uom_id, round=False)
                
                if record.blue_h_uom != meter_uom_id:
                    height = record.blue_h_uom._compute_quantity(record.blue_h, meter_uom_id, round=False)
                
                if template_price_config:
                    record.blue_curve_cost = (template_price_config.blue_curve_cost + height) * (template_price_config.blue_curve_cost + advance)
                else:
                    record.blue_curve_cost = (0 + height) * (0 + advance)
            else:
                record.blue_curve_cost = 0
    
    @api.depends('blue_curve_cost', 'template_price_config_id')
    def _compute_blue_eps_cost(self):
        for record in self:
            template_price_config = record.template_price_config_id
            if template_price_config:
                record.blue_eps_cost = template_price_config.blue_eps_cost * record.blue_curve_cost
            else:
                record.blue_eps_cost = 0

    def action_save(self):
        description = ''
        if self.related_type == 'llh':
            description = f'{self.product_id.name} / M³: {self.blue_m3} / M²: {self.blue_m2} / L: {self.blue_I} {self.blue_I_uom.name} / L: {self.blue_II} {self.blue_II_uom.name}/ H: {self.blue_h} {self.blue_h_uom.name}'
        elif self.related_type == 'm':
            description = f'{self.product_id.name} / M³: {self.blue_m3} / M²: {self.blue_m2} / Avanço: {self.blue_advance} {self.blue_advance_uom.name}/ H: {self.blue_h} {self.blue_h_uom.name}'

        self.order_line_id.update({
            'product_uom_qty': self.quantity,
            'price_unit': ((self.price_unit * self.blue_m3) / self.quantity) if self.related_type == 'llh' else self.price_unit_m,
            'blue_I': self.blue_I,
            'blue_II': self.blue_II,
            'blue_h': self.blue_h,
            'blue_I_uom': self.blue_I_uom.id,
            'blue_II_uom': self.blue_II_uom.id,
            'blue_h_uom': self.blue_h_uom.id,
            'blue_m3': self.blue_m3,
            'blue_m2': self.blue_m2,
            'name': description,
            'price_unit_2': self.price_unit if self.related_type == 'llh' else self.price_unit_llh,
            'blue_advance': self.blue_advance,
            'blue_wall': self.blue_wall,    
            'blue_wall_uom': self.blue_wall_uom.id,
            'blue_advance_uom': self.blue_advance_uom.id,
            'blue_tela_cost': self.blue_tela_cost,
            'blue_eps_cost': self.blue_eps_cost,
            'blue_curve_cost': self.blue_curve_cost,
        })
        self.order_line_id._compute_blue_m3()  # garante cálculo armazenado
        self.order_line_id._compute_blue_m2()
        if self.related_type == 'm':
            
            if self.template_price_config_id:
                valor_custo = self.blue_m2 * self.template_price_config_id.blue_tela_cost * self.template_price_config_id.blue_tela_multi * self.template_price_config_id.blue_tela_multi2
                valor_custo = valor_custo + (self.blue_m3 * self.template_price_config_id.blue_eps_cost)
                valor_custo = valor_custo + (valor_custo * self.template_price_config_id.blue_margin_percent / 100)
            else:
                valor_custo = 0
            
         