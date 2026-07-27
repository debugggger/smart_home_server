-- Обновляем существующие записи и добавляем новые
DO $$
DECLARE
    record_data jsonb;
    json_data jsonb;
    inserted_count integer := 0;
    updated_count integer := 0;
BEGIN
    -- Создаем временный JSON с данными
    json_data := '[
  {
    "name": "serv",
    "description": "server",
    "param_names": {
      "display_name": "сервер",
      "device_params":{},
      "reading_commands":[],

      "sending_commands":
      {
        "numeric": [
              {
                 "display_name": "Прибавить значение",
               "system_name": "addValue",
                "sending_name": "changeVal/plus",
                "dataType": "intT"
               },
               {
                 "display_name": "Вычесть значение",
               "system_name": "minusValue",
                "sending_name": "changeVal/minus",
                "dataType": "intT"
               }
        ],
            "binary": [

              ]
        }
    }
  },
  {
    "name": "btn",
    "description": "button",
    "param_names": {
      "display_name": "кнопка",
      "device_params":
      {
        "port": "порт подключения"
      },
      "reading_commands":[
        {
          "display_name":"Состояние кнопки",
          "system_name":"btnGetState",
          "parameter_number":0,
          "returning_values":[
          {
            "0":{"description":"Удержание"},
            "1":{"description":"Одиночное нажатие"},
            "2":{"description":"Двойное нажатие"},
            "3":{"description":"Длинное нажатие"},
            "4":{"description":"Отпущена"}
          }
          ]
        }
      ],
      "sending_commands":{
        "numeric":[],
        "binary":[]
      }

    }
  },
  {
    "name": "binOut",
    "description": "any binary out",
    "param_names": {
      "display_name": "двоичный выход",
      "device_params":
      {
        "port": "порт подключения"
      },
      "reading_commands":[
        {
          "display_name":"Состояние выхода",
          "system_name":"binOutGetState",
          "parameter_number":0,
          "dataType": "boolT",
          "returning_values":[
          {
            "0":{"description":"Выключен"},
            "1":{"description":"Включен"}
          }
          ]
        }
      ],
      "sending_commands":{
        "numeric":[],
        "binary":[
          {"display_name":"Переключить","system_name":"toggleBinOut","sending_name":"toggle"},
          {"display_name":"Включить","system_name":"setHighBinOut","sending_name":"setHigh"},
          {"display_name":"Выключить","system_name":"setLowBinOut","sending_name":"setLow"}
        ]
      }
    }
  },
  {
    "name": "bin",
    "description": "binary input",
    "param_names": {
      "display_name": "двоичный вход",
      "device_params":
      {
        "port": "порт подключения"
      },
      "reading_commands":[
        {
          "display_name":"Состояние входа",
          "system_name":"binGetState",
          "parameter_number":0,
          "returning_values":[
          {
            "0":{"description":"Высокий уровень"},
            "1":{"description":"Низкий уровень"},
            "2":{"description":"Переход в высокий уровень"},
            "3":{"description":"Переход в низкий уровень"}
          }
          ]
        }
      ],
      "sending_commands":{
        "numeric":[],
        "binary":[]
      }
    }
  },
  {
    "name": "aht",
    "description": "aht20 sensor",
    "param_names": {
      "display_name": "датчик температуры и влажности",
      "device_params":
      {
        "port": "порт подключения SDA",
        "port2": "порт подключения SCL"
      },
      "reading_commands":[
      {
        "display_name":"Температура",
        "system_name":"ahtGetTemp",
        "parameter_number":0,
        "returning_values":[]
      },
      {
        "display_name":"Влажность",
        "system_name":"ahtGetHum",
        "parameter_number":1,
        "returning_values":[]
      }
      ],
      "sending_commands":{
        "numeric":[],
        "binary":[]
      }
    }
  },
  {
    "name": "led",
    "description": "smart led sensor",

    "param_names": {
      "display_name": "адресная светодиодная лента",
      "device_params":
      {
        "port": "порт подключения",
        "led count": "число светодиодов"
      },
      "reading_commands":[
        {
          "display_name":"Состояние входа",
          "system_name":"binGetState",
          "parameter_number":0,
          "returning_values":[
          {
            "0":{"description":"Высокий уровень"},
            "1":{"description":"Низкий уровень"},
            "2":{"description":"Переход в высокий уровень"},
            "3":{"description":"Переход в низкий уровень"}
          }
          ]
        }
      ],
      "sending_commands":{
        "numeric":[],
        "binary":[]
      }
    }
  },
  {
    "name": "stepper",
    "description": "stepper motor",
    "param_names": {
      "display_name": "шаговый двигатель",
      "device_params":
      {
        "port": "порт подключения EN",
        "port2": "порт подключения STEP",
        "port3": "порт подключения DIR"
      },
      "reading_commands": [],
      "sending_commands":
      {
        "numeric": [
              {
                 "display_name": "Скорость",
               "system_name": "speedStepper",
                "sending_name": "setSpeed",
                "dataType": "intT"
               },
               {
                 "display_name": "Направление",
               "system_name": "dirStepper",
                "sending_name": "setDir",
                "dataType": "boolT"
               }
              ],
            "binary": [

              ]
        }
    }
  },
  {
    "name": "analog",
    "description": "analog input",
    "param_names": {
      "display_name": "аналоговый вход",
      "device_params":
      {
        "port": "порт подключения"
      }
    }
  },
  {
    "name": "micro",
    "description": "smart led sensor",
    "param_names": {
      "display_name": "микрофон",
      "device_params":
      {
        "port": "порт подключения"
      }
    }
  }

]'::jsonb;

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