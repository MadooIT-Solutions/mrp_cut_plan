from odoo import api, models, fields, _
from odoo.exceptions import UserError

class OsPurchase(models.Model):
    _inherit = "purchase.order"

    chave_pix = fields.Char(
            string='Chave Pix',
            readonly=True,
            compute='_compute_chave_pix',
            store=False,  # ou True, se quiser armazenar
            copy=False
        )
    forma_pagamento = fields.Many2one('payment.provider', string='Forma de Pagamento',
                                          ondelete='restrict', index=True, copy=False)
    payment_mode_id_name = fields.Char(
        string="Nome da Forma de Pagamento",
        related="payment_mode_id.name",
        store=False,
    )
    incoterm_id = fields.Many2one(required=True)
    fiscal_position_id = fields.Many2one(required=True)
    payment_term_id = fields.Many2one(required=True)


    def action_open_pix_wizard(self):
        self.ensure_one()
        if not self.partner_id:
            raise UserError("Informe o parceiro antes de tentar cadastrar a chave PIX.")
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'missing.pix.key.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_partner_id': self.partner_id.id,
            }
        }


    @api.depends('payment_mode_id', 'partner_id', 'partner_id.pix_key_ids')
    def _compute_chave_pix(self):
        for rec in self:
            if (
                    rec.payment_mode_id and rec.payment_mode_id.name == 'PIX'
                    and rec.partner_id and rec.partner_id.pix_key_ids
            ):
                # Pega o valor da chave pix do primeiro item
                rec.chave_pix = rec.partner_id.pix_key_ids[0].key
            else:
                rec.chave_pix = False


    @api.onchange('payment_mode_id')
    def _onchange_forma_pagamento_pix(self):
        if self.payment_mode_id and self.payment_mode_id.name == 'PIX':
            if self.partner_id and not self.partner_id.pix_key_ids:
                self.chave_pix = False
                return {
                    'warning': {
                        'title': "Chave PIX ausente",
                        'message': "Este parceiro não possui chave PIX cadastrada. Por favor, cadastre uma chave antes de continuar.",
                    }
                }
        else:
            self.chave_pix = False