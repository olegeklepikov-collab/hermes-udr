# Классы моделей

[Главная](../../README.ru.md) · [English](../en/model-classes.md)

Класс — заданное оператором имя маршрута, а не фиксированная модель или гарантия качества. Меняйте соответствие в конфигурации своего профиля Hermes без пересборки плагина. Имена и значения ниже — примеры; замените их на доступные вашему Hermes.

```yaml
research:
  default_model_class: balanced
  model_classes:
    balanced:
      provider: your-provider-id
      model: your-current-model-id
      reasoning: medium
    advanced:
      provider: another-provider-id
      model: your-current-reasoning-model-id
      reasoning: high
```

Автономный `run_research.py` принимает `--model-class advanced`; также поддерживается `HERMES_RESEARCH_MODEL_CLASS`. Без таблицы классов используется явно заданная модель Hermes. Неверная настройка не вызывает молчаливой подмены поставщика. Допустимые уровни рассуждения определяет выбранная модель.

В режиме Foundation `run_in_host` использует уже созданный агент: класс разрешает существующий управляющий сеанс до его создания. Плагин не заменяет модель действующего агента. Авторизация API/OAuth и адреса сервисов остаются настройками Hermes; ключи не входят в конфигурацию исследования и в публикуемые артефакты.
