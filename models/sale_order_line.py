from odoo import fields, models, _, api
import logging

_logger = logging.getLogger(__name__)

class SaleOrderLine(models.Model):
    _inherit = "sale.order.line"

    related_blue_area_calc = fields.Selection(related="product_template_id.blue_area_calc")

    blue_I_uom = fields.Many2one(
        comodel_name="uom.uom",
        string="Udm",
        default=lambda self: self.env.ref('uom.product_uom_meter').id,
    )
    blue_II_uom = fields.Many2one(
        comodel_name="uom.uom",
        string="Udm ",
        default=lambda self: self.env.ref('uom.product_uom_meter').id
    )
    blue_h_uom = fields.Many2one(
        comodel_name="uom.uom",
        string="Udm  ",
        default=lambda self: self.env.ref('uom.product_uom_meter').id
    )
    blue_I = fields.Float(string="L")
    blue_II = fields.Float(string="L")
    blue_h = fields.Float(string="H")
    blue_m3 = fields.Float(string="Total in m³", compute="_compute_blue_m3", store=True)
    blue_m2 = fields.Float(string="Total in m²", compute="_compute_blue_m2", store=True)
    is_llh_calculation = fields.Boolean(string="Is LLH Calculation", compute="_compute_is_llh_calculation")

    price_unit_2 = fields.Float(string="Price Unit 2")

    blue_advance = fields.Float(string="Advance")
    blue_wall = fields.Float(string="Wall")
    blue_wall_uom = fields.Many2one(comodel_name="uom.uom", string="Udm")
    blue_advance_uom = fields.Many2one(comodel_name="uom.uom", string="Udm")

    blue_tela_cost = fields.Float(string="Screen Cost")
    blue_eps_cost = fields.Float(string="EPS Cost")
    blue_curve_cost = fields.Float(string="Curve Cost")

    binany_field = fields.Image(string="Imagem")
    blue_m3_final = fields.Float(string="Total m³ Final", compute="_compute_final_values", store=True)
    blue_m2_final = fields.Float(string="Total m² Final", compute="_compute_final_values", store=True)

    categ_display_name = fields.Char(
        string='Categoria (Hierárquica)',
        related='product_id.categ_id.display_name',
        store=True  # Importante para performance no pivô
    )

    def _action_launch_stock_rule(self, previous_product_uom_qty=False):
        lines_with_cut_plan = self.filtered(
            lambda l: l.product_id.product_tmpl_id.blue_area_calc != 'n'
        )

        normal_lines = self - lines_with_cut_plan

        # 🔥 linhas normais seguem o fluxo padrão
        if normal_lines:
            super(SaleOrderLine, normal_lines)._action_launch_stock_rule(
                previous_product_uom_qty=previous_product_uom_qty
            )

        # 🔥 linhas com cut plan NÃO DISPARAM estoque
        # (o Cut Plan cuidará de tudo)
        return True

    def _run_cut_plan_flow(self, procurement):
        product = procurement.product_id
        sale_line = procurement.values.get('sale_line_id')

        if not sale_line:
            return

        _logger.error(
            "✂️ Criando Cut Plan | produto=%s | linha=%s",
            product.display_name,
            sale_line.id
        )

        self.env['mrp_cut_plan.mrp_cut_plan'].create({
            'sale_id': sale_line.order_id.id,
            'sale_line_id': sale_line.id,
            'product_id': product.id,
            'blue_qty': procurement.product_qty,
            'blue_bom_template_id': product.bom_ids[:1].id,
            'blue_origin': sale_line.order_id.name,
        })


    @api.depends('blue_m3', 'blue_m2', 'product_uom_qty')
    def _compute_final_values(self):
        for line in self:
            line.blue_m3_final = line.blue_m3
            line.blue_m2_final = line.blue_m2


    @api.onchange('product_id')
    def onchange_product(self):
        self.binany_field = self.product_id.image_1920

    @api.depends('product_template_id')
    def _compute_is_llh_calculation(self):
        for rec in self:
            rec.is_llh_calculation = True if rec.product_template_id.blue_area_calc else False

    def button_configure_product(self):
        # self.set_uom_values()
        template_price_config_id = self.env['mrp_cut_plan.template_price_config'].search([('product_id', '=', self.product_id.id)])
        uom = self.env.ref('uom.product_uom_meter')

        context = {
            'default_product_id': self.product_id.id,
            'default_order_line_id': self.id,
            'default_blue_I_uom': self.blue_I_uom.id,
            'default_blue_II_uom': self.blue_II_uom.id,
            'default_blue_h_uom': self.blue_h_uom.id if self.blue_h_uom else uom.id,
            'default_blue_m3': self.blue_m3,
            'default_blue_m2': self.blue_m2,
            'default_blue_I': self.blue_I,
            'default_blue_II': self.blue_II,
            'default_blue_h': self.blue_h,
            'default_product_template_id': self.product_template_id.id,
            'default_quantity': self.product_uom_qty,
            'default_price_unit': self.price_unit_2 if self.price_unit_2 else self.price_unit,
            'default_pricelist_id': self.order_id.pricelist_id.id,
            'default_template_price_config_id': template_price_config_id.id if template_price_config_id else False,
            'default_blue_advance': self.blue_advance,
            'default_blue_wall': template_price_config_id.blue_wall if template_price_config_id else 0,
            'default_blue_wall_uom': template_price_config_id.blue_wall_uom.id if template_price_config_id else False,
            'default_blue_advance_uom': self.blue_advance_uom.id if self.blue_advance_uom else uom.id,
            'default_blue_tela_cost': self.blue_tela_cost,
            'default_blue_eps_cost': self.blue_eps_cost,
            'default_blue_curve_cost': self.blue_curve_cost
        }
        return {
            'name': _('Configure'),
            'type': 'ir.actions.act_window',
            'res_model': 'sale.order.line.config',
            'view_id': self.env.ref('mrp_cut_plan.sale_order_line_prod_config_view_form').id,
            'context': context,
            'view_mode': 'form',
            'target': 'new',
        }


    def _process_category_hierarchy(self, read_group_results, fields):
        """Processa os resultados do read_group para somar pais com filhos"""

        # Verifica se read_group_results é válido
        if not read_group_results:
            return []

        # Mapeia cada caminho completo para seu total
        category_totals = {}
        category_names = {}

        for result in read_group_results:
            # Verifica se result existe
            if not result:
                continue

            # Extrai o caminho completo com verificação segura
            path = result.get('product_id.categ_id.complete_name_store')
            if not path or not isinstance(path, str):
                continue

            category_totals[path] = result.get('price_subtotal', 0)
            category_names[path] = result.get('product_id.categ_id.complete_name_store_display_name', path)

        # Calcula totais para pais
        parent_totals = {}
        for path, total in category_totals.items():
            if not path:
                continue
            parts = path.split(' / ')
            for i in range(len(parts)):
                parent_path = ' / '.join(parts[:i + 1])
                parent_totals[parent_path] = parent_totals.get(parent_path, 0) + total

        # Recria os resultados incluindo os pais
        new_results = []
        processed_paths = set()

        for path, total in parent_totals.items():
            if path and path not in processed_paths:
                # Cria um resultado fictício para o pai
                parent_result = {
                    'product_id.categ_id.complete_name_store': path,
                    'product_id.categ_id.complete_name_store_display_name': path,
                    'price_subtotal': total,
                    '__count': 0,
                    '__domain': [],
                }

                # Adiciona campos adicionais
                for field in fields:
                    if field and field not in parent_result:
                        parent_result[field] = 0

                new_results.append(parent_result)
                processed_paths.add(path)

        # Ordena por hierarquia
        new_results.sort(key=lambda x: x.get('product_id.categ_id.complete_name_store', ''))

        return new_results

    # ---------------------------------------------
    # Computes para medidas (blue_m3 e blue_m2)
    # ---------------------------------------------
    @api.depends('blue_I','blue_II','blue_h','blue_I_uom','blue_II_uom','blue_h_uom','blue_advance','blue_advance_uom','blue_wall','blue_wall_uom','product_id')
    def _compute_blue_m3(self):
        meter_uom = self.env.ref('uom.product_uom_meter')
        for line in self:
            if line.product_id.blue_area_calc == 'llh':
                I = line.blue_I_uom._compute_quantity(line.blue_I, meter_uom) if line.blue_I_uom else line.blue_I
                II = line.blue_II_uom._compute_quantity(line.blue_II, meter_uom) if line.blue_II_uom else line.blue_II
                H = line.blue_h_uom._compute_quantity(line.blue_h, meter_uom) if line.blue_h_uom else line.blue_h
                line.blue_m3 = I * II * H * line.product_uom_qty
            elif line.product_id.blue_area_calc == 'm':
                adv = line.blue_advance_uom._compute_quantity(line.blue_advance, meter_uom) if line.blue_advance_uom else line.blue_advance
                H = line.blue_h_uom._compute_quantity(line.blue_h, meter_uom) if line.blue_h_uom else line.blue_h
                line.blue_m3 = adv * H
            else:
                line.blue_m3 = 0

    @api.depends('blue_I','blue_II','blue_I_uom','blue_II_uom','blue_advance','blue_wall','blue_advance_uom','blue_wall_uom','product_id','blue_h','blue_h_uom')
    def _compute_blue_m2(self):
        meter_uom = self.env.ref('uom.product_uom_meter')
        for line in self:
            if line.product_id.blue_area_calc == 'llh':
                I = line.blue_I_uom._compute_quantity(line.blue_I, meter_uom) if line.blue_I_uom else line.blue_I
                II = line.blue_II_uom._compute_quantity(line.blue_II, meter_uom) if line.blue_II_uom else line.blue_II
                line.blue_m2 = I * II * line.product_uom_qty
            elif line.product_id.blue_area_calc == 'm':
                wall = line.blue_wall_uom._compute_quantity(line.blue_wall, meter_uom) if line.blue_wall_uom else line.blue_wall
                adv = line.blue_advance_uom._compute_quantity(line.blue_advance, meter_uom) if line.blue_advance_uom else line.blue_advance
                H = line.blue_h_uom._compute_quantity(line.blue_h, meter_uom) if line.blue_h_uom else line.blue_h
                line.blue_m2 = wall + H + adv + adv
            else:
                line.blue_m2 = 0

    @api.model
    def read_group(self, domain, fields, groupby, offset=0, limit=None, orderby=False, lazy=True):
        """Soma valores dos filhos nas categorias pai"""

        if 'categ_display_name' not in str(groupby):
            return super().read_group(domain, fields, groupby, offset, limit, orderby, lazy)

        # Obtém resultados originais
        result = super().read_group(domain, fields, groupby, offset, limit, orderby, lazy)

        if not result:
            return result

        # Calcula totais dos pais (primeiro nível apenas)
        parent_totals = {}
        for line in result:
            path = line.get('categ_display_name')
            if path and ' / ' in path:
                parent = path.split(' / ')[0]
                parent_totals[parent] = parent_totals.get(parent, 0) + line.get('price_subtotal', 0)

        # Adiciona totais dos pais como novas linhas
        added_parents = set()
        for parent, total in parent_totals.items():
            if parent not in added_parents:
                # Verifica se já existe linha para este pai
                parent_exists = any(r.get('categ_display_name') == parent for r in result)
                if not parent_exists:
                    result.append({
                        'categ_display_name': parent,
                        'price_subtotal': total,
                        '__count': 0,
                    })
                added_parents.add(parent)

        return result