// Менеджер видеозвонков на основе LiveKit
class CallManager {
    constructor() {
        this.room = null;
        this.currentCall = null;
        this.localTracks = {};
        this.remoteParticipants = new Map();
        this.callTimer = null;
        this.callStartTime = null;
        this.isIncomingCall = false;
        this.isOutgoingCall = false;
        this.isAcceptingCall = false; // Защита от двойного нажатия
        this.localTracksEnabled = false; // Флаг для предотвращения дублирования треков

        // Звуки для звонков
        this.sounds = {
            incoming: new Audio('/static/sounds/incoming-call.mp3'),
            outgoing: new Audio('/static/sounds/outgoing-call.mp3'),
            ended: new Audio('/static/sounds/call-ended.mp3')
        };

        // Настройка звуков
        Object.values(this.sounds).forEach(audio => {
            audio.loop = true;
            audio.volume = 0.5;
        });
        this.sounds.ended.loop = false;

        this.initEventListeners();
    }

    // Инициализация после загрузки LiveKit
    static init() {
        if (typeof window.LiveKit === 'undefined') {
            console.error('LiveKit SDK не доступен');
            return;
        }

        // Создаем глобальный экземпляр
        window.callManager = new CallManager();
        console.log('CallManager инициализирован успешно');
    }

    initEventListeners() {
        console.log('CallManager: Event listeners initialized');
    }

