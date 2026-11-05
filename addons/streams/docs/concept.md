# Streams — Concept

**Module:** `streams` 19.0.1.7.0 · **Target platform:** Odoo 19.0 · **Depends on:** `mail`, `queue_job`
**Status:** this document describes the module *as implemented* in the working tree on 2026-11-05. Planned work and known gaps live in [roadmap.md](roadmap.md). The original specification (Russian, written for Odoo 15) and the per-phase design contracts are preserved in [history/](history/).

---

## 1. Why the module exists

The standard Odoo chatter mixes four kinds of content into one feed: correspondence with customers, internal notes, the audit trail of field changes, and system events. The follower mechanism treats all of them alike and leaks outward by default: external contacts are auto-subscribed to records and receive e-mail about internal events.

Streams restructures the messaging layer around four ideas:

1. **Streams.** Every message on a record belongs to exactly one stream with its own delivery semantics: *note*, *comment*, *message*, *change*, *activity*.
2. **Explicit-only following.** Nothing subscribes anyone automatically, only internal users can follow a record, and internal users never receive e-mail from records.
3. **Record channels.** Every record that is actually discussed gets a Discuss channel. The chatter and the channel are two views of the same messages, not two stores.
4. **Priority notifications.** A separate, in-app-only notification entity with popups, voice, and read receipts, independent of the chatter.

On top of these, the module adds controlled **guest access** for customers by one-time link, a personal **Changes** feed for field-level subscriptions, and a **virtual partner chatter** that aggregates the messages of every record linked to a contact.

The module applies to **every `mail.thread` model** in the database. It is not an application; it changes how Discuss and the chatter behave everywhere.

---

## 2. Terminology

The module redefines a few words relative to standard Odoo. Within this project the table below is the only correct usage.

| Term | Subtype / type | Meaning | Who may see it |
|---|---|---|---|
| **Note** | `mail.mt_note` | Internal record "for me and colleagues" | Internal users only. The one stream never shown to an invited customer |
| **Comment** | `mail.mt_comment` | Internal discussion among employees about the record | Internal users and invited guests |
| **Message** | `streams.mt_message`, or any `email` / `email_outgoing` message | External correspondence: mail from and to customers | Internal users and invited guests |
| **Change** | `streams.mt_change`, or any `notification` message without one of our subtypes | A tracked field change, or the system autolog ("Lead created", "Record created", core service posts) | Internal users |
| **Activity** | `streams.mt_activity` | Synthetic message about a `mail.activity` event | Internal users |
| **Notification** | model `mail.notify` | Priority, addressed, in-app notification with a popup | Internal users |

What older discussions called an "internal message" is a **comment** here. "Message" means external correspondence only.

Messages that match no stream are **other**: `user_notification` messages and messages posted with a foreign subtype that are neither autolog nor e-mail. They never create a channel, never count as unread and are always shown.

---

## 3. Architecture

### 3.1 One set of messages, several projections

A `mail.message` is written once, on its record, exactly as in standard Odoo. The module adds a many-to-many field `stream_channel_ids` (table `mail_message_stream_channel_rel`) that links the message to any number of `discuss.channel` records. Every feed in the module is a *projection* of the same rows:

- the **record chatter** shows the messages of the record (standard);
- the **record channel** in Discuss shows the messages linked to it, filtered by the user's stream filters;
- the **personal Changes channel** of each subscriber shows the change messages linked to it, with tracking values filtered to the subscribed fields;
- the **virtual partner chatter** shows messages of other records through a SQL view, without any link at all;
- the **guest page** shows the channel's messages filtered to what a customer may see.

No message is ever copied. Access to a projection is always decided against the source record.

### 3.2 Three kinds of channels

`discuss.channel` gets a `channel_kind` field:

| Kind | One per | Content | Where it appears |
|---|---|---|---|
| `record` | record (`res_model`, `res_id`) | Group discussion of the record; all five streams | Discuss sidebar, category **Messages** |
| `changes` | user (`owner_user_id`) | Changes of the fields the user subscribed to, grouped by record | Discuss sidebar, core **Channels** category |
| `notifications` | user (`owner_user_id`) | Received and sent priority notifications (holds no `mail.message`) | Discuss sidebar, core **Channels** category; systray bell |

