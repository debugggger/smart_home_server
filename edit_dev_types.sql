-- Обновляем существующие записи и добавляем новые
DO $$
DECLARE
    record_data jsonb;
    json_data jsonb;
    inserted_count integer := 0;
    updated_count integer := 0;
BEGIN
    -- Создаем временный JSON с данными
    json_data := pg_read_file('D:/smart-home26/smart_home_server/init/device_types.json')::jsonb;

    -- Проходим по каждому элементу
    FOR record_data IN SELECT * FROM jsonb_array_elements(json_data)
    LOOP
        -- Проверяем наличие обязательного поля name
        IF NOT (record_data ? 'name') OR record_data->>'name' IS NULL OR record_data->>'name' = '' THEN
            RAISE NOTICE 'Пропущен элемент без поля "name" или с пустым именем';
            CONTINUE;
        END IF;

        -- Проверяем, существует ли запись
        IF EXISTS (SELECT 1 FROM public.device_types WHERE name = record_data->>'name') THEN
            -- Обновляем существующую запись
            UPDATE public.device_types 
            SET 
                description = COALESCE(record_data->>'description', description),
                param_names = record_data->'param_names'
            WHERE name = record_data->>'name';
            
            updated_count := updated_count + 1;
            RAISE NOTICE 'Обновлена запись: %', record_data->>'name';
        ELSE
            -- Вставляем новую запись
            INSERT INTO public.device_types (name, description, param_names)
            VALUES (
                record_data->>'name',
                COALESCE(record_data->>'description', ''),
                record_data->'param_names'
            );
            
            inserted_count := inserted_count + 1;
            RAISE NOTICE 'Добавлена новая запись: %', record_data->>'name';
        END IF;
    END LOOP;

    -- Итоговая информация
    RAISE NOTICE '========================================';
    RAISE NOTICE 'Обновление завершено.';
    RAISE NOTICE 'Обновлено: % записей', updated_count;
    RAISE NOTICE 'Добавлено: % записей', inserted_count;
    RAISE NOTICE '========================================';
END $$;

-- Проверяем результат
DO $$
DECLARE
    total_count integer;
BEGIN
    SELECT COUNT(*) INTO total_count FROM public.device_types;
    RAISE NOTICE 'Всего записей в таблице device_types: %', total_count;
END $$;