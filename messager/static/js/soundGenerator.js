// Генератор звуков для звонков
class SoundGenerator {
    constructor() {
        this.audioContext = new (window.AudioContext || window.webkitAudioContext)();
    }
    
    // Генерируем звук входящего звонка
    generateIncomingRing() {
        const duration = 0.8;
        const sampleRate = this.audioContext.sampleRate;
        const buffer = this.audioContext.createBuffer(1, duration * sampleRate, sampleRate);
        const data = buffer.getChannelData(0);
        
        // Создаем мелодию как в Telegram
        const frequencies = [800, 600, 800, 600, 800, 600, 800];
        const noteDuration = duration / frequencies.length;
        
        frequencies.forEach((freq, index) => {
            const startSample = Math.floor(index * noteDuration * sampleRate);
            const endSample = Math.floor((index + 0.8) * noteDuration * sampleRate);
            
            for (let i = startSample; i < endSample && i < data.length; i++) {
                const t = (i - startSample) / sampleRate;
                data[i] = Math.sin(2 * Math.PI * freq * t) * Math.exp(-t * 3) * 0.3;
            }
        });
        
        return buffer;
    }
    
    // Генерируем звук исходящего звонка
    generateOutgoingRing() {
        const duration = 1.0;
        const sampleRate = this.audioContext.sampleRate;
        const buffer = this.audioContext.createBuffer(1, duration * sampleRate, sampleRate);
        const data = buffer.getChannelData(0);
        
        // Простые гудки
        const frequency = 425;
        for (let i = 0; i < data.length; i++) {
            const t = i / sampleRate;
            if (t < 0.5) {
                data[i] = Math.sin(2 * Math.PI * frequency * t) * 0.3;
            } else {
                data[i] = 0;
            }
        }
        
        return buffer;
    }
    
    // Генерируем звук окончания звонка
    generateEndSound() {
        const duration = 0.5;
        const sampleRate = this.audioContext.sampleRate;
        const buffer = this.audioContext.createBuffer(1, duration * sampleRate, sampleRate);
        const data = buffer.getChannelData(0);
        
        // Нисходящий тон
        const startFreq = 800;
        const endFreq = 400;
        for (let i = 0; i < data.length; i++) {
            const t = i / sampleRate;
            const freq = startFreq + (endFreq - startFreq) * (t / duration);
            data[i] = Math.sin(2 * Math.PI * freq * t) * Math.exp(-t * 2) * 0.3;
        }
        
        return buffer;
    }
    
    // Создаем и воспроизводим звук
    playSound(buffer, loop = false) {
        const source = this.audioContext.createBufferSource();
        source.buffer = buffer;
        source.loop = loop;
        
        const gainNode = this.audioContext.createGain();
        gainNode.gain.value = 0.5;
        
        source.connect(gainNode);
        gainNode.connect(this.audioContext.destination);
        
        source.start();
        
        return source;
    }
    
    // Получаем Audio буферы
    getIncomingRingBuffer() {
        return this.generateIncomingRing();
    }
    
    getOutgoingRingBuffer() {
        return this.generateOutgoingRing();
    }
    
    getEndSoundBuffer() {
        return this.generateEndSound();
    }
}

// Создаем глобальный экземпляр
window.soundGenerator = new SoundGenerator();
