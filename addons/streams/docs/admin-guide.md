# Streams — Administrator Guide

For the person who installs, configures and operates the `streams` module on Odoo 19. Behaviour and rationale are in [concept.md](concept.md); open issues in [roadmap.md](roadmap.md).

---

## 1. Installation

**Requirements**

- Odoo 19.0.
- The OCA module `queue_job` (19.0 branch) in the addons path. It is a hard dependency; voice transcription runs as a queue job.
- Python: nothing beyond Odoo's and `queue_job`'s requirements. Transcription uses `requests`.
- PostgreSQL: the module creates one plain SQL view (`streams_partner_message`); no extensions are needed.

**Install**

Install `streams` from Apps (it is not flagged as an application; search with the Apps filter removed) or with `-i streams`. The module applies to **every `mail.thread` model**, so install it on a staging copy first and read section 4.

**Post-install hook.** On installation every internal user (archived included) is switched to *Notifications: Handle in Odoo* (`notification_type = inbox`). This is re-applied whenever a user is created or their notification type, groups or active flag change. Share (portal) users are forced to e-mail.

**First run.** The partner-feed registry (section 3.4) is seeded with the installed models among `crm.lead`, `sale.order`, `purchase.order`, `account.move`, `stock.picking`, `project.task`, each via `partner_id`. Seeding happens once per database; models installed later are seeded on the next registry hook run, rows you delete are never re-created.

**Existing databases.** The module does not clean up existing followers. External partners that were followers before installation stay followers and keep receiving e-mail for events on those records, because the e-mail filter only drops internal users. If this matters, remove non-user partners from `mail.followers` yourself before go-live (there is no migration tool; the 15→19 data migration was dropped by decision).

**Uninstall.** There is no uninstall hook. The SQL view, the `streams.*` system parameters and the forced `inbox` notification type survive uninstallation; record channels turn into ordinary channels. See the roadmap.

---

## 2. Upgrading the module

Run `-u streams`. The SQL view is rebuilt on registry load when its signature (derived from the active registry rows) changed or the view is missing; the signature is stored in `streams.partner_view_signature`. After changing Python code on a running instance, restart the server before testing in a browser: running tests alone does not reload the HTTP workers.

---

## 3. Configuration

### 3.1 Settings › Streams

Visible to the *Administration / Settings* group.

| Setting | System parameter | Default | Meaning |
|---|---|---|---|
| Notification popup timeout | `streams.notify_timeout` | 10 s | Default popup lifetime for non-sticky notifications. Clamped to 3–300 |
| OpenAI API key | `openai_api_key` | empty | Enables voice transcription. The key is shared with other modules that use the same parameter. Empty means no transcript |
| Transcription model | `streams.transcription_model` | `whisper-1` | Model passed to `/v1/audio/transcriptions` |
| Guest session lifetime | `streams.guest_session_days` | 7 days | How long a customer's chat session lives; it slides on use |
| Guest page poll interval | `streams.guest_poll_interval` | 10 s | Refresh rate of the customer chat page |
| Guest edit/delete window | `streams.guest_edit_window` | 120 s | How long a customer may edit or delete their own message |
| Guest presence timeout | `streams.guest_presence_timeout` | 120 s | After this much time without a heartbeat the customer counts as absent for the digest |
| Guest max upload | `streams.guest_max_upload_mb` | 25 MB | Per-file limit on the guest page |
| Digest interval | cron `streams.ir_cron_streams_guest_digest` | 1 h | Stored as the cron interval, not as a parameter |

Guest parameters that are zero, negative or not a number fall back to the default; they cannot be used to switch a feature off.

Internal parameters you should not edit: `streams.partner_view_signature`, `streams.partner_sources_seeded`.

Core settings the module relies on: `web.base.url` (guest links in e-mails) and the **catchall alias and alias domain** (Settings › Technical › Aliases). Without a catchall, invitation and digest mails have no `reply_to` and customer replies by e-mail cannot be routed back; the invite wizard shows a warning in that case.

### 3.2 Scheduled actions

| Cron | Interval | Purpose |
|---|---|---|
| `streams.ir_cron_streams_guest_digest` | 1 hour | E-mails absent customers that there are new messages and rotates consumed links |
| `streams.ir_cron_streams_notify_transcribe` | 5 minutes | Re-queues transcriptions stuck in `queued` for more than 10 minutes, or resets them to `none` when there is no API key. Logs the number of orphaned pending attachments (does not delete them) |

Queue job channel: function `mail.notify._job_transcribe`, retry pattern 60 s / 300 s / 1800 s after the 1st / 3rd / 5th failure. Network errors, HTTP 429 and 5xx retry; other errors mark the transcript `failed`.

### 3.3 E-mail templates

`streams.mail_template_guest_invite` and `streams.mail_template_guest_digest`, both on the external participant model, rendered in the partner's language. The digest intentionally contains no message text. Both carry the catchall reply-to and `References` to an anchor message so replies thread correctly.

### 3.4 Partner Feed Sources

