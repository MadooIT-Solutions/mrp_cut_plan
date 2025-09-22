{
    'name': "Plano de Corte Polispan",
    'version': '16.0.1.0.0+auto1',
    'description': """Plano de Corte Polispan""",
    'author': "Madureira Ind. e Com. Ltda.",
    'depends': [
        'sale',
        'sale_management',
        'mrp',
        'stock',
        # 'bi_product_secondary_uom',
    ],
    'data': [
        'security/ir.model.access.csv',
        'data/ir_sequence_data.xml',
        'views/mrp_cut_plan_views.xml',
        'views/mrp_bom_views.xml',
        'views/product_template_views.xml',
        'views/sale_order_views.xml',
        'wizards/sale_order_line_config_views.xml',
        'views/template_price_config_view.xml',
        'report/mrp_production_template.xml',
        'report/sale_report_templates.xml',
        'views/mrp_production.xml',
    ],
    'license': 'LGPL-3',
    'installable': True,
   
}