    async initiateCall(userId, userName, isVideo = true) {
        console.log('📞 initiateCall START: userId=', userId, 'userName=', userName, 'isVideo=', isVideo);

        if (!userName) {
            console.error('📞 No userName provided');
            return;
        }

        try {
            this.isOutgoingCall = true;
            this.showOutgoingCallModal(userName, userId);

            // Воспроизводим звук исходящего звонка
            this.playSound('outgoing');

            // Создаем комнату для звонка
            const roomName = `call_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;

            // Получаем токен для комнаты
            const tokenData = await this.getLiveKitToken(roomName, 'caller');

            // Отправляем запрос на звонок через WebSocket
            console.log('📞 About to send call request...');
            this.sendCallRequest({
                to_user_id: userId,
                room_name: roomName,
                is_video: isVideo
            });
            console.log('📞 Call request sent');

            this.currentCall = {
                roomName,
                userId,
                userName,
                isVideo,
                tokenData
            };
            console.log('📞 Current call set:', this.currentCall);

        } catch (error) {
            console.error('Ошибка при инициации звонка:', error);
            this.hideAllCallModals();
            this.stopAllSounds();
            this.showNotification('Ошибка при инициации звонка', 'error');
        }
    }

    handleIncomingCall(data) {
        this.isIncomingCall = true;
        this.currentCall = {
            roomName: data.room_name,
            userId: data.from_user_id,
            userName: data.from_user_name,
            isVideo: data.is_video
        };

        // Показываем модальное окно входящего звонка
        this.showIncomingCallModal(data.from_user_name, data.from_user_id);

        // Воспроизводим звук входящего звонка
        this.playSound('incoming');
    }

    async acceptCall() {
        console.log('📞 CallManager.acceptCall called');

        // Защита от двойного нажатия
        if (this.isAcceptingCall) {
            console.log('📞 Already accepting call, ignoring...');
            return;
        }

        this.isAcceptingCall = true;

        try {
            this.stopAllSounds();
            console.log('📞 Sounds stopped');

            if (!this.currentCall) {
                console.error('📞 No current call to accept');
                return;
            }

            console.log('📞 Getting token for room:', this.currentCall.roomName);

            // Получаем токен для подключения
            const tokenData = await this.getLiveKitToken(
                this.currentCall.roomName,
                'receiver'
            );

            console.log('📞 Token received, connecting to room');

            // Подключаемся к комнате
            await this.connectToRoom(tokenData);

            console.log('📞 Connected to room');

            // Отправляем подтверждение принятия звонка
            this.sendCallAccepted({
                to_user_id: this.currentCall.userId,
                room_name: this.currentCall.roomName
            });

            console.log('📞 Call acceptance sent');

            // Показываем интерфейс звонка
            this.showCallInterface();

            console.log('📞 Call interface shown');

        } catch (error) {
            console.error('📞 Ошибка при принятии звонка:', error);
            this.showNotification('Ошибка при принятии звонка', 'error');
        } finally {
            this.isAcceptingCall = false;
        }
    }

    declineCall() {
        this.stopAllSounds();

        if (this.currentCall) {
            this.sendCallDeclined({
                to_user_id: this.currentCall.userId,
                room_name: this.currentCall.roomName
            });
        }

        this.hideAllCallModals();
        this.currentCall = null;
        this.isIncomingCall = false;
    }

    handleCallAccepted(data) {
        this.stopAllSounds();

        // Подключаемся к комнате как инициатор звонка
        if (this.currentCall && this.currentCall.tokenData) {
            this.connectToRoom(this.currentCall.tokenData);
            this.showCallInterface();
        }
    }

    handleCallDeclined(data) {
        this.stopAllSounds();
        this.hideAllCallModals();
        this.showNotification(`${this.currentCall?.userName || 'Пользователь'} отклонил звонок`, 'info');
        this.currentCall = null;
        this.isOutgoingCall = false;
    }

    handleCallEnded(data) {
        console.log('📞 handleCallEnded called with data:', data);
        this.endCall();
    }

    async getLiveKitToken(roomName, identity) {
        const response = await fetch('/api/livekit/token', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                room_name: roomName,
                user_identity: identity,
                can_publish: true,
                can_subscribe: true
            })
        });

        if (!response.ok) {
            throw new Error('Не удалось получить токен LiveKit');
        }

        return await response.json();
    }

    setupRoomEventListeners() {
        console.log('📞 Setting up room event listeners...');

        // Участник подключился
        this.room.on('ParticipantConnected', (participant) => {
            console.log('📞 Участник подключился:', participant.identity);
            this.remoteParticipants.set(participant.identity, participant);

            // Ждем немного перед публикацией треков
            setTimeout(() => {
                this.enableLocalTracks(this.currentCall.isVideo);
            }, 1000);
        });

        // Публикация трека участником
        this.room.on('TrackPublished', (publication, participant) => {
            console.log('📞 Участник опубликовал трек:', publication.kind, 'от', participant.identity);

            // Автоматически подписываемся на трек (основной способ LiveKit)
            if (!publication.isSubscribed) {
                publication.setSubscribed(true).catch(err => {
                    console.error('Не удалось подписаться на трек:', err);
                });
            }
        });

        // Трек участника подписан
        this.room.on('TrackSubscribed', (track, publication, participant) => {
            console.log('📞 Подписались на трек:', track.kind, 'от участника:', participant.identity);
            this.attachRemoteTrack(track, participant);
        });

        // Участник отключился
        this.room.on('ParticipantDisconnected', (participant) => {
            console.log('📞 Участник отключился:', participant.identity);
            this.remoteParticipants.delete(participant.identity);
        });

        console.log('📞 Room event listeners set up complete');
    }

    async connectToRoom(tokenData) {
        try {
            // Проверяем доступность LiveKit
            if (!window.LiveKit || !window.LiveKit.Room) {
                throw new Error('LiveKit SDK не загружен');
            }

            // Создаем комнату
            this.room = new window.LiveKit.Room();

            // Настраиваем обработчики событий комнаты
            this.setupRoomEventListeners();

            // Подключаемся к комнате
            await this.room.connect(tokenData.url, tokenData.token);

            // Включаем локальные треки (камеру и микрофон)
            await this.enableLocalTracks(this.currentCall.isVideo);

            // Запускаем таймер звонка
            this.startCallTimer();

            console.log('✅ Подключены к комнате:', this.room.name);
            console.log('📞 Local participant:', this.room.localParticipant.identity);
            console.log('📞 Remote participants count:', this.room.remoteParticipants.size);

        } catch (error) {
            console.error('Ошибка подключения к комнате:', error);
            this.showNotification('Ошибка подключения к комнате', 'error');
            this.endCall(); // безопасный выход
        }
    }

    async enableLocalTracks(videoEnabled = true) {
        try {
            console.log('📞 Creating local tracks...');

            // Проверяем, есть ли уже опубликованные аудио треки
            const existingTracks = this.room.localParticipant.audioTracks;
            if (existingTracks && existingTracks.size > 0) {
                console.log('📞 Audio track already exists, skipping creation');
                return;
            }

            // Проверяем флаг, чтобы избежать дублирования
            if (this.localTracksEnabled) {
                console.log('📞 Local tracks already enabled, skipping');
                return;
            }
            this.localTracksEnabled = true;

            // Включаем микрофон
            const audioTrack = await window.LiveKit.createLocalAudioTrack();
            this.localTracks.audio = audioTrack;
            this.room.localParticipant.publishTrack(audioTrack);
            console.log('📞 Audio track created and published');

            // Включаем камеру если нужно
            if (videoEnabled) {
                const videoTrack = await window.LiveKit.createLocalVideoTrack();
                this.localTracks.video = videoTrack;
                this.room.localParticipant.publishTrack(videoTrack);
                console.log('📞 Video track created and published');

                // Отображаем локальное видео
                this.attachLocalVideo(videoTrack);
            }

        } catch (error) {
            console.error('Ошибка включения локальных треков:', error);
            throw error;
        }
    }

    attachLocalVideo(videoTrack) {
        const localVideoElement = document.getElementById('localVideo');
        if (localVideoElement) {
            videoTrack.attach(localVideoElement);
        }
    }

    attachRemoteTrack(track, participant) {
        console.log('📞 Attaching remote track:', track.kind, 'from participant:', participant.identity);

        if (track.kind === 'video') {
            const remoteVideo = document.getElementById('remoteVideo');
            if (remoteVideo) {
                track.attach(remoteVideo);
                console.log('📞 Remote video attached');
            }
        } else if (track.kind === 'audio') {
            const remoteAudio = document.getElementById('remoteAudio');
            if (remoteAudio) {
                track.attach(remoteAudio);
                console.log('📞 Remote audio attached');
            }
        }
    }

    toggleAudio() {
        if (this.localTracks.audio) {
            if (this.localTracks.audio.isMuted) {
                this.localTracks.audio.unmute();
                this.updateAudioButton(false);
            } else {
                this.localTracks.audio.mute();
                this.updateAudioButton(true);
            }
        }
    }

    toggleVideo() {
        if (this.localTracks.video) {
            if (this.localTracks.video.isMuted) {
                this.localTracks.video.unmute();
                this.updateVideoButton(false);
            } else {
                this.localTracks.video.mute();
                this.updateVideoButton(true);
            }
        }
    }

    endCall() {
        console.log('📞 endCall called. Current call:', this.currentCall);

        this.stopAllSounds();
        this.stopCallTimer();

        // Отключаем локальные треки
        Object.values(this.localTracks).forEach(track => {
            if (track && track.stop) track.stop();
        });
        this.localTracks = {};

        // Отключаемся от комнаты
        if (this.room) {
            this.room.disconnect();
            this.room = null;
        }

        // Очищаем участников
        this.remoteParticipants.clear();

        // Сбрасываем флаг локальных треков
        this.localTracksEnabled = false;

        // Отправляем уведомление об окончании звонка
        if (this.currentCall) {
            this.sendCallEnded({
                to_user_id: this.currentCall.userId,
                room_name: this.currentCall.roomName
            });
        }

        // Воспроизводим звук окончания
        this.playSound('ended');

        // Скрываем интерфейс звонка
        this.hideAllCallModals();

        this.currentCall = null;
        this.isIncomingCall = false;
        this.isOutgoingCall = false;
    }

    startCallTimer() {
        this.callStartTime = Date.now();
        this.updateCallTimer();

        this.callTimer = setInterval(() => {
            this.updateCallTimer();
        }, 1000);
    }

    stopCallTimer() {
        if (this.callTimer) {
            clearInterval(this.callTimer);
            this.callTimer = null;
        }
    }

    updateCallTimer() {
        const timerElement = document.getElementById('callTimer');
        if (timerElement && this.callStartTime) {
            const duration = Math.floor((Date.now() - this.callStartTime) / 1000);
            const minutes = Math.floor(duration / 60);
            const seconds = duration % 60;
            timerElement.textContent = `${minutes.toString().padStart(2, '0')}:${seconds.toString().padStart(2, '0')}`;
        }
    }

    playSound(type) {
        if (this.sounds[type]) {
            this.sounds[type].play().catch(e => console.error('Ошибка воспроизведения звука:', e));
        }
    }

    stopAllSounds() {
        Object.values(this.sounds).forEach(audio => {
            audio.pause();
            audio.currentTime = 0;
        });
    }

    showIncomingCallModal(userName, userId) {
        this.hideAllCallModals();

        const modal = document.getElementById('incomingCallModal');
        if (modal) {
            document.getElementById('incomingCallerName').textContent = userName;
            modal.style.display = 'flex';
        }
    }

    showOutgoingCallModal(userName, userId) {
        this.hideAllCallModals();

        const modal = document.getElementById('outgoingCallModal');
        if (modal) {
            document.getElementById('outgoingCalleeName').textContent = userName;
            modal.style.display = 'flex';
        }
    }

    showCallInterface() {
        this.hideAllCallModals();

        const modal = document.getElementById('activeCallModal');
        if (modal) {
            document.getElementById('activeCallUserName').textContent = this.currentCall.userName;
            modal.style.display = 'flex';
        }
    }

    hideAllCallModals() {
        const modals = ['incomingCallModal', 'outgoingCallModal', 'activeCallModal'];
        modals.forEach(modalId => {
            const modal = document.getElementById(modalId);
            if (modal) {
                modal.style.display = 'none';
            }
        });
    }

    updateAudioButton(isMuted) {
        const button = document.getElementById('muteButton');
        if (button) {
            const icon = button.querySelector('i');
            if (isMuted) {
                icon.className = 'fas fa-microphone-slash';
                button.classList.add('muted');
            } else {
                icon.className = 'fas fa-microphone';
                button.classList.remove('muted');
            }
        }
    }

    updateVideoButton(isMuted) {
        const button = document.getElementById('videoButton');
        if (button) {
            const icon = button.querySelector('i');
            if (isMuted) {
                icon.className = 'fas fa-video-slash';
                button.classList.add('muted');
            } else {
                icon.className = 'fas fa-video';
                button.classList.remove('muted');
            }
        }
    }

    showNotification(message, type = 'info') {
        console.log(`[${type}] ${message}`);
    }

    // Методы для отправки сообщений через существующий WebSocket
    sendCallRequest(data) {
        console.log('📞 sendCallRequest called with:', data);

        if (typeof ws !== 'undefined' && ws && ws.readyState === WebSocket.OPEN) {
            const message = JSON.stringify({
                type: 'call_request',
                to_user_id: data.to_user_id,
                room_name: data.room_name,
                is_video: data.is_video
            });
            ws.send(message);
            console.log('📞 Call request sent successfully');
        } else {
            console.error('📞 WebSocket not available for call request');
        }
    }

    sendCallAccepted(data) {
        if (typeof ws !== 'undefined' && ws && ws.readyState === WebSocket.OPEN) {
            ws.send(JSON.stringify({
                type: 'call_accepted',
                to_user_id: data.to_user_id,
                room_name: data.room_name
            }));
        } else {
            console.error('WebSocket not available for call accepted');
        }
    }

    sendCallDeclined(data) {
        if (typeof ws !== 'undefined' && ws && ws.readyState === WebSocket.OPEN) {
            ws.send(JSON.stringify({
                type: 'call_declined',
                to_user_id: data.to_user_id,
                room_name: data.room_name
            }));
        } else {
            console.error('WebSocket not available for call declined');
        }
    }

    sendCallEnded(data) {
        if (typeof ws !== 'undefined' && ws && ws.readyState === WebSocket.OPEN) {
            ws.send(JSON.stringify({
                type: 'call_ended',
                to_user_id: data.to_user_id,
                room_name: data.room_name
            }));
        } else {
            console.error('WebSocket not available for call ended');
        }
    }
}

// Делаем функцию инициализации доступной глобально
window.callManagerInit = CallManager.init;