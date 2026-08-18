# -*- encoding: utf-8 -*-
{
    'name': 'Streams Mobile',
    'version': '19.0.1.0.0',
    'category': 'Discuss',
    'summary': 'Token-based mobile API and push infrastructure for Streams',
    'description': """
Streams Mobile — server side
============================

Versioned JSON API (``/streams/mobile/v1``) for the Flutter mobile client:

* token authentication with per-device revocable tokens;
* messaging endpoints on top of the streams projections;
* per-stream push policy (FCM transport pluggable, stub until keys);
* bus poll endpoint replacing the removed longpolling.
""",
    'author': 'VelesAgro',
    'license': 'LGPL-3',
    'depends': [
        'streams',
    ],
    'data': [
        'security/ir.model.access.csv',
        'security/streams_mobile_security.xml',
        'data/streams_mobile_data.xml',
        'views/streams_mobile_device_views.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
}
