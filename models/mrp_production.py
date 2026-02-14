from odoo import models, fields, api, _
from odoo.exceptions import UserError
import logging

_logger = logging.getLogger(__name__)


class MrpProduction(models.Model):
    _inherit = "mrp.production"

    parent_production_id = fields.Many2one(
        'mrp.production', string='OP Pai', index=True
    )

    child_production_ids = fields.One2many(
        'mrp.production', 'parent_production_id', string='OPs Filhas'
    )

    cut_plan_id = fields.Many2one(
        'mrp_cut_plan.mrp_cut_plan', string='Plano de Corte',
        domain="['|', ('company_id', '=', False), ('company_id', '=', company_id)]",
        copy=True, index=True
    )

    has_child_production = fields.Boolean(
        compute='_compute_has_child_production', store=True
    )

    blue_m3 = fields.Float(
        store=True,
        readonly=False
    )

    blue_m2 = fields.Float(
        store=True,
        readonly=False
    )

    # Flag para controle interno
    _parent_updating = False

    def _is_parent_production(self):
        """Verifica se é OP pai"""
        self.ensure_one()
        return not bool(self.parent_production_id)

    def _get_moves_raw_values(self):
        """
        🔥 PARA OP PAI: retorna valores SEMPRE sem calcular
        """
        self.ensure_one()

        if self._is_parent_production():
            _logger.info(f"🚫 OP PAI {self.name} - usando valores padrão (SEM CÁLCULO)")
            return super()._get_moves_raw_values()

        moves = super()._get_moves_raw_values()

        if not self.cut_plan_id:
            return moves

        cut_plan = self.cut_plan_id

        for move_vals in moves:
            product_id = move_vals.get('product_id')
            if not product_id:
                continue

            bom_line = self.bom_id.bom_line_ids.filtered(
                lambda l: l.product_id.id == product_id
            )
            if not bom_line:
                continue

            bom_line = bom_line[0]
            qty = cut_plan._calculate_component_quantity_with_measures(bom_line)

            move_vals['product_uom_qty'] = qty
            move_vals['calc'] = False

        return moves

    def _update_raw_moves(self):
        """
        🔥 BLOQUEIA recalculo automático de componentes para OP PAI
        """
        parent_mos = self.filtered(lambda m: m._is_parent_production())

        if parent_mos:
            for mo in parent_mos:
                _logger.info(f"🚫 OP PAI {mo.name} - _update_raw_moves BLOQUEADO")

            # Só executa para OPs filhas
            child_mos = self - parent_mos
            if child_mos:
                return super(MrpProduction, child_mos)._update_raw_moves()
            return

        return super()._update_raw_moves()

    def _onchange_product_qty(self):
        """
        🔥 PARA OP PAI: permite alterar mas avisa e NÃO recalcula
        """
        for mo in self:
            if mo._is_parent_production() and mo.move_raw_ids:
                _logger.info(f"⚠️ OP PAI {mo.name} - quantidade alterada para {mo.product_qty}")
                # Não chama super() para evitar recálculos
                return {
                    'warning': {
                        'title': 'Atenção',
                        'message': 'A quantidade da OP pai foi alterada. Os componentes NÃO serão recalculados automaticamente.'
                    }
                }

        return super()._onchange_product_qty()

    def _generate_moves(self):
        """
        Gera movimentos normalmente
        """
        return super(MrpProduction, self)._generate_moves()

    def _create_child_productions_from_components(self):
        """Cria OPs filhas para componentes fabricados"""
        self.ensure_one()

        if not self.cut_plan_id:
            _logger.info("🚫 Sem plano de corte, não cria OPs filhas")
            return

        _logger.info(f"🔍 Criando OPs filhas para OP {self.name}")
        child_ops_created = []

        for move in self.move_raw_ids:
            product = move.product_id

            if product.id == self.product_id.id:
                _logger.info(f"   ⏭️  {product.name} é o produto da OP pai - IGNORADO")
                continue

            if not product.bom_ids:
                _logger.info(f"   ⏭️  {product.name} não tem BOM - ignorado")
                continue

            manufacture_route = self.env.ref('mrp.route_warehouse0_manufacture', raise_if_not_found=False)
            if manufacture_route and manufacture_route not in product.route_ids:
                _logger.info(f"   ⏭️  {product.name} não tem rota de fabricação - ignorado")
                continue

            if move.product_uom_qty <= 0:
                _logger.info(f"   ⏭️  {product.name} quantidade zero - ignorado")
                continue

            is_component = any(bom_line.product_id.id == product.id
                               for bom_line in self.bom_id.bom_line_ids)
            if not is_component:
                _logger.info(f"   ⏭️  {product.name} não é componente da BOM - ignorado")
                continue

            _logger.info(f"   ✅ {product.name} será fabricado (qty: {move.product_uom_qty})")

            bom = self.env['mrp.bom'].sudo().search([
                ('product_id', '=', product.id),
                ('type', '=', 'normal'),
                ('active', '=', True)
            ], limit=1)

            if not bom:
                _logger.warning(f"   ⚠️  BOM não encontrada para {product.name}")
                continue

            child_mo_vals = {
                'product_id': product.id,
                'product_qty': move.product_uom_qty,
                'product_uom_id': product.uom_id.id,
                'bom_id': bom.id,
                'company_id': self.company_id.id,
                'origin': f"{self.name}: {product.name}",
                'parent_production_id': self.id,
                'cut_plan_id': self.cut_plan_id.id,
                'sale_id': self.sale_id.id if self.sale_id else False,
            }

            try:
                child_mo = self.env['mrp.production'].create(child_mo_vals)
                child_mo.action_confirm()
                child_mo.state = 'draft'
                child_ops_created.append(child_mo)

                _logger.info(f"      ✅ OP filha {child_mo.name} criada")

                if not child_mo.sale_id and self.sale_id:
                    child_mo.write({'sale_id': self.sale_id.id})

                move.write({
                    'child_production_id': child_mo.id,
                    'calc': False,
                })

            except Exception as e:
                _logger.error(f"      ❌ Erro ao criar OP filha: {str(e)}")

        _logger.info(f"🏁 Total de OPs filhas criadas: {len(child_ops_created)}")
        return child_ops_created

    def _create_delivery_from_production(self):
        """Cria ordem de entrega para OP pai concluída"""
        self.ensure_one()

        if not self.sale_id or self.parent_production_id:
            return False

        _logger.info(f"📦 Verificando entrega para OP PAI {self.name}")

        delivery = self.env['stock.picking'].search([
            ('sale_id', '=', self.sale_id.id),
            ('picking_type_id.code', '=', 'outgoing'),
            ('state', 'not in', ['cancel'])
        ], limit=1)

        if delivery:
            _logger.info(f"📦 Usando entrega existente: {delivery.name}")

            if self.cut_plan_id and self.cut_plan_id.sale_line_id:
                existing_move = delivery.move_ids.filtered(
                    lambda m: m.sale_line_id.id == self.cut_plan_id.sale_line_id.id
                )
                if not existing_move:
                    move_vals = {
                        'name': self.cut_plan_id.sale_line_id.name or self.product_id.display_name,
                        'product_id': self.product_id.id,
                        'product_uom_qty': self.product_qty,
                        'product_uom': self.product_uom_id.id,
                        'location_id': delivery.location_id.id,
                        'location_dest_id': delivery.location_dest_id.id,
                        'company_id': delivery.company_id.id,
                        'sale_line_id': self.cut_plan_id.sale_line_id.id,
                        'picking_id': delivery.id,
                        'description_picking': self.cut_plan_id.sale_line_id.name,
                    }
                    self.env['stock.move'].create(move_vals)
                    _logger.info(f"✅ Item adicionado à entrega {delivery.name}")
        else:
            delivery = self.cut_plan_id._create_delivery_with_items(self.sale_id)

        return delivery

    @api.depends('child_production_ids.state')
    def _compute_has_child_production(self):
        for mo in self:
            mo.has_child_production = any(
                c.state not in ('done', 'cancel')
                for c in mo.child_production_ids
            )

    def action_confirm(self):
        """
         Confirma a OP e suas respectivas OPs filhas
         """
        _logger.info(f"🔍 action_confirm chamado para {len(self)} OPs")
        _logger.info(f"📋 IDs das OPs que estão sendo confirmadas AGORA: {self.ids}")

        res = super().action_confirm()

        # Depois de confirmar, busca e confirma as filhas APENAS das OPs que foram confirmadas
        for mo in self:
            _logger.info(f"📋 Verificando filhas da OP: {mo.name} (ID: {mo.id})")

            # Busca APENAS as filhas desta OP específica que estão em draft
            child_ops = self.env['mrp.production'].search([
                ('parent_production_id', '=', mo.id),
                ('state', '=', 'draft')
            ])

            _logger.info(f"   - OPs filhas em draft encontradas: {child_ops.ids}")

            if child_ops:
                _logger.info(f"🔄 Confirmando {len(child_ops)} OPs filhas da OP {mo.name}")

                for child in child_ops:
                    _logger.info(f"   - Confirmando filha: {child.name} (ID: {child.id})")
                    super(MrpProduction, child).action_confirm()
                    _logger.info(f"   - Filha {child.name} confirmada")

        return res

    def button_mark_done(self):

        # 1️⃣ Validações normais (como você já tem)
        for mo in self:
            missing = mo._check_mandatory_components()
            if missing:
                raise UserError(_("Componentes obrigatórios sem consumo."))

            if mo.parent_production_id:
                mo._update_parent_consumption_from_child()

            if mo.child_production_ids.filtered(lambda c: c.state != 'done'):
                raise UserError(_("Existem OPs filhas pendentes."))

        # 2️⃣ Conclui OP
        res = super().button_mark_done()

        # 3️⃣ Apenas libera reserva (NÃO mexe em qty_done)
        for mo in self.filtered(lambda m: not m.parent_production_id):

            if not mo.procurement_group_id:
                continue

            pickings = self.env['stock.picking'].search([
                ('group_id', '=', mo.procurement_group_id.id),
                ('state', 'in', ('confirmed', 'waiting')),
            ])

            for picking in pickings:
                picking.action_assign()

        return res

    def _check_mandatory_components(self):
        """Verifica componentes obrigatórios"""
        self.ensure_one()
        missing = []

        mandatory_lines = self.bom_id.bom_line_ids.filtered(lambda l: l.mandatory)
        if not mandatory_lines:
            return missing

        for bom_line in mandatory_lines:
            product = bom_line.product_id
            moves = self.move_raw_ids.filtered(lambda m: m.product_id == product)

            if not moves:
                missing.append(f"{product.name} (nenhum movimento)")
                continue

            total_consumed = 0
            for move in moves:
                qty_done = move.quantity_done
                if qty_done <= 0 and move.move_line_ids:
                    qty_done = sum(move.move_line_ids.mapped('qty_done'))
                total_consumed += qty_done

            if total_consumed <= 0:
                missing.append(f"{product.name} (consumo: 0)")

        return missing

    def _update_parent_consumption_from_child(self):
        """Atualiza consumo na OP pai"""
        self.ensure_one()

        parent = self.parent_production_id
        if not parent:
            return

        _logger.info(f"🔄 Atualizando consumo na OP pai {parent.name}")

        produced_product = self.product_id
        produced_qty = self.product_qty

        parent_move = parent.move_raw_ids.filtered(
            lambda m: m.product_id == produced_product
        )

        if not parent_move:
            _logger.warning(f"⚠️ Produto {produced_product.name} não encontrado na OP pai")
            return

        parent_move = parent_move[0]

        _logger.info(f"   Componente: {produced_product.name} = {parent_move.quantity_done} -> {produced_qty}")

        parent_move.with_context(
            force_allow_write=True,
            skip_consumption_check=True,
            from_child_production=True,
        ).write({'quantity_done': produced_qty})

        if parent_move.move_line_ids:
            for line in parent_move.move_line_ids:
                line.write({'qty_done': produced_qty})
        else:
            self.env['stock.move.line'].create({
                'move_id': parent_move.id,
                'product_id': produced_product.id,
                'product_uom_id': produced_product.uom_id.id,
                'qty_done': produced_qty,
                'location_id': parent_move.location_id.id,
                'location_dest_id': parent_move.location_dest_id.id,
                'company_id': parent_move.company_id.id,
            })

    def _update_count_sale_mrp(self):
        """Atualiza contador de OPs no pedido de venda"""
        for record in self:
            if not record.sale_id:
                continue

            ops = self.env['mrp.production'].search([
                ('sale_id', '=', record.sale_id.id)
            ])

            all_ops = ops
            for op in ops:
                if op.child_production_ids:
                    all_ops |= op.child_production_ids

            record.sale_id.write({
                'mrp_production_count': len(all_ops),
                'mrp_production_ids': [(6, 0, all_ops.ids)]
            })

    def write(self, vals):
        if 'product_qty' in vals:
            parent_mos = self.filtered(lambda m: m._is_parent_production())
            if parent_mos:
                _logger.info("🚫 OP PAI - bloqueando recálculo automático")
                self = self.with_context(skip_set_qty_producing=True)

        return super().write(vals)

    def _set_qty_producing(self):

        parent_mos = self.filtered(lambda m: m._is_parent_production())

        # 🔥 Permite execução normal se estiver concluindo
        if self.env.context.get('from_mark_done'):
            return super()._set_qty_producing()

        if parent_mos:
            for mo in parent_mos:
                _logger.info(
                    f"🚫 OP PAI {mo.name} - _set_qty_producing BLOQUEADO (edição manual)"
                )

            child_mos = self - parent_mos
            if child_mos:
                return super(MrpProduction, child_mos)._set_qty_producing()
            return

        return super()._set_qty_producing()



