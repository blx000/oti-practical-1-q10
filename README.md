# Практическая работа № 1: локальный Lakehouse, вариант 2

**Студент:** Левченков Артемий Викторович. **Вариант:** TPC-H Q10, Returned Item Reporting. **Масштаб:** `tpch.sf1`.

Проект строит три слоя Iceberg поверх S3-совместимого хранилища: четыре полные исходные таблицы TPC-H в Bronze, две согласованные таблицы в Silver и витрину топ-20 клиентов в Gold. SQL выполняет Trino, метаданные Iceberg хранит Lakekeeper в PostgreSQL. Superset подключается к Trino и показывает Bronze.

## Требования

- Docker Desktop (проверено при лимите **4 ГБ RAM**; для запаса рекомендовано 8 ГБ), Python 3.10+ и около 15 ГБ свободного места под образы и данные.
- Свободные порты `9000`, `19001`, `8181`, `8080`, `18088`. `19001` выбран для консоли хранилища, потому что локальный `9001` занят.
- Интернет для получения контейнерных образов. TPC-H генерируется коннектором Trino, отдельный датасет скачивать не нужно.

## Запуск

Из корня проекта:

```bash
python3 scripts/setup_local.py
docker compose up -d minio postgres lakekeeper trino
docker compose run --rm minio-init
python3 scripts/setup_local.py --register
docker compose restart trino
docker compose ps
python3 scripts/run_lab.py load
python3 scripts/run_lab.py evolution
python3 scripts/run_lab.py benchmark
```

Загрузка образов при первом запуске может занять несколько минут. `setup_local.py` создаёт `.env` с паролями и `.local/catalog/` с настройками Trino. Эти локальные файлы не входят в репозиторий. При повторном запуске `load` таблицы проекта пересоздаются. Benchmark создаёт четыре отдельных набора Bronze и не меняет витрину Gold.

Superset запускается отдельно после основного бенчмарка, чтобы не конкурировать за память во время измерений:

```bash
docker compose --profile bi up -d --build superset
```

Адреса: Silo UI `http://localhost:19001`, Lakekeeper `http://localhost:8181/ui/`, Trino `http://localhost:8080`, Superset `http://localhost:18088`. Логин Silo и пароль Superset находятся только в локальном `.env`. В Superset подключить Trino через `trino://lab1@trino:8080/bronze`, затем открыть `bronze.lab.customer` в SQL Lab или создать датасет.

## Проверки и результаты

`scripts/run_lab.py load` проверяет количества строк, уникальность ключей и совпадение топ-20 витрины Gold с прямым Q10 по `tpch.sf1`. Числовые результаты, идентификатор снапшота, времена записи и чтения, а также физические размеры файлов сохраняются в [results/measurements.json](results/measurements.json). Итоги приведены в [отчёте](отчет.md). Размеры взяты из метаданных `"table$files"` текущих Iceberg-снапшотов без исторических файлов. Время запроса взято из `elapsedTimeMillis` Trino. Для каждого набора выполнен прогрев и пять измерений; в отчёте указаны медиана, минимум и максимум.

Запрос для самостоятельной проверки:

```sql
SELECT custkey, name, revenue, nation
FROM gold.lab.q10_top20_customers
ORDER BY revenue DESC, custkey;
```

Исходный вариант Q10: [sql/q10_reference.sql](sql/q10_reference.sql). Снимки и результаты проверок находятся в `evidence/`. Скриншот всего бакета Bronze включает также четыре набора бенчмарка и Iceberg-метаданные; размеры таблиц в отчёте относятся только к файлам их текущих снапшотов.

## Решения и ограничения

- Bronze хранит **все** столбцы источника. Silver оставляет необходимые поля, проверяет ключи и диапазоны цены/скидки, объединяет строки заказов и обогащает клиентов страной. Gold отвечает на один бизнес-вопрос Q10.
- Для `sf1` партиции не созданы: разбиение небольшого набора по датам увеличило бы число мелких файлов и накладные расходы каталога. Для большего масштаба стоит проверить `month(orderdate)` на Silver.
- Основной Bronze использует Parquet + GZIP, Silver — Parquet + ZSTD, Gold — Parquet + Snappy. Скорость и объём сравниваются по фактическим замерам.
- Учебный стенд не предназначен для внешнего доступа: сервисы без TLS и без промышленной модели прав. Локальные порты и секреты не публикуются в репозитории.

При развёртывании образ `quay.io/minio/minio:latest` вернул `401 Unauthorized`, поэтому для S3-хранилища используется совместимый форк [Silo (`pgsty/minio`)](https://hub.docker.com/r/pgsty/minio). Бакеты создаёт его [клиент](https://hub.docker.com/r/pgsty/mc).
