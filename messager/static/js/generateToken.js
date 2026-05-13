// Утилиты для работы с LiveKit токенами
class TokenManager {
    constructor() {
        this.apiBase = '/api/livekit';
    }
    
    // Генерация токена для комнаты
    async generateToken(roomName, identity, options = {}) {
        try {
            const response = await fetch(`${this.apiBase}/token`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    room_name: roomName,
                    user_identity: identity,
                    can_publish: options.canPublish !== false,
                    can_subscribe: options.canSubscribe !== false
                })
            });
            
            if (!response.ok) {
                throw new Error(`HTTP error! status: ${response.status}`);
            }
            
            return await response.json();
            
        } catch (error) {
            console.error('Ошибка генерации токена:', error);
            throw error;
        }
    }
    
    // Создание уникального имени комнаты
    createRoomName(prefix = 'room') {
        const timestamp = Date.now();
        const random = Math.random().toString(36).substr(2, 9);
        return `${prefix}_${timestamp}_${random}`;
    }
    
    // Валидация токена
    validateToken(token) {
        try {
            // Простая проверка формата JWT
            const parts = token.split('.');
            return parts.length === 3;
        } catch (error) {
            return false;
        }
    }
}

// Создаем глобальный экземпляр
window.tokenManager = new TokenManager();

// Экспортируем для использования в других модулях
export { TokenManager };