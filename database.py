import os
import ydb
import asyncio
import logging 

# Заводим логгер для database
logger = logging.getLogger(__name__)


YDB_ENDPOINT = os.getenv("YDB_ENDPOINT")
YDB_DATABASE = os.getenv("YDB_DATABASE")

# Драйвер и глобальный пул
# Инициализация происходит синхронно при импорте модуля
driver = ydb.Driver(
    ydb.DriverConfig(
        YDB_ENDPOINT,
        YDB_DATABASE,
        credentials=ydb.credentials_from_env_variables(),
        root_certificates=ydb.load_ydb_root_certificate(),
    )
)
# Ожидаем готовность драйвера
try:
    driver.wait(fail_fast=True, timeout=5)
    logger.info("YDB driver is ready.")
except Exception as e:
    logger.critical(f"Failed to connect to YDB driver: {e}")


# Глобальный пул
pool: ydb.SessionPool = ydb.SessionPool(driver)
logger.info("YDB SessionPool initialized.")

# Вопросы и ответы
quiz_data = [
    {
        'question': 'В каком году был запущен проект SpaceX по коммерческой доставке грузов на МКС?',
        'options': ['2015', '2010', '2012', '2008'],
        'correct_option': 2
    },
    {
        'question': 'Какая социальная сеть впервые внедрила функцию "Stories"?',
        'options': ['Instagram', 'Facebook', 'Snapchat', 'TikTok'],
        'correct_option': 2
    },
    {
        'question': 'В каком году был представлен первый коммерческий электромобиль Tesla Model S?',
        'options': ['2018', '2020', '2015', '2012'],
        'correct_option': 3
    },
    {
        'question': 'Какая страна первой легализовала использование криптовалюты в национальной экономике?',
        'options': ['Эль-Сальвадор', 'Япония', 'США', 'Мали'],
        'correct_option': 0
    },
    {
        'question': 'Какой вирус стал причиной глобальной пандемии в 2020 году?',
        'options': ['Троянский конь', 'COVID-19', 'Вирус ГРИППа', 'H1N1'],
        'correct_option': 1
    },
    {
        'question': 'Какая технология стала основной для развития "умных городов"?',
        'options': ['Блокчейн', 'Интернет вещей (IoT)', 'Искусственный интеллект', 'Дополненная реальность'],
        'correct_option': 1
    },
    {
        'question': 'Кто стал первым миллиардером, заработавшим состояние на криптовалюте?',
        'options': ['Питер Паркер', 'Сатоши Накамото', 'Чарли Шин', 'Илон Маск'],
        'correct_option': 1
    },
    {
        'question': 'В каком году состоялась первая успешная миссия по посадке робота на Марс?',
        'options': ['2016', '2018', '2024', '2021'],
        'correct_option': 3
    },
    {
        'question': 'Какое изобретение 21 века кардинально изменило подход к хранению и обмену информацией?',
        'options': ['Облачное хранилище', 'USB-накопитель', 'Блокчейн', 'SSD-диск'],
        'correct_option': 0
    },
    {
        'question': 'Какая технология обеспечивает безопасность данных с помощью шифрования и аутентификации?',
        'options': ['Блокчейн', 'Криптография', 'Искусственный интеллект', 'Облачное хранение'],
        'correct_option': 1
    }
]

# Оставляем простую версию, добавляющую $ к ключам
def _format_kwargs(kwargs):
    return {
        '$' + k: v for k, v in kwargs.items()
    }

async def execute_update_query(pool: ydb.SessionPool, query: str, **kwargs) -> None:
    def callee(session: ydb.Session):
        prepared_query = session.prepare(query)
        tx_context = session.transaction(ydb.SerializableReadWrite())
        try:
            result_sets = tx_context.execute(prepared_query, _format_kwargs(kwargs), commit_tx=True)
            return result_sets
        except Exception as e:
            tx_context.rollback()
            logger.error(f"Update query failed: {query} with params {kwargs}", exc_info=True)
            raise
    await asyncio.get_event_loop().run_in_executor(
        None, lambda: pool.retry_operation_sync(callee)
    )

async def execute_select_query(pool: ydb.SessionPool, query: str, **kwargs) -> list[dict]:
    def callee(session: ydb.Session):
        prepared_query = session.prepare(query)
        # Используем OnlineReadOnly для SELECT запросов
        tx_context = session.transaction(ydb.OnlineReadOnly())
        try:
            result_sets = tx_context.execute(prepared_query, _format_kwargs(kwargs), commit_tx=True) 
            if not result_sets:
                 logger.warning(f"Select query returned no result sets: {query} with params {kwargs}")
                 return [] # Вернуть пустой список строк, если нет наборов результатов
            # Возвращаем строки из первого набора результатов
            return result_sets[0].rows
        except Exception as e:
            # Для Readonly транзакций откат не всегда необходим, но хорошая практика
            tx_context.rollback()
            logger.error(f"Select query failed: {query} with params {kwargs}", exc_info=True)
            raise

    results_from_callee = await asyncio.get_event_loop().run_in_executor(
        None, lambda: pool.retry_operation_sync(callee)
    )

    if not isinstance(results_from_callee, list):
        logger.error(f"Unexpected non-list result from YDB select: {results_from_callee}")
        return []

    
    final_results = []
    # Проверяем, что список строк не пустой
    if results_from_callee:
        try:
             column_names = list(results_from_callee[0].keys())
             for row in results_from_callee:
                 row_dict = {}
                 for col_name in column_names:
                     # Доступ к значению по имени колонки
                     row_dict[col_name] = row[col_name]
                 final_results.append(row_dict)
        except Exception as e:
             # Логируем ошибку, если не удалось обработать строку
             logger.error(f"Failed to process YDB row: {results_from_callee[0]}", exc_info=True)
             # В случае ошибки обработки строки, возвращаем пустой список или то, что удалось собрать
             return [] 

    return final_results