Settings › Technical › Email › **Partner Feed Sources** (system group). One row per (model, partner field). Only models that inherit `mail.thread` and stored many2one fields to `res.partner` are accepted; the pair is unique. **Preview** counts the messages a row would contribute. Archiving or deleting a row removes its branch from the view immediately. Add rows for custom models whose partner field is not `partner_id`, and remove rows for fields that do not mean "the customer" (an internal company, a lab, a customs office). Indirect relations (through an intermediate record) are not supported by the registry.

### 3.5 Message subtypes

Three subtypes are created (`noupdate`): `streams.mt_message` (external, not default), `streams.mt_change` (internal, hidden), `streams.mt_activity` (internal, hidden). Do not delete them.

---

## 4. What changes in a standard Odoo

Read this section before installing on a database with business modules.

**Changed for every `mail.thread` model**

- Creating a record subscribes nobody. `_message_auto_subscribe` and `_message_auto_subscribe_notify` are disabled: responsible-user fields no longer create followers or "assigned to you" notifications.
- `message_post` never subscribes the author or the recipients. Separately, Streams subscribes the author of a *comment* or external *message* (not of a note).
- `message_subscribe` silently drops any partner that has no internal user. Customers and portal users cannot become followers, from the UI or from code.
- Internal users receive **no e-mail** from records. Follower invitations by e-mail are blocked too. System mails (password reset, signup, mass mailing) are unaffected.
- Every internal user is kept on `notification_type = inbox`; share users on `email`.
- Tracking messages get the subtype `streams.mt_change`; system log messages (`notification` type without our subtypes) are treated as changes as well.
- Every record discussed gets a Discuss channel, created with sudo, named like the record.

**Side effects to expect**

- Portal access rules that rely on `message_partner_ids` (sale, project, helpdesk portals) stop working for *new* customers, since customers can no longer be followers.
- Business modules that call `message_subscribe` with customer partners now do nothing for those partners.
- Users who relied on e-mail digests of chatter activity get nothing by e-mail; all delivery is in-app (plus the separate `streams_mobile` push module, if installed).

### What standard behaviour is not changed

- Core `mail.activity` still subscribes the **assignee** as a follower (and therefore as a channel member) and still sends the assignee an inbox notification. This contradicts the "activities subscribe nobody" rule and is tracked in the roadmap.
- Core inbox notifications for followers (comments, `@mentions`, subtype-based tracking notifications) still happen, alongside the channel unread counters.
- Explicit `message_subscribe` of internal users from business code still works.
- Standard record merges (CRM leads, partners) move messages by writing `res_id` directly; they do not call `message_change_thread`, so the Streams merge hook does not run and the source record's channel is left behind. Tracked in the roadmap.
- Deleting a record does not delete its channel or the field subscriptions on it.

---

## 5. Security

**Groups.** No new groups. Everything is keyed to `base.group_user` and `base.group_system`.

**Access rights** (`security/ir.model.access.csv`)

| Model | Internal users | System |
|---|---|---|
| `mail.field.subscription` | CRUD, own rows only (record rule) | — |
| `mail.notify` | CRUD; read as author or recipient, write/delete as author (record rules) | — |
| `mail.notify.recipient` | read own rows or as author; a user may change only `read_date` / `popup_shown` on their own row | — |
| `streams.field.subscription.wizard`, `streams.guest.invite.wizard` (+ line) | CRUD (transient) | — |
| `streams.partner.source` | read | CRUD |
| `mail.channel.external.participant` | none; the invite wizard acts with sudo | CRUD |

Guest tokens, session tokens and link URLs are `groups=base.group_system` fields.

**Channel visibility — known issue, verify on your database.** Record channels and the personal Changes/Notifications channels are created with `channel_type = 'channel'` and no authorised group. Odoo 19 core then assigns `group_public_id = base.group_user`, and the core record rule makes such a channel readable and joinable by **every internal user**, not only members. Joining creates a member and, through the mirror, a follower. Message bodies still pass the usual `mail.message` access checks, and bus delivery is restricted to members who can read the record, but channel names (record display names) and membership are exposed. On Odoo 15 these channels were `public = 'private'`; the port dropped the equivalent. This is the first item in the roadmap. Until it is fixed, treat record channels as visible to all employees.

**Guest surface.** Routes under `/streams/guest/*` are public. Access is a 256-bit one-time token exchanged by POST (CSRF-protected) for an HttpOnly, SameSite=Lax session cookie scoped to `/streams`. Secrets are compared in constant time. The upload route is `csrf=False` and relies on the cookie's SameSite attribute. Message bodies shown to guests have backend links rewritten or removed. Guests can only download attachments of messages they can see.

**Other points to be aware of** (details in the roadmap): the invite wizard's *Revoke* line action does not re-check the caller's access to the record; the notify sender reads the source record's display name with sudo; the `streams_guest_edit` context key bypasses the core message-edit gate for any caller that sets it.

---

## 6. Operations

**Monitoring**

