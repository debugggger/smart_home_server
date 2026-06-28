-- Загрузка данных в таблицу device_types из JSON файла
-- Скрипт проверяет наличие данных и добавляет только новые записи

DO $$
DECLARE
    record_data jsonb;
    json_data jsonb;
    file_content text;
    inserted_count integer := 0;
    duplicate_count integer := 0;
BEGIN
    -- Читаем содержимое JSON файла
    BEGIN
        SELECT pg_read_file('/docker-entrypoint-initdb.d/device_types_data.json') INTO file_content;
    EXCEPTION
        WHEN OTHERS THEN
            RAISE NOTICE 'Файл device_types_data.json не найден или не может быть прочитан: %', SQLERRM;
            RETURN;
    END;

    -- Проверяем, что файл не пустой
    IF file_content IS NULL OR file_content = '' THEN
        RAISE NOTICE 'Файл device_types_data.json пуст';
        RETURN;
    END IF;

    -- Преобразуем текст в JSON
    BEGIN
        json_data := file_content::jsonb;
    EXCEPTION
        WHEN OTHERS THEN
            RAISE NOTICE 'Ошибка парсинга JSON: %', SQLERRM;
            RAISE NOTICE 'Содержимое файла: %', LEFT(file_content, 200);
            RETURN;
    END;

    -- Проверяем, что это массив (используем правильную функцию jsonb_typeof)
    IF jsonb_typeof(json_data) != 'array' THEN
        RAISE NOTICE 'Данные должны быть в формате JSON массива, получено: %', jsonb_typeof(json_data);
        RETURN;
    END IF;

    -- Проверяем, что массив не пустой
    IF jsonb_array_length(json_data) = 0 THEN
        RAISE NOTICE 'JSON массив пуст';
        RETURN;
    END IF;

    RAISE NOTICE 'Начинаем загрузку % записей в таблицу device_types', jsonb_array_length(json_data);

    -- Проходим по каждому элементу массива
    FOR record_data IN SELECT * FROM jsonb_array_elements(json_data)
    LOOP
        -- Проверяем наличие обязательного поля name
        IF NOT (record_data ? 'name') OR record_data->>'name' IS NULL OR record_data->>'name' = '' THEN
            RAISE NOTICE 'Пропущен элемент без поля "name" или с пустым именем';
            CONTINUE;
        END IF;

        -- Проверяем, существует ли уже запись с таким именем
        IF EXISTS (SELECT 1 FROM public.device_types WHERE name = record_data->>'name') THEN
            RAISE NOTICE 'Пропущена (уже существует): %', record_data->>'name';
            duplicate_count := duplicate_count + 1;
            CONTINUE;
        END IF;

        -- Вставляем данные
        BEGIN
            INSERT INTO public.device_types (name, description, param_names)
            VALUES (
                record_data->>'name',
                COALESCE(record_data->>'description', ''),
                record_data->'param_names'
            );

            inserted_count := inserted_count + 1;
            RAISE NOTICE 'Добавлена запись: %', record_data->>'name';
        EXCEPTION
            WHEN unique_violation THEN
                RAISE NOTICE 'Конфликт уникальности для: %', record_data->>'name';
                duplicate_count := duplicate_count + 1;
            WHEN OTHERS THEN
                RAISE NOTICE 'Ошибка при вставке записи %: %', record_data->>'name', SQLERRM;
        END;
    END LOOP;

    -- Итоговая информация
    RAISE NOTICE '========================================';
    RAISE NOTICE 'Загрузка завершена.';
    RAISE NOTICE 'Добавлено: % записей', inserted_count;
    RAISE NOTICE 'Пропущено (уже существовали): % записей', duplicate_count;
    RAISE NOTICE '========================================';

EXCEPTION
    WHEN OTHERS THEN
        RAISE NOTICE 'Критическая ошибка при загрузке данных: %', SQLERRM;
        RAISE;
END $$;

-- Проверяем результат
DO $$
DECLARE
    total_count integer;
BEGIN
    SELECT COUNT(*) INTO total_count FROM public.device_types;
    RAISE NOTICE 'Всего записей в таблице device_types: %', total_count;
END $$;