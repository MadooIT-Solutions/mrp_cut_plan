# -*- coding: utf-8 -*-

from odoo import models, fields, api

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
        readonly=True
    )
    quantity = fields.Integer(
        string="Quantity",
        default=1
    )
    pricelist_id = fields.Many2one(
        comodel_name="product.pricelist"
    )
    currency_id = fields.Many2one(
        related='pricelist_id.currency_id',
        depends=["pricelist_id"],
        store=True,
        ondelete="restrict"
    )
    price_unit = fields.Monetary(
        string="Price",
        currency_field="currency_id",
    )
    # Removido store=True para garantir atualização no wizard
    price_total = fields.Monetary(
        string="Total",
        currency_field="currency_id",
        readonly=True,
        compute="_compute_price"
    )
    blue_I_uom = fields.Many2one(comodel_name="uom.uom", string="Udm")
    blue_II_uom = fields.Many2one(comodel_name="uom.uom", string="Udm")
    blue_h_uom = fields.Many2one(comodel_name="uom.uom", string="Udm")
    blue_I = fields.Float(string="L ", digits='Product Unit of Measure')
    blue_II = fields.Float(string="L", digits='Product Unit of Measure')
    blue_h = fields.Float(string="H", digits='Product Unit of Measure')

    # Removido store=True de todos os campos computados do wizard
    blue_m3 = fields.Float(
        string="Total in m³",
        readonly=True,
        compute="_compute_blue_m3",
        digits='Product Unit of Measure'
    )
    blue_m2 = fields.Float(
        string="Total in m²",
        readonly=True,
        compute="_compute_blue_m2",
        digits='Product Unit of Measure'
    )
    blue_m3_unit = fields.Float(
        string="m³ Unit",
        readonly=True,
        compute="_compute_blue_m3_unit",
        digits='Product Unit of Measure'
    )
    blue_m2_unit = fields.Float(
        string="m² Unit",
        readonly=True,
        compute="_compute_blue_m2_unit",
        digits='Product Unit of Measure'
    )

    blue_advance = fields.Float(string="Advance", digits='Product Unit of Measure')
    blue_wall = fields.Float(string="Wall", digits='Product Unit of Measure')
    blue_wall_uom = fields.Many2one(comodel_name="uom.uom", string="Udm Wall")
    blue_advance_uom = fields.Many2one(comodel_name="uom.uom", string="Udm Advance")

    blue_tela_cost = fields.Float(string="Screen Cost", compute="_compute_blue_tela_cost", digits='Product Unit of Measure')
    blue_eps_cost = fields.Float(string="EPS Cost", compute="_compute_blue_eps_cost", digits='Product Unit of Measure')
    blue_curve_cost = fields.Float(string="CNC Cost Lost", compute="_compute_blue_curve_cost", digits='Product Unit of Measure')

    template_price_config_id = fields.Many2one(comodel_name="mrp_cut_plan.template_price_config", string="Template Price Config")
    related_type = fields.Selection(related="product_template_id.blue_area_calc")
    price_unit_llh = fields.Float(string="Price Unit llh")
    price_unit_m = fields.Float(string="Price Unit M", compute="_compute_price_unit_m")

    @api.depends('quantity', 'template_price_config_id', 'blue_tela_cost', 'blue_eps_cost')
    def _compute_price_unit_m(self):
        for record in self:
            blue_margin_percent = record.template_price_config_id.blue_margin_percent if record.template_price_config_id else 1
            record.price_unit_m = ((record.blue_tela_cost * blue_margin_percent) / 100) + record.blue_tela_cost

    @api.depends('price_unit', 'price_unit_m', 'blue_m2', 'blue_m3', 'quantity', 'related_type')
    def _compute_price(self):
        for record in self:
            if record.related_type == 'llh':
                record.price_total = record.price_unit * record.blue_m3
            else:
                record.price_total = record.price_unit_m * record.quantity
                record.price_unit = record.price_total / record.quantity if record.quantity else 0

    @api.depends('blue_I', 'blue_I_uom', 'blue_h', 'blue_h_uom', 'blue_II', 'blue_II_uom', 'quantity', 'blue_advance', 'blue_advance_uom', 'related_type')
    def _compute_blue_m3(self):
        for record in self:
            meter_uom = self.env.ref('uom.product_uom_meter')
            res = 0.0
            if record.related_type == 'llh':
                if all([record.blue_I, record.blue_II, record.blue_h, record.blue_I_uom, record.blue_II_uom, record.blue_h_uom]):
                    s1 = record.blue_I_uom._compute_quantity(record.blue_I, meter_uom)
                    s2 = record.blue_II_uom._compute_quantity(record.blue_II, meter_uom)
                    h = record.blue_h_uom._compute_quantity(record.blue_h, meter_uom)
                    res = s1 * s2 * h * record.quantity
            elif record.related_type == 'm':
                if all([record.blue_advance, record.blue_advance_uom, record.blue_h, record.blue_h_uom]):
                    adv = record.blue_advance_uom._compute_quantity(record.blue_advance, meter_uom)
                    h = record.blue_h_uom._compute_quantity(record.blue_h, meter_uom)
                    res = adv * h * record.quantity
            record.blue_m3 = res

    @api.depends('blue_I', 'blue_II', 'blue_I_uom', 'blue_h', 'blue_h_uom', 'blue_II_uom', 'quantity', 'blue_advance', 'blue_wall', 'blue_wall_uom', 'blue_advance_uom', 'related_type')
    def _compute_blue_m2(self):
        for record in self:
            meter_uom = self.env.ref('uom.product_uom_meter')
            res = 0.0
            if record.related_type == 'llh':
                if all([record.blue_I, record.blue_II, record.blue_I_uom, record.blue_II_uom]):
                    s1 = record.blue_I_uom._compute_quantity(record.blue_I, meter_uom)
                    s2 = record.blue_II_uom._compute_quantity(record.blue_II, meter_uom)
                    h = record.blue_h_uom._compute_quantity(record.blue_h, meter_uom) if record.blue_h_uom else 1.0
                    res = s1 * s2 * h * record.quantity
            elif record.related_type == 'm':
                if all([record.blue_wall, record.blue_advance, record.blue_wall_uom, record.blue_advance_uom, record.blue_h, record.blue_h_uom]):
                    wall = record.blue_wall_uom._compute_quantity(record.blue_wall, meter_uom)
                    adv = record.blue_advance_uom._compute_quantity(record.blue_advance, meter_uom)
                    h = record.blue_h_uom._compute_quantity(record.blue_h, meter_uom)
                    # CORREÇÃO: Multiplicando a soma total pela quantidade
                    res = (wall + h + adv + adv) * record.quantity
            record.blue_m2 = res

    @api.onchange('blue_I', 'blue_II', 'blue_I_uom', 'blue_h', 'blue_h_uom', 'blue_II_uom', 'quantity', 'blue_advance', 'blue_wall', 'blue_wall_uom', 'blue_advance_uom', 'related_type')


    @api.depends('blue_I', 'blue_I_uom', 'blue_h', 'blue_h_uom', 'blue_II', 'blue_II_uom', 'related_type')
    def _compute_blue_m3_unit(self):
        for record in self:
            meter_uom = self.env.ref('uom.product_uom_meter')
            res = 0.0
            if record.related_type == 'llh' and all([record.blue_I, record.blue_II, record.blue_h]):
                s1 = record.blue_I_uom._compute_quantity(record.blue_I, meter_uom)
                s2 = record.blue_II_uom._compute_quantity(record.blue_II, meter_uom)
                h = record.blue_h_uom._compute_quantity(record.blue_h, meter_uom)
                res = s1 * s2 * h
            elif record.related_type == 'm' and all([record.blue_advance, record.blue_h]):
                adv = record.blue_advance_uom._compute_quantity(record.blue_advance, meter_uom)
                h = record.blue_h_uom._compute_quantity(record.blue_h, meter_uom)
                res = adv * h
            record.blue_m3_unit = res

    @api.depends('blue_I', 'blue_II', 'blue_I_uom', 'blue_II_uom', 'blue_wall', 'blue_wall_uom', 'blue_advance', 'blue_advance_uom', 'blue_h', 'blue_h_uom', 'related_type')
    def _compute_blue_m2_unit(self):
        for record in self:
            meter_uom = self.env.ref('uom.product_uom_meter')
            res = 0.0
            if record.related_type == 'llh' and all([record.blue_I, record.blue_II]):
                s1 = record.blue_I_uom._compute_quantity(record.blue_I, meter_uom)
                s2 = record.blue_II_uom._compute_quantity(record.blue_II, meter_uom)
                res = s1 * s2
            elif record.related_type == 'm' and all([record.blue_wall, record.blue_advance, record.blue_h]):
                wall = record.blue_wall_uom._compute_quantity(record.blue_wall, meter_uom)
                adv = record.blue_advance_uom._compute_quantity(record.blue_advance, meter_uom)
                h = record.blue_h_uom._compute_quantity(record.blue_h, meter_uom)
                res = wall + h + adv + adv
            record.blue_m2_unit = res

    @api.depends('blue_m2_unit', 'blue_eps_cost', 'template_price_config_id')
    def _compute_blue_tela_cost(self):
        for record in self:
            conf = record.template_price_config_id
            if conf:
                record.blue_tela_cost = ((conf.blue_tela_cost * record.blue_m2_unit) * conf.blue_tela_multi * conf.blue_tela_multi2) + record.blue_eps_cost
            else:
                record.blue_tela_cost = 0

    @api.depends('blue_h', 'blue_advance', 'template_price_config_id', 'blue_h_uom', 'blue_advance_uom')
    def _compute_blue_curve_cost(self):
        for record in self:
            conf = record.template_price_config_id
            meter_uom = self.env.ref('uom.product_uom_meter')
            if all([record.blue_advance, record.blue_advance_uom, record.blue_h, record.blue_h_uom]):
                adv = record.blue_advance_uom._compute_quantity(record.blue_advance, meter_uom)
                h = record.blue_h_uom._compute_quantity(record.blue_h, meter_uom)
                c_cost = conf.blue_curve_cost if conf else 0.0
                record.blue_curve_cost = (c_cost + h) * (c_cost + adv)
            else:
                record.blue_curve_cost = 0

    @api.depends('blue_curve_cost', 'template_price_config_id')
    def _compute_blue_eps_cost(self):
        for record in self:
            conf = record.template_price_config_id
            record.blue_eps_cost = (conf.blue_eps_cost * record.blue_curve_cost) if conf else 0

    def action_save(self):
        self.ensure_one()
        # Construção da descrição baseada no tipo
        if self.related_type == 'llh':
            desc = f"{self.product_id.name} / M³: {self.blue_m3_unit:.3f} / M²: {self.blue_m2_unit:.3f} / L: {self.blue_I} {self.blue_I_uom.name} / L: {self.blue_II} {self.blue_II_uom.name}/ H: {self.blue_h} {self.blue_h_uom.name}"
        else:
            desc = f"{self.product_id.name} / M³: {self.blue_m3_unit:.3f} / M²: {self.blue_m2_unit:.3f} / Avanço: {self.blue_advance} {self.blue_advance_uom.name}/ H: {self.blue_h} {self.blue_h_uom.name}"

        vals = {
            'product_uom_qty': self.quantity,
            'price_unit': ((self.price_unit * self.blue_m3) / self.quantity) if self.related_type == 'llh' and self.quantity else self.price_unit_m,
            'blue_I': self.blue_I,
            'blue_II': self.blue_II,
            'blue_h': self.blue_h,
            'blue_I_uom': self.blue_I_uom.id,
            'blue_II_uom': self.blue_II_uom.id,
            'blue_h_uom': self.blue_h_uom.id,
            'blue_m3': self.blue_m3,
            'blue_m2': self.blue_m2,
            'name': desc,
            'price_unit_2': self.price_unit if self.related_type == 'llh' else self.price_unit_llh,
            'blue_advance': self.blue_advance,
            'blue_wall': self.blue_wall,
            'blue_wall_uom': self.blue_wall_uom.id,
            'blue_advance_uom': self.blue_advance_uom.id,
            'blue_tela_cost': self.blue_tela_cost,
            'blue_eps_cost': self.blue_eps_cost,
            'blue_curve_cost': self.blue_curve_cost,
        }
        self.order_line_id.write(vals)
        return {'type': 'ir.actions.act_window_close'}