- Queue jobs: Settings › Technical › Queue Job. Transcriptions stuck in `queued` are picked up by the 5-minute cron.
- Logs: the module logs with the `odoo.addons.streams` loggers. A missing partner view is logged as an error and the partner chatter falls back to Direct scope. The transcription cron logs orphaned pending attachments at `info`.
- The bus: notifications and record channel messages are pushed per partner. If users do not see popups, check that the websocket (`/websocket`) works through your proxy; the SharedWorker fails silently on certificate problems.

**Housekeeping (manual, nothing is automatic yet)**

- `mail.notify` rows, their recipients and voice attachments are never garbage-collected.
- Pending attachments uploaded to the notify composer or the guest page but never bound to a message accumulate (`res_model` set, `res_id = 0` or the participant id).
- `mail.field.subscription` rows for deleted records remain.
- Channels of deleted records remain, archived or not.

**Reverse proxies and WAF.** The guest page uses JSON-RPC POSTs to `/streams/guest/*` and multipart uploads; the backend uses the websocket bus. Rules that block POST without a browser session, or that challenge unknown user agents, break both. The mobile API (`streams_mobile`) is affected the same way.

---

## 7. Testing

**Server tests.** `--test-tags /streams` runs 115 test methods (110 functional, 1 Hoot wrapper, 4 tour wrappers), all `post_install`. Two tests skip when `crm` is not installed. The five browser wrappers skip when no Chrome is available, so a run inside a container without Chrome reports green without exercising the JavaScript. Some tests assume this project's custom access rules on `res.partner`; see the roadmap.

**JavaScript tests.** 41 Hoot tests (suite `@streams`) and 4 tours (`streams_chatter_tour`, `streams_channel_tour`, `streams_notify_tour`, `streams_partner_scope_tour`). They require a real Chrome. Hoot selection must use `&id=<hash of "@streams">` rather than `&filter=`, which is fuzzy and runs thousands of core tests; `tests/test_js.py` documents the recipe. In Docker containers on the development host Chromium crashes (seccomp), so browser runs are made from the host against the environment through an HTTPS proxy with `--ignore-certificate-errors`.

**Technical users on the development database.** `streams.ci` (system group) exists for browser runs. Do not create such a user in production; remove it before cloning a development database to production.

---

## 8. RPC and bus contract

For integrators (the mobile API module `streams_mobile` is built on these).

**Store keys added**

- `discuss.channel`: `channel_kind`, `res_model`, `res_id`, `streams_filters` (current user's filters, record channels only).
- `mail.message`: `streams_kind` (`note` | `comment` | `message` | `change` | `activity` | none), `stream_channel_ids`.
- `res.partner`: `streams_company_scope_available`.
- `res.users.settings`: `streams_partner_scope`, `is_streams_notify_sound_muted`, `is_discuss_sidebar_category_streams_open`.
- Global `streams_notify` in the init payload: `{counter, channel_id, default_timeout, pending[]}`.

**ORM entry points**

| Model · method | Purpose |
|---|---|
| `discuss.channel.streams_set_filters(filters)` | Save stream filters for the current member; returns the stored dict |
| `discuss.channel.streams_changes_feed(limit=30, before_id=None, with_cursor=False)` | Changes feed; with `with_cursor` returns `{items, cursor, has_more}`, otherwise a bare list |
| `discuss.channel.streams_mark_read(last_message_id)` | Mark a Changes/record channel read up to a message; returns `{unread}` |
| `<any mail.thread>.streams_get_field_subscription()` / `streams_set_field_subscription(field_ids)` | Read or write the current user's field subscription on a record; empty list unsubscribes |
| `mail.notify.streams_notify_send(vals)` / `streams_notify_reply(parent_id, vals)` | Send or reply |
| `mail.notify.streams_notify_feed(box, limit, before_id)` | Received or sent box |
| `mail.notify.streams_notify_mark_read(ids)` / `streams_notify_popup_shown(ids)` | Receipt bookkeeping |
| `mail.notify.streams_notify_open_channel()` | Returns `{channel_id, data}` for the personal channel |
| `streams.partner.source.action_preview()` | Count messages a registry row contributes |
| `mail.channel.external.participant.action_revoke()` | Revoke a guest |

**HTTP routes**

- `POST /streams/notify/attachment/upload` (`auth=user`, 25 MB) → `{id, name, mimetype, size}`.
- `GET|POST /streams/guest/<token>`, `GET /streams/guest/chat`, JSON `POST /streams/guest/{feed,post,update,delete,reaction}`, `POST /streams/guest/upload`, `GET /streams/guest/attachment/<id>` (all public, session by cookie).
- `/mail/thread/messages` is overridden for `res.partner` so that reading the aggregated feed does not mark other records' needaction messages as done.

**Context keys** honoured by the server: `streams_unfiltered` (ignore stream filters), `streams_partner_direct` (force Direct scope), `streams_sync` (internal recursion guard), `streams_skip_view_rebuild`.

**Bus notification types**: `discuss.channel/new_message` (core, record channels; not sent for changes), `streams.changes/updated {id}`, `streams.notify/new`, `streams.notify/update`, `streams.notify/counter`.
