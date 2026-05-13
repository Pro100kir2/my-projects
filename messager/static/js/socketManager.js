// WebSocket менеджер для сигнализации звонков
class SocketManager {
    constructor() {
        this.socket = null;
        this.userId = null;
        this.callbacks = {};
        
        // Колбэки для звонков
        this.onCallIncoming = null;
        this.onCallAccepted = null;
        this.onCallDeclined = null;
        this.onCallEnded = null;
    }
    
    async connect(token) {
        try {
            // Пробуем подключиться к WebSocket
            const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
            const wsUrl = `${protocol}//${window.location.host}/ws?token=${token}`;
            
            this.socket = new WebSocket(wsUrl);
            
            this.socket.onopen = () => {
                console.log('WebSocket connected');
                this.emit('connected');
            };
            
            this.socket.onmessage = (event) => {
                try {
                    const data = JSON.parse(event.data);
                    this.handleMessage(data);
                } catch (error) {
                    console.error('Error parsing WebSocket message:', error);
                }
            };
            
            this.socket.onclose = () => {
                console.log('WebSocket disconnected');
                this.emit('disconnected');
                
                // Попытка переподключения через 5 секунд
                setTimeout(() => {
                    if (this.userId) {
                        this.connect(token);
                    }
                }, 5000);
            };
            
            this.socket.onerror = (error) => {
                console.error('WebSocket error:', error);
                this.emit('error', error);
            };
            
        } catch (error) {
            console.error('Failed to connect WebSocket:', error);
        }
    }
    
    handleMessage(data) {
        console.log('WebSocket message received:', data);
        
        // Обработка сообщений о звонках
        switch (data.type) {
            case 'call_request':
                if (this.onCallIncoming) {
                    this.onCallIncoming({
                        from_user_id: data.from_user_id,
                        from_user_name: data.from_user_name,
                        room_name: data.room_name,
                        is_video: data.is_video
                    });
                }
                break;
                
            case 'call_accepted':
                if (this.onCallAccepted) {
                    this.onCallAccepted({
                        from_user_id: data.from_user_id,
                        room_name: data.room_name
                    });
                }
                break;
                
            case 'call_declined':
                if (this.onCallDeclined) {
                    this.onCallDeclined({
                        from_user_id: data.from_user_id,
                        room_name: data.room_name
                    });
                }
                break;
                
            case 'call_ended':
                if (this.onCallEnded) {
                    this.onCallEnded({
                        from_user_id: data.from_user_id,
                        room_name: data.room_name
                    });
                }
                break;
                
            default:
                console.log('Unknown message type:', data.type);
        }
    }
    
    sendCallRequest(data) {
        this.send({
            type: 'call_request',
            to_user_id: data.to_user_id,
            room_name: data.room_name,
            is_video: data.is_video
        });
    }
    
    sendCallAccepted(data) {
        this.send({
            type: 'call_accepted',
            to_user_id: data.to_user_id,
            room_name: data.room_name
        });
    }
    
    sendCallDeclined(data) {
        this.send({
            type: 'call_declined',
            to_user_id: data.to_user_id,
            room_name: data.room_name
        });
    }
    
    sendCallEnded(data) {
        this.send({
            type: 'call_ended',
            to_user_id: data.to_user_id,
            room_name: data.room_name
        });
    }
    
    send(data) {
        if (this.socket && this.socket.readyState === WebSocket.OPEN) {
            this.socket.send(JSON.stringify(data));
        } else {
            console.error('WebSocket not connected');
        }
    }
    
    emit(event, data) {
        if (this.callbacks[event]) {
            this.callbacks[event].forEach(callback => callback(data));
        }
    }
    
    on(event, callback) {
        if (!this.callbacks[event]) {
            this.callbacks[event] = [];
        }
        this.callbacks[event].push(callback);
    }
    
    off(event, callback) {
        if (this.callbacks[event]) {
            this.callbacks[event] = this.callbacks[event].filter(cb => cb !== callback);
        }
    }
    
    disconnect() {
        if (this.socket) {
            this.socket.close();
            this.socket = null;
        }
        this.userId = null;
    }
}

// Создаем глобальный экземпляр
window.socketManager = new SocketManager();

// Экспортируем для использования в других модулях
if (typeof module !== 'undefined' && module.exports) {
    module.exports = SocketManager;
}