All three are created lazily and are protected by partial unique indexes.

### 3.3 Classification

A message is classified once from `(subtype_id, message_type)`, in this order:

1. `message_type = user_notification` → other;
2. `message_type` in (`email`, `email_outgoing`) → **message**;
3. subtype `streams.mt_change` / `mt_activity` / `mt_message` → **change** / **activity** / **message**;
4. `message_type = notification` with any other subtype or none → **change** (system autolog);
5. subtype `mail.mt_note` → **note**; `mail.mt_comment` → **comment**;
6. anything else → other.

A notification message that carries tracking values is rewritten to `streams.mt_change` on create, so standard tracking becomes the change stream. The server also exposes the same rules as an ORM domain per stream; a test keeps the classifier and the domain in sync.

### 3.4 Where filtering happens

Stream filters are **a per-user, per-channel display preference, not a subscription**. All messages are always linked to the channel; the server applies the user's filters inside `_message_fetch` for `record` channels. Clients therefore receive only what the user asked to see, and the mobile API can bypass filters with the `streams_unfiltered` context.

---

## 4. Record channel

### 4.1 Lazy creation

A channel is created on the first message of a *triggering* stream posted on a record:

- first **comment**;
- first **note**;
- first **message** (incoming or outgoing e-mail);
- first **activity** event;
- an **invitation** of an external participant from the chatter (the invite wizard creates the channel).

A channel is **never** created by record creation, by field changes (any number of them), by the system autolog, by adding a follower, or on blacklisted models (`discuss.channel`, `mail.activity`, `connect_messagebox.message`, abstract and transient models).

On creation the channel receives the **entire history** of the record (every message except `user_notification`), inserted in one SQL batch. From then on every new message of the record, change messages and autolog included, is linked to the channel at create time.

### 4.2 Name, company, archiving

- Name = the record's `display_name` (e.g. `S00025`). Writes on the record's `_rec_name` field rename the channel.
- `company_id` is copied from the record at creation when the model has that field.
- Archiving the record archives the channel; unarchiving restores it; a new posted message on an archived record revives the channel. An archived channel also disables guest links.

### 4.3 Members are followers

Channel members and record followers are **the same set**, synchronised in both directions:

- follower added on the record → member added to the channel, and vice versa;
- member removed or leaving → follower removed, and vice versa.

The `streams_sync` context key guards against recursion. Only partners that have an internal user can be followers; attempts to subscribe customers or portal users are silently dropped.

The author of a **comment** or **message** is subscribed automatically to the record (both the person who starts the thread and anyone who replies). The author of a **note** is not: a note is the way to write into the channel without following. External authors are never subscribed. A guest's reply subscribes the user who invited the guest.

### 4.4 Delivery, unread and sorting

| Stream | Who is notified |
|---|---|
| Note | Nobody except `@mentions` in the body |
| Comment | Channel members (unread counter) |
| Message | Members (unread counter); the customer through guest access |
| Change | Only the Changes channels of users subscribed to the changed fields. No popups |
| Activity | Nobody. Counts as unread in the channel |

Bus delivery of a new message goes **only to members who can read the source record** (model ACL plus the evaluated `ir.rule` domain, checked per member). Change messages are not broadcast at all, so they cannot surface in the feed of someone who has the Changes filter off.

The channel's unread counter counts comments, notes, messages, activities and "other" messages that are not the user's own. **Changes and autolog never affect unread.**

### 4.5 Posting from Discuss

A comment or note written in a record channel is posted **on the record itself**, after checking that the real user may read the record. The channel sees it through the projection. The Discuss composer therefore cannot write anything that would not exist in the chatter.

---

## 5. Explicit-only following and e-mail suppression

Installing the module changes the following standard behaviours for every `mail.thread` model:

