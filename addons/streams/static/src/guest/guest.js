/*
 * Гостевая страница чата (§9.5, Б2).
 *
 * Обычный vanilla-скрипт без сборки: у публичной страницы не должно быть
 * ни OWL, ни web.assets_*, ни longpolling-шины. Обновление — AJAX-поллинг
 * с паузой на скрытой вкладке; пауза и есть heartbeat присутствия (§9.5):
 * гость со свёрнутой вкладкой честно считается отсутствующим и получает
 * дайджест.
 */
(function () {
    'use strict';

    var configEl = document.getElementById('sg-config');
    if (!configEl) {
        return;
    }
    var CONFIG = JSON.parse(configEl.dataset.config || '{}');
    var initialFeed = JSON.parse(configEl.dataset.feed || 'null');

    var messagesEl = document.getElementById('sg-messages');
    var membersEl = document.getElementById('sg-members');
    var statusEl = document.getElementById('sg-status');
    var inputEl = document.getElementById('sg-input');
    var sendEl = document.getElementById('sg-send');
    var fileEl = document.getElementById('sg-file');
    var pendingEl = document.getElementById('sg-pending');
    var errorEl = document.getElementById('sg-error');

    var state = {
        messages: [],
        byId: {},
        lastId: 0,
        pending: [],
        stopped: false,
        backoff: 0,
        timer: null,
    };

    // --- транспорт ----------------------------------------------------

    function rpc(route, params) {
        return fetch(route, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                jsonrpc: '2.0',
                method: 'call',
                params: params || {},
            }),
        }).then(function (response) {
            if (response.status === 410) {
                return { error: 'gone' };
            }
            return response.json();
        }).then(function (payload) {
            if (payload && payload.error === 'gone') {
                return { error: 'gone' };
            }
            if (payload && payload.error && payload.error.data) {
                throw new Error(payload.error.message || 'rpc error');
            }
            return payload ? payload.result : null;
        });
    }

    function stopForever() {
        state.stopped = true;
        if (state.timer) {
            window.clearTimeout(state.timer);
            state.timer = null;
        }
        setStatus('This chat link is no longer active.', true);
        if (sendEl) {
            sendEl.disabled = true;
        }
        if (inputEl) {
            inputEl.disabled = true;
        }
    }

    function setStatus(text, isError) {
        statusEl.textContent = text;
        statusEl.classList.toggle('sg-status-error', !!isError);
    }

    function setError(text) {
        errorEl.textContent = text || '';
    }

    // --- отрисовка ----------------------------------------------------

    function formatDate(value) {
        if (!value) {
            return '';
        }
        // сервер отдаёт наивный UTC — превращаем в локальное время браузера
        var date = new Date(value.replace(' ', 'T') + 'Z');
        if (isNaN(date.getTime())) {
            return value;
        }
        return date.toLocaleString();
    }

    function renderMembers(members) {
        membersEl.innerHTML = '';
        (members || []).forEach(function (member, index) {
            var span = document.createElement('span');
            span.textContent = member.name + (member.is_external ? ' (external)' : '');
            if (member.is_external) {
                span.classList.add('sg-member-external');
            }
            membersEl.appendChild(span);
            if (index < members.length - 1) {
                membersEl.appendChild(document.createTextNode(', '));
            }
        });
    }

    function isEditable(message) {
        if (!message.is_own || !message.editable_until) {
            return false;
        }
        var until = new Date(message.editable_until.replace(' ', 'T') + 'Z');
        return until.getTime() > Date.now();
    }

    function renderMessage(message) {
        var wrapper = document.createElement('div');
        wrapper.className = 'sg-message' + (message.is_own ? ' sg-own' : '');
        wrapper.dataset.messageId = message.id;

        var meta = document.createElement('div');
        meta.className = 'sg-meta';
        meta.textContent = message.author + ' · ' + formatDate(message.date);
        wrapper.appendChild(meta);

        var bubble = document.createElement('div');
        bubble.className = 'sg-bubble';
        // тело уже прошло серверную санитизацию mail.message.body и
        // переписывание бэкенд-ссылок; своего HTML гость не присылает
        bubble.innerHTML = message.body || '';
        if (message.attachments && message.attachments.length) {
            var box = document.createElement('div');
            box.className = 'sg-attachments';
            message.attachments.forEach(function (attachment) {
                var link = document.createElement('a');
                link.href = '/streams/guest/attachment/' + attachment.id + '?download=1';
                link.textContent = attachment.name;
                box.appendChild(link);
            });
            bubble.appendChild(box);
        }
        wrapper.appendChild(bubble);

        var reactions = document.createElement('div');
        reactions.className = 'sg-reactions';
        (CONFIG.reactions || []).forEach(function (content) {
            var group = (message.reactions || []).filter(function (item) {
                return item.content === content;
            })[0];
            var button = document.createElement('button');
            button.type = 'button';
            button.className = 'sg-reaction' + (group && group.mine ? ' sg-mine' : '');
            button.textContent = content + (group ? ' ' + group.count : '');
            button.addEventListener('click', function () {
                toggleReaction(message, content, !!(group && group.mine));
            });
            reactions.appendChild(button);
        });
        wrapper.appendChild(reactions);

        if (isEditable(message)) {
            var actions = document.createElement('div');
            actions.className = 'sg-actions';
            var edit = document.createElement('button');
            edit.type = 'button';
            edit.textContent = 'Edit';
            edit.addEventListener('click', function () {
                startEdit(message);
            });
            var remove = document.createElement('button');
            remove.type = 'button';
            remove.textContent = 'Delete';
            remove.addEventListener('click', function () {
                deleteMessage(message);
            });
            actions.appendChild(edit);
            actions.appendChild(remove);
            wrapper.appendChild(actions);
        }
        return wrapper;
    }

    function render() {
        var atBottom = messagesEl.scrollTop + messagesEl.clientHeight
            >= messagesEl.scrollHeight - 40;
        messagesEl.innerHTML = '';
        state.messages.forEach(function (message) {
            messagesEl.appendChild(renderMessage(message));
        });
        if (atBottom) {
            messagesEl.scrollTop = messagesEl.scrollHeight;
        }
    }

    function mergeFeed(payload) {
        if (!payload) {
            return;
        }
        if (payload.members) {
            renderMembers(payload.members);
        }
        (payload.messages || []).forEach(function (message) {
            if (state.byId[message.id]) {
                var index = state.messages.indexOf(state.byId[message.id]);
                state.messages[index] = message;
            } else {
                state.messages.push(message);
            }
            state.byId[message.id] = message;
            state.lastId = Math.max(state.lastId, message.id);
        });
        state.messages.sort(function (left, right) {
            return left.id - right.id;
        });
        render();
    }

    // --- действия ------------------------------------------------------

    function refresh(full) {
        if (state.stopped) {
            return Promise.resolve();
        }
        var params = full ? {} : { after_id: state.lastId || null };
        return rpc('/streams/guest/feed', params).then(function (payload) {
            if (payload && payload.error === 'gone') {
                stopForever();
                return;
            }
            state.backoff = 0;
            setStatus('Connected');
            mergeFeed(payload);
        }).catch(function () {
            state.backoff = Math.min((state.backoff || 1) * 2, 60);
            setStatus('Reconnecting…', true);
        });
    }

    function scheduleRefresh() {
        if (state.timer) {
            window.clearTimeout(state.timer);
        }
        if (state.stopped) {
            return;
        }
        var delay = (state.backoff || CONFIG.pollInterval || 10) * 1000;
        state.timer = window.setTimeout(function () {
            if (document.visibilityState !== 'hidden') {
                refresh().then(scheduleRefresh);
            } else {
                scheduleRefresh();
            }
        }, delay);
    }

    function send() {
        var body = (inputEl.value || '').trim();
        var attachmentIds = state.pending.map(function (item) {
            return item.id;
        });
        if (!body && !attachmentIds.length) {
            return;
        }
        sendEl.disabled = true;
        setError('');
        rpc('/streams/guest/post', {
            body: body,
            attachment_ids: attachmentIds,
        }).then(function (payload) {
            sendEl.disabled = false;
            if (payload && payload.error === 'gone') {
                stopForever();
                return;
            }
            if (payload && payload.error) {
                setError('The message was not sent.');
                return;
            }
            inputEl.value = '';
            state.pending = [];
            renderPending();
            refresh();
        }).catch(function () {
            sendEl.disabled = false;
            setError('The message was not sent.');
        });
    }

    function startEdit(message) {
        var plain = document.createElement('div');
        plain.innerHTML = message.body || '';
        var current = (plain.textContent || '').trim();
        var next = window.prompt('Edit your message', current);
        if (next === null) {
            return;
        }
        next = next.trim();
        if (!next) {
            return;
        }
        rpc('/streams/guest/update', {
            message_id: message.id,
            body: next,
        }).then(function (payload) {
            if (payload && payload.error === 'gone') {
                stopForever();
                return;
            }
            if (payload && payload.error) {
                setError(payload.error);
                return;
            }
            setError('');
            refresh(true);
        });
    }

    function deleteMessage(message) {
        if (!window.confirm('Delete this message?')) {
            return;
        }
        rpc('/streams/guest/delete', { message_id: message.id }).then(
            function (payload) {
                if (payload && payload.error === 'gone') {
                    stopForever();
                    return;
                }
                if (payload && payload.error) {
                    setError(payload.error);
                    return;
                }
                setError('');
                // удалённое сообщение выпадает из гостевой выдачи, поэтому
                // ленту перезапрашиваем целиком
                state.messages = [];
                state.byId = {};
                state.lastId = 0;
                refresh(true);
            });
    }

    function toggleReaction(message, content, mine) {
        rpc('/streams/guest/reaction', {
            message_id: message.id,
            content: content,
            action: mine ? 'remove' : 'add',
        }).then(function (payload) {
            if (payload && payload.error === 'gone') {
                stopForever();
                return;
            }
            refresh(true);
        });
    }

    function renderPending() {
        pendingEl.innerHTML = '';
        state.pending.forEach(function (item) {
            var span = document.createElement('span');
            span.textContent = item.name;
            pendingEl.appendChild(span);
        });
    }

    function upload(file) {
        var form = new FormData();
        form.append('ufile', file);
        return fetch('/streams/guest/upload', {
            method: 'POST',
            body: form,
        }).then(function (response) {
            return response.json();
        }).then(function (payload) {
            if (payload.error === 'gone') {
                stopForever();
                return;
            }
            if (payload.error) {
                setError('The file was not uploaded.');
                return;
            }
            state.pending.push(payload);
            renderPending();
        }).catch(function () {
            setError('The file was not uploaded.');
        });
    }

    // --- запуск --------------------------------------------------------

    sendEl.addEventListener('click', send);
    inputEl.addEventListener('keydown', function (ev) {
        if (ev.key === 'Enter' && !ev.shiftKey) {
            ev.preventDefault();
            send();
        }
    });
    fileEl.addEventListener('change', function () {
        Array.prototype.slice.call(fileEl.files || []).forEach(upload);
        fileEl.value = '';
    });
    document.addEventListener('visibilitychange', function () {
        if (document.visibilityState !== 'hidden') {
            refresh().then(scheduleRefresh);
        }
    });

    mergeFeed(initialFeed);
    messagesEl.scrollTop = messagesEl.scrollHeight;
    // кнопки правки гаснут по таймеру локально; сервер всё равно перепроверяет
    window.setInterval(render, 15000);
    scheduleRefresh();
})();
