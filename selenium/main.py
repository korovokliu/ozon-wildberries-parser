import re
import time
from selenium.webdriver import Chrome, ChromeOptions, DesiredCapabilities, Proxy, Keys
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from webdriver_manager.chrome import ChromeDriverManager
import csv
from datetime import datetime, timedelta
import abc # abstract base class
from bs4 import BeautifulSoup
from loguru import logger

options = ChromeOptions()
#options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/104.0.0.0 Safari/537.36")
options.add_argument("user-agent=Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/15.4 Safari/605.1.15")
options.add_argument("--disable-blink-features=AutomationControlled")


class Parser(abc.ABC):
    browser = Chrome(service=Service(ChromeDriverManager().install()), options=options)
    # автоматическая установка веб-драйвера - вручную можно передавать адрес до скачанного
    # драйвера executable_path="chromdriver.exe", но этот метод уже нежелателен:
    # "executable_path has been deprecated, please pass in a Service object"

    def __init__(self, site: str, link: str, timing: int):
        self.site = site
        self.link = link
        self.all_reviews = []
        self.fieldnames = []

    @abc.abstractmethod
    def get_data(self, link, timing):
        Parser.browser.get(link)
        time.sleep(timing)

    @abc.abstractmethod
    def _parse_data(self, source):
        ...

    @logger.catch
    @staticmethod
    def writing_in_csv(list_of_dict: list[dict], name: str, fieldnames: list, encoding="utf-8", newline="", delimiter=";"):
        print(f"Идёт запись в файл {name}")
        with open(f"{name}.csv", "a", encoding=encoding, newline=newline) as csv_file:  # Определили список заголовков столбцов
            writer = csv.DictWriter(csv_file, fieldnames=fieldnames, delimiter=delimiter)  # Подготовили дескриптор файла для записи CSV
            #if not csv_file:  # если файл создается впервые, записывается headers
            writer.writeheader()  # Записываем список словарей с данным, где ключ равен заголовку столбца
            writer.writerows(list_of_dict)


class ParserWildberries(Parser):

    def __init__(self, link, timing=2):
        print("Работает парсер Wildberries")
        self.link = link.replace("detail.aspx", "feedbacks")
        super().__init__(site="wildberries", link=self.link, timing=timing)
        self.source = ''
        self.fieldnames = ['Дата', 'Количество звезд', 'Комментарий', 'Лайки', 'Дизлайки']
        self.site = "wildberries"

    def _parse_data(self, source, timing=2):
        soup = BeautifulSoup(source, "lxml")
        for i in soup.find_all("span", class_="feedback__date hide-mobile"):
            extracted_time = i.get('content')
           # TODO: add if extracted_time == milliseconds

        date = [datetime.strptime(i.get('content'), '%Y-%m-%dT%H:%M:%SZ') + timedelta(hours=3) for i in
                       soup.find_all("span", class_="feedback__date hide-mobile")]
        stars = [int(i.get('class')[2][-1]) for i in soup.find_all("span", itemprop="reviewRating")]
        reviews = [(i.find_all("p", class_="feedback__text")[-1]).text for i in
                   soup.find_all("li", class_="comments__item feedback j-feedback-slide")]
        likes = [i.text[2] for i in soup.find_all("div", class_="vote__wrap")]
        dislikes = [i.text[5] for i in soup.find_all("div", class_="vote__wrap")]

        for review in zip(date, stars, likes, dislikes, reviews):
            self.all_reviews.append({key: value for key, value in zip(self.fieldnames, review)})

        return self.all_reviews

    @logger.catch
    def get_data(self):
        """ Т.к. счетчик количества отзывов в карточке товара Wildberries считает за новые обновленные
            (отредактированные) отзывы, то в таблице после парсинга их может оказаться меньше, чем есть на сайте.
            Здесь все данные таблицы отдельно извлекаются по своим css селекторам """
        super().get_data(link=self.link, timing=2)
        # region SCROLL DOWN
        reviews_count = super().browser.find_element(By.CSS_SELECTOR, 'p.rating-product__review span')
        scroll_iterations = int(reviews_count.text) // 10 + 1
        for _ in range(scroll_iterations):
            super().browser.execute_script("window.scrollTo(0,document.body.scrollHeight)")
            time.sleep(1.5)
        self._parse_data(super().browser.page_source)
        super().browser.close()
        super().browser.quit()
        csv_name = re.search(r"(?<=catalog/)(\d+)(?=/feedbacks)", self.link)
        Parser.writing_in_csv(list_of_dict=self.all_reviews, name=f"{self.site}-{csv_name.group(1)}",
                              fieldnames=self.fieldnames)
        return self.all_reviews


