/** @odoo-module **/

/**
 * Запись голоса для уведомлений (§12.3).
 *
 * В Odoo 15 рекордера нет вовсе (`MediaRecorder` не встречается ни в
 * `addons/`, ни в `odoo/`), поэтому пишем свой. Формат — «как записалось»:
 * первый поддерживаемый браузером контейнер, без перекодирования.
 * Рекордер доступен только в диалоге уведомления; в чаттер и канал записи
 * он сознательно не выносится.
 */

const MIME_CANDIDATES = [
    'audio/webm;codecs=opus',
    'audio/ogg;codecs=opus',
    'audio/mp4',
];

// Жёсткий стоп: лимит продукта (5 минут) и заодно лимит OpenAI по объёму.
export const MAX_VOICE_DURATION = 300;

export function isVoiceRecordingSupported() {
    return typeof MediaRecorder !== 'undefined'
        && Boolean(navigator.mediaDevices
                   && navigator.mediaDevices.getUserMedia);
}

function pickMimeType() {
    if (typeof MediaRecorder === 'undefined'
            || !MediaRecorder.isTypeSupported) {
        return '';
    }
    for (const candidate of MIME_CANDIDATES) {
        if (MediaRecorder.isTypeSupported(candidate)) {
            return candidate;
        }
    }
    return '';
}

export class VoiceRecorder {

    /**
     * @param {Object} handlers
     * @param {function} handlers.onTick  секунда записи прошла
     * @param {function} handlers.onStop  запись закончена: (Blob, seconds)
     */
    constructor(handlers) {
        this.handlers = handlers || {};
        this.duration = 0;
        this.isRecording = false;
        this._chunks = [];
        this._recorder = undefined;
        this._stream = undefined;
        this._interval = undefined;
    }

    async start() {
        if (this.isRecording) {
            return;
        }
        this._stream = await navigator.mediaDevices.getUserMedia(
            { audio: true });
        const mimeType = pickMimeType();
        this._recorder = new MediaRecorder(
            this._stream, mimeType ? { mimeType } : {});
        this._chunks = [];
        this.duration = 0;
        this._recorder.ondataavailable = event => {
            if (event.data && event.data.size) {
                this._chunks.push(event.data);
            }
        };
        this._recorder.onstop = () => {
            const type = this._recorder.mimeType || mimeType || 'audio/webm';
            const blob = new Blob(this._chunks, { type });
            this.release();
            if (this.handlers.onStop) {
                this.handlers.onStop(blob, this.duration, type);
            }
        };
        this._recorder.start();
        this.isRecording = true;
        this._interval = setInterval(() => {
            this.duration += 1;
            if (this.handlers.onTick) {
                this.handlers.onTick(this.duration);
            }
            if (this.duration >= MAX_VOICE_DURATION) {
                this.stop();
            }
        }, 1000);
    }

    stop() {
        if (!this.isRecording) {
            return;
        }
        this.isRecording = false;
        if (this._interval) {
            clearInterval(this._interval);
            this._interval = undefined;
        }
        if (this._recorder && this._recorder.state !== 'inactive') {
            this._recorder.stop();
        }
    }

    /**
     * Микрофонный трек обязательно останавливаем: иначе в браузере остаётся
     * гореть индикатор записи и после закрытия диалога.
     */
    release() {
        if (this._interval) {
            clearInterval(this._interval);
            this._interval = undefined;
        }
        this.isRecording = false;
        if (this._stream) {
            for (const track of this._stream.getTracks()) {
                track.stop();
            }
            this._stream = undefined;
        }
    }

    /**
     * Имя файла записи: дата и время, чтобы вложение было узнаваемым.
     *
     * @param {string} mimeType
     * @returns {string}
     */
    static buildFileName(mimeType) {
        const extension = (mimeType || '').includes('ogg') ? 'ogg'
            : (mimeType || '').includes('mp4') ? 'm4a' : 'webm';
        return 'voice-' + moment().format('YYYYMMDD-HHmmss') + '.' + extension;
    }
}
