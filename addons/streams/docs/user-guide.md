# Streams — User Guide

This guide is for employees (internal users) working in Odoo with the Streams module installed. The last section is for customers who received a chat link. Concepts and rules are explained in [concept.md](concept.md); setup is in [admin-guide.md](admin-guide.md).

---

## 1. The five streams in one sentence each

| Stream | Use it for | Who sees it |
|---|---|---|
| **Comment** | Talking to colleagues about this record | Colleagues; invited customers too |
| **Note** | A private remark, for yourself and colleagues, without following the record | Colleagues only |
| **Message** | E-mail to or from a customer | Colleagues; invited customers too |
| **Change** | Nothing to write: tracked field changes and system log lines land here automatically | Colleagues |
| **Activity** | Nothing to write: scheduled, rescheduled, reassigned, cancelled and done activities land here automatically | Colleagues |

**Priority notifications** are a separate thing (section 6). They never appear in the chatter.

---

## 2. Working in the chatter of a record

The composer is **always open** on any saved record. Type your text and choose how to send it:

- **Send** (Alt+M) posts a **comment**. You become a follower of the record if you were not one already.
- **Note** (Alt+Shift+M) posts the same text as a **note**. You do not become a follower.

After sending, the composer clears and stays open. Use `@name` in a note or comment to notify a specific colleague; mentions are the only way a note notifies anyone.

The chatter topbar has four extra buttons (they appear once the record is saved):

| Button | What it does |
|---|---|
| **Message** | Opens the full e-mail composer (templates, attachments, recipients). This is the only way to e-mail a customer from a record |
| **Notify** | Sends a priority notification about this record (section 6) |
| **Changes** | Chooses which field changes you want in your personal Changes feed (section 5) |
| **Invite** | Gives a customer access to the record's chat by a personal link (section 7) |

The core **Schedule Activity**, attachments and followers controls work as usual.

Things that are different from standard Odoo:

- There is no "To:" row and nobody is added as a recipient automatically. Customers never get mail unless you use **Message**.
- Nobody is subscribed automatically: not you when you create a record, not the person set as responsible, not the customer. Followers are only those who commented, sent a message, or were added by hand. Only employees can be followers; a customer cannot be added.
- You will never receive e-mail about records. Everything is in Odoo: the chatter, Discuss, the Changes feed and notifications.
- The chatter shows all streams, including changes, as before. Filtering by stream is available in Discuss (section 3).

### 2.1 The chatter of a contact

On a contact (`res.partner`) the chatter can aggregate the messages of all records linked to that contact. A segment in the topbar switches the scope:

- **Direct**: only what was written on the contact itself.
- **Related** (default): Direct plus the messages of every lead, order, invoice, picking or task where this contact is the partner.
- **Company**: Related for every contact of the same company. Hidden for a private person without a company.

Each aggregated message carries an "on <record>" link that opens the source record. You only see messages of records you may read. Your choice is remembered. Writing in the contact's composer always posts on the contact itself.

---

## 3. Record channels in Discuss

As soon as somebody comments on a record, writes a note, exchanges an e-mail with the customer, schedules an activity, or invites a customer, the record gets a channel in Discuss. It appears in the sidebar under **Messages**, named like the record (for example `S00025`), and holds the full history of the record. Only followers of the record are members; joining or leaving the channel is the same as following or unfollowing the record.

Channel header actions:

| Action | What it does |
|---|---|
| **Open Record** | Opens the source record. Also available in the channel's mini-menu in the sidebar, and as a link at the top of the channel history |
| **Streams** | Opens the filter panel: toggles for Comments, Notes, Customers, Changes, Activities. Changes is off by default. The setting is yours and is remembered per channel |
| **Notify** | Priority notification about the record |
| **Invite customer** | Same as Invite in the chatter |
| **Schedule activity** | Same as in the chatter |

Composer: the **Comment / Note** toggle at the left of the composer chooses the stream of what you type next (the choice is kept until you reload the page). **Send Message** opens the full e-mail composer for the record. Whatever you write in the channel is posted on the record itself; the channel just shows it.

Unread badges count comments, notes, customer messages and activities from other people. Field changes never make a channel unread.

---

## 4. Field changes

Changes to tracked fields and system log lines ("Record created", "Lead created") are the **Changes** stream. In the chatter they look exactly like standard Odoo tracking. In a channel they are hidden until you switch the Changes filter on.

---

## 5. Your personal Changes feed

If you want to be told when specific fields of specific records change, subscribe to them:

1. Open the record and click **Changes** in the chatter topbar.
2. The dialog proposes the record's tracked fields on first use. Tick or untick anything you like and click **Save**. **Unsubscribe** removes your subscription for this record.

