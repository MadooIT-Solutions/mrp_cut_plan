from odoo import models, fields, api, _
from odoo.exceptions import UserError
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
    company_id = fields.Many2one(
        'res.company',
        string='Empresa',
        required=True,
        default=lambda self: self.env.company,
        index=True
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
        related="sale_id.partner_id",
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

    sale_id = fields.Many2one(
        comodel_name="sale.order",
        string="Cotação",
    )

    # NOVO CAMPO PARA ESTRATÉGIA MTO
    blue_mto_strategy = fields.Boolean(
        string="MTO Strategy",
        compute="_compute_blue_mto_strategy",
        help="If True, uses MTO strategy without creating production orders"
    )

    mo_id = fields.Many2one(
        'mrp.production',
        string='Ordem de Produção',
        readonly=True,
        ondelete='set null'
    )

    sale_line_id = fields.Many2one(
        'sale.order.line',
        string='Linha do Pedido de Venda',
        ondelete='cascade',
        index=True,
    )


    def action_create_child_mo(self):
        self.ensure_one()

        if not self.production_id:
            raise UserError("Plano de corte sem OP pai")

        child_mo = self.env['mrp.production'].create({
            'product_id': self.product_id.id,
            'product_qty': self.blue_qty,
            'bom_id': self.bom_id.id,
            'parent_production_id': self.production_id.id,
            'cut_plan_id': self.id,
            'origin': self.production_id.name,
            'sale_id': self.product_id.sale_id.id
        })

        child_mo.action_confirm()

    def _create_parent_mo(self):
        self.ensure_one()

        # 🔥 Verificar se já existe OP para este plano de corte
        if self.mo_id:
            _logger.info(f"⏭️ Plano de corte {self.name} já possui OP {self.mo_id.name}")
            return self.mo_id

        sale = self.sale_id
        if not sale:
            raise UserError(_('Plano de corte sem pedido de venda.'))

        if not sale.procurement_group_id:
            sale.procurement_group_id = self.env['procurement.group'].create({
                'name': sale.name,
                'partner_id': sale.partner_id.id,
            })

        mo_vals = {
            'product_id': self.product_id.id,
            'product_qty': self.blue_qty,
            'product_uom_id': self.product_id.uom_id.id,
            'bom_id': self.blue_bom_template_id.id,
            'company_id': sale.company_id.id,
            'origin': self.sale_id.name,
            'sale_id': self.sale_id.id,
            'procurement_group_id': sale.procurement_group_id.id,
            'cut_plan_id': self.id,
        }

        mo = self.env['mrp.production'].create(mo_vals)

        # Confirma a OP (cria os movimentos)
        mo.action_confirm()

        # 🔥 APENAS UMA CHAMADA - CRIA AS OPs FILHAS UMA ÚNICA VEZ
        mo._create_child_productions_from_components()

        self.mo_id = mo.id
        self.state = 'prod_order'

        _logger.info(f"✅ OP {mo.name} criada para plano de corte {self.name}")
        return mo

    def _create_delivery_from_mo(self):
        self.ensure_one()
        sale = self.sale_id
        if not sale:
            return

        picking_type = sale.warehouse_id.out_type_id

        picking = self.env['stock.picking'].create({
            'partner_id': sale.partner_id.id,
            'sale_id': sale.id,
            'origin': sale.name,
            'picking_type_id': picking_type.id,
            'location_id': picking_type.default_location_src_id.id,
            'location_dest_id': sale.partner_id.property_stock_customer.id,
            'company_id': sale.company_id.id,
            'group_id': sale.procurement_group_id.id,
        })

        self.env['stock.move'].create({
            'name': self.product_id.display_name,
            'product_id': self.product_id.id,
            'product_uom_qty': self.blue_qty,
            'product_uom': self.product_uom_id.id,
            'picking_id': picking.id,
            'sale_line_id': self.sale_line_id.id,
            'location_id': picking.location_id.id,
            'location_dest_id': picking.location_dest_id.id,
            'company_id': picking.company_id.id,
        })

        picking.action_confirm()

    def _create_delivery_with_items(self, sale):
        """
        Cria uma ordem de entrega com todos os itens do pedido de venda
        """
        self.ensure_one()

        _logger.warning(f"📦 Criando ordem de entrega para pedido {sale.name}")

        # 🔥 VERIFICAR SE JÁ EXISTE ENTREGA
        existing_delivery = self.env['stock.picking'].search([
            ('sale_id', '=', sale.id),
            ('picking_type_id.code', '=', 'outgoing'),
            ('state', 'not in', ['cancel'])
        ], limit=1)

        if existing_delivery:
            _logger.warning(f"⏭️ Entrega já existe: {existing_delivery.name}")
            return existing_delivery

        # Encontrar o tipo de operação de saída
        picking_type = sale.warehouse_id.out_type_id
        if not picking_type:
            picking_type = self.env['stock.picking.type'].search([
                ('code', '=', 'outgoing'),
                ('warehouse_id.company_id', '=', sale.company_id.id)
            ], limit=1)

        if not picking_type:
            _logger.error("❌ Tipo de operação de saída não encontrado")
            return False

        # Criar a ordem de entrega
        picking_vals = {
            'partner_id': sale.partner_id.id,
            'sale_id': sale.id,
            'origin': sale.name,
            'picking_type_id': picking_type.id,
            'location_id': picking_type.default_location_src_id.id,
            'location_dest_id': sale.partner_id.property_stock_customer.id,
            'company_id': sale.company_id.id,
            'group_id': sale.procurement_group_id.id if sale.procurement_group_id else False,
            'move_ids': []
        }

        # Adicionar movimentos para cada linha do pedido
        for line in sale.order_line.filtered(lambda l: l.product_id.type == 'product'):
            if line.product_uom_qty <= 0:
                continue

            move_vals = {
                'name': line.name or line.product_id.display_name,
                'product_id': line.product_id.id,
                'product_uom_qty': line.product_uom_qty,
                'product_uom': line.product_uom.id,
                'location_id': picking_type.default_location_src_id.id,
                'location_dest_id': sale.partner_id.property_stock_customer.id,
                'company_id': sale.company_id.id,
                'sale_line_id': line.id,
                'description_picking': line.name,  # 🔥 CAMPO ESPECÍFICO
            }
            picking_vals['move_ids'].append((0, 0, move_vals))

        try:
            picking = self.env['stock.picking'].create(picking_vals)
            picking.action_confirm()
            picking.action_assign()

            _logger.warning(f"✅ Ordem de entrega criada: {picking.name} com {len(picking.move_ids)} itens")
            return picking

        except Exception as e:
            _logger.error(f"❌ Erro ao criar ordem de entrega: {str(e)}")
            import traceback
            _logger.error(traceback.format_exc())
            return False

    def _add_item_to_delivery(self, delivery):
        """
        Adiciona um item à ordem de entrega existente
        """
        self.ensure_one()

        if not delivery or not self.sale_line_id:
            return False

        _logger.warning(f"📦 Adicionando item à entrega {delivery.name}")

        # Verificar se o item já existe na entrega
        existing_move = delivery.move_ids.filtered(
            lambda m: m.sale_line_id.id == self.sale_line_id.id
        )

        if existing_move:
            _logger.warning(f"⏭️ Item já existe na entrega")
            return delivery

        # Criar novo movimento
        move_vals = {
            'name': self.sale_line_id.name or self.product_id.display_name,
            'product_id': self.product_id.id,
            'product_uom_qty': self.blue_qty,
            'product_uom': self.product_uom_id.id,
            'location_id': delivery.location_id.id,
            'location_dest_id': delivery.location_dest_id.id,
            'company_id': delivery.company_id.id,
            'sale_line_id': self.sale_line_id.id,
            'picking_id': delivery.id,
            'description_picking': self.sale_line_id.name,  # 🔥 CAMPO ESPECÍFICO
        }

        try:
            move = self.env['stock.move'].create(move_vals)
            delivery.write({'move_ids': [(4, move.id)]})

            _logger.warning(f"✅ Item adicionado à entrega {delivery.name}")
            return delivery

        except Exception as e:
            _logger.error(f"❌ Erro ao adicionar item à entrega: {str(e)}")
            return False

    def _create_child_production(self):
        self.ensure_one()

        if not self.mo_id:
            raise UserError(_("Plano de corte sem OP pai."))

        parent_mo = self.mo_id

        child_mo = parent_mo.copy({
            'parent_production_id': parent_mo.id,
            'cut_plan_id': self.id,
            'product_qty': self.blue_qty,
            'origin': parent_mo.name,
        })

        child_mo.action_confirm()
        return child_mo

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
        pedido = self.sale_id.id

        mrp_production_ids = self.env['mrp.production'].search([('sale_id','=',pedido)])
        sale = self.env['sale.order'].browse(pedido)
        sale.mrp_production_count = len(mrp_production_ids)
        sale.mrp_production_ids = mrp_production_ids


    def _prepare_child_production_vals(self, bom_line, quantity):
        vals = super()._prepare_child_production_vals(bom_line, quantity)

        if self.cut_plan_id:
            vals['cut_plan_id'] = self.cut_plan_id.id
            vals['parent_production_id'] = self.id

        return vals

    def button_mark_done_custom(self):
        for record in self:
            if record.related_type == 'm':
                raise UserError("Este botão não está disponível para Mold Calculation.")

            return super(BlueMrpProduction, record).button_mark_done()

    def button_create_po(self):
        """
        Botão legado - redireciona para o método multi
        """
        return self.button_create_po_multi()

    def button_create_po_multi(self):
        """
        Cria ordens de produção para múltiplos planos de corte
        """
        # 🔥 Verificar se temos registros no recordset OU no contexto
        if not self and not self.env.context.get('active_ids'):
            raise UserError(_("Por favor, selecione pelo menos um registro na listagem."))

        # Se veio do botão na árvore, usa self
        records = self

        # Se veio de outro lugar com active_ids no contexto, usa o contexto
        if not records and self.env.context.get('active_ids'):
            records = self.env[self._name].browse(self.env.context.get('active_ids'))
        created_orders = []
        failed_plans = []

        # Filtrar apenas planos SEM OP
        plans_without_mo = records.filtered(lambda p: not p.mo_id)

        if not plans_without_mo:
            raise UserError(_("Todos os planos de corte selecionados já possuem ordens de produção."))

        # 🔥 VERIFICAR SE TODOS OS PLANOS TÊM A MESMA EMPRESA
        companies = set()
        for plan in plans_without_mo:
            plan_company = plan.company_id or (plan.sale_id and plan.sale_id.company_id)
            if plan_company:
                companies.add(plan_company.id)

        if len(companies) > 1:
            _logger.warning(f"⚠️ Planos de empresas diferentes detectados: {companies}")
            # Opção 1: Usar a empresa do ambiente
            company = self.env.company
            _logger.warning(f"🏢 Usando empresa do ambiente: {company.name}")
            # Opção 2: Levantar erro (descomente se preferir)
            # raise UserError("Não é possível processar planos de empresas diferentes simultaneamente.")
        elif len(companies) == 1:
            company_id = list(companies)[0]
            company = self.env['res.company'].browse(company_id)
            _logger.warning(f"🏢 Todos os planos usam a mesma empresa: {company.name}")
        else:
            # Nenhuma empresa definida, usar empresa do ambiente
            company = self.env.company
            _logger.warning(f"🏢 Nenhuma empresa definida nos planos, usando empresa do ambiente: {company.name}")

        # 🔥 VERIFICAR SE A EMPRESA EXISTE
        if not company:
            raise UserError("❌ Nenhuma empresa válida encontrada para criar as ordens de produção.")

        # 🔥 BUSCAR ARMAZÉM DA EMPRESA
        warehouse = self.env['stock.warehouse'].search([('company_id', '=', company.id)], limit=1)
        if not warehouse:
            raise UserError(f"❌ Nenhum armazém encontrado para a empresa {company.name}.")

        # 🔥 BUSCAR PICKING TYPE DE FABRICAÇÃO
        picking_type = self.env['stock.picking.type'].search([
            ('warehouse_id', '=', warehouse.id),
            ('code', '=', 'mrp_operation')
        ], limit=1)

        if not picking_type:
            # Se não encontrar o específico, pega qualquer picking type do armazém
            picking_type = self.env['stock.picking.type'].search([
                ('warehouse_id', '=', warehouse.id),
            ], limit=1)

        if not picking_type:
            raise UserError(f"❌ Tipo de operação de fabricação não encontrado para a empresa {company.name}.")

        _logger.warning(f"🔍 Usando picking_type: {picking_type.name} para empresa {company.name}")

        created_orders = []
        deliveries_created = {}

        # 🔹 Iterar sobre TODOS os registros selecionados (apenas os sem OP)
        for record in plans_without_mo:
            try:
                # 🔥 GARANTIR QUE O PLANO ESTÁ NA MESMA EMPRESA
                if record.company_id and record.company_id.id != company.id:
                    _logger.warning(f"⚠️ Ajustando empresa do plano {record.name} para {company.name}")
                    record.write({'company_id': company.id})

                # Atualizar estado do registro atual
                record.state = 'prod_order'

                venda = record.sale_id.procurement_group_id if record.sale_id else False
                data_plan = record.sale_id.commitment_date if record.sale_id else False



                # 🔹 Criação da OP para o registro atual
                production_data = {
                    'company_id': company.id,
                    'location_src_id': warehouse.lot_stock_id.id,
                    'location_dest_id': warehouse.lot_stock_id.id,
                    'picking_type_id': picking_type.id,
                    'cut_plan_id': record.id,
                    'product_id': record.product_id.id,
                    'product_uom_id': record.product_id.uom_id.id,
                    'bom_id': record.blue_bom_template_id.id,
                    'product_qty': record.blue_qty,
                    'partner_id': record.partner_id.id,
                    'origin': record.blue_origin,
                    'sale_id': record.sale_id.id if record.sale_id else False,
                    'sale_line_id': record.sale_line_id.id,
                    'blue_m2': record.sale_line_id.blue_m2,
                    'blue_m3': record.sale_line_id.blue_m3,
                    'source_procurement_group_id': venda.id if venda else False,
                }

                if data_plan:
                    production_data['date_planned_start'] = data_plan

                # Criar OP pai com contexto da empresa correta
                production_order = self.env['mrp.production'].with_company(company).with_context(
                    allowed_company_ids=[company.id],
                    company_id=company.id
                ).create(production_data)

                # 🔥 LOG para confirmar que sale_id foi salvo
                _logger.warning(f"   ✅ OP criada: {production_order.name}")
                _logger.warning(
                    f"   Sale ID na OP: {production_order.sale_id.id if production_order.sale_id else 'None'}")

                # 🔥 GARANTIA: Se por algum motivo o sale_id não foi salvo, força agora
                if not production_order.sale_id and record.sale_id:
                    production_order.write({'sale_id': record.sale_id.id})
                    _logger.warning(f"   🔥 Sale ID FORÇADO na OP: {record.sale_id.name}")

                # Confirmar OP (cria movimentos)
                production_order.action_confirm()
                production_order.state = 'draft'

                # Ajustar quantidades dos componentes
                for bom_line in record.blue_bom_template_id.bom_line_ids:
                    for move in production_order.move_raw_ids:
                        if move.product_id == bom_line.product_id:
                            # Nova lógica: Se OP é 'llh' ou 'm' e componente é 'massa', calcular quantidade como blue_m2 / cement
                            if production_order.product_id.blue_area_calc in ['llh', 'm'] and bom_line.product_id.blue_area_calc == 'massa':
                                cement = bom_line.product_id.cement
                                if cement > 0:
                                    move.product_uom_qty = production_order.blue_m2 * cement * production_order.product_qty
                                else:
                                    move.product_uom_qty = 0
                                    _logger.warning(
                                        f"Cement <= 0 para produto {bom_line.product_id.name}, definindo quantidade como 0")
                            elif move.product_id.blue_area_calc in ['llh', 'm']:
                                if bom_line.blue_multiplier:
                                    move.product_uom_qty = bom_line.product_qty
                                else:
                                    move.product_uom_qty = production_order.blue_m3
                            else:
                                if bom_line.blue_multiplier:
                                    move.product_uom_qty = bom_line.product_qty
                                else:
                                    move.product_uom_qty = (
                                            (
                                                        record.blue_qty / record.blue_bom_template_id.product_qty) * bom_line.product_qty
                                    )

                            # Usar record.related_type (que existe no cut plan)
                            if record.related_type == 'm':
                                if move.product_id.boolean_coefficient_or_screen == 'tl' and move.product_id.blue_area_calc != 'massa':
                                    move.product_uom_qty = production_order.blue_m2
                                elif move.product_id.boolean_coefficient_or_screen == 'coe' and move.product_id.blue_area_calc != 'massa':
                                    template_price_config_id = self.env['mrp_cut_plan.template_price_config'].search([
                                        ('product_id', '=', record.product_id.id)
                                    ], limit=1)
                                    if template_price_config_id:
                                        move.product_uom_qty = production_order.blue_m2 * template_price_config_id.mortar_coefficient
                                    else:
                                        move.product_uom_qty = 0

                # 🔥 CRIAR OPs FILHAS
                production_order._create_child_productions_from_components()

                # 🔥 APÓS CRIAR AS FILHAS, VERIFICAR SE TODAS TÊM SALE_ID
                all_ops = self.env['mrp.production'].search([
                    ('cut_plan_id', '=', record.id)
                ])

                for op in all_ops:
                    if not op.sale_id and record.sale_id:
                        op.write({'sale_id': record.sale_id.id})
                        _logger.warning(f"   🔥 Sale ID FORÇADO na OP {op.name}: {record.sale_id.name}")

                # Refazer reservas
                production_order.move_raw_ids._action_assign()

                # Vincular OP ao plano de corte
                record.mo_id = production_order.id

                created_orders.append(production_order)
                _logger.warning(f"✅ OP CRIADA: {production_order.name} para registro {record.name}")

                # 🔥 CRIAR OU ATUALIZAR ORDEM DE ENTREGA
                if record.sale_id and not record.parent_production_id:  # Só para OPs pai
                    sale = record.sale_id

                    # Verificar se já existe uma ordem de entrega para este pedido
                    if sale.id not in deliveries_created:
                        existing_delivery = self.env['stock.picking'].search([
                            ('sale_id', '=', sale.id),
                            ('picking_type_id.code', '=', 'outgoing'),
                            ('state', 'not in', ['cancel']),
                            ('company_id', '=', company.id)  # Filtrar por empresa
                        ], limit=1)

                        if not existing_delivery:
                            if sale.id not in deliveries_created:
                                # Criar nova ordem de entrega
                                deliveries_created[sale.id] = record._create_delivery_with_items(sale)
                        else:
                            _logger.warning(f"📦 Entrega já existe: {existing_delivery.name}")
                            deliveries_created[sale.id] = existing_delivery
                    else:
                        # Adicionar item à entrega existente
                        record._add_item_to_delivery(deliveries_created[sale.id])

            except Exception as e:
                _logger.error(f"❌ Erro ao criar OP para registro {record.name}: {str(e)}")
                import traceback
                _logger.error(traceback.format_exc())
                continue

        # 🔥 FORÇAR VINCULAÇÃO EM TODAS AS OPs
        for record in plans_without_mo:
            if record.sale_id:
                all_productions = self.env['mrp.production'].search([
                    ('cut_plan_id', '=', record.id)
                ])

                for production in all_productions:
                    if production.sale_id.id != record.sale_id.id:
                        production.write({'sale_id': record.sale_id.id})
                        _logger.warning(f"   ✅ OP {production.name} vinculada ao pedido {record.sale_id.name}")

        # Atualizar contador de OPs
        for record in records:
            record._update_count_sale_mrp()

            if record.sale_id:
                ops_count = self.env['mrp.production'].search_count([('sale_id', '=', record.sale_id.id)])
                _logger.warning(f"📊 Pedido {record.sale_id.name} agora tem {ops_count} OPs vinculadas")

        if created_orders:
            return {
                'type': 'ir.actions.act_window',
                'name': 'Ordens de Produção Criadas',
                'res_model': 'mrp.production',
                'view_mode': 'tree,form',
                'domain': [('id', 'in', [op.id for op in created_orders])],
                'context': {'create': False},
            }

        if not created_orders:
            raise UserError("❌ Nenhuma ordem de produção foi criada. Verifique os logs para mais detalhes.")

    def _force_link_sale_to_productions(self):
        """
        Força a vinculação de todas as OPs (pai e filhas) ao pedido de venda
        """
        self.ensure_one()

        if not self.sale_id:
            _logger.warning(f"⚠️ Plano {self.name} não tem pedido de venda vinculado")
            return

        # Buscar todas as OPs relacionadas a este plano de corte
        all_productions = self.env['mrp.production'].search([
            ('cut_plan_id', '=', self.id)
        ])

        if not all_productions:
            _logger.info(f"ℹ️ Nenhuma OP encontrada para o plano {self.name}")
            return

        _logger.info(f"🔗 Forçando vinculação de {len(all_productions)} OPs ao pedido {self.sale_id.name}")

        # Forçar vinculação em todas as OPs
        for production in all_productions:
            if production.sale_id.id != self.sale_id.id:
                production.write({
                    'sale_id': self.sale_id.id
                })
                _logger.info(f"   ✅ OP {production.name} vinculada ao pedido {self.sale_id.name}")
            else:
                _logger.info(f"   ⏭️ OP {production.name} já está vinculada corretamente")

        # Também buscar OPs filhas recursivamente
        for production in all_productions:
            if production.child_production_ids:
                for child in production.child_production_ids:
                    if child.sale_id.id != self.sale_id.id:
                        child.write({
                            'sale_id': self.sale_id.id
                        })
                        _logger.info(f"      ✅ OP filha {child.name} vinculada ao pedido {self.sale_id.name}")

    def button_cancel(self):
        self.state = 'canceled'

    def _calculate_component_quantity_with_measures(self, bom_line):
        """Calcula quantidade do componente considerando medidas"""
        _logger.info(f"🔍 Calculando quantidade para {bom_line.product_id.name}:")
        _logger.info(f"   bom_line.calc = {bom_line.calc}")
        _logger.info(f"   bom_line.blue_multiplier = {bom_line.blue_multiplier}")
        _logger.info(f"   blue_m3 = {self.blue_m3}")

        # REGRA 1: Campo 'calc' ativo → usa blue_m3
        if bom_line.calc:
            qty = self.blue_m3 or bom_line.product_qty
            _logger.info(f"   ✅ Usando blue_m3 (calc=True): {qty}")
            return qty

        # REGRA 2: Campo 'blue_multiplier' ativo → quantidade fixa
        elif bom_line.blue_multiplier:
            qty = bom_line.product_qty
            _logger.info(f"   ✅ Usando qty fixa (blue_multiplier=True): {qty}")
            return qty

        # REGRA 3: Cálculo proporcional padrão
        else:
            if bom_line.product_id.blue_area_calc in ['llh', 'm']:
                qty = self.blue_m3 or bom_line.product_qty
                _logger.info(f"   ✅ Componente com área calc, usando: {qty}")
                return qty
            else:
                if self.blue_bom_template_id.product_qty > 0:
                    qty = (self.blue_qty / self.blue_bom_template_id.product_qty) * bom_line.product_qty
                    _logger.info(f"   ✅ Cálculo proporcional: {qty}")
                    return qty
                else:
                    qty = bom_line.product_qty
                    _logger.info(f"   ✅ Usando qty padrão: {qty}")
                    return qty

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
                    if record.blue_qty:
                        record.blue_m3 = side1 * side2 * height * record.blue_qty
                    else:
                        record.blue_m3 = side1 * side2 * height
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

                    if record.blue_qty:
                        record.blue_m3 = advance * height * record.blue_qty
                    else:
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

    @api.depends('product_id')
    def _compute_product_id_number(self):
        for record in self:
            record.product_id_number = record.product_id.id

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

    # No mrp_cut_plan.py, adicione este método na classe MrpCutPlan:

    def calculate_component_quantity_corrected(self, bom_line):
        """Calcula quantidade do componente CORRETAMENTE"""
        _logger.info(f"🔍 calculate_component_quantity_corrected para {bom_line.product_id.name}")
        _logger.info(f"   bom_line.product_qty: {bom_line.product_qty}")
        _logger.info(f"   bom_line.calc: {bom_line.calc}")
        _logger.info(f"   bom_line.blue_multiplier: {bom_line.blue_multiplier}")
        _logger.info(f"   blue_m3: {self.blue_m3}")
        _logger.info(f"   blue_qty: {self.blue_qty}")
        _logger.info(f"   bom product_qty: {self.blue_bom_template_id.product_qty}")

        # REGRA 1: Campo 'blue_multiplier' ativo → quantidade fixa da BOM
        if bom_line.blue_multiplier:
            qty = bom_line.product_qty
            _logger.info(f"   ✅ blue_multiplier=True: usando quantidade fixa da BOM: {qty}")
            return qty

        # REGRA 2: Campo 'calc' ativo → usa blue_m3 (mas só na OP filha!)
        # Na OP pai, mesmo com calc=True, usa quantidade da BOM
        if bom_line.calc:
            # 🔥 CORREÇÃO: Na OP pai, NÃO usa blue_m3, usa quantidade da BOM
            qty = bom_line.product_qty
            _logger.info(f"   ⚠️  calc=True na OP pai: usando quantidade da BOM: {qty}")
            return qty

        # REGRA 3: Cálculo proporcional padrão
        if self.blue_bom_template_id.product_qty > 0:
            qty = (self.blue_qty / self.blue_bom_template_id.product_qty) * bom_line.product_qty
            _logger.info(f"   ✅ Cálculo proporcional: {qty}")
            return qty
        else:
            qty = bom_line.product_qty
            _logger.info(f"   ✅ Usando qty padrão: {qty}")
            return qty



class WizardCreateAllProductionOrders(models.TransientModel):
    _name = 'wizard.create.all.production.orders'
    _description = 'Wizard para criar todas as ordens de produção'

    confirm = fields.Boolean(string='Confirmar criação?', default=True)
    note = fields.Text(
        string='Observação',
        default='Deseja criar ordens de produção para todos os registros selecionados? Esta ação não pode ser desfeita.'
    )

    def action_confirm_create_all(self):
        self.ensure_one()

        # Obter o modelo atual do contexto
        active_model = self.env.context.get('active_model')
        active_ids = self.env.context.get('active_ids')

        if not active_model or not active_ids:
            raise UserError(_("Nenhum registro selecionado!"))

        # Buscar todos os registros selecionados
        records = self.env[active_model].browse(active_ids)

        # Filtrar apenas registros que podem ter OP criada
        valid_records = records.filtered(lambda r: r.state not in ['prod_order', 'done', 'cancel'])

        if not valid_records:
            raise UserError(_("Nenhum registro válido para criar ordem de produção!"))

        # Criar OPs para cada registro
        created_orders = []
        for record in valid_records:
            try:
                # Chamar o método original em cada registro
                result = record.button_create_po()
                if result and result.get('res_id'):
                    created_orders.append(result['res_id'])
            except Exception as e:
                # Log do erro e continuar com os próximos
                _logger.error(f"Erro ao criar OP para {record.name}: {str(e)}")
                continue

        # Retornar ação para mostrar resultados
        if created_orders:
            return {
                'name': _('Ordens de Produção Criadas'),
                'type': 'ir.actions.act_window',
                'res_model': 'mrp.production',
                'view_mode': 'tree,form',
                'domain': [('id', 'in', created_orders)],
                'target': 'current',
            }
        else:
            raise UserError(_("Nenhuma ordem de produção foi criada."))