- creating a record no longer subscribes the creator (`mail_create_nosubscribe` is forced);
- `_message_auto_subscribe` and `_message_auto_subscribe_notify` are no-ops: no auto-follow from `user_id`-like fields, no "you have been assigned" notification from the tracking mechanism;
- `message_post` never subscribes the author or the recipients (`mail_post_autofollow` off);
- `message_subscribe` drops every partner that is not linked to an internal (non-share) user;
- `_notify_thread_by_email` drops every recipient of type `user`, so **internal users never receive e-mail from records**, including follower invitations. Portal and customer recipients still receive mail when they are explicit recipients;
- every internal user is forced to `notification_type = inbox` (on install, on user creation and on relevant writes); share users are forced back to `email`.

System e-mails (password reset, signup, mass mailing) are untouched. A customer receives mail only when an operator explicitly sends a Message, or through the guest invitation and digest.

Core behaviours that are **not** suppressed and that the administrator should know about are listed in the [admin guide](admin-guide.md#what-standard-behaviour-is-not-changed).

---

## 6. Field subscriptions and the personal Changes channel

### 6.1 Subscription

`mail.field.subscription` holds one row per `(user, res_model, res_id)` with the set of subscribed `ir.model.fields`. Rules:

- subscriptions are personal and per record; by default nobody is subscribed to anything;
- a user may subscribe without being a channel member, and a member is subscribed to nothing until they choose;
- the subscription wizard, opened by the **Changes** button of the chatter, prefills the fields with `tracking=True` on first use; the user's choice then takes precedence;
- fields hidden from the user by `groups=` are not offered. Service fields (`message_*`, `activity_*`, `create_*`, `write_*`, …) are excluded. Note that the wizard currently offers every stored field, while only tracked fields ever produce a change (see roadmap).

### 6.2 Recording

A write produces one collapsed change message, as standard tracking does. At create time the module links it to the record channel (if any) and to the Changes channel of every user whose subscription on that record intersects the changed fields. The author is treated like everyone else. The owner of each affected Changes channel receives the bus event `streams.changes/updated`.

### 6.3 The Changes feed

The Changes channel replaces the Discuss content area with its own feed:

- one item per **source record**, sorted by the latest change, name clickable;
- inside, up to 20 changes with "field: old → new", showing **only the fields the user subscribed to** (filtered at read time, no per-user copies);
- the unread counter counts **records**, not changes;
- items are marked read by scrolling past them;
- cursor pagination with a **Load More** button.

### 6.4 Access loss

The feed and the counter re-check, as the real user, that each source record is still readable. Records the user lost access to disappear retroactively; the link is kept, so they return when access is restored. Deleted records drop out, but their subscriptions are not garbage-collected.

---

## 7. Priority notifications (`mail.notify`)

Notifications are **not** `mail.message`: they are never in the chatter, never in record channels, never e-mailed. They are in-app only.

**Model.** `mail.notify` holds author, HTML body, attachments, an optional voice attachment with duration, a transcript with its state (`none` / `queued` / `done` / `failed`), an optional source record with a snapshot of its name, `is_sticky`, `timeout` (seconds, default from settings, clamped to 3–300), and `parent_id` for reply chains. `mail.notify.recipient` holds one row per recipient with `read_date` and `popup_shown`.

**Sending.** From the chatter or channel of a record (the notification links to it), or from the Notifications channel without a record. Recipients are any active internal users. A voice note forces `is_sticky`.

**Voice and transcription.** Audio is stored as `ir.attachment` (whitelisted mimetypes, at most 25 MB and 5 minutes). If an OpenAI key is configured, a `queue_job` transcribes it in the background; the text arrives through the bus and is shown under the player. Without a key, or on failure, the audio stays without text. A 5-minute cron re-queues stuck jobs.

**Delivery.** Bus events `streams.notify/new`, `/update`, `/counter`. Transient popups close after `timeout`; sticky ones stack with a pager. A sound plays for every notification (main browser tab only, muteable per user). Popups that accumulated while the user was offline are delivered at the next login (up to 20, no older than 7 days).

**Notifications channel.** A personal channel with **Received** and **Sent** boxes. Sent shows every recipient with their read time. A notification counts as read when it has been scrolled into view; the systray counter and the channel badge are the same number.

**Replies.** A reply goes to the author of the parent only, inherits sticky/timeout as defaults, and chains are unlimited.

---

## 8. Guest access for customers

Inviting a customer is a **rare, deliberate action** for one discussion, not a permanent chat mode. The Odoo portal is not used; the module has its own public controller.

### 8.1 Model

`mail.channel.external.participant` (named for future transports; the only `transport` today is `link`) ties a `res.partner` (a person, not a company, not an internal user) to a record channel. It holds the one-time link token, the session token and expiry, `history_from`, `is_link_consumed`, `active`, `last_seen`, `last_digest_sent`, the e-mail anchor message and the inviting user. All secrets are restricted to the system group.

### 8.2 Invitation

The **Invite** wizard, available in the chatter and in the channel header:

- accepts several contacts; **each contact gets their own link**;
- has a **"show history from"** datetime (default: now) that can be moved back;
- optionally e-mails the invitation (in the partner's language);
- always displays the links for manual delivery, with a copy button;
- warns that the guest will see all comments and messages from that moment;
- lists existing accesses with **Revoke**;
- warns when no catchall alias is configured (e-mail replies would not route).

### 8.3 Access mechanics

- The link is **one-time**. A GET shows a confirmation page and does not burn the token (mail scanners click links). A POST on **Enter chat** exchanges the token for a session cookie (`sgsid`, HttpOnly, SameSite=Lax, path `/streams`).
- Session lifetime is a setting (default 7 days) and slides on use.
- There is no authentication: identity is the contact the link was issued to. Everything the guest writes is posted on the record as that contact.
- **No recovery.** An expired or lost link is not renewed; a leaked link is guaranteed to stop working. Revocation and channel archiving kill access immediately.

### 8.4 What the guest sees and can do

Sees: comments, messages (including their own), their attachments, the member list (employees by name, other externals flagged), history from `history_from`. Does **not** see: notes, changes, activities, the autolog, "other" messages.

Can: post text and files (at most 10 attachments, 10,000 characters), react with a fixed palette of 7 emoji, edit and delete their own messages within a window (default 2 minutes; deletion turns the message into a note prefixed "Deleted by the customer:"). Backend links inside message bodies are rewritten or removed.

### 8.5 Guest page

A standalone HTML page without the Odoo web client: polling every 10 seconds (setting), paused while the tab is hidden. Polling doubles as the presence heartbeat.

### 8.6 Hourly digest and e-mail replies

An hourly cron finds active link participants who are **absent** (no heartbeat within the presence timeout) and who have new visible messages from other authors since the last digest. It sends a short e-mail **without message content**; if the old link was already consumed, a new link is issued with the same `history_from`, and the existing session stays valid.

Invitation and digest mails carry the record's catchall `reply_to` and `References` to an anchor message on the channel, so a reply by ordinary e-mail is routed by the core mail gateway onto the record as a **message**, visible to the guest and to the channel.

---

## 9. Activities

Each `mail.activity` event produces a synthetic **activity** message on the record and in the channel: scheduled, rescheduled (deadline change), reassigned, cancelled, and done (the core "activity done" message is re-subtyped, so it keeps feedback and attachments). The author is the acting user, or OdooBot when the action ran as superuser (cron, server action). Activity messages notify nobody by themselves; they count as unread in the channel and are a channel-creation trigger. Activities can be scheduled from the chatter and from the channel header.

---

## 10. Virtual partner chatter

The chatter of `res.partner` is an **aggregator**: it shows the messages of every record linked to the contact (leads, orders, invoices, pickings, tasks, …). Aggregation is a projection, not a copy; messages keep their `model`/`res_id`.

**Scopes** (header segment on the partner chatter, persisted per user in `res.users.settings.streams_partner_scope`, default *Related*):

| Scope | Shows |
|---|---|
| Direct | only messages of the partner record itself |
| Related | Direct plus messages of every record where this contact is the partner |
| Company | Related for every contact of the commercial entity; hidden for a person without a company |

**Registry.** `streams.partner.source` maps a model to its partner field (Settings › Technical › Email › Partner Feed Sources). Seeded once per database for the installed models among `crm.lead`, `sale.order`, `purchase.order`, `account.move`, `stock.picking`, `project.task` × `partner_id`. Changing the registry rebuilds the SQL view `streams_partner_message` (message_id, partner_id, commercial_partner_id). Rows the administrator deleted are never re-seeded.

**Rules.** No sudo: users see only messages of records they may read, and the server over-fetches after ACL to fill a page. Virtual **changes** and "other" messages are excluded; the partner's own changes follow the usual filters. Each virtual message carries a clickable "on <record>" link. Aggregation does not touch unread counters, the partner's own record channel, followers or field subscriptions. Posting from the partner chatter posts on the partner, as standard. If the view is missing the chatter degrades to Direct and logs an error.

The `/mail/thread/messages` route is overridden for `res.partner` so that opening a partner does not mark needaction messages of *other* records as done.

---

## 11. Web client

The client is OWL 2 patches over the Odoo 19 mail Store (`static/src/**`, bundled into `web.assets_backend`; the guest page is excluded and loaded by plain `<script>`). The Odoo 15 client in `static/legacy15/` is not bundled and is kept only as a reference.

**Record chatter.** The composer is **always open** in comment mode with the placeholder "Post an internal comment…". The footer has **Send** (comment) and **Note** (same text as a note; Alt+M / Alt+Shift+M). The topbar has **Message** (full external composer with `streams.mt_message`), **Notify**, **Changes**, **Invite** and the core Schedule Activity. The "To:" recipients row is hidden and no recipients are auto-suggested. The chatter has no stream filters: it shows everything.

**Discuss.** Record channels appear in a **Messages** category (sorted by last activity, hidden when empty, fold state persisted). Channel header actions: Open Record (also in the sidebar mini-menu), Streams (filter panel with five toggles, Changes off by default), Notify, Invite customer, Schedule activity. The composer offers a Comment/Note toggle and Send Message. A link "Open <record>" sits under the start of the channel.

**Changes and Notifications channels** replace the Discuss content area with their own feeds (see §6.3 and §7). The systray bell left of the Discuss icon opens the Notifications channel.

Client-server contract (Store keys and RPC entry points) is listed in the [admin guide](admin-guide.md#rpc-and-bus-contract).

---

## 12. Invariants

Any change to the module must preserve these:

1. The chatter and the record channel are two projections of one set of `mail.message` (m2m `stream_channel_ids`), never two stores.
2. Following is explicit only; followers are internal users only; members ⇄ followers are synchronised in both directions (guard context `streams_sync`).
3. Internal users never receive e-mail from records.
4. `change` messages never affect unread counters, never create a channel and are never broadcast on the bus.
5. Projections are delivered only to members who can read the source record; the partner feed and the Changes feed re-check access on every read.
6. Guests see comments and messages only, never notes, changes, activities or "other".
7. Notifications are not messages: never in the chatter, never in a channel's message list, never e-mailed.

---

## 13. Decisions that shaped the design

- **Odoo 19 is the only target** (2026-08-18). The module started on Odoo 15 and was ported in phase 5; the 15 code is dead. No data is migrated from the 15 database.
- **Server-side filtering** (phase 8): filters moved from the 15 client into `_message_fetch`, so every client, mobile included, gets the same semantics.
- **System autolog is a change** (2026-08-20): "Lead created" and similar core posts behave like field changes; "other" is reduced to `user_notification` and foreign-subtype comments.
- **Always-open composer, Send + Note** (2026-08-19): replaced the Comment/Note topbar buttons, which did not fit the side chatter layout.
- **External participant, not guest link** (amendment to the original spec): the model is named for the participant so a future Telegram transport can reuse it; digest rules look at the transport.
- **Partner feed as a plain SQL view**: materialisation only if pages exceed roughly 300 ms on a production copy.
- **Send Message reuses the core full composer** with our subtype; a bespoke external-message form is deferred.
