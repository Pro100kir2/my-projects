from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
import os

app = FastAPI()

app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/", response_class=HTMLResponse)
async def serve_html():
    html_content = """
<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Наша История ❤️ - Для тебя от Кирилла</title>
    <link href="https://fonts.googleapis.com/css2?family=Playfair+Display:wght@700&family=Great+Vibes&family=Poppins:wght@400;600&display=swap" rel="stylesheet">
    <style>
        * { margin:0; padding:0; box-sizing:border-box; }
        body {
            font-family: 'Poppins', sans-serif;
            background: #0d0015;
            color: #fff;
            height: 100vh;
            overflow: hidden;
            position: relative;
            cursor: pointer;
        }
        #intro {
            position: absolute;
            inset: 0;
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            text-align: center;
            z-index: 10;
            background: rgba(0,0,0,0.55);
        }
        #text-overlay {
            font-family: 'Great Vibes', cursive;
            font-size: clamp(2.8rem, 9vw, 7.5rem);
            color: #ff69b4;
            text-shadow: 0 0 35px #ff1493, 0 0 70px #c71585;
            opacity: 0;
            transform: scale(0.75);
            transition: all 2s ease;
            margin-bottom: 2rem;
            pointer-events: none;
            line-height: 1.1;
        }
        #photo-container {
            width: 90vmin;
            height: 90vmin;
            max-width: 600px;
            max-height: 600px;

            position: relative;
            border-radius: 28px;
            overflow: hidden;
            box-shadow: 0 0 90px rgba(255,105,180,0.5);
            border: 2px solid rgba(255,105,180,0.3);
        }
        .slide {
            position: absolute;
            inset: 0;
            background-size: cover;
            background-position: center;
            opacity: 0;
            transform: scale(1.08) translateY(20px);
            transition: opacity 2.4s ease, transform 5s ease;
        }
        .slide.active {
            opacity: 1;
            transform: scale(1) translateY(0);
        }
        #continue-btn {
            margin-top: 4rem;
            padding: 1.4rem 5rem;
            font-size: 1.8rem;
            font-weight: 600;
            background: linear-gradient(45deg, #ff4081, #f50057, #c51162);
            border: none;
            border-radius: 999px;
            color: white;
            cursor: pointer;
            box-shadow: 0 0 60px rgba(245,0,87,0.9);
            opacity: 0;
            transform: translateY(60px);
            transition: all 1.5s ease;
        }
        #continue-btn.visible {
            opacity: 1;
            transform: translateY(0);
        }
        #continue-btn:hover {
            transform: scale(1.12);
            box-shadow: 0 0 100px #ff1493;
        }
        .heart {
            position: absolute;
            font-size: 2.2rem;
            color: #ff69b4;
            pointer-events: none;
            animation: floatHeart 14s linear infinite;
            opacity: 0.75;
        }
        @keyframes floatHeart {
            0%   { transform: translateY(110vh) rotate(-30deg); opacity: 0; }
            15%  { opacity: 1; }
            85%  { opacity: 1; }
            100% { transform: translateY(-30vh) rotate(720deg); opacity: 0; }
        }
        #main-screen {
            display: none;
            overflow-y: auto;
            height: 100vh;
            padding: 5rem 1.5rem 8rem;
            background: linear-gradient(135deg, #1a0010, #0a0015);
        }
        h1.main-title {
            text-align: center;
            font-family: 'Playfair Display', serif;
            font-size: clamp(3.5rem, 8vw, 6rem);
            color: #ff69b4;
            margin-bottom: 4rem;
            text-shadow: 0 0 40px rgba(255,105,180,0.7);
        }
        .timeline {
            max-width: 950px;
            margin: 0 auto;
        }
        .event {
            background: rgba(255,255,255,0.07);
            backdrop-filter: blur(14px);
            border: 1px solid rgba(255,105,180,0.2);
            border-radius: 24px;
            padding: 2.5rem;
            margin: 4rem 0;
            box-shadow: 0 20px 60px rgba(0,0,0,0.6);
            transition: all 0.6s ease;
        }
        .event:hover {
            transform: translateY(-15px);
            box-shadow: 0 30px 80px rgba(255,105,180,0.35);
            border-color: rgba(255,105,180,0.45);
        }
        .event h3 {
            color: #ff69b4;
            font-size: 2rem;
            margin-bottom: 1.2rem;
        }
        .event p {
            font-size: 1.2rem;
            line-height: 1.7;
            opacity: 0.93;
        }
        .event img, .event video {
            width: 100%;
            border-radius: 16px;
            margin: 1.6rem 0 1rem;
            box-shadow: 0 10px 40px rgba(0,0,0,0.7);
        }
        #valentine-btn {
            display: block;
            margin: 6rem auto 4rem;
            padding: 1.6rem 5rem;
            font-size: 1.9rem;
            font-weight: 600;
            background: linear-gradient(45deg, #ff4081, #f50057);
            border: none;
            border-radius: 999px;
            color: white;
            cursor: pointer;
            box-shadow: 0 0 70px rgba(245,0,87,0.8);
            animation: pulse 2.5s infinite;
        }
        #valentine-btn:hover {
            transform: scale(1.12);
            box-shadow: 0 0 110px #ff1493;
        }
        @keyframes pulse {
            0%,100% { transform: scale(1); }
            50%     { transform: scale(1.07); }
        }
    </style>
</head>
<body>

    <div id="intro">
        <div id="text-overlay"></div>
        <div id="photo-container"></div>
        <button id="continue-btn">Продолжить нашу историю ❤️</button>
        
    </div>

    <div id="main-screen">
        <h1 class="main-title">От первого взгляда до навсегда</h1>

        <div class="timeline">
            <div class="event">
                <h3>1 декабря 2023</h3>
                <p>Первый наш разговор в доме родителей… тот момент, когда время остановилось, а сердце билось так громко, что казалось — слышно на всю улицу ❤️</p>
                <p>Ну и видео когда я понял что я точно по уши в тебя влюбился )</p>
                <video src="/static/video1.mp4" controls preload="metadata"></video>
            </div>

            <div class="event">
                <h3>7 декабря 2023</h3>
                <p>Начало отношений в Coffee Story. Кофе, неловкость , Perfect и я на одном колене</p>
                <img src="/static/photo-coffee.jpg" alt="Coffee Story" loading="lazy">
            </div>

            <div class="event">
                <h3>7 июля 2024</h3>
                <p>Признание в любви в деревне. Под звёздами, со слезами на глазах и самым искренним «Я люблю тебя» в моей жизни 🌌💍</p>
                <video src="/static/video-confession.mp4" controls preload="metadata"></video>
            </div>

            <div class="event">
                <h3>22 августа 2024</h3>
                <p>В нашей семье появился Персик — самый пушистый, самый наглый и самый любимый котик 💕</p>
                <img src="/static/percik-main.jpg" alt="Персик" loading="lazy">
                <img src="/static/percik-main2.jpg" alt="Персик" loading="lazy">
            </div>

            <!-- Добавляй сюда остальные события, фото, видео по аналогии -->
        </div>

        <button id="valentine-btn">Will you be my Valentine?</button>
    </div>

    <audio id="bg-music" loop preload="auto">
        <source src="/static/our-song.mp3" type="audio/mpeg">
        Your browser does not support the audio element.
    </audio>

    <script>
        // Твои 45 фото — замени пути на реальные файлы в /static/
        const photos = [
            "/static/1.jpg", "/static/2.jpg", "/static/3.jpg", "/static/4.jpg", "/static/5.jpg",
            "/static/6.jpg", "/static/7.jpg", "/static/8.jpg", "/static/9.jpg", "/static/10.jpg",
            "/static/11.jpg", "/static/12.jpg", "/static/13.jpg", "/static/14.jpg", "/static/15.jpg",
            "/static/16.jpg", "/static/17.jpg", "/static/18.jpg", "/static/19.jpg", "/static/20.jpg",
            "/static/21.jpg", "/static/22.jpg", "/static/23.jpg", "/static/24.jpg", "/static/25.jpg",
            "/static/26.jpg", "/static/27.jpg", "/static/28.jpg", "/static/29.jpg", "/static/30.jpg",
            "/static/31.jpg", "/static/32.jpg",
        ];

        const stages = [
            { text: "Вспомним как всё начиналось ...",     duration: 4000, photosCount: 4  },
            { text: "Неожиданно появилась ты ...",         duration: 5000, photosCount: 5 },
            { text: "И влюбила меня в себя ...",            duration: 6000, photosCount: 6 },
            { text: "Очаровала меня ...",                   duration: 4000, photosCount: 4  },
            { text: "Заманила меня ...",                    duration: 7000, photosCount: 7  },
            { text: "И теперь ...",                         duration:  4000, photosCount: 4  },
            { text: "Тебе не уйти ...",                     duration: 4000, photosCount: 2  }
        ];

        let currentStageIndex = 0;
        let currentPhotoIndex = 0;

        const textElement     = document.getElementById('text-overlay');
        const photoContainer  = document.getElementById('photo-container');
        const continueButton  = document.getElementById('continue-btn');
        const backgroundMusic = document.getElementById('bg-music');

        // Создаём все слайды один раз
        photos.forEach(src => {
            const slide = document.createElement('div');
            slide.className = 'slide';
            slide.style.backgroundImage = `url(${src})`;
            photoContainer.appendChild(slide);
        });

        const allSlides = document.querySelectorAll('.slide');

        function showText(content) {
            textElement.style.opacity = 0;
            textElement.style.transform = 'scale(0.7)';
            setTimeout(() => {
                textElement.textContent = content;
                textElement.style.opacity = 1;
                textElement.style.transform = 'scale(1)';
            }, 600);
        }

        function activateNextSlide() {
            if (currentPhotoIndex >= photos.length) return;
            allSlides.forEach(s => s.classList.remove('active'));
            allSlides[currentPhotoIndex].classList.add('active');
            currentPhotoIndex++;
        }

        function runStage() {
            if (currentStageIndex >= stages.length) {
                showText("Тебе не уйти ...");
                continueButton.classList.add('visible');
                return;
            }

            const stage = stages[currentStageIndex];
            showText(stage.text);

            let photosInThisStage = 0;
            const photoInterval = setInterval(() => {
                if (photosInThisStage < stage.photosCount && currentPhotoIndex < photos.length) {
                    activateNextSlide();
                    photosInThisStage++;
                } else {
                    clearInterval(photoInterval);
                    currentStageIndex++;
                    setTimeout(runStage, 2200); // пауза между этапами
                }
            }, stage.duration / Math.max(1, stage.photosCount || 1));
        }

        // Запуск анимации и музыки после первого клика по экрану
        document.body.addEventListener('click', function firstInteraction(e) {
            backgroundMusic.volume = 0.24;
            backgroundMusic.play().catch(() => console.log("Автозапуск музыки заблокирован браузером"));

            // Запускаем летающие сердечки
            setInterval(() => {
                const h = document.createElement('div');
                h.className = 'heart';
                h.textContent = ['❤️','💖','💕','💗','💘'][Math.floor(Math.random()*1)];
                h.style.left = Math.random() * 100 + 'vw';
                h.style.animationDuration = (10 + Math.random()*10) + 's';
                document.body.appendChild(h);
                setTimeout(() => h.remove(), 20000);
            }, 900);

            showText(stages[0].text);
            activateNextSlide(); // первое фото сразу

            setTimeout(runStage, stages[0].duration + 800);

            document.body.removeEventListener('click', firstInteraction);
        }, { once: true });

        // Переход на основной экран по клику на кнопку
        continueButton.addEventListener('click', () => {
            document.getElementById('intro').style.opacity = '0';
            setTimeout(() => {
                document.getElementById('intro').style.display = 'none';
                document.getElementById('main-screen').style.display = 'block';
            }, 1400);
        });

        // Кнопка Valentine (редирект в бота)
        document.addEventListener('click', e => {
            if (e.target.id === 'valentine-btn') {
                setTimeout(() => {
                    window.location.href = 'https://t.me/ForAlechkaBot?start=quest';
                }, 1800);
            }
        });
    </script>
</body>
</html>
    """
    return html_content

@app.get("/static/{file_name:path}")
async def serve_static(file_name: str):
    file_path = f"static/{file_name}"
    if os.path.exists(file_path):
        return FileResponse(file_path)
    raise HTTPException(status_code=404, detail="File not found")

@app.get("/favicon.ico")
async def favicon():
    return FileResponse("static/favicon.ico")