You do not have to be a follower of the record, and being a follower subscribes you to nothing.

Your subscriptions feed a personal channel named **Changes** in the Discuss sidebar (in the Channels group):

- one card per record, the most recently changed on top, record name clickable;
- each card lists "field: old value → new value" for **the fields you subscribed to** only, even if more fields changed in the same write;
- your own changes appear too;
- the unread counter counts **records**, not individual changes; cards are marked read as you scroll past them;
- **Load More** at the bottom fetches older cards.

If you lose access to a record, its card disappears; it comes back if access is restored.

---

## 6. Priority notifications

A notification is for "look at this now": it pops up on the recipient's screen, plays a sound, can carry files and a voice message, and shows you who has read it and when. It is never e-mailed and never appears in any chatter.

### 6.1 Sending

Click **Notify** in a record's chatter or channel (the notification links to the record), or open the **Notifications** channel and click **New notification** (no record). In the dialog:

- **Recipients**: start typing a colleague's name; several recipients are allowed.
- **Message**: plain text.
- **Attachments**: any files.
- **Record voice**: records from your microphone; stop, listen, remove. A voice note forces *sticky*.
- **Sticky**: the popup stays until the recipient closes it. When unticked, a **Timeout** field (seconds, 3–300, default set by the administrator) decides when the popup disappears on its own.

### 6.2 Receiving

Popups appear at the bottom right. Transient popups close after their timeout (hovering pauses the timer). Sticky popups stack; use the ‹ N / M › pager to move between them and × to close one. Every popup has a **Reply** button. Notifications that arrived while you were logged out pop up at your next login.

The bell in the top bar, left of the Discuss icon, shows your unread count and opens the **Notifications** channel.

### 6.3 The Notifications channel

In Discuss, under Channels. Two tabs:

- **Received**: your notifications, unread ones highlighted. Scrolling a card into view marks it read. Each card shows the author, time, record link, text, voice player and transcript (if the administrator enabled transcription), and attachments.
- **Sent**: what you sent, with each recipient marked "Read at <time>" or "Unread".

The speaker icon in the header mutes or unmutes the notification sound for you.

### 6.4 Replying

**Reply** answers the author only. Sticky and timeout default to the original's values and can be changed. You can reply to a reply; there is no limit on the chain, so files can be exchanged this way.

---

## 7. Inviting a customer into a record's chat

Inviting a customer is meant for a specific discussion, not as a permanent channel. The customer gets a web page with the chat; no Odoo login and no portal is involved.

1. On the record (or in its channel) click **Invite**.
2. Pick one or more **contacts** (persons, not companies). Each gets their own link.
3. **Show history from** defaults to now. Move it back to let the customer read earlier comments and messages.
4. Tick **Send invitation by e-mail** if the contact has an address. The wizard warns if replies by e-mail cannot be routed; ask your administrator.
5. Click **Invite**. The wizard shows each link with a copy button; you can paste it into a messenger if there is no e-mail.
6. The same wizard lists everyone who already has access to this chat, with **Revoke**.

What the customer will see: all **comments** and **messages** from the chosen moment on, their attachments, and the list of participants (employee names as they are). Notes, changes and activities stay hidden. Keep private remarks in notes.

Rules to remember:

- The link works **once**. The customer opens the page, presses **Enter chat**, and from then on their browser keeps a session (7 days by default, extended on use). If they lose the link or the session expires, there is no recovery: issue a new invitation.
- Revoking, or archiving the record, cuts access immediately.
- Anything the customer writes appears on the record and in the channel as a **message** from that contact. If the customer replies to the invitation or digest e-mail instead, the reply is routed to the record the same way, and you are subscribed to the record as the inviter.
- A customer who is away gets at most one short e-mail per hour saying there are new messages, with a fresh link. The e-mail never contains the messages themselves.

---

## 8. For customers: using the chat page

You received a link to a chat about a document (an order, an invoice, a request). How it works:

1. Open the link. You see the company name and the chat's name. Click **Enter chat**. The link is now used up; your browser remembers you for about a week, longer if you keep using the chat.
2. Read the conversation. You see the team's comments and messages from the moment you were invited (or earlier, if the team chose so). Attachments are downloadable.
3. Write in the box at the bottom and press **Enter** to send (Shift+Enter for a new line). **Attach** adds files. You can edit or delete your own message for two minutes after sending; the buttons disappear afterwards. You can react to a message with one of the offered emoji.
4. The page refreshes itself every few seconds while it is open.
5. If the page says the chat is no longer active, your access has ended or expired. Ask your contact at the company for a new link, or reply by e-mail; e-mail replies reach the same conversation.

If you lose the link, do not search for it: it cannot be reused anyway. Ask for a new one.
