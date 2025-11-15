from odoo import models, api
import logging

_logger = logging.getLogger(__name__)


class MrpProductionDebug(models.Model):
    _inherit = "mrp.production"

    @api.model
    def create(self, vals):
        if vals.get('origin_production_id') or ('origin' in vals and 'Matriz' in str(vals.get('origin', ''))):
            _logger.error("🚨🚨🚨 CRIAÇÃO DE OP FILIAL DETECTADA GLOBALMENTE")
            _logger.error(f"   • Valores: {vals}")
            _logger.error(f"   • Módulo atual: {__name__}")
            _logger.error("   • STACK TRACE COMPLETA:")
            import traceback
            stack = traceback.format_stack()
            for line in stack[:-1]:  # Exclui a linha atual do traceback
                _logger.error(line.strip())

            # Não bloqueie, apenas log para identificarmos a fonte
        return super(MrpProductionDebug, self).create(vals)