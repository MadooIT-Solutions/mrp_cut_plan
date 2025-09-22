from odoo import models, fields, api, _
from odoo.exceptions import UserError


class TemplatePriceConfig(models.Model):
    _name = 'mrp_cut_plan.template_price_config'
    _description = 'Template Price Config'
    _inherit = 'mail.thread'
    _rec_name = 'product_id'

    blue_wall = fields.Float(
        string="Standard Wall"
    )

    blue_wall_uom = fields.Many2one(
        comodel_name="uom.uom",
        string="Udm"
    )

    blue_eps_product_id = fields.Many2one(
        comodel_name="product.product",
        string="EPS Product"
    )

    blue_eps_cost = fields.Float(
        related="blue_eps_product_id.standard_price",
        string="EPS Cost"
    )

    blue_tela_product_id = fields.Many2one(
        comodel_name="product.product",
        string="Canvas/Mortar Product"
    )

    blue_tela_cost = fields.Float(
        related="blue_tela_product_id.standard_price",
        string="Screen Cost"
    )

    blue_tela_multi = fields.Float(
        string="Labor Cost",
        default=1
    )

    blue_tela_multi2 = fields.Float(
        string="Cost of Mortar m2",
        default=1
    )

    blue_curve_cost = fields.Float(
        string="Additional Cost Curve"
    )

    blue_margin_percent = fields.Float(
        string="Marge Percentage"
    )

    product_id = fields.Many2one(
        comodel_name="product.product",
        string="Produto"
    )

    _sql_constraints = [
        ('product_id', 'unique (product_id)', 'Já existe um template configurado para esse produto')
    ]

    mortar_coefficient = fields.Float(
        string="Coeficiente Argamassa"
    )

    # def _get_or_create_bom(self, product):
    #     """
    #     Retorna uma BoM existente ou cria uma nova se não existir.
    #     Se a BoM existir mas não tiver componentes, adiciona os produtos EPS e Tela.
    #     """
    #     Bom = self.env["mrp.bom"]
    #     BomLine = self.env["mrp.bom.line"]
    #
    #     # Buscar BoM existente
    #     bom = Bom.search([("product_tmpl_id", "=", product.product_tmpl_id.id)], limit=1)
    #
    #     if not bom:
    #         # Criar nova BoM se não existir
    #         bom = Bom.create({
    #             "product_tmpl_id": product.product_tmpl_id.id,
    #             "product_qty": 1.0,
    #             "type": "normal",
    #         })
    #
    #     # Se a BoM não tiver linhas, incluir EPS e Tela
    #     if not bom.bom_line_ids:
    #         lines = []
    #         if self.blue_eps_product_id:
    #             lines.append({
    #                 "product_id": self.blue_eps_product_id.id,
    #                 "product_qty": 1.0,
    #             })
    #         if self.blue_tela_product_id:
    #             lines.append({
    #                 "product_id": self.blue_tela_product_id.id,
    #                 "product_qty": 1.0,
    #             })
    #
    #         if lines:
    #             for line in lines:
    #                 line.update({"bom_id": bom.id})
    #                 BomLine.create(line)
    #
    #     # Se mesmo assim não houver componentes, lançar aviso
    #     if not bom.bom_line_ids:
    #         raise UserError(
    #             _(f"Por gentileza, revise e ajuste a lista de materiais conforme necessário do produto: {product.display_name}")
    #         )
    #
    #     return bom
    #
    # def action_create_mo(self):
    #     """
    #     Cria uma MO garantindo que exista uma BoM válida
    #     """
    #     Production = self.env["mrp.production"]
    #
    #     for rec in self:
    #         product = rec.product_id
    #         bom = rec._get_or_create_bom(product)
    #
    #         mo = Production.create({
    #             "product_id": product.id,
    #             "product_qty": 1.0,  # Aqui você pode ajustar para rec.blue_qty se existir no modelo
    #             "bom_id": bom.id,
    #         })
    #
    #         mo.action_confirm()
    #         mo.action_assign()
    #
    #     return True
    #
    #
    #
    # def _get_or_create_component_product(self, product_type, default_name):
    #     """Cria ou retorna um produto componente baseado no tipo"""
    #     product_field = f'blue_{product_type}_product_id'
    #     existing_product = getattr(self, product_field)
    #
    #     if existing_product:
    #         return existing_product
    #
    #     # Criar novo produto
    #     product_vals = {
    #         'name': f"{default_name} - {self.product_id.name}",
    #         'default_code': f"{product_type.upper()}_{self.product_id.default_code or self.product_id.id}",
    #         'type': 'product',
    #         'detailed_type': 'consu',
    #         'categ_id': self.product_id.categ_id.id or self.env.ref('product.product_category_all').id,
    #         'uom_id': self.env.ref('uom.product_uom_unit').id,
    #         'uom_po_id': self.env.ref('uom.product_uom_unit').id,
    #         'standard_price': 0.0,
    #         'blue_area_calc': 'llh',
    #     }
    #
    #     new_product = self.env['product.product'].create(product_vals)
    #
    #     # Atualizar o campo no template
    #     setattr(self, product_field, new_product.id)
    #
    #     return new_product
    #
    # def _get_or_create_bom(self, product):
    #     """
    #     Retorna uma BoM existente ou cria uma nova se não existir.
    #     Cria produtos EPS e Tela automaticamente se necessário.
    #     """
    #     Bom = self.env["mrp.bom"]
    #     BomLine = self.env["mrp.bom.line"]
    #
    #     # Buscar BoM existente
    #     bom = Bom.search([
    #         ("product_tmpl_id", "=", product.product_tmpl_id.id),
    #         ("type", "=", "normal")
    #     ], limit=1)
    #
    #     if not bom:
    #         # Criar nova BoM se não existir
    #         bom = Bom.create({
    #             "product_tmpl_id": product.product_tmpl_id.id,
    #             "product_id": product.id,
    #             "product_qty": 1.0,
    #             "type": "normal",
    #             "company_id": self.env.company.id,
    #         })
    #
    #     # Garantir que os produtos EPS e Tela existam
    #     eps_product = self._get_or_create_component_product('eps', 'EPS')
    #     tela_product = self._get_or_create_component_product('tela', 'Tela')
    #
    #     # Verificar e adicionar linhas da BoM se não existirem
    #     existing_products = bom.bom_line_ids.mapped('product_id')
    #
    #     if eps_product not in existing_products:
    #         BomLine.create({
    #             "bom_id": bom.id,
    #             "product_id": eps_product.id,
    #             "product_qty": 1.0,
    #             "product_uom_id": eps_product.uom_id.id,
    #         })
    #
    #     if tela_product not in existing_products:
    #         BomLine.create({
    #             "bom_id": bom.id,
    #             "product_id": tela_product.id,
    #             "product_qty": 1.0,
    #             "product_uom_id": tela_product.uom_id.id,
    #         })
    #
    #     # Se ainda não houver componentes, tentar adicionar padrões
    #     if not bom.bom_line_ids:
    #         # Tentar adicionar produtos padrão do sistema
    #         default_eps = self.env['product.product'].search([
    #             ('default_code', 'ilike', 'EPS'),
    #             ('type', '=', 'product')
    #         ], limit=1)
    #
    #         default_tela = self.env['product.product'].search([
    #             ('default_code', 'ilike', 'TELA'),
    #             ('type', '=', 'product')
    #         ], limit=1)
    #
    #         if default_eps:
    #             BomLine.create({
    #                 "bom_id": bom.id,
    #                 "product_id": default_eps.id,
    #                 "product_qty": 1.0,
    #                 "product_uom_id": default_eps.uom_id.id,
    #             })
    #
    #         if default_tela:
    #             BomLine.create({
    #                 "bom_id": bom.id,
    #                 "product_id": default_tela.id,
    #                 "product_qty": 1.0,
    #                 "product_uom_id": default_tela.uom_id.id,
    #             })
    #
    #     # Verificação final
    #     if not bom.bom_line_ids:
    #         raise UserError(
    #             _("Não foi possível criar componentes para a BoM. "
    #               "Por favor, configure manualmente os produtos EPS e Tela.")
    #         )
    #
    #     return bom
    #
    # @api.model
    # def create(self, vals):
    #     """Sobrescrever create para garantir criação de produtos componentes"""
    #     record = super(TemplatePriceConfig, self).create(vals)
    #
    #     # Se não tem produtos EPS/Tela, criar automaticamente
    #     if not record.blue_eps_product_id:
    #         record._get_or_create_component_product('eps', 'EPS')
    #
    #     if not record.blue_tela_product_id:
    #         record._get_or_create_component_product('tela', 'Tela')
    #
    #     return record
    #
    # def write(self, vals):
    #     """Sobrescrever write para garantir produtos componentes"""
    #     res = super(TemplatePriceConfig, self).write(vals)
    #
    #     # Se produto principal foi alterado, atualizar componentes
    #     if 'product_id' in vals:
    #         for record in self:
    #             if not record.blue_eps_product_id:
    #                 record._get_or_create_component_product('eps', 'EPS')
    #             if not record.blue_tela_product_id:
    #                 record._get_or_create_component_product('tela', 'Tela')
    #
    #     return res