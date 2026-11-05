# Streams — Roadmap

**Updated:** 2026-11-05, from a code review of the working tree (module 19.0.1.7.0, including the uncommitted phase 9.7 "autolog is a change" work).

This file lists only what is **not done, not verified, or to be decided**. What the module does today is in [concept.md](concept.md). The original specification and the history of phases 1–9.7 are in [history/roadmap.md](history/roadmap.md) and the design contracts in [history/](history/).

Priorities: **P0** security or data integrity · **P1** behaviour that contradicts the concept · **P2** gaps and unverified areas · **P3** housekeeping and polish.

---

## 1. Status against the original specification

| Area (spec §) | Status | Notes |
|---|---|---|
| Streams, subtypes, classification (§2, §4.1, §6) | Done | Autolog reclassified as change (2026-08-20) |
| Record channel: lazy creation, history, revive, filters (§5.1, §5.5, §6) | Done | Rename on `_rec_name` only (see 3.4); deletion and merge not handled (3.2, 3.3) |
| Members ⇄ followers, internal-only followers (§5.3, §10.3) | Done | Direct `mail.followers` writes bypass the mirror |
| Channel access rights (§5.4) | **Regressed on 19** | See 2.1 |
| Unread and sorting (§5.7) | Partial | Unread correct; last-message preview may be a change (3.5) |
| No auto-subscribe, no internal e-mail (§7, §10.1–10.2) | Done with exceptions | Core activity assignee still subscribed and notified (3.1); existing external followers not cleaned |
| Field subscriptions and Changes feed (§8) | Done | Wizard offers untracked fields (4.2); no GC (6.1) |
| Guest access (§9) | Done on the server | Guest page never run in a browser on 19 (5.1) |
| Priority notifications (§12) | Done | No GC (6.1); live transcription only tested with a mock |
| Activities (§13) | Done | "No notifications" broken by core `action_notify` (3.1) |
| Chatter UI (§11.1), Discuss channel UI (§11.2), navbar bell (§11.4) | Done | Topbar overflow on partner chatter awaiting decision (7.1) |
| Sidebar quick filter and search mode (§11.3, §14) | **Not implemented** | See 4.1 |
| Bespoke external-message composer (§11.1 "Message") | Not implemented | Core `mail.compose.message` with our subtype is used; unification with other modules' Send Email pending |
| Virtual partner chatter (§18) | Done | Seed narrower than spec; no hook for indirect relations; performance unmeasured (5.3) |
| Migration from Odoo 15 (§15) | Dropped | Decision 2026-08-18 |
| Translations | Not started | No `i18n/` directory (4.3) |

---

## 2. P0 — security

### 2.1 Record and personal channels are visible to every internal user
Channels are created with `channel_type='channel'` and no `group_public_id` (`models/mail_thread.py:305`, `models/discuss_channel.py:166`). Core Odoo 19 computes `group_public_id = base.group_user` for such channels and the rule `mail.ir_rule_discuss_channel_all` grants read to that group, so any employee can list record channels (named after the records), join them and thereby become a follower. Personal Changes and Notifications channels are exposed the same way. On 15 the channels were `public='private'`; the phase 5 port dropped the equivalent (`history/design-phase5-notes.md`) without a replacement.
- Verify on a live database with a non-admin user (Discuss "browse channels", direct `search_read`).
- Fix: use a channel type that is member-only (`group`) or keep `channel` but set a dedicated group that nobody holds, and add a Streams record rule that restricts `record`/`changes`/`notifications` channels to members (and, for `record`, to users who can read the source record, spec §5.4). Enforce `company_id` for multi-company.
- Add tests: non-member cannot read or join; member who lost access to the record no longer sees the channel.

### 2.2 Smaller access checks
- Invite wizard line `action_revoke_participant` revokes any participant id written into a wizard line without checking the caller's access to the channel's record (`wizard/streams_guest_invite_wizard.py:214-231`).
- `mail.notify` creation reads `record_name` for any `res_model`/`res_id` with sudo, and accepts `voice_attachment_id` without an ownership check (`models/mail_notify.py:269-286`).
- The `streams_guest_edit` context bypasses `_check_can_update_message_content` for any caller (`models/mail_thread.py:180-189`); it is probably vestigial, since guest comments already pass the core gate. Remove or restrict.
- `/streams/guest/upload` is `csrf=False` and relies on the SameSite cookie alone.
- `streams.ci` technical user with system rights exists on the development database; must not reach production.

---

## 3. P1 — behaviour that contradicts the concept

### 3.1 Activity assignee is still subscribed and notified
Core `mail.activity` calls `message_subscribe` for the assignee and `action_notify` sends them an inbox notification. This breaks "activities subscribe nobody, notifications only through Notify". Decide: override in `mail.activity` (skip subscribe, skip `action_notify`) or accept and document.

### 3.2 Record merge never reaches the channel merge hook
The hook on `message_change_thread` (`models/mail_thread.py:515`, `models/discuss_channel.py:108`) is not called by Odoo 19: CRM lead merge and partner merge rewrite `mail_message.res_id` and move followers with direct writes. Result: the source channel is orphaned, message links point at the old channel, members are not mirrored. Hook the actual merge paths (`crm.lead._merge_*`, `base.partner.merge.automatic.wizard._update_foreign_keys`/`_merge`) or a generic `mail.message.write` on `res_id`.

### 3.3 Deleting a record leaves its channel and subscriptions behind
No `unlink` override. Add: archive or delete the record channel, revoke guest participants, delete `mail.field.subscription` rows.

### 3.4 Channel rename only follows `_rec_name`
Spec §5.2 asks to follow every dependency of `display_name`. Today only writes to `_rec_name` and `active` resync (`models/mail_thread.py:477-513`); a partner whose company changes, or a document whose name is computed from several fields, keeps a stale channel name. The phase-1 "re-check in `message_post`" is absent in the 19 code. Also `company_id` is copied at creation and never re-synced.

### 3.5 Channel sorting and preview include changes
`_get_last_messages` takes the max message id over own messages plus projections, so a change message can become the channel preview, and `last_interest_dt` is never bumped for record channels (`models/discuss_channel.py:523-548`; posting from Discuss bypasses core `message_post`, `:486-509`). Spec §5.7 says changes must not affect sorting. Decide the intended sort key and implement it.

### 3.6 Inactive internal users can be followers and members
`_streams_internal_partner_ids` uses `active_test=False` (`models/mail_thread.py:443-445`), so archived users and OdooBot's partner pass the filter and OdooBot can be auto-subscribed as an author. Decide whether archived users should be dropped.

### 3.7 Guest digest window
The digest reports messages since `last_digest_sent` (or one interval), not since the guest's last visit, so it can announce messages the guest already read. Spec §9.6 intends "absent and new messages since they left".

---

## 4. P2 — specified but not implemented

### 4.1 Discuss sidebar quick filter and search mode (§11.3, §14)
Odoo 19's sidebar has no quick search and the module adds none. The optional "name + message content" mode (trigram index, debounced endpoint, ACL-filtered reverse mapping) is also absent, as is its setting. Decide whether it is still wanted on 19.

### 4.2 Field subscription wizard offers untracked fields
`_streams_available_fields` keeps `store or tracking` (`models/mail_field_subscription.py:135-136`), so dozens of fields are offered while only `tracking=True` ones ever produce a change. Either restrict to tracked fields or mark untracked ones in the dialog.

### 4.3 Translations
No `i18n/`, no `.pot`. Activity event bodies and the guest page strings are hard-coded English (`models/mail_activity.py:87-148`, `static/src/guest/guest.js`, `views/guest_templates.xml`). Export the template, translate the guest page (partner language is known) and the event bodies.

### 4.4 Stream identity in the UI
`Message.streams_kind` and `stream_channel_ids` are delivered to the client but nothing renders them (no badge or icon per stream, no marker of what a guest can see). Decide whether a visual marker is wanted; otherwise drop the unused keys and the unused `isStreamsChange` / `Thread.isStreamsRecordChannel` getters.

### 4.5 Posting on a never-saved record
Topbar buttons and the composer require `state.thread.id`, so nothing can be posted before the first save (`static/src/chatter/web/chatter_patch.xml:42-60`). Core auto-saves on Send; decide whether to mirror that.

### 4.6 Bespoke external-message composer and Send Email unification
"Message" opens the core full composer with `streams.mt_message`. The spec's own form (templates, attachments, recipients) and the unification with `velesagro_crm` / `email_document` Send Email buttons remain open and partly outside this repository.

### 4.7 Partner feed: hook for indirect relations
Spec §18.3 mentions models linked through an intermediate record; the registry only supports a direct stored many2one. Not implemented.

---

## 5. P2 — never verified live on Odoo 19

- **5.1 Guest page.** `static/src/guest/guest.js` and the 11 routes of `controllers/guest.py` have no HTTP tests and have never been opened in a browser on 19. Needed: confirm/enter flow (GET does not consume, POST does, cookie flags), 404/410, upload limits, attachment route, link rewriting, edit/delete window, reactions, polling pause on hidden tab. Also older-history pagination is not used by the page (server supports `before_id`/`has_more`).
- **5.2 E-mail reply by a guest end-to-end** through the real mail gateway (tested only with `message_process`), and the invitation/digest `References` threading in real mail clients.
- **5.3 Partner feed performance** on a production-sized copy: 10–15 UNION branches, cost of the ACL over-fetch; escalate to a materialised table only if pages exceed ~300 ms. Users with very narrow record rules may still get under-filled pages (constants `models/mail_message.py:48-49`).
- **5.4 Mass write / import performance.** Change routing and channel linking run per message; bus fan-out evaluates ACL per member per message. Measure with thousands of records and 50 subscribers.
- **5.5 Uninstall / reinstall** has never been run. Expected leftovers: SQL view `streams_partner_message`, `streams.*` parameters, forced `inbox` notification type, record channels becoming plain channels. Write an `uninstall_hook`.
- **5.6 Notifications**: popups accumulated before login, microphone-denied branch, successful transcription against the real OpenAI endpoint, Sent tab live update after sending (currently not refreshed).
- **5.7 Install on a database with existing data**: external followers remain (see admin guide); consider an optional cleanup action.

---

## 6. P3 — housekeeping

### 6.1 Garbage collection
Nothing is cleaned automatically: `mail.notify` with recipients and voice attachments, pending attachments never bound (notify composer and guest upload), `mail.field.subscription` rows of deleted records, channels of deleted records. Add autovacuum hooks with retention settings.

### 6.2 Dead code and stale text
- `static/legacy15/` (Odoo 15 client) is not bundled and is no longer a useful reference now that the OWL client exists; delete it.
- Manifest description still says the 15 client is kept "until the OWL rewrite phase" (`__manifest__.py:20-21`).
- Comment "filters are hidden on the client" (`models/mail_message.py:30-31`) is stale: filtering is server-side.
- Anchor docstring still calls the anchor "other" (`models/mail_channel_external_participant.py:389-393`); it is `change` since 2026-08-20.
- `_streams_event_body` has a dead `done` branch (`models/mail_activity.py:115-116`).
- `composer_patch.js` `sendMessage` override copies core code verbatim (`static/src/core/common/composer_patch.js:110-119`); fragile on core upgrades.
- Voice duration is parsed from a formatted string (`static/src/notify/streams_notify_composer.js:192`).
- `tests/test_js.py` docstring says 26 Hoot tests; there are 41.

### 6.3 Client polish
- Notify cards show time only (`TIME_SIMPLE`), so older items have no date.
- Notifications feed `hasMore` is a length heuristic, not a cursor; the Sent tab has no Reply and no live update.
- No "mark all read" for Notifications or Changes.
- Changes feed prints raw `String(value)` and no model label; dates are UTC strings converted client-side.
- Discuss Comment/Note toggle is client-only and lost on reload.
- Core channel header actions are not filtered for the Changes and Notifications channels.
- Guest page: no removal of a pending file before sending, `window.prompt` edit loses formatting, no older-history pagination.

### 6.4 Test infrastructure
- The host-side browser recipe (Chrome from `~/.cache/ms-playwright`, `LD_LIBRARY_PATH`, HTTPS proxy, `--ignore-certificate-errors`, `&id=` selection) exists only in the history roadmap; the scripts lived in `/tmp` and are gone. Put a script into the repo.
- `test_js.py` waits for the Hoot success signal only; an empty suite (wrong hash) passes silently. Assert the test count.
- Two tests assume this project's custom ACL on `res.partner` (`tests/test_streams_changes.py:232-236`, `tests/test_streams_guest.py:31`); make them self-contained.
- Container runs skip all 5 browser wrappers and therefore do not guard JS at all; consider a CI job on a host with Chrome.

### 6.5 Test coverage gaps (code exists, no test)
- Followers sync: `message_unsubscribe` → member removal; member create → follower; invite wizard share-partner filter; channel `company_id`.
- Channel lifecycle: rename, merge, `_get_last_messages`, activity unread increment, own messages not counted.
- Activities: reschedule, reassign, cancel, OdooBot author for cron.
- Changes: bus event `streams.changes/updated`; wizard `action_save` / `action_unsubscribe`.
- Notify: stuck-job cron, voice over 5 minutes and size limit, `streams_notify_open_channel`, `streams_notify_popup_shown`, Hoot for voice recording and pending popups at login.
- Guest: all HTTP routes and the page (see 5.1).
- UI: Discuss composer Comment/Note/Send Message actions; header actions Notify, Invite, Schedule activity; unsaved-record chatter.
- Settings `get_values`/`set_values`; `post_init_hook`.

---

## 7. Decisions needed from the product owner

1. **7.1 Partner chatter topbar overflow.** With the Direct/Related/Company segment the topbar is up to 170 px wider than the side chatter layout at 1600×900. Options: icon-only buttons, a dropdown for the scope, or a second row.
2. **7.2 Orphan incoming e-mail.** An incoming message on a record with no followers creates a channel with no members; nobody is told. Decide an owner rule (record `user_id`, alias owner, a fallback user) or accept.
3. **7.3 Activity assignee** (3.1): suppress core subscription and notification, or keep them.
4. **7.4 Channel sort key** (3.5): last non-change message, or last message of any stream.
5. **7.5 Sidebar quick filter / content search** (4.1): still wanted on 19 or drop from scope.
6. **7.6 Stream markers in the UI** (4.4): add badges or drop the unused Store keys.

---

## 8. Out of scope (unchanged decisions)

- Field subscriptions at **model** level ("watch `state` on all orders"): per record only.
- Threads/topics inside a record channel: the feed is flat, `parent_id` unused.
- Discuss sidebar rework (grouping record channels by model, collapsible sections).
- Odoo portal chat: not used, by design.
- Data migration from Odoo 15: dropped (2026-08-18).
- Other transports for external participants (Telegram): the model is prepared (`transport`), nothing else.

---

## 9. Related modules (not part of `streams`)

- **`streams_mobile`** (API v1, device tokens, push queue): FCM transport is a stub (`_streams_fcm_send` raises `NotImplementedError`) awaiting service-account keys; the mobile API is blocked from outside by the Cloudflare WAF / CSRF rules in front of the development host. `streams_kind` and `stream_channel_ids` Store keys are not consumed there either.
- **Flutter app** (`app/`): MVP; limitations listed in `history/roadmap.md` ("Фаза 7").
