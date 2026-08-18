# -*- encoding: utf-8 -*-
{
    'name': 'Streams',
    'version': '15.0.1.4.0',
    'category': 'Discuss',
    'summary': 'Record channels, message streams and explicit-only following',
    'description': """
Streams — server core
=====================

Splits the chatter into streams with independent delivery semantics:
note, comment, message (external correspondence), change and activity.

* every record gets a lazily created ``mail.channel`` mirroring its chatter;
* automatic following is removed — subscriptions are explicit only;
* only internal users can follow a record, and they never receive email;
* channel members and record followers are kept in sync both ways;
* ``mail.activity`` events produce synthetic activity messages.
""",
    'author': 'VelesAgro',
    'license': 'LGPL-3',
    'depends': [
        'mail',
        'mail_extra_recipients',
        'mailgun',
        'bus_actions',
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
    'assets': {
        'web.assets_backend': [
            'streams/static/src/js/streams_filters.js',
            'streams/static/src/models/message.js',
            'streams/static/src/models/thread.js',
            'streams/static/src/models/thread_cache.js',
            'streams/static/src/models/thread_view_topbar.js',
            'streams/static/src/models/chatter.js',
            'streams/static/src/models/discuss.js',
            'streams/static/src/models/discuss_sidebar_category.js',
            'streams/static/src/models/discuss_sidebar_category_item.js',
            'streams/static/src/models/messaging_initializer.js',
            'streams/static/src/models/messaging_notification_handler.js',
            'streams/static/src/components/streams_changes_feed/streams_changes_feed.js',
            'streams/static/src/js/notify_bridge.js',
            'streams/static/src/js/voice_recorder.js',
            'streams/static/src/components/streams_notify_popup/streams_notify_popup.js',
            'streams/static/src/components/streams_notify_composer/streams_notify_composer.js',
            'streams/static/src/components/streams_notify_feed/streams_notify_feed.js',
            'streams/static/src/js/notify_service.js',
            'streams/static/src/js/notify_systray.js',
            'streams/static/src/scss/streams.scss',
        ],
        'web.assets_qweb': [
            'streams/static/src/components/streams_changes_feed/streams_changes_feed.xml',
            'streams/static/src/components/streams_notify_popup/streams_notify_popup.xml',
            'streams/static/src/components/streams_notify_composer/streams_notify_composer.xml',
            'streams/static/src/components/streams_notify_feed/streams_notify_feed.xml',
            'streams/static/src/xml/notify_systray.xml',
            'streams/static/src/xml/chatter_topbar.xml',
            'streams/static/src/xml/discuss.xml',
            'streams/static/src/xml/discuss_sidebar.xml',
            'streams/static/src/xml/message.xml',
            'streams/static/src/xml/thread_view_topbar.xml',
        ],
    },
    'post_init_hook': 'post_init_hook',
    'installable': True,
    'application': False,
    'auto_install': False,
}