class ParserOzon(Parser):

    def __init__(self, link):
        print("Работает парсер Ozon")
        self.site = 'ozon'
        self.link = f"{link}/reviews/"
        super().__init__(site=self.site, link=self.link, timing=5)
        self.fieldnames = ['ID', 'Количество звезд', 'Дата', 'Достоинства', 'Недостатки', 'Комментарии', 'Лайки', 'Дизлайки']

    def _parse_data(self, source):
        """ Один из вариантов извлечения данных: вместо обращения к каждому отдельному атрибуту по css селекторам
            или XPath, которые могут динамически или вручную изменяться разработчиками, можно извлекать только
            текстовые данные с ID сообщения и разбивать текст с помощью регулярных выражений. Для Озон этот способ подходит,
            т.к. названия классов не имеют осмысленного названия и динмамически меняются """

        reviews_webelements = source

        all_reviews = []

        for review in reviews_webelements:
        # region assign regex comiled string
            single_review = {
                'ID': review.get_attribute("data-review-id"),
                'Количество звезд': re.compile(r'<div class=".+" style="width:(...?)%;"></div>'),
                'Дата': re.compile(r"\n(\d{1,2}\s[А-Яа-я]+\s\d{4})\n"),
                'Достоинства': '',
                'Недостатки': '',
                'Комментарии': '',
                'Лайки': re.compile(r"\nДа\s(\d+)\nНет"),
                'Дизлайки': re.compile(r"\nДа\s\d+\nНет\s(\d+)")
            }

            if "Достоинства" in review.text:
                if "Недостатки" not in review.text:
                    single_review["Достоинства"] = re.compile(r"(?<=Достоинства\n)(.*?)(?=\nКомментарий|\nВам помог этот отзыв\?)", re.DOTALL)
                else:
                    single_review["Достоинства"] = re.compile(r"(?<=Достоинства\n)(.*?)(?=\nНедостатки)", re.DOTALL)
                    single_review["Недостатки"] = re.compile(
                        r"(?<=Недостатки\n)(.*?)(?=\nКомментарий|\nВам помог этот отзыв\?)", re.DOTALL)

            if "Комментарии" in review.text:
                single_review["Комментарии"] = re.compile(r"(?<=Комментарий\n)(.*?)(?=\nВам помог этот отзыв\?)")

            else:
                single_review["Комментарии"] = re.compile(r"(?<=\d{3}\n)(.*?)(?=\nВам помог этот отзыв\?)", re.DOTALL)
        # endregion

            try:
                for key in single_review:
                    if key == 'ID':
                        continue  # Идет на след итерацию в списке
                    if key == 'Количество звезд':
                        matched = re.search(single_review[key], review.get_attribute('innerHTML'))
                        single_review[key] = int(matched.group(1)) // 20
                        # количество звезд определяется шириной элемента: 100% - 5 звезд, 80% - 4 звезды и т.д.
                    elif single_review[key] != '':
                        single_review[key] = re.search(single_review[key], review.text).group(1)

            except Exception as e:
                print(f'Ошибка в отзыве с ID: {single_review["ID"]}:\n{e}')
            else:
                all_reviews.append(single_review)
        return all_reviews


    @logger.catch
    def get_data(self, link='', timing=7):
        if link == '':
            link = self.link
        i = 1
        while True:
            super().browser.get(f"{link}/?page={i}")
            time.sleep(timing)
            try:
                reviews_webelements = super().browser.find_elements(By.CSS_SELECTOR, 'div[data-review-id]')
                if reviews_webelements:  # не пустой список
                    print(f"Парсим страницу отзывов {i}")
                    csv_name = re.search('product/(.*)/reviews', a.link)
                    list_of_page_reviews = self._parse_data(source=reviews_webelements)
                    print(f"На странице {i} количество отзывов: {len(list_of_page_reviews)}")
                    Parser.writing_in_csv(list_of_dict=list_of_page_reviews, name=f"ozon-{csv_name.group(1)}",
                                           fieldnames=self.fieldnames)
                else:
                    break

            except Exception as e:
                print(f"Произошла ошибка {e}")
                input("Нажми ENTER для продолжения ")

            i += 1


if __name__ == "__main__":
    links_ozon = [
        'https://www.ozon.ru/product/kedy-adidas-hoops-3-0-405912833'
    ]

    links_wild = [
        'https://www.wildberries.ru/catalog/9907589/detail.aspx'
    ]

    for link in links_ozon:
        a = ParserOzon(link)
        a.get_data()

    for link in links_wild:
        a = ParserWildberries(link)
        a.get_data()



    # name = re.search('product/(.*)/reviews', a.link)
    # a.writing_in_csv(self=name.group(1), list_of_dict=list_of_dicts)

# s = Service(executable_path="/path/chromedriver")
# driver = webdriver.Chrome(service=s, options=options)

# Для Озона: Дата, сколько звездочек, Достоинства, Недостатки, Комментарий, лайки/дизлайки
# Для Вайлдберриз: Дата, Сколько звездочек, Комментарий, лайки/дизлайки
#