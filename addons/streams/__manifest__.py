# -*- encoding: utf-8 -*-
{
    'name': 'Streams',
    'version': '19.0.1.4.0',
    'category': 'Discuss',
    'summary': 'Record channels, message streams and explicit-only following',
    'description': """
Streams — server core
=====================

Splits the chatter into streams with independent delivery semantics:
note, comment, message (external correspondence), change and activity.

* every record gets a lazily created ``discuss.channel`` mirroring its chatter;
* automatic following is removed — subscriptions are explicit only;
* only internal users can follow a record, and they never receive email;
* channel members and record followers are kept in sync both ways;
* ``mail.activity`` events produce synthetic activity messages.

Ported to Odoo 19 (phase 5); the Odoo 15 web client lives in
``static/legacy15`` as a reference until the OWL rewrite phase.
""",
    'author': 'VelesAgro',
    'license': 'LGPL-3',
    'depends': [
        'mail',
        'queue_job',
    ],
    'data': [
        'security/ir.model.access.csv',
        'security/streams_security.xml',
        'data/mail_message_subtype_data.xml',
        'data/streams_notify_data.xml',
        'data/streams_guest_data.xml',
        'views/streams_field_subscription_wizard_views.xml',
        'views/streams_guest_invite_wizard_views.xml',
        'views/guest_templates.xml',
        'views/res_config_settings_views.xml',
    ],
    'post_init_hook': 'post_init_hook',
    'installable': True,
    'application': False,
    'auto_install': False,
}
