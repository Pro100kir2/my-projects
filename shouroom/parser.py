import time
import random

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.chrome.service import Service

from config import AVITO_URL
from db import save_product


def human_sleep(a=1.0, b=3.0):
    time.sleep(random.uniform(a, b))


def setup_driver():
    options = Options()
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--start-maximized")
    options.add_argument(
        "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    )

    return webdriver.Chrome(
        service=Service(ChromeDriverManager().install()),
        options=options
    )


def scroll_page(driver):
    last_height = driver.execute_script("return document.body.scrollHeight")
    while True:
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        human_sleep(2, 4)
        new_height = driver.execute_script("return document.body.scrollHeight")
        if new_height == last_height:
            break
        last_height = new_height


def parse():
    driver = setup_driver()
    driver.get(AVITO_URL)
    human_sleep(4, 6)

    scroll_page(driver)

    items = driver.find_elements(By.CSS_SELECTOR, 'div[data-item-id]')
    print(f"Найдено товаров: {len(items)}")

    for item in items:
        try:
            title = item.find_element(By.CSS_SELECTOR, '[data-marker="item-title"]').text

            href = item.find_element(
                By.CSS_SELECTOR,
                '[data-marker="item-title"]'
            ).get_attribute("href")
            url = "https://www.avito.ru" + href

            price = item.find_element(
                By.CSS_SELECTOR,
                'meta[itemprop="price"]'
            ).get_attribute("content")
            price = int(price)

            description = item.find_element(
                By.CSS_SELECTOR,
                'meta[itemprop="description"]'
            ).get_attribute("content")

            image = item.find_element(
                By.CSS_SELECTOR,
                'img[itemprop="image"]'
            ).get_attribute("src")

            category = "Одежда / Обувь / Аксессуары"

            save_product(
                title=title,
                category=category,
                url=url,
                price=price,
                description=description,
                image=image
            )

            print(f"✔ {title} — {price}₽")
            human_sleep(1.0, 2.0)

        except Exception as e:
            print("❌ Ошибка:", e)

    driver.quit()


if __name__ == "__main__":
    parse